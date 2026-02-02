from __future__ import annotations

import json
import logging
import asyncio
from datetime import datetime

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, retry_if_exception, retry

from classificationg2s.core import config
from classificationg2s.models import OCRFailed, BusinessEntities
from classificationg2s.services.azure_clients import auth_headers, Clients
from classificationg2s.services.settings_store import get_categories_prompt_text, load_settings
from classificationg2s.services.annotations import ImageDescription

logger = logging.getLogger(__name__)

tracer = trace.get_tracer(__name__)

# --- Start Entity Extraction Logic ---

async def extract_business_entities(
    text_markdown: str,
    *,
    clients: Clients | None = None,
    config_deployment: str | None = None, # Allow override for specific model
    config_endpoint: str | None = None
) -> dict:
    """
    Extracts structured business entities (people, orgs, dates, amounts, etc.) from text.
    Uses the configured Phi-4 (or fallback) model.
    Returns a dict that conforms to BusinessEntities schema (but as dict via json_object mode).
    """

    # Defaults to Phi-4 config if not specified
    deployment = config_deployment or config.PHI_DEPLOYMENT
    endpoint = config_endpoint or config.PHI_ENDPOINT or config.AI_ENDPOINT

    if not endpoint or not deployment:
         # Fallback to pure regex or empty if no LLM (not implemented here, returning empty)
         logger.warning("No LLM endpoint available for entity extraction. Returning empty entities.")
         return BusinessEntities().model_dump()

    system_prompt_entities = """
You are an expert data extractor. Your task is to extract specific business entities from the document text.
Extract ALL occurrences of the following categories into a JSON object:
- people: Full names of individuals (e.g., John Smith, Marie Curie).
- organizations: Company names, institutions, banks, insurers.
- dates: Specific dates discovered in text. Prefer 'YYYY-MM-DD' if clear, otherwise keep original string.
- monetary_amounts: Currency values found (e.g., "$500", "1000 EUR", "50€").
- reference_numbers: Any unique identifiers like Policy numbers, Claim IDs, Invoice numbers, weird tracking codes.

If nothing is found for a category, return an empty list.

Example JSON Output:
{
  "people": ["Alice Bob"],
  "organizations": ["Contoso Insurance"],
  "dates": ["2023-12-05"],
  "monetary_amounts": ["$120.50"],
  "reference_numbers": ["POL-999-XYZ"]
}
"""

    # Helper function re-use logic
    # We re-use _classify_with_single_model logic but need custom system prompt.
    # To avoid strict code duplication, we inline the call logic for this distinct task.
    # Token estimation
    # system_tokens = estimate_tokens_rough(system_prompt_entities)
    # overhead_tokens = 200
    # Use fallback sizing just in case, aiming for speed/safety
    max_user = config.PHI_FALLBACK_MAX_INPUT_TOKENS - 1000

    user_content, truncated = clamp_text_to_token_budget(text_markdown or "", max_user)

    headers = await auth_headers(clients=clients)

    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={config.AI_API_VERSION}"

    payload = {
        "model": deployment,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt_entities},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": 1500, # Enough for a long list of entities
    }

    with tracer.start_as_current_span(f"extract_entities_{deployment}") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.operation", "extract.entities")

        async with httpx.AsyncClient(timeout=45) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                usage = data.get("usage", {})

                logger.info(f"[metrics] Entity Extraction Success: {usage.get('total_tokens', 0)} tokens")

                # Parse JSON
                entities_raw = json.loads(content)

                # Validate with Pydantic (leniently)
                # Ensure all fields exist and are lists
                validated = BusinessEntities(
                    people=entities_raw.get("people", []) or [],
                    organizations=entities_raw.get("organizations", []) or [],
                    dates=entities_raw.get("dates", []) or [],
                    monetary_amounts=entities_raw.get("monetary_amounts", []) or [],
                    reference_numbers=entities_raw.get("reference_numbers", []) or []
                )

                return {
                    "entities": validated.model_dump(),
                    "usage": usage
                }

            except Exception as ex:
                logger.error(f"Entity extraction failed: {ex}")
                span.record_exception(ex)
                # Return empty compliant structure on failure, don't crash pipeline
                return {
                    "entities": BusinessEntities().model_dump(),
                    "usage": {},
                    "error": str(ex)
                }

