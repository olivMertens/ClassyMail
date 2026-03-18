from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from classymail.models import EmailRecord, ClassificationResult
from classymail.services.azure_clients import download_blob_as_base64, blob_id_from_url, Clients
from classymail.services.llm_pipeline import ocr_with_mistral, ocr_with_document_intelligence, classify_with_phi4, process_agent_response, generate_embedding, extract_business_entities
from classymail.services.circuit_breaker import mistral_ocr_breaker, doc_intelligence_breaker
from classymail.services.costing import compute_cost_di, compute_cost_llm, compute_cost_mistral
from classymail.models import ContentFilterError
from classymail.core import config
import logging

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def chunk_markdown(markdown: str, chunk_size: int = 2000, overlap: int = 200) -> list[dict]:
    """
    Splits markdown into overlapping chunks for RAG.
    Returns list of {index, content} dicts.
    """
    if not markdown:
        return []
    chunks: list[dict] = []
    start = 0
    n = len(markdown)
    while start < n:
        end = min(n, start + chunk_size)
        content = markdown[start:end]
        chunks.append({"index": len(chunks), "content": content})
        if end == n:  # Reached the end
            break
        start = end - overlap
        if start < 0:
            start = 0
    return chunks


def estimate_pdf_pages(pdf_bytes: bytes) -> int:
    try:
        return max(pdf_bytes.count(b"/Type /Page"), 1)
    except Exception:
        return 1



