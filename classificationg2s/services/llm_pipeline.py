from __future__ import annotations

import json
import logging
import asyncio

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, retry_if_exception, retry

from classificationg2s.core import config
from classificationg2s.models import OCRFailed
from classificationg2s.services.azure_clients import auth_headers, Clients
from classificationg2s.services.settings_store import get_categories_prompt_text, load_settings
from classificationg2s.services.annotations import ImageDescription

logger = logging.getLogger(__name__)

tracer = trace.get_tracer(__name__)


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
            image_notes = []
            for img in page_images:
                summary = img.get("summary")
                details = img.get("details")
                img_type = img.get("image_type") or img.get("type")
                if summary or details:
                    note = f"> [Visual Content ({img_type or 'image'})]: {summary} | Details: {details}"
                    image_notes.append(note)
            if image_notes:
                markdown_parts.append("\n\n--- Visual Context ---\n" + "\n".join(image_notes) + "\n----------------------\n")

        for img in page_images:
            annotated_images.append({
                "id": img.get("id"),
                "page_index": page_idx,
                "image_type": img.get("type") or img.get("image_type"),
                "description": img.get("description") or img.get("summary"),
                "bbox": img.get("bbox"),
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

        with tracer.start_as_current_span("mistral_document_ai_page") as span:
            span.set_attribute("gen_ai.system", "mistral")
            span.set_attribute("gen_ai.operation", "document.ocr")

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
                        resp = await client.post(url, json=payload, headers=headers)
                        try:
                            resp.raise_for_status()
                        except httpx.HTTPStatusError as ex:
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
            return local_ocr_pages, local_usage

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


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception(retryable_httpx))
async def classify_with_phi4(text_markdown: str, *, force_fallback: bool = False, strategy: str = "standard", clients: Clients | None = None) -> dict:
    if not config.PHI_ENDPOINT:
        raise RuntimeError("PHI_ENDPOINT is not set")
    if not config.PHI_FALLBACK_ENDPOINT:
        raise RuntimeError("PHI_FALLBACK_ENDPOINT is not set")

    headers = await auth_headers(clients=clients)

    categories_text = get_categories_prompt_text()

    extra_instructions = ""
    if strategy == "reasoning":
        extra_instructions = "\nIMPORTANT : Adopte une approche 'Step-by-step'. Analyse d'abord le contexte, puis déduis les intentions. Sois très précis sur la justification."
    elif strategy == "vision":
        extra_instructions = "\nNOTE : Le document peut contenir des descriptions d'images. Prends en compte le contexte visuel décrit."

    system_prompt = f"""
Tu es un assistant expert en classification d'emails d'assurance.{extra_instructions}
Ta tâche est d'analyser le contenu de l'email (fourni en markdown) et d'identifier "
- TOUTES les intentions présentes.
- Le sujet principal (Subject).
- L'expéditeur (Sender) si identifiable.

LISTE DES INTENTIONS POSSIBLES :
{categories_text}

RÈGLES DE CLASSIFICATION :
- Un email peut contenir UNE SEULE intention OU PLUSIEURS intentions.
- Si aucune intention ne correspond, retourne une liste vide (detected_intents: []).
- Assigne un score de confiance (0.0 à 1.0) pour CHAQUE intention détectée.

FORMAT DE RÉPONSE ATTENDU (JSON UNIQUEMENT) :
{{
    "detected_intents": [
        {{
            "intent": "Nom de l'intention",
            "confidence": 0.95,
            "justification": "Court extrait du texte justifiant ce choix"
        }}
    ],
    "global_complexity": "Simple|Complexe",
    "subject": "Sujet ou Objet de l'email extrait du texte",
    "sender": "Nom ou Email de l'expéditeur extrait"
}}
"""

    system_tokens = estimate_tokens_rough(system_prompt)
    overhead_tokens = 200
    user_tokens_est = estimate_tokens_rough(text_markdown or "")

    max_user_primary = max(
        500,
        config.PHI_PRIMARY_MAX_INPUT_TOKENS - config.PHI_RESERVED_OUTPUT_TOKENS - system_tokens - overhead_tokens,
    )
    max_user_fallback = max(
        500,
        config.PHI_FALLBACK_MAX_INPUT_TOKENS - config.PHI_RESERVED_OUTPUT_TOKENS - system_tokens - overhead_tokens,
    )

    use_fallback = force_fallback or (user_tokens_est > max_user_primary)
    chosen_endpoint = config.PHI_FALLBACK_ENDPOINT if use_fallback else config.PHI_ENDPOINT
    chosen_deployment = config.PHI_FALLBACK_DEPLOYMENT if use_fallback else config.PHI_DEPLOYMENT
    user_budget = max_user_fallback if use_fallback else max_user_primary
    user_content, truncated = clamp_text_to_token_budget(text_markdown or "", user_budget)

    payload = {
        "model": chosen_deployment,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": config.PHI_RESERVED_OUTPUT_TOKENS,
    }

    url = f"{chosen_endpoint.rstrip('/')}/openai/deployments/{chosen_deployment}/chat/completions?api-version={config.AI_API_VERSION}"

    logger.info(f"[metrics] Classify Request: {chosen_deployment} strategy={strategy} fallback={use_fallback}")
    logger.info(f"[metrics] Token Estimate: system={system_tokens} user={user_tokens_est} truncated={truncated}")

    with tracer.start_as_current_span("phi4_classify") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.operation", "chat.completions")
        span.set_attribute("gen_ai.request.model", chosen_deployment)
        span.set_attribute("app.fallback_used", bool(use_fallback))
        span.set_attribute("app.context_truncated", bool(truncated))
        span.set_attribute("app.estimated.user_tokens", int(user_tokens_est))
        span.set_attribute("app.user_budget_tokens", int(user_budget))

        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPStatusError as ex:
                status = ex.response.status_code if ex.response is not None else None
                body = ex.response.text if ex.response is not None else ""

                logger.error(f"[metrics] Classify Failed: {status} - {body}")

                if (
                    (not use_fallback)
                    and status in (400, 413)
                    and ("context" in body.lower() or "token" in body.lower() or "length" in body.lower())
                ):
                    logger.warning("[metrics] Token limit reached! Retrying with fallback model.")
                    return await classify_with_phi4(text_markdown, force_fallback=True)
                raise

            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            usage = data.get("usage", {})

            logger.info(f"[metrics] Classify Success: {usage.get('total_tokens', 0)} tokens used")
            # Log the first 100 chars of content just to see if it looks like JSON
            logger.info(f"[metrics] Response preview: {content[:100]}...")

            span.set_attribute("gen_ai.usage.input_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.output_tokens", usage.get("completion_tokens", 0))
            span.set_attribute("gen_ai.usage.total_tokens", usage.get("total_tokens", 0))

            payload_dict = json.loads(content)
            payload_dict["usage"] = usage
            payload_dict["model"] = chosen_deployment
            payload_dict["fallback_used"] = bool(use_fallback)
            payload_dict["context_truncated"] = bool(truncated)
            payload_dict["estimated_user_tokens"] = int(user_tokens_est)
            return payload_dict


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