# --- End Entity Extraction Logic ---

def pydantic_to_mistral_schema(model: type[BaseModel]) -> dict:
    """
    Converts a Pydantic model to the JSON schema format expected by Mistral API.
    """
    schema = model.model_json_schema()
    return {
        "type": "json_schema",
        "json_schema": schema
    }


def retryable_httpx(exc: Exception) -> bool:
    if isinstance(exc, OCRFailed):
        return bool(getattr(exc, "retryable", False))
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response is not None
        and exc.response.status_code in (429, 500, 502, 503, 504)
    )


def estimate_tokens_rough(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def clamp_text_to_token_budget(text: str, max_tokens: int) -> tuple[str, bool]:
    if not text or max_tokens <= 0:
        return "", bool(text)
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _combine_ocr_pages(ocr_pages: list[dict], enable_vision_enrichment: bool = False, data: dict | None = None) -> tuple[str, list[dict]]:
    """
    Combine OCR pages into markdown and log per-page metrics.
    Logs:
    - total pages received
    - per-page markdown length and image count
    - warnings for empty pages
    - final combined content stats
    - raw response preview on empty content error
    """
    logger.info(f"[metrics] OCR Response: {len(ocr_pages)} pages received from Mistral Document AI")

    markdown_parts: list[str] = []
    total_content_chars = 0
    annotated_images: list[dict] = []

    for page_idx, page in enumerate(ocr_pages):
        page_md = page.get("markdown", "") or ""
        page_images = page.get("images", []) or []
        logger.info(f"[metrics] Page {page_idx}: markdown_length={len(page_md)} chars, images={len(page_images)}")
        if not page_md.strip() and not page_images:
            logger.warning(f"[metrics] Page {page_idx}: empty content")

        total_content_chars += len(page_md)

        if page_md:
            markdown_parts.append(page_md)

        if page_images and enable_vision_enrichment:
            # Append rich contextual descriptions for images (Mistral already includes ![...](img-X.jpeg) in markdown)
            # We enrich with detailed annotations to help Phi-4 understand visual context
            image_notes = []
            for img in page_images:
                summary = img.get("summary") or ""
                details = img.get("details") or ""
                img_type = img.get("image_type") or img.get("type") or "image"
                img_id = img.get("id") or f"img-{len(image_notes)}"

                # Generate rich contextual annotation
                if summary or details:
                    annotation = f"📎 **Image Context ({img_id})**: {img_type}"
                    if summary:
                        annotation += f" - {summary}"
                    if details:
                        annotation += f" ({details})"
                    image_notes.append(annotation)

            if image_notes:
                markdown_parts.append("\n\n---\n**Visual Elements Detected:**\n" + "\n".join(image_notes) + "\n---\n")

        for img in page_images:
            # Normalize bounding box from various Mistral formats to standard {x_min, y_min, x_max, y_max}
            bbox = img.get("bbox")
            if not bbox and "top_left_x" in img:
                # Handle flattened coordinates often returned by Mistral
                bbox = {
                    "x_min": img.get("top_left_x", 0),
                    "y_min": img.get("top_left_y", 0),
                    "x_max": img.get("bottom_right_x", 0),
                    "y_max": img.get("bottom_right_y", 0)
                }

            annotated_images.append({
                "id": img.get("id"),
                "page_index": page_idx,
                "image_type": img.get("type") or img.get("image_type"),
                "summary": img.get("summary") or img.get("description"),
                "bbox": bbox,
                "details": img.get("details"),
                "is_relevant": img.get("is_relevant"),
            })

    content = "\n\n".join(markdown_parts)
    logger.info(f"[metrics] OCR Final combined content: {len(content)} chars (from {total_content_chars} chars across {len(ocr_pages)} pages)")

    if not content.strip():
        logger.error(f"[metrics] OCR Failed: Empty content after combining {len(ocr_pages)} pages. Raw response preview: {str(data)[:500] if data else ''}")
        raise OCRFailed("Empty OCR content from Mistral Document AI")

    return content, annotated_images


async def ocr_with_mistral(
    base64_pdf: str,
    clients: Clients | None = None,
    include_images: bool = False,
    enable_vision_enrichment: bool = False
) -> dict:
    ocr_pages = []
    # Use central auth headers helper
    headers = await auth_headers(clients=clients, model_type="mistral")

    settings = load_settings()
    attempts = max(1, min(10, int(settings.get("ocr_max_attempts", getattr(config, "MISTRAL_OCR_MAX_ATTEMPTS", 3)))))

    # Mistral Document AI API format (Microsoft Foundry)
    if not config.MISTRAL_ENDPOINT:
        raise RuntimeError("MISTRAL_ENDPOINT not configured.")

    base_end = config.MISTRAL_ENDPOINT.rstrip("/")
    if base_end.endswith("/providers/mistral/azure/ocr"):
        url = base_end
    else:
        url = f"{base_end}/providers/mistral/azure/ocr"

    # Prepare payloads (per page if image conversion works, else single PDF)
    # NOTE: Vision strategy uses OCR-rendered page images only (no attachments/external images).
    payloads = []
    try:
        import fitz
        from PIL import Image
        import io
        import base64

        def _split_pdf_base64(pdf_data: bytes, max_pages: int = 30) -> list[str]:
            """Split PDF into base64-encoded chunks of max_pages each.
            Reference: https://github.com/mistralai/cookbook/blob/main/mistral/ocr/documentChunking/documentAIChunking.py
            """
            doc_full = fitz.open(stream=pdf_data, filetype="pdf")
            chunks: list[str] = []
            for start in range(0, len(doc_full), max_pages):
                sub = fitz.open()
                sub.insert_pdf(doc_full, from_page=start, to_page=min(len(doc_full) - 1, start + max_pages - 1))
                chunks.append(base64.b64encode(sub.tobytes()).decode())
                sub.close()
            doc_full.close()
            return chunks

        pdf_data = base64.b64decode(base64_pdf)
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        page_count = len(doc)

        if page_count >= 30:
            # Chunk large PDFs by pages and send as PDF (document_url)
            for chunk_b64 in _split_pdf_base64(pdf_data, max_pages=30):
                p = {
                    "model": config.MISTRAL_DEPLOYMENT,
                    "document": {
                        "type": "document_url",
                        "document_url": f"data:application/pdf;base64,{chunk_b64}"
                    },
                    "include_image_base64": include_images
                }
                if enable_vision_enrichment:
                    p["bbox_annotation_format"] = pydantic_to_mistral_schema(ImageDescription)
                payloads.append(p)
        else:
            # Per-page image conversion
            for page_idx in range(page_count):
                page = doc.load_page(page_idx)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                img_b64 = base64.b64encode(buf.getvalue()).decode()

                p = {
                    "model": config.MISTRAL_DEPLOYMENT,
                    "document": {
                        "type": "image_url",
                        "image_url": f"data:image/jpeg;base64,{img_b64}"
                    },
                    "include_image_base64": include_images
                }
                if enable_vision_enrichment:
                    p["bbox_annotation_format"] = pydantic_to_mistral_schema(ImageDescription)
                payloads.append(p)
        doc.close()
    except Exception as e:
        logger.warning(f"Failed to convert PDF to images, falling back to raw PDF base64: {e}")
        p = {
            "model": config.MISTRAL_DEPLOYMENT,
            "document": {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{base64_pdf}"
            },
            "include_image_base64": include_images
        }
        if enable_vision_enrichment:
            p["bbox_annotation_format"] = pydantic_to_mistral_schema(ImageDescription)
        payloads.append(p)

    ocr_pages: list = []
    usage_info: dict = {}

    # Process pages concurrently
    async def process_payload(payload):
        processing_log: list[dict] = []
        local_ocr_pages = []
        local_usage = {}

        # Clone payload to allow modification (fallback)
        current_payload = payload.copy()
        fallback_attempted = False

        while True:
            with tracer.start_as_current_span("mistral_document_ai_page") as span:
                span.set_attribute("gen_ai.system", "mistral")
                span.set_attribute("gen_ai.operation", "document.ocr")
                if fallback_attempted:
                    span.set_attribute("app.vision_fallback", True)

                try:
                    async for attempt in AsyncRetrying(
                        stop=stop_after_attempt(attempts),
                        wait=wait_exponential(multiplier=1, min=1, max=10),
                        retry=retry_if_exception(retryable_httpx),
                        reraise=True,
                    ):
                        with attempt:
                            attempt_no = attempt.retry_state.attempt_number
                            logger.info(f"[metrics] OCR Request attempt {attempt_no}/{attempts}: {url}")

                            async with httpx.AsyncClient(timeout=90) as client:
                                resp = await client.post(url, json=current_payload, headers=headers)
                                try:
                                    resp.raise_for_status()
                                except httpx.HTTPStatusError as ex:
                                    if ex.response.status_code == 422:
                                        # Special handling for 422 (Unprocessable Entity)
                                        # This often happens with Vision features on unsupported regions or schema issues
                                        logger.warning(f"[metrics] OCR 422 Unprocessable Entity: {ex.response.text[:200]}")
                                        raise OCRFailed(f"OCR 422: {ex.response.text}", retryable=False) # Break retry loop to trigger fallback logic below

                                    logger.error(f"[metrics] OCR Failed: {ex.response.status_code} - {ex.response.text[:500]}")
                                    span.record_exception(ex)
                                    raise

                                try:
                                    data = resp.json()
                                    local_ocr_pages = data.get("pages", [])
                                    local_usage = data.get("usage", {})
                                except json.JSONDecodeError as ex:
                                    response_text = resp.text[:1000]
                                    log_entry = {
                                        "status_code": resp.status_code,
                                        "text_snippet": response_text,
                                        "attempt": attempt_no,
                                    }
                                    processing_log.append(log_entry)
                                    logger.error(f"[metrics] OCR JSON Parse Error: {ex}")
                                    raise OCRFailed(f"stage=ocr: Invalid JSON response: {ex}", processing_log=processing_log, retryable=True)

                            if not local_ocr_pages:
                                raise OCRFailed("No pages in Mistral Document AI response")

                    # Success
                    return local_ocr_pages, local_usage

                except OCRFailed as e:
                    # Check if we can fallback for 422
                    if "OCR 422" in str(e) and not fallback_attempted and "bbox_annotation_format" in current_payload:
                        logger.warning("[metrics] Vision enrichment failed (422). Retrying without vision params.")
                        fallback_attempted = True
                        if "bbox_annotation_format" in current_payload:
                            del current_payload["bbox_annotation_format"]
                        # Continue outer while loop to retry with new payload
                        continue
                    raise e
                except Exception as e:
                    raise e
            break # Should not be reached if successful return inside loop

    # Run tasks
    with tracer.start_as_current_span("mistral_document_process_all") as span:
        tasks = [process_payload(p) for p in payloads]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        for pages, usage in results:
            ocr_pages.extend(pages)
            # Accumulate usage roughly
            for k, v in usage.items():
                usage_info[k] = usage_info.get(k, 0) + v

        content, annotated_images = _combine_ocr_pages(ocr_pages, enable_vision_enrichment=enable_vision_enrichment, data=None)

        pages_count = len(ocr_pages)

        logger.info(f"[metrics] OCR Success: {pages_count} pages processed")

        span.set_attribute("gen_ai.usage.pages_processed", pages_count)
        span.set_attribute("gen_ai.usage.input_tokens", usage_info.get("prompt_tokens", 0))
        span.set_attribute("gen_ai.usage.output_tokens", usage_info.get("completion_tokens", 0))

    return {"markdown": content, "usage": usage_info, "images": annotated_images}


async def _classify_with_single_model(
    text_markdown: str,
    *,
    endpoint: str,
    deployment: str,
    strategy: str = "standard",
    clients: Clients | None = None,
) -> dict:
    """
    Internal generic function to classify with a specific model endpoint/deployment.
    Used by both classify_with_phi4() and comparison logic.
    """
    if not endpoint:
        raise RuntimeError(f"Endpoint not configured for {deployment}")

    headers = await auth_headers(clients=clients)
    categories_text = get_categories_prompt_text()

    extra_instructions = ""
    if strategy == "reasoning":
        extra_instructions = "\nIMPORTANT : Adopte une approche 'Step-by-step'. Analyse d'abord le contexte, puis déduis les intentions. Sois très précis sur la justification."
    elif strategy == "vision":
        extra_instructions = "\nNOTE : Le document peut contenir des descriptions d'images. Prends en compte le contexte visuel décrit."

    system_prompt = f"""
Tu es un assistant expert en classification d'emails d'assurance.{extra_instructions}
Ta tâche est d'analyser le contenu de l'email (fourni en markdown) et d'identifier :
- TOUTES les intentions présentes.
- Le sujet principal (Subject).
- L'expéditeur (Sender) si identifiable.

LISTE DES INTENTIONS POSSIBLES (NOM + DESCRIPTION) :
{categories_text}

RÈGLES DE CLASSIFICATION :
- Choisis les intentions dont la DESCRIPTION correspond le mieux au contenu. Appuie-toi sur les mots/phrases clés des descriptions.
- Un email peut contenir UNE SEULE intention OU PLUSIEURS intentions.
- Si aucune intention ne correspond vraiment, retourne une liste vide (detected_intents: []). NE PAS deviner.
- Assigne un score de confiance (0.0 à 1.0) pour CHAQUE intention détectée.
- La justification DOIT citer un extrait du texte et/ou la description de la catégorie correspondante.

FORMAT DE RÉPONSE ATTENDU (JSON UNIQUEMENT) :
{{
    "detected_intents": [
        {{
            "intent": "Nom de l'intention",
            "confidence": 0.95,
            "justification": "Court extrait du texte ou référence à la description justifiant ce choix"
        }}
    ],
    "global_complexity": "Simple|Complexe",
    "classification_reason": "Explication courte si detected_intents est vide (ex: 'Aucune intention ne correspond car le contenu est hors périmètre assurance')",
    "subject": "Sujet ou Objet de l'email extrait du texte",
    "sender": "Nom ou Email de l'expéditeur extrait"
}}

IMPORTANT: Si detected_intents est vide, TOUJOURS remplir classification_reason avec une explication claire.
"""

    system_tokens = estimate_tokens_rough(system_prompt)
    overhead_tokens = 200
    user_tokens_est = estimate_tokens_rough(text_markdown or "")

    # Determine token budget based on deployment
    if deployment == config.PHI_FALLBACK_DEPLOYMENT:
        max_user = config.PHI_FALLBACK_MAX_INPUT_TOKENS - config.PHI_RESERVED_OUTPUT_TOKENS - system_tokens - overhead_tokens
    else:
        max_user = config.PHI_PRIMARY_MAX_INPUT_TOKENS - config.PHI_RESERVED_OUTPUT_TOKENS - system_tokens - overhead_tokens

    max_user = max(500, max_user)
    user_content, truncated = clamp_text_to_token_budget(text_markdown or "", max_user)

    payload = {
        "model": deployment,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": config.PHI_RESERVED_OUTPUT_TOKENS,
    }

    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={config.AI_API_VERSION}"

    logger.info(f"[metrics] Classify Request: {deployment} strategy={strategy}")
    logger.info(f"[metrics] Token Estimate: system={system_tokens} user={user_tokens_est} truncated={truncated}")

    with tracer.start_as_current_span(f"classify_{deployment}") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.operation", "chat.completions")
        span.set_attribute("gen_ai.request.model", deployment)
        span.set_attribute("app.context_truncated", bool(truncated))
        span.set_attribute("app.estimated.user_tokens", int(user_tokens_est))
        span.set_attribute("app.user_budget_tokens", int(max_user))

        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPStatusError as ex:
                status = ex.response.status_code if ex.response is not None else None
                body = ex.response.text if ex.response is not None else ""
                logger.error(f"[metrics] Classify Failed ({deployment}): {status} - {body}")
                raise

            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            usage = data.get("usage", {})

            logger.info(f"[metrics] Classify Success ({deployment}): {usage.get('total_tokens', 0)} tokens used")
            logger.info(f"[metrics] Response preview: {content[:100]}...")

            span.set_attribute("gen_ai.usage.input_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.output_tokens", usage.get("completion_tokens", 0))
            span.set_attribute("gen_ai.usage.total_tokens", usage.get("total_tokens", 0))

            payload_dict = json.loads(content)
            payload_dict["usage"] = usage
            payload_dict["model"] = deployment
            payload_dict["context_truncated"] = bool(truncated)
            payload_dict["estimated_user_tokens"] = int(user_tokens_est)
            return payload_dict


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception(retryable_httpx))
async def classify_with_phi4(text_markdown: str, *, force_fallback: bool = False, strategy: str = "standard", clients: Clients | None = None) -> dict:
    """
    Classify email with Phi-4 (or fallback to gpt-4o-mini if token budget exceeded).

    Args:
        text_markdown: Email content in markdown format
        force_fallback: Force use of fallback model (gpt-4o-mini)
        strategy: "standard", "reasoning", or "vision" - affects system prompt
        clients: Optional pre-configured clients (for testing/DI)

    Returns:
        Classification result dict with intents, complexity, usage, model info
    """
    if not config.PHI_ENDPOINT:
        raise RuntimeError("PHI_ENDPOINT is not set")
    if not config.PHI_FALLBACK_ENDPOINT:
        raise RuntimeError("PHI_FALLBACK_ENDPOINT is not set")

    # Determine which model to use based on token budget
    system_prompt_rough = "Tu es un assistant expert en classification d'emails d'assurance."
    system_tokens = estimate_tokens_rough(system_prompt_rough)
    overhead_tokens = 200
    user_tokens_est = estimate_tokens_rough(text_markdown or "")

    max_user_primary = max(
        500,
        config.PHI_PRIMARY_MAX_INPUT_TOKENS - config.PHI_RESERVED_OUTPUT_TOKENS - system_tokens - overhead_tokens,
    )

    use_fallback = force_fallback or (user_tokens_est > max_user_primary)
    chosen_endpoint = config.PHI_FALLBACK_ENDPOINT if use_fallback else config.PHI_ENDPOINT
    chosen_deployment = config.PHI_FALLBACK_DEPLOYMENT if use_fallback else config.PHI_DEPLOYMENT

    logger.info(f"[metrics] Classify Request: {chosen_deployment} strategy={strategy} fallback={use_fallback}")

    try:
        result = await _classify_with_single_model(
            text_markdown,
            endpoint=chosen_endpoint,
            deployment=chosen_deployment,
            strategy=strategy,
            clients=clients,
        )
        result["fallback_used"] = bool(use_fallback)
        return result
    except httpx.HTTPStatusError as ex:
        status = ex.response.status_code if ex.response is not None else None
        body = ex.response.text if ex.response is not None else ""

        # If primary model fails due to token limit, retry with fallback
        if (
            (not use_fallback)
            and status in (400, 413)
            and ("context" in body.lower() or "token" in body.lower() or "length" in body.lower())
        ):
            logger.warning("[metrics] Token limit exceeded! Retrying with fallback model.")
            return await classify_with_phi4(text_markdown, force_fallback=True, strategy=strategy, clients=clients)
        raise