async def run_classification_pipeline(
    blob_url: str,
    *,
    settings: Optional[dict] = None,
    cost_overrides: Optional[dict] = None, # Legacy support
    clients: Clients | None = None,
    locale: str = "en",
) -> EmailRecord:
    import time

    processing_log: list[dict] = []
    stage_timings = {}  # Track timing for each stage
    ocr_detail = {}  # Extra OCR diagnostic metadata

    logger.info(f"[pipeline] -> Starting pipeline for: {blob_url}")

    # Merge overrides if provided separately (legacy) or extract from settings
    if settings:
        final_overrides = settings.get("cost_overrides", {})
        strategy = settings.get("processing_strategy", "standard")
    else:
        final_overrides = cost_overrides or {}
        strategy = "standard"

    span = tracer.start_span("pipeline.classification")
    span.set_attribute("app.blob_url", blob_url)
    span.set_attribute("app.strategy", strategy)

    def log(stage: str, event: str, detail: Optional[str] = None) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "event": event,
            "detail": detail,
        }
        processing_log.append(entry)
        logger.info(f"[pipeline] [{stage}] {event}" + (f": {detail}" if detail else ""))

    try:
        log("download", "start")
        stage_start = time.perf_counter()
        pdf_b64, pdf_bytes = await download_blob_as_base64(blob_url, return_bytes=True, clients=clients)
        stage_timings["download"] = (time.perf_counter() - stage_start) * 1000
        log("download", "ok", f"{len(pdf_bytes)} bytes ({stage_timings['download']:.0f}ms)")
    except Exception as ex:
        from classymail.models import OCRFailed

        log("download", "error", f"{type(ex).__name__}: {ex}")
        err = OCRFailed(f"stage=download: {type(ex).__name__}: {ex}")
        setattr(err, "processing_log", processing_log)
        span.set_status(Status(StatusCode.ERROR, str(ex)))
        span.end()
        raise err from ex

    ocr_provider = "mistral_ocr"  # Track which OCR provider was used

    try:
        log("ocr", "start")
        stage_start = time.perf_counter()
        # Enable image extraction only if strategy is 'vision' to save costs/latency
        include_img = (strategy == "vision")

        mistral_failed = False
        mistral_error = None

        # Check circuit breaker state before attempting Mistral
        if mistral_ocr_breaker.current_state == "open":
            log("ocr", "circuit_breaker", "Mistral OCR circuit breaker is OPEN — skipping to fallback")
            mistral_failed = True
            mistral_error = "Circuit breaker open"
            ocr_detail["mistral_skip_reason"] = "circuit_breaker_open"
        else:
            try:
                ocr_result = await ocr_with_mistral(
                    pdf_b64,
                    clients=clients,
                    include_images=include_img,
                    enable_vision_enrichment=include_img
                )
                # Record success on circuit breaker
                mistral_ocr_breaker.success()
            except Exception as mistral_ex:
                mistral_failed = True
                mistral_error = f"{type(mistral_ex).__name__}: {mistral_ex}"
                ocr_detail["mistral_error_type"] = type(mistral_ex).__name__
                log("ocr", "mistral_failed", mistral_error)
                # Record failure on circuit breaker
                from classymail.services.circuit_breaker import should_trip_on_exception
                if should_trip_on_exception(mistral_ex):
                    mistral_ocr_breaker.failure()

        # Fallback to Document Intelligence if Mistral failed and DI is configured
        if mistral_failed:
            if config.DOC_INTELLIGENCE_ENDPOINT:
                log("ocr", "fallback", "Attempting Document Intelligence OCR fallback")
                ocr_provider = "document_intelligence"

                if doc_intelligence_breaker.current_state == "open":
                    from classymail.models import OCRFailed as _OCRFailed
                    log("ocr", "error", "Both OCR providers unavailable (circuit breakers open)")
                    err = _OCRFailed(f"stage=ocr: All OCR providers failed. Mistral: {mistral_error}. Document Intelligence circuit breaker open.")
                    setattr(err, "processing_log", processing_log)
                    span.set_status(Status(StatusCode.ERROR, "All OCR providers failed"))
                    span.end()
                    raise err

                try:
                    ocr_result = await ocr_with_document_intelligence(pdf_b64, clients=clients)
                    doc_intelligence_breaker.success()
                    log("ocr", "fallback_ok", "Document Intelligence OCR succeeded")
                except Exception as di_ex:
                    from classymail.models import OCRFailed as _OCRFailed
                    from classymail.services.circuit_breaker import should_trip_on_exception
                    if should_trip_on_exception(di_ex):
                        doc_intelligence_breaker.failure()
                    log("ocr", "error", f"Document Intelligence also failed: {di_ex}")
                    err = _OCRFailed(f"stage=ocr: All OCR providers failed. Mistral: {mistral_error}. DocIntel: {di_ex}")
                    setattr(err, "processing_log", processing_log)
                    span.set_status(Status(StatusCode.ERROR, str(di_ex)))
                    span.end()
                    raise err from di_ex
            else:
                from classymail.models import OCRFailed as _OCRFailed
                log("ocr", "error", f"Mistral OCR failed and no fallback configured: {mistral_error}")
                err = _OCRFailed(f"stage=ocr: {mistral_error}")
                setattr(err, "processing_log", processing_log)
                span.set_status(Status(StatusCode.ERROR, mistral_error))
                span.end()
                raise err

        stage_timings["ocr"] = (time.perf_counter() - stage_start) * 1000
        if ocr_detail:
            stage_timings["ocr_detail"] = ocr_detail
        log("ocr", "ok", f"provider={ocr_provider} ({stage_timings['ocr']:.0f}ms)")
    except Exception as ex:
        # Only re-raise if not already handled above
        if "stage=ocr" in str(ex):
            raise
        from classymail.models import OCRFailed

        log("ocr", "error", f"{type(ex).__name__}: {ex}")
        err = OCRFailed(f"stage=ocr: {type(ex).__name__}: {ex}")
        setattr(err, "processing_log", processing_log)
        span.set_status(Status(StatusCode.ERROR, str(ex)))
        span.end()
        raise err from ex

    markdown = ocr_result.get("markdown") or ""
    mistral_images = ocr_result.get("images", [])

    # Extract generic entities (Broad Net Strategy)
    entities_data = None
    entities_usage = None
    try:
        log("extraction", "start")
        stage_start = time.perf_counter()
        # Run in parallel with classification potentially? For now sequential to keep logs clean
        # and maybe allow injection later.
        extraction_result = await extract_business_entities(markdown, clients=clients)
        entities_data = extraction_result.get("entities")
        entities_usage = extraction_result.get("usage")
        stage_timings["extraction"] = (time.perf_counter() - stage_start) * 1000
        log("extraction", "ok", f"Found {len(entities_data.get('dates', []))} dates, {len(entities_data.get('reference_numbers', []))} refs ({stage_timings['extraction']:.0f}ms)")
    except Exception as ex:
        log("extraction", "error", f"Entity extraction failed (non-critical): {ex}")
        # Non-critical, continue

    try:
        log("classify", "start")
        stage_start = time.perf_counter()
        classification_raw = await classify_with_phi4(markdown, strategy=strategy, clients=clients, locale=locale)
        stage_timings["classify"] = (time.perf_counter() - stage_start) * 1000
        log("classify", "ok", f"({stage_timings['classify']:.0f}ms)")
    except ContentFilterError as cf_ex:
        stage_timings["classify"] = (time.perf_counter() - stage_start) * 1000
        log("classify", "content_filtered", f"Content filter triggered on {cf_ex.deployment}")
        logger.warning(f"[pipeline] Content filter triggered: {cf_ex}")

        span.set_attribute("app.content_filter.triggered", True)
        span.set_attribute("app.result_status", "CONTENT_FILTERED")

        record = EmailRecord(
            id=blob_id_from_url(blob_url),
            file_url=blob_url,
            markdown=markdown[:30000] if markdown else None,
            processing_strategy=strategy,
            ocr_provider=ocr_provider,
            stage_timings=stage_timings,
            status="CONTENT_FILTERED",
            content_filter_result=cf_ex.filter_result,
            error=str(cf_ex),
            error_stage="classify",
            updated_at=datetime.now(timezone.utc),
            processing_log=processing_log,
        )
        span.set_attribute("app.result_id", record.id)
        span.set_status(Status(StatusCode.ERROR, "Content filter triggered"))
        span.end()
        return record
    except Exception as ex:
        from classymail.models import OCRFailed

        log("classify", "error", f"{type(ex).__name__}: {ex}")
        err = OCRFailed(f"stage=classify: {type(ex).__name__}: {ex}")
        setattr(err, "processing_log", processing_log)
        span.set_status(Status(StatusCode.ERROR, str(ex)))
        span.end()
        raise err from ex
    processed = process_agent_response(classification_raw)

    # Generate Embeddings
    vector = []
    chunk_docs: list[dict] = []
    try:
        log("embedding", "start")
        stage_start = time.perf_counter()
        if markdown:
            vector = await generate_embedding(markdown, clients=clients)
            # Chunking & chunk embeddings for RAG
            chunks = chunk_markdown(markdown)
            for ch in chunks:
                ch_vec = []
                try:
                    ch_vec = await generate_embedding(ch["content"], clients=clients)
                except Exception as ex_inner:
                    log("embedding", "warn", f"Chunk {ch['index']} embed failed: {ex_inner}")
                chunk_docs.append({
                    "index": ch["index"],
                    "content": ch["content"],
                    "vector": ch_vec,
                })
        stage_timings["embedding"] = (time.perf_counter() - stage_start) * 1000
        log("embedding", "ok", f"dim={len(vector)} chunks={len(chunk_docs)} ({stage_timings['embedding']:.0f}ms)")
    except Exception as ex:
        log("embedding", "error", f"Failed to generate embedding: {ex}")
        # We generally don't want to fail the whole pipeline if embedding fails,
        # but we should log it.

    status = "REVIEW_REQUIRED" if processed.get("needs_review") else "PROCESSED"
    markdown_trunc = markdown[:30000] if markdown else None

    mistral_usage = ocr_result.get("usage") or {}
    pages = mistral_usage.get("pages_processed") or mistral_usage.get("pages") or estimate_pdf_pages(pdf_bytes)
    stage_timings["pages"] = pages

    llm_usage = classification_raw.get("usage") if isinstance(classification_raw, dict) else None
    fallback_used = bool(classification_raw.get("fallback_used")) if isinstance(classification_raw, dict) else False
    model_name = classification_raw.get("model") if isinstance(classification_raw, dict) else None
    if fallback_used:
        stage_timings["classify_detail"] = {"fallback_model": model_name or "gpt-4o-mini"}

    # Calculate costs with model-aware pricing
    llm_cost = compute_cost_llm(llm_usage, fallback_used=fallback_used, model_name=model_name, overrides=final_overrides)
    # Add extraction cost (uses same model/pricing approx)
    extraction_cost = compute_cost_llm(entities_usage, fallback_used=False, model_name=model_name, overrides=final_overrides) if entities_usage else 0.0

    total_phi4_cost = (llm_cost or 0.0) + (extraction_cost or 0.0)

    # Build OCR cost block based on actual provider
    if ocr_provider == "document_intelligence":
        ocr_cost_block = {
            "estimated_pages": pages,
            "cost_usd": compute_cost_di(pages, overrides=final_overrides),
            "annotations_count": len(mistral_images),
        }
        mistral_block = {"estimated_pages": 0, "cost_usd": 0.0, "annotations_count": 0}
    else:
        ocr_cost_block = {
            "estimated_pages": pages,
            "cost_usd": compute_cost_mistral(pages, overrides=final_overrides),
            "annotations_count": len(mistral_images),
        }
        mistral_block = ocr_cost_block

    usage = {
        "phi4": llm_usage,
        "phi4_cost_usd": total_phi4_cost, # Aggregate cost
        "phi4_model": classification_raw.get("model") if isinstance(classification_raw, dict) else None,
        "phi4_fallback_used": fallback_used,
        "phi4_context_truncated": bool(classification_raw.get("context_truncated")) if isinstance(classification_raw, dict) else False,
        "extraction_usage": entities_usage, # detailed usage for extraction
        "mistral": mistral_block,
        "doc_intelligence": ocr_cost_block if ocr_provider == "document_intelligence" else None,
    }

    # Extract metadata from JSON response if present
    response_data = processed.get("raw_response", {})

    from classymail.models import BusinessEntities

    # Extract PII results from classification if present
    pii_detected_val = classification_raw.get("pii_detected", False) if isinstance(classification_raw, dict) else False
    pii_data_val = classification_raw.get("detected_pii") if isinstance(classification_raw, dict) else None
    preprocessing_meta = classification_raw.get("preprocessing_metadata") if isinstance(classification_raw, dict) else None

    record = EmailRecord(
        id=blob_id_from_url(blob_url),
        file_url=blob_url,
        markdown=markdown_trunc,
        subject=response_data.get("subject"),
        sender=response_data.get("sender"),
        vector=vector,
        processing_strategy=strategy,
        ocr_provider=ocr_provider,
        stage_timings=stage_timings,
        classification=ClassificationResult(
            **{
                "detected_intents": processed.get("intents", []),
                "global_complexity": response_data.get("global_complexity")
                if processed.get("raw_response")
                else None,
                "classification_reason": response_data.get("classification_reason"),
                "needs_review": processed.get("needs_review", False),
                "raw_response": processed.get("raw_response"),
            }
        ),
        entities=BusinessEntities(**entities_data) if entities_data else None,
        vision_analysis=mistral_images if mistral_images else None,
        pii_detected=pii_detected_val,
        pii_data=pii_data_val,
        preprocessing_metadata=preprocessing_meta,
        status=status,
        usage=usage,
        updated_at=datetime.now(timezone.utc),
        processing_log=processing_log,
    )
    if chunk_docs:
        setattr(record, "chunks", chunk_docs)

    # Log stage timing summary for performance diagnostics
    total_ms = sum(v for v in stage_timings.values() if isinstance(v, (int, float)))
    timing_summary = " | ".join([f"{stage}={ms:.0f}ms" for stage, ms in sorted(stage_timings.items()) if isinstance(ms, (int, float))])
    logger.info(f"[pipeline] STAGE_TIMINGS: {timing_summary} | TOTAL={total_ms:.0f}ms")

    # Vision analysis telemetry
    if strategy == "vision" and mistral_images:
        described = sum(1 for img in mistral_images if img.get("summary") and not img["summary"].strip().endswith((".jpeg", ".png", ".jpg", ".gif")))
        span.set_attribute("app.vision.images_total", len(mistral_images))
        span.set_attribute("app.vision.images_described", described)
        span.add_event("vision.pipeline_complete", {
            "strategy": strategy,
            "images_total": len(mistral_images),
            "images_described": described,
            "images_filename_only": len(mistral_images) - described,
        })
        logger.info(f"[pipeline] Vision analysis: {len(mistral_images)} images, {described} with descriptions, {len(mistral_images) - described} filename-only")

    span.set_attribute("app.result_status", status)
    span.set_attribute("app.result_id", record.id)
    span.set_attribute("app.stage_timings", {k: (f"{v:.0f}ms" if isinstance(v, (int, float)) else str(v)) for k, v in stage_timings.items()})
    span.set_status(Status(StatusCode.OK))
    span.end()
    return record
