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

from classymail.core import config
from classymail.core.llm_compat import build_chat_params, extract_message_content, supports_response_format
from classymail.models import OCRFailed, BusinessEntities
from classymail.services.azure_clients import auth_headers, Clients
from classymail.services.settings_store import get_categories_prompt_text, load_settings
from classymail.services.annotations import ImageDescription
from classymail.services.email_preprocessing import preprocess_email_content
from classymail.services.pii_detection import detect_pii
from classymail.core.llm_limits import get_limiter
# from classymail.services.circuit_breaker import with_ocr_circuit_breaker, with_classification_circuit_breaker

logger = logging.getLogger(__name__)

tracer = trace.get_tracer(__name__)

# --- Start Entity Extraction Logic ---

async def extract_business_entities(
    text_markdown: str,
    *,
    clients: Clients | None = None,
    config_deployment: str | None = None, # Allow override for specific model
    config_endpoint: str | None = None,
    api_version: str | None = None,
) -> dict:
    """
    Extracts structured business entities (people, orgs, dates, amounts, etc.) from text.
    Uses the configured primary (or fallback) model.
    Returns a dict that conforms to BusinessEntities schema (but as dict via json_object mode).
    """

    # Defaults to primary config if not specified
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

    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version or config.AI_API_VERSION}"

    payload = {
        "model": deployment,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt_entities},
            {"role": "user", "content": user_content},
        ],
        **build_chat_params(deployment, temperature=0.1, max_output_tokens=1500),
    }

    with tracer.start_as_current_span(f"extract_entities_{deployment}") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.operation", "extract.entities")

        async with httpx.AsyncClient(timeout=45) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                content = extract_message_content(data.get("choices", [{}])[0].get("message", {})) or "{}"
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

    The official Mistral SDK (response_format_from_pydantic_model) wraps the schema
    in {"name": ..., "schema": ..., "strict": true} inside json_schema.
    Azure AI Foundry's Mistral endpoint requires this exact format — omitting the
    wrapper causes HTTP 422.
    """
    schema = model.model_json_schema()
    # Remove $defs/title that Pydantic adds but Mistral doesn't need at top level
    schema.pop("$defs", None)
    # Ensure additionalProperties: false (required by strict mode)
    schema.setdefault("additionalProperties", False)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": model.__name__,
            "schema": schema,
            "strict": True,
        },
    }


def retryable_httpx(exc: Exception) -> bool:
    if isinstance(exc, OCRFailed):
        return bool(getattr(exc, "retryable", False))
    # ConnectTimeout = service unreachable, fail fast to trigger fallback
    if isinstance(exc, httpx.ConnectTimeout):
        return False
    # Retry on other timeouts (ReadTimeout, WriteTimeout, PoolTimeout)
    if isinstance(exc, httpx.TimeoutException):
        return True
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


def _is_filename_like(summary: str) -> bool:
    """Check if a summary is just a filename (e.g. 'img-0.jpeg') rather than real content."""
    import re
    if not summary or not summary.strip():
        return True
    s = summary.strip()
    # Matches patterns like img-0.jpeg, image_1.png, etc.
    return bool(re.fullmatch(r'img[-_]?\d+\.?(jpe?g|png|gif|bmp|webp|svg)?', s, re.IGNORECASE))


async def _describe_image_with_vision(
    image_base64: str,
    clients: Clients | None = None,
) -> str:
    """Call GPT-4o-mini to generate a description for an image that has no Mistral annotation."""
    headers = await auth_headers(clients=clients)
    url = (
        f"{config.VISION_ENDPOINT.rstrip('/')}/openai/deployments/"
        f"{config.VISION_DEPLOYMENT}/chat/completions"
        f"?api-version={config.VISION_API_VERSION}"
    )
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Décris brièvement cette image en une ou deux phrases. "
                            "Indique le type d'image (photo, graphique, logo, tableau, etc.) "
                            "et son contenu principal."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                    },
                ],
            }
        ],
        "max_tokens": 150,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        async with get_limiter("vision"):
            resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return extract_message_content(data)


def _combine_ocr_pages(ocr_pages: list[dict], enable_vision_enrichment: bool = False, data: dict | None = None) -> tuple[str, list[dict]]:
    """
    Combine OCR pages into markdown and log per-page metrics.
    Also extracts image descriptions from Mistral's markdown output.

    Logs:
    - total pages received
    - per-page markdown length and image count
    - warnings for empty pages
    - final combined content stats
    - raw response preview on empty content error
    """
    import re

    logger.info(f"[metrics] OCR Response: {len(ocr_pages)} pages received from Mistral Document AI")

    markdown_parts: list[str] = []
    total_content_chars = 0
    annotated_images: list[dict] = []

    # Pre-process all markdown to extract image descriptions early
    all_markdown = ""
    image_markdown_refs = {}  # Map img-id to description from markdown

    for page_idx, page in enumerate(ocr_pages):
        page_md = page.get("markdown", "") or ""
        all_markdown += page_md + "\n"

        # Extract image descriptions from markdown syntax: ![description](url)
        image_pattern = r'!\[([^\]]*)\]\(([^)]*)\)'
        for match in re.finditer(image_pattern, page_md):
            desc_text, img_url = match.groups()
            if desc_text and img_url:
                # Store by img_url (e.g., 'img-0.jpeg')
                img_key = img_url.split('/')[-1] if '/' in img_url else img_url
                image_markdown_refs[img_key] = desc_text
                image_markdown_refs[f"page_{page_idx}_{img_key}"] = desc_text

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
                summary = img.get("summary") or img.get("description") or ""
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

        # Only collect annotated images when vision enrichment is enabled
        # to avoid showing image metadata in standard/reasoning modes
        if enable_vision_enrichment:
            for img_idx, img in enumerate(page_images):
                # Debug: Log raw image data to understand Mistral response structure
                logger.debug(f"[metrics] Raw image from Mistral: {json.dumps(img, default=str)[:500]}")

                # Try multiple sources for image description.
                # Mistral bbox_annotation_format may return annotations:
                #   - as flat fields (summary, description)
                #   - nested under 'annotation' dict
                #   - as JSON string in 'content'
                summary = img.get("summary") or img.get("description") or ""
                nested = img.get("annotation") or {}
                if isinstance(nested, str):
                    try:
                        nested = json.loads(nested)
                    except (json.JSONDecodeError, TypeError):
                        nested = {}
                if not summary and isinstance(nested, dict):
                    summary = nested.get("summary") or nested.get("description") or ""
                # Also try 'content' field (JSON string from structured output)
                content_str = img.get("content")
                if not summary and content_str and isinstance(content_str, str):
                    try:
                        content_parsed = json.loads(content_str)
                        if isinstance(content_parsed, dict):
                            summary = content_parsed.get("summary") or content_parsed.get("description") or ""
                    except (json.JSONDecodeError, TypeError):
                        pass

                # If no API description, try to get from markdown
                if not summary:
                    img_id_candidates = [
                        img.get("id"),
                        f"img-{img_idx}.jpeg",
                        f"img-{img_idx}",
                        f"page_{page_idx}_img-{img_idx}.jpeg"
                    ]
                    for candidate in img_id_candidates:
                        if candidate and candidate in image_markdown_refs:
                            summary = image_markdown_refs[candidate]
                            logger.info(f"[metrics] Found markdown description for image {candidate}: '{summary[:100]}'")
                            break

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

                # Also pull details/is_relevant/image_type from nested annotation
                details_val = img.get("details") or (nested.get("details") if isinstance(nested, dict) else None)
                is_relevant_val = img.get("is_relevant")
                if is_relevant_val is None and isinstance(nested, dict):
                    is_relevant_val = nested.get("is_relevant")
                img_type_val = img.get("type") or img.get("image_type")
                if not img_type_val and isinstance(nested, dict):
                    img_type_val = nested.get("image_type") or nested.get("type")

                vision_item = {
                    "id": img.get("id"),
                    "page_index": page_idx,
                    "image_type": img_type_val,
                    "summary": summary,
                    "bbox": bbox,
                    "details": details_val,
                    "is_relevant": is_relevant_val,
                }
                # Preserve base64 temporarily for GPT-4o-mini fallback (stripped later)
                raw_b64 = img.get("image_base64") or img.get("base64") or ""
                if raw_b64:
                    vision_item["_image_base64"] = raw_b64
                logger.info(f"[metrics] Extracted vision item for page {page_idx}: type={vision_item.get('image_type')}, has_summary={bool(vision_item.get('summary'))}, summary='{(vision_item.get('summary') or '')[:80]}'")
                annotated_images.append(vision_item)

    content = "\n\n".join(markdown_parts)
    logger.info(f"[metrics] OCR Final combined content: {len(content)} chars (from {total_content_chars} chars across {len(ocr_pages)} pages), total_images={len(annotated_images)}")

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
    if "?" not in url:
        url = f"{url}?api-version={config.MISTRAL_API_VERSION}"

    # Prepare payloads (per page if image conversion works, else single PDF)
    # NOTE: Vision strategy uses OCR-rendered page images only (no attachments/external images).
    payloads = []
    image_conversion_total_ms = 0  # Track vision-specific overhead
    try:
        import fitz
        from PIL import Image
        import io
        import base64
        import time

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
        elif enable_vision_enrichment:
            # Vision enrichment: send as document_url (PDF) so Mistral can extract
            # embedded images and return image_base64. Per-page JPEG (image_url) only
            # returns bbox for detected sub-images but NOT their base64, which prevents
            # the GPT-4o-mini fallback from working.
            logger.info(f"[metrics] Vision strategy: sending {page_count}-page PDF as document_url for image extraction")
            p = {
                "model": config.MISTRAL_DEPLOYMENT,
                "document": {
                    "type": "document_url",
                    "document_url": f"data:application/pdf;base64,{base64_pdf}"
                },
                "include_image_base64": include_images
            }
            p["bbox_annotation_format"] = pydantic_to_mistral_schema(ImageDescription)
            payloads.append(p)
        else:
            # Per-page image conversion (standard/reasoning strategy)
            # Note: Reduced resolution (1x instead of 2x) and quality (75 instead of 85)
            # to improve performance. Mistral Document AI performs rescaling internally.
            image_conversion_start = time.perf_counter()
            for page_idx in range(page_count):
                page = doc.load_page(page_idx)
                pix = page.get_pixmap(matrix=fitz.Matrix(1, 1))  # 1x resolution (50% faster) vs 2x
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=75)  # Reduced from 85 to 75 for faster encoding
                img_b64 = base64.b64encode(buf.getvalue()).decode()

                p = {
                    "model": config.MISTRAL_DEPLOYMENT,
                    "document": {
                        "type": "image_url",
                        "image_url": f"data:image/jpeg;base64,{img_b64}"
                    },
                    "include_image_base64": include_images
                }
                payloads.append(p)
            image_conversion_total_ms = (time.perf_counter() - image_conversion_start) * 1000
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

                            async with httpx.AsyncClient(timeout=120) as client:
                                async with get_limiter("mistral"):
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

                                    # Log response structure for first page to understand image field names
                                    if local_ocr_pages and attempt_no == 1:
                                        first_page_images = local_ocr_pages[0].get("images", [])
                                        if first_page_images:
                                            logger.info(f"[metrics] Mistral response - First image keys: {list(first_page_images[0].keys())}, Full sample: {json.dumps(first_page_images[0], default=str)[:1000]}")
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

        # --- GPT-4o-mini fallback for images without useful descriptions ---
        vision_fallback_ok = 0
        vision_fallback_failed = 0
        if enable_vision_enrichment and annotated_images:
            # Log detailed vision analysis inventory
            filename_only = [img for img in annotated_images if _is_filename_like(img.get("summary", ""))]
            has_desc = [img for img in annotated_images if not _is_filename_like(img.get("summary", ""))]
            has_b64 = [img for img in filename_only if img.get("_image_base64")]
            no_b64 = [img for img in filename_only if not img.get("_image_base64")]

            logger.info(
                f"[metrics] Vision analysis inventory: "
                f"total_images={len(annotated_images)}, "
                f"with_description={len(has_desc)}, "
                f"filename_only={len(filename_only)}, "
                f"fallback_eligible(has_b64)={len(has_b64)}, "
                f"no_fallback(no_b64)={len(no_b64)}"
            )
            span.add_event("vision.analysis_inventory", {
                "total_images": len(annotated_images),
                "with_description": len(has_desc),
                "filename_only": len(filename_only),
                "fallback_eligible": len(has_b64),
                "no_fallback": len(no_b64),
            })

            needs_description = [
                img for img in annotated_images
                if _is_filename_like(img.get("summary", "")) and img.get("_image_base64")
            ]
            if needs_description:
                logger.info(f"[metrics] Vision fallback: {len(needs_description)} images need GPT-4o-mini description")

                async def _fill_description(img: dict) -> None:
                    nonlocal vision_fallback_ok, vision_fallback_failed
                    try:
                        desc = await _describe_image_with_vision(img["_image_base64"], clients=clients)
                        if desc:
                            img["summary"] = desc
                            img["image_type"] = img.get("image_type") or "image"
                            vision_fallback_ok += 1
                            logger.info(f"[metrics] Vision fallback OK for {img.get('id')}: '{desc[:80]}'")
                        else:
                            vision_fallback_failed += 1
                            logger.warning(f"[metrics] Vision fallback returned empty for {img.get('id')}")
                    except Exception as e:
                        vision_fallback_failed += 1
                        logger.warning(f"[metrics] Vision fallback failed for {img.get('id')}: {e}")

                await asyncio.gather(*[_fill_description(img) for img in needs_description])

                span.add_event("vision.fallback_complete", {
                    "requested": len(needs_description),
                    "succeeded": vision_fallback_ok,
                    "failed": vision_fallback_failed,
                })

                # Inject GPT-4o-mini descriptions into the markdown so Phi-4
                # can use them as classification context
                enriched_notes = []
                for img in needs_description:
                    s = img.get("summary", "")
                    if s and not _is_filename_like(s):
                        img_id = img.get("id") or "image"
                        img_type = img.get("image_type") or "image"
                        enriched_notes.append(f"📎 **Image Context ({img_id})**: {img_type} - {s}")
                if enriched_notes:
                    content += (
                        "\n\n---\n**Visual Elements (enriched):**\n"
                        + "\n".join(enriched_notes)
                        + "\n---\n"
                    )
            elif filename_only:
                # Images need description but have no base64 for fallback
                logger.warning(
                    f"[metrics] Vision: {len(filename_only)} images have filename-only summaries "
                    f"but no base64 data for GPT-4o-mini fallback. "
                    f"Check that include_image_base64=True is set in OCR request."
                )
                span.add_event("vision.no_fallback_data", {
                    "count": len(filename_only),
                    "image_ids": [img.get("id", "unknown") for img in filename_only[:5]],
                })

            # Strip temporary base64 data from all images (not needed downstream)
            for img in annotated_images:
                img.pop("_image_base64", None)

        pages_count = len(ocr_pages)

        logger.info(f"[metrics] OCR Success: {pages_count} pages processed")
        if image_conversion_total_ms > 0:
            logger.info(f"[metrics] Image conversion (vision strategy): {image_conversion_total_ms:.1f}ms ({image_conversion_total_ms/pages_count:.1f}ms/page)")

        span.set_attribute("gen_ai.usage.pages_processed", pages_count)
        span.set_attribute("gen_ai.usage.input_tokens", usage_info.get("prompt_tokens", 0))
        span.set_attribute("gen_ai.usage.output_tokens", usage_info.get("completion_tokens", 0))
        if image_conversion_total_ms > 0:
            span.set_attribute("app.image_conversion_ms", image_conversion_total_ms)
        # Vision-specific telemetry attributes
        if enable_vision_enrichment:
            span.set_attribute("app.vision.total_images", len(annotated_images))
            span.set_attribute("app.vision.fallback_ok", vision_fallback_ok)
            span.set_attribute("app.vision.fallback_failed", vision_fallback_failed)
            described = sum(1 for img in annotated_images if not _is_filename_like(img.get("summary", "")))
            span.set_attribute("app.vision.images_with_description", described)
            span.set_attribute("app.vision.images_filename_only", len(annotated_images) - described)

    return {"markdown": content, "usage": usage_info, "images": annotated_images}


async def ocr_with_document_intelligence(
    base64_pdf: str,
    clients: Clients | None = None,
) -> dict:
    """
    Fallback OCR using Azure Document Intelligence (prebuilt-layout model).
    Returns text-only output (no images) in the same format as ocr_with_mistral.

    Used when Mistral OCR is unavailable (circuit breaker open or retries exhausted).
    Requires AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT to be configured.
    """
    if not config.DOC_INTELLIGENCE_ENDPOINT:
        raise RuntimeError("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT not configured — cannot use Document Intelligence fallback.")

    # Auth: prefer Managed Identity, fall back to key
    # v4.0 REST API expects Content-Type: application/json with base64Source body
    # Ref: https://learn.microsoft.com/en-us/rest/api/aiservices/document-models/analyze-document
    if config.DOC_INTELLIGENCE_KEY:
        headers = {
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": config.DOC_INTELLIGENCE_KEY,
        }
    else:
        clients_ref = clients or __import__("classymail.services.azure_clients", fromlist=["get_default_clients"]).get_default_clients()
        token = await clients_ref.credential.get_token("https://cognitiveservices.azure.com/.default")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token.token}",
        }

    base_url = config.DOC_INTELLIGENCE_ENDPOINT.rstrip("/")
    api_version = config.DOC_INTELLIGENCE_API_VERSION
    url = f"{base_url}/documentintelligence/documentModels/prebuilt-layout:analyze?api-version={api_version}&outputContentFormat=markdown"

    # Estimate raw PDF size for telemetry (without fully decoding)
    pdf_size_estimate = len(base64_pdf) * 3 // 4

    with tracer.start_as_current_span("document_intelligence_ocr") as span:
        span.set_attribute("gen_ai.system", "azure_document_intelligence")
        span.set_attribute("gen_ai.operation", "document.analyze")
        span.set_attribute("app.pdf_size_bytes", pdf_size_estimate)

        # v4.0 REST API: POST JSON body with base64Source field
        request_body = {"base64Source": base64_pdf}

        async with httpx.AsyncClient(timeout=180) as client:
            # Step 1: Submit the analysis request
            logger.info(f"[metrics] Document Intelligence OCR: submitting ~{pdf_size_estimate} bytes to {url}")
            resp = await client.post(url, json=request_body, headers=headers)

            if resp.status_code not in (200, 202):
                error_text = resp.text[:500]
                logger.error(f"[metrics] Document Intelligence OCR submit failed: {resp.status_code} - {error_text}")
                raise OCRFailed(
                    f"Document Intelligence submit failed: {resp.status_code} - {error_text}",
                    retryable=resp.status_code in (429, 500, 502, 503, 504),
                )

            # Step 2: Poll for results (202 = async operation)
            if resp.status_code == 202:
                operation_url = resp.headers.get("Operation-Location")
                if not operation_url:
                    raise OCRFailed("Document Intelligence: missing Operation-Location header")

                # Remove Content-Type for GET polling
                poll_headers = {k: v for k, v in headers.items() if k != "Content-Type"}

                max_polls = 60  # 60 * 3s = 3 minutes max
                for poll_idx in range(max_polls):
                    await asyncio.sleep(3)
                    poll_resp = await client.get(operation_url, headers=poll_headers)
                    poll_resp.raise_for_status()
                    poll_data = poll_resp.json()
                    status = poll_data.get("status", "")

                    if status == "succeeded":
                        result = poll_data.get("analyzeResult", {})
                        break
                    elif status == "failed":
                        error_detail = poll_data.get("error", {}).get("message", "Unknown error")
                        raise OCRFailed(f"Document Intelligence analysis failed: {error_detail}")
                    elif status in ("running", "notStarted"):
                        logger.debug(f"[metrics] Document Intelligence polling ({poll_idx + 1}/{max_polls}): {status}")
                        continue
                    else:
                        raise OCRFailed(f"Document Intelligence unexpected status: {status}")
                else:
                    raise OCRFailed("Document Intelligence analysis timed out after polling")
            else:
                # Synchronous response (200)
                result = resp.json().get("analyzeResult", {})

        # Step 3: Extract markdown content
        content = result.get("content", "")
        pages = result.get("pages", [])
        page_count = len(pages)

        if not content.strip():
            raise OCRFailed("Document Intelligence returned empty content")

        logger.info(
            f"[metrics] Document Intelligence OCR Success: {page_count} pages, "
            f"{len(content)} chars"
        )

        span.set_attribute("app.pages_processed", page_count)
        span.set_attribute("app.content_length", len(content))

        usage_info = {
            "pages_processed": page_count,
            "provider": "document_intelligence",
        }

        return {"markdown": content, "usage": usage_info, "images": []}


async def _classify_with_single_model(
    text_markdown: str,
    *,
    endpoint: str,
    deployment: str,
    strategy: str = "standard",
    api_version: str | None = None,
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

    if "(aucune catégorie" in categories_text.lower() or "(no categories" in categories_text.lower():
        logger.warning("[classify] No categories configured – classification will return empty intents")

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

LISTE DES INTENTIONS POSSIBLES (NOM + DÉFINITION + EXCLUSIONS) :
{categories_text}

RÈGLES DE CLASSIFICATION :
- Choisis les intentions dont la DÉFINITION correspond le mieux au contenu. Appuie-toi sur les mots/phrases clés des définitions.
- Les EXCLUSIONS précisent ce que chaque catégorie ne doit PAS inclure. Utilise-les pour éliminer les faux positifs.
- Un email peut contenir UNE SEULE intention OU PLUSIEURS intentions.
- Si aucune intention ne correspond vraiment, retourne une liste vide (detected_intents: []). NE PAS deviner.
- Assigne un score de confiance (0.0 à 1.0) pour CHAQUE intention détectée.
- La justification DOIT citer un extrait du texte et/ou la définition de la catégorie correspondante.

EXTRACTION DU SENDER (Expéditeur) - PRIORITAIRE :
Pour le sender, cherche en priorité :
1. Email address (pattern: xxx@xxx.xxx) - récupère le PREMIER email trouvé
2. "From:", "De:", "Sender:" suivi d'un nom ou email
3. Signature à la fin (ex: "Cordialement, Jean Dupont")
4. Si trouvé: retourne le sender. Sinon: retourne null (pas "Non identifiable")

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
    "subject": "Sujet ou Objet de l'email extrait du texte (ou null si absent)",
    "sender": "Email address or name extracted (ex: 'john@example.com' or 'John Dupont'). Use null if not found."
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
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        **build_chat_params(deployment, temperature=0.1, max_output_tokens=config.PHI_RESERVED_OUTPUT_TOKENS),
    }
    if supports_response_format(deployment):
        payload["response_format"] = {"type": "json_object"}

    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version or config.AI_API_VERSION}"

    logger.info(f"[metrics] Classify Request: {deployment} strategy={strategy} reasoning={not supports_response_format(deployment)}")
    logger.info(f"[metrics] Token Estimate: system={system_tokens} user={user_tokens_est} truncated={truncated}")

    limiter = get_limiter("phi")

    with tracer.start_as_current_span(f"classify_{deployment}") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.operation", "chat.completions")
        span.set_attribute("gen_ai.request.model", deployment)
        span.set_attribute("app.context_truncated", bool(truncated))
        span.set_attribute("app.estimated.user_tokens", int(user_tokens_est))
        span.set_attribute("app.user_budget_tokens", int(max_user))

        async with httpx.AsyncClient(timeout=120) as client:
            try:
                # Best-effort TPM gating
                while not await limiter.consume_if_allowed(user_tokens_est + config.PHI_RESERVED_OUTPUT_TOKENS):
                    await asyncio.sleep(1)

                async with limiter:
                    resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPStatusError as ex:
                status = ex.response.status_code if ex.response is not None else None
                body = ex.response.text if ex.response is not None else ""
                logger.error(f"[metrics] Classify Failed ({deployment}): {status} - {body}")
                raise

            data = resp.json()
            content = extract_message_content(data.get("choices", [{}])[0].get("message", {})) or "{}"
            usage = data.get("usage", {})

            logger.info(f"[metrics] Classify Success ({deployment}): {usage.get('total_tokens', 0)} tokens used")
            logger.info(f"[metrics] Response preview: {content[:200]}...")

            span.set_attribute("gen_ai.usage.input_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.output_tokens", usage.get("completion_tokens", 0))
            span.set_attribute("gen_ai.usage.total_tokens", usage.get("total_tokens", 0))

            # Parse JSON – reasoning models may wrap JSON in markdown fences
            try:
                payload_dict = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code fences or mixed text
                import re
                json_match = re.search(r'```(?:json)?\s*\n?(\{.*?\})\s*```', content, re.DOTALL)
                if not json_match:
                    json_match = re.search(r'(\{[^{}]*"detected_intents"[^{}]*\})', content, re.DOTALL)
                if json_match:
                    logger.warning(f"[metrics] Classify ({deployment}): Extracted JSON from non-JSON response")
                    payload_dict = json.loads(json_match.group(1))
                else:
                    logger.error(f"[metrics] Classify ({deployment}): Failed to parse response as JSON: {content[:300]}")
                    raise

            payload_dict["usage"] = usage
            payload_dict["model"] = deployment
            payload_dict["context_truncated"] = bool(truncated)
            payload_dict["estimated_user_tokens"] = int(user_tokens_est)
            return payload_dict


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception(retryable_httpx))
async def classify_with_phi4(text_markdown: str, *, force_fallback: bool = False, strategy: str = "standard", clients: Clients | None = None) -> dict:
    """
    Classify email with Primary LLM (or fallback to secondary if token budget exceeded).

    Args:
        text_markdown: Email content in markdown format
        force_fallback: Force use of fallback model
        strategy: "standard", "reasoning", or "vision" - affects system prompt
        clients: Optional pre-configured clients (for testing/DI)

    Returns:
        Classification result dict with intents, complexity, usage, model info,
        optional PII data and preprocessing metadata
    """
    if not config.PHI_ENDPOINT:
        raise RuntimeError("PHI_ENDPOINT is not set")
    if not config.PHI_FALLBACK_ENDPOINT:
        raise RuntimeError("PHI_FALLBACK_ENDPOINT is not set")

    # --- EMAIL PREPROCESSING (Client G2S) ---
    preprocessing_metadata = {}
    pii_result = None
    settings = load_settings()
    preprocessing_config = settings.get("email_preprocessing", {})

    # Apply preprocessing if enabled
    if preprocessing_config.get("enabled", True):
        try:
            text_markdown, preprocessing_metadata = await preprocess_email_content(
                text_markdown,
                clients=clients,
                override_settings=settings
            )
            logger.info(f"Preprocessing applied: {preprocessing_metadata}")
        except Exception as e:
            logger.warning(f"Preprocessing failed, using original content: {e}")
            preprocessing_metadata = {"error": str(e)}

    # PII Detection if enabled (default True — matches DEFAULT_SETTINGS)
    if preprocessing_config.get("detect_pii", True):
        try:
            pii_method = preprocessing_config.get("pii_detection_method", "llm")
            pii_llm_model = preprocessing_config.get("pii_llm_model", "auto")
            # Resolve "auto" to the classification model
            if pii_llm_model in ("auto", None, ""):
                pii_llm_model = settings.get("ai_model", "phi4")
            # Resolve friendly model name to actual Azure deployment name
            # e.g. "phi4" → config.PHI_DEPLOYMENT ("Phi-4")
            _, resolved_deployment, _ = resolve_model_config(pii_llm_model)
            logger.info(f"Running PII detection with method: {pii_method}, model: {pii_llm_model} → deployment: {resolved_deployment}")
            pii_result = await detect_pii(text_markdown, method=pii_method, clients=clients, model=resolved_deployment)
            logger.info(f"PII detection: {pii_result.total_count} items ({', '.join(pii_result.pii_types)})")
        except Exception as e:
            logger.warning(f"PII detection failed: {e}")

    # --- CONTINUE WITH CLASSIFICATION ---
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

        # Add preprocessing metadata and PII to result
        if preprocessing_metadata:
            result["preprocessing_metadata"] = preprocessing_metadata
        if pii_result:
            result["detected_pii"] = pii_result.model_dump()
            result["pii_detected"] = pii_result.has_pii

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


def resolve_model_config(model_key: str) -> tuple[str, str, str]:
    """
    Resolves a model key/name to an (endpoint, deployment, api_version) tuple.

    Most models use the default ``config.AI_API_VERSION``.
    Kimi-K2.5 requires ``2024-05-01-preview``.
    """
    k = model_key.lower().strip()
    default_api_version: str = config.AI_API_VERSION

    # Models that need a non-default api-version
    _MODEL_API_VERSIONS: dict[str, str] = {
        "kimi-k2.5": "2024-05-01-preview",
    }

    def _api_version_for(deployment: str) -> str:
        return _MODEL_API_VERSIONS.get(deployment.lower(), default_api_version)

    # Direct match with configured deployments (preferred)
    if config.PHI_DEPLOYMENT and k == config.PHI_DEPLOYMENT.lower():
         return config.PHI_ENDPOINT, config.PHI_DEPLOYMENT, _api_version_for(config.PHI_DEPLOYMENT)
    if config.PHI_FALLBACK_DEPLOYMENT and k == config.PHI_FALLBACK_DEPLOYMENT.lower():
         return config.PHI_FALLBACK_ENDPOINT, config.PHI_FALLBACK_DEPLOYMENT, _api_version_for(config.PHI_FALLBACK_DEPLOYMENT)

    # Aliases
    if k in ("phi-4", "phi4", "standard", "primary"):
        return config.PHI_ENDPOINT, config.PHI_DEPLOYMENT, default_api_version
    if k in ("gpt-4o-mini", "gpt4o-mini", "gpt4o_mini", "fallback", "audit"):
        return config.PHI_FALLBACK_ENDPOINT, config.PHI_FALLBACK_DEPLOYMENT, default_api_version

    # Kimi K2.5 (Moonshot AI via Foundry) – deployed on the primary endpoint
    if k in ("kimi-k2.5", "kimi_k2.5", "kimik2.5"):
        return config.PHI_ENDPOINT, "Kimi-K2.5", "2024-05-01-preview"

    # Fallback/Generic: Assume the key is the deployment name on the primary endpoint
    # This supports 'gpt5-nano', 'gpt4.1-nano' etc. if they are deployed on the same resource
    return config.PHI_ENDPOINT, model_key, _api_version_for(model_key)


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
        endpoint, deployment, _api_ver = resolve_model_config(m)
        if not endpoint:
             logger.warning(f"No endpoint found for model '{m}', skipping")
             continue

        resolved_names.append(m)
        tasks.append(_classify_with_single_model(
            text_markdown,
            endpoint=endpoint,
            deployment=deployment,
            strategy=strategy,
            api_version=_api_ver,
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

    # Calculate confidence_delta: max - min of top-intent confidences
    confidence_delta = None
    top_confidences = []
    for res in model_results.values():
        intents = res.get("detected_intents") or []
        if intents:
            top_confidences.append(intents[0].get("confidence", 0.0))
        elif not res.get("error"):
            top_confidences.append(0.0)
    if len(top_confidences) >= 2:
        confidence_delta = max(top_confidences) - min(top_confidences)

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
            "confidence_delta": confidence_delta,
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
        **build_chat_params(config.PHI_DEPLOYMENT, temperature=0.3, max_output_tokens=150),
    }

    url = f"{config.PHI_ENDPOINT.rstrip('/')}/openai/deployments/{config.PHI_DEPLOYMENT}/chat/completions?api-version={config.AI_API_VERSION}"

    try:
        async with httpx.AsyncClient(timeout=10) as client: # Fast timeout for UI responsiveness
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return (extract_message_content(data.get("choices", [{}])[0].get("message", {})) or "").strip()
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