def resolve_model_config(model_key: str) -> tuple[str, str]:
    """
    Resolves a model key/name to an (endpoint, deployment) tuple.
    """
    k = model_key.lower().strip()
    if k in ("phi-4", "phi4", "standard", "primary"):
        return config.PHI_ENDPOINT, config.PHI_DEPLOYMENT
    if k in ("gpt-4o-mini", "gpt4o-mini", "gpt4o_mini", "fallback", "audit"):
        return config.PHI_FALLBACK_ENDPOINT, config.PHI_FALLBACK_DEPLOYMENT

    # Fallback/Generic: Assume the key is the deployment name on the primary endpoint
    # This supports 'gpt5-nano', 'gpt4.1-nano' etc. if they are deployed on the same resource
    return config.PHI_ENDPOINT, model_key


async def classify_comparison(
    text_markdown: str,
    *,
    models: list[str],
    strategy: str = "standard",
    clients: Clients | None = None,
) -> dict:
    """
    Compare classification across multiple models.
    Args:
        models: List of model keys/deployment names (e.g. ['phi-4', 'gpt5-nano'])
    """
    if not models or len(models) < 1:
        raise ValueError("At least one model must be specified for comparison")

    import time
    start_time = time.time()

    tasks = []
    resolved_names = []

    for m in models:
        endpoint, deployment = resolve_model_config(m)
        if not endpoint:
             logger.warning(f"No endpoint found for model '{m}', skipping")
             continue

        resolved_names.append(m)
        tasks.append(_classify_with_single_model(
            text_markdown,
            endpoint=endpoint,
            deployment=deployment,
            strategy=strategy,
            clients=clients
        ))

    if not tasks:
        return {
            "model_results": {},
            "comparison_meta": {
                "executed_at": datetime.utcnow().isoformat(),
                "error": "No valid models configured for comparison",
                "elapsed_ms": 0
            }
        }

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Assemble results
    model_results = {}
    valid_intents = []

    for name, res in zip(resolved_names, results):
        if isinstance(res, Exception):
            logger.error(f"Model {name} failed: {res}")
            model_results[name] = {
                "detected_intents": [],
                "error": str(res),
                "needs_review": True
            }
        else:
            model_results[name] = res
            if res.get("detected_intents"):
                valid_intents.append(res["detected_intents"][0]["intent"])

    # Calculate agreement (simplistic: all top intents match)
    agreement = False
    if valid_intents:
        agreement = all(i == valid_intents[0] for i in valid_intents)
        # Verify confidence delta if exactly 2 models (legacy support)
        # Note: Delta is less meaningful for n > 2, but we could calc max-min

    elapsed_ms = int((time.time() - start_time) * 1000)

    # Legacy Backward Compat if exactly 2 specific models used
    # This ensures older UI or consumers don't break immediately
    legacy_phi4 = model_results.get("phi-4") or model_results.get("phi4")
    legacy_gpt4o = model_results.get("gpt-4o-mini") or model_results.get("gpt4o_mini")

    return {
        "model_results": model_results,
        "comparison_meta": {
            "executed_at": datetime.utcnow().isoformat(),
            "agreement": agreement,
            "models_executed": resolved_names,
            "elapsed_ms": elapsed_ms,
            "error": None,
        },
        # Legacy Top-level keys
        "phi4": legacy_phi4,
        "gpt4o_mini": legacy_gpt4o
    }


async def classify_with_both_models(
    text_markdown: str,
    *,
    strategy: str = "standard",
    clients: Clients | None = None,
) -> dict:
    """
    DEPRECATED: Use classify_comparison
    Maintains backward compatibility for adversarial comparison (Phi-4 vs GPT-4o-mini).
    """
    return await classify_comparison(
        text_markdown,
        models=[config.PHI_DEPLOYMENT or "phi-4", config.PHI_FALLBACK_DEPLOYMENT or "gpt-4o-mini"],
        strategy=strategy,
        clients=clients
    )





def process_agent_response(agent_response: dict) -> dict:
    import logging

    try:
        data = agent_response if isinstance(agent_response, dict) else json.loads(agent_response)
        intents = data.get("detected_intents", [])
        needs_review = False
        settings = load_settings()
        review_threshold = float(settings.get("review_confidence_threshold", getattr(config, "REVIEW_CONFIDENCE_THRESHOLD", 0.85)))
        if not intents:
            needs_review = True
        for item in intents:
            if item.get("confidence", 0) < review_threshold:
                needs_review = True
                break
        if len(intents) > 3:
            needs_review = True
        return {
            "intents": intents,
            "needs_review": needs_review,
            "raw_response": data,
        }
    except json.JSONDecodeError:
        logging.error("Agent returned invalid JSON")
        return {"needs_review": True, "error": "Invalid JSON"}


async def analyze_correction(
    text_markdown: str,
    old_intents: list[dict],
    new_intents: list[dict],
    reason: str,
    clients: Clients | None = None
) -> str | None:
    """
    Uses Phi-4 to analyze the human correction and provide insights for prompt reinforcement.
    """
    if not config.PHI_ENDPOINT or not reason:
        return None

    system_prompt = """
Tu es un expert en amélioration de classification automatique.
Un utilisateur humain a corrigé la classification d'un email faite par une IA.
Ta tâche est d'analyser la correction et le commentaire de l'utilisateur pour générer une "Leçon Apprise" concise.
Cette leçon servira à améliorer le prompt système futur.

FORMAT DE SORTIE :
Une seule phrase ou un court paragraphe expliquant la nuance manquée par l'IA.
Exemple : "L'IA a manqué l'intention 'Résiliation' car le terme utilisé était 'clôture de compte' dans le contexte d'un décès."
"""

    user_content = f"""
EMAIL :
{text_markdown[:2000]}... (tronqué)

CLASSIFICATION IA (Précédente) :
{json.dumps(old_intents, ensure_ascii=False)}

CLASSIFICATION HUMAINE (Corrigée) :
{json.dumps(new_intents, ensure_ascii=False)}

RAISON DE L'UTILISATEUR :
{reason}

Analyse cette correction.
    """

    headers = await auth_headers(clients=clients)
    payload = {
        "model": config.PHI_DEPLOYMENT,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
        "max_tokens": 150,
    }

    url = f"{config.PHI_ENDPOINT.rstrip('/')}/openai/deployments/{config.PHI_DEPLOYMENT}/chat/completions?api-version={config.AI_API_VERSION}"

    try:
        async with httpx.AsyncClient(timeout=10) as client: # Fast timeout for UI responsiveness
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    except Exception:
        pass

    return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5), retry=retry_if_exception(retryable_httpx))
async def generate_embedding(text: str, clients: Clients | None = None) -> list[float]:
    """
    Generates vector embeddings for the given text using the configured embedding model.
    """
    if not config.EMBEDDING_ENDPOINT or not text:
        return []

    # Truncate text to avoid token limits (text-embedding-3-small limit is ~8k tokens)
    # 24k chars is roughly 6k tokens, safe enough.
    text_truncated = text[:24000]

    headers = await auth_headers(clients=clients)

    url = f"{config.EMBEDDING_ENDPOINT.rstrip('/')}/openai/deployments/{config.EMBEDDING_DEPLOYMENT}/embeddings?api-version={config.EMBEDDING_API_VERSION}"

    payload = {
        "input": text_truncated,
        "model": config.EMBEDDING_DEPLOYMENT
    }

    with tracer.start_as_current_span("generate_embedding") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.operation", "embeddings")

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return data["data"][0]["embedding"]
            except Exception as ex:
                logger.error(f"Embedding generation failed: {ex}")
                span.record_exception(ex)
                span.set_status(Status(StatusCode.ERROR))
                # Depending on requirement, we might want to return empty list or raise
                # Returning empty list allows processing to continue without vector search capability for this item
                return []
