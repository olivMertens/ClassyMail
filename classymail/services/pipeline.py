from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from classymail.models import EmailRecord, ClassificationResult
from classymail.services.azure_clients import download_blob_as_base64, blob_id_from_url, Clients
from classymail.services.llm_pipeline import ocr_with_mistral, classify_with_phi4, process_agent_response, generate_embedding, extract_business_entities, classify_comparison
from classymail.services.costing import compute_cost_llm, compute_cost_mistral
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


async def run_reclassification_pipeline(
    item_id: str,
    *,
    models: list[str] = None,
    clients: Clients | None = None,
) -> EmailRecord:
    """
    Orchestrates reclassification (comparison) without re-running OCR.
    Reads existing markdown from Cosmos, runs comparison, updates record.
    """
    if models is None:
        models = [config.PHI_DEPLOYMENT, config.PHI_FALLBACK_DEPLOYMENT]

    with tracer.start_as_current_span("pipeline.reclassification") as span:
        span.set_attribute("app.item_id", item_id)
        span.set_attribute("app.models", ",".join(models))

        logger.info(f"[pipeline] -> Starting reclassification for item: {item_id} with models={models}")

        await clients.ensure_cosmos_container()
        try:
            item_data = await clients.cosmos_container.read_item(item=item_id, partition_key=item_id)
            email_accord = EmailRecord(**item_data)
        except Exception as e:
            logger.error(f"Failed to fetch item {item_id}: {e}")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

        if not email_accord.markdown:
            raise ValueError(f"Item {item_id} has no markdown content, cannot reclassify.")

        # Run Comparison
        comparison_result = await classify_comparison(email_accord.markdown, models=models, clients=clients)

        # Store result
        meta = comparison_result.get("comparison_meta", {})
        comparison_record = {
            "meta": {
                "executed_at": meta.get("executed_at", datetime.now(timezone.utc).isoformat()),
                "agreement": meta.get("agreement", False),
                "confidence_delta": meta.get("confidence_delta", 0.0),
                "elapsed_ms": meta.get("elapsed_ms", 0),
            },
            "model_results": comparison_result.get("model_results", {}),
            "mode": "async", # This ran via worker
            # Legacy fields
            "phi4": comparison_result.get("phi4"),
            "gpt4o_mini": comparison_result.get("gpt4o_mini")
        }

        # Append to existing results
        if not email_accord.comparison_results:
            email_accord.comparison_results = []

        email_accord.comparison_results.append(comparison_record)
        email_accord.updated_at = datetime.now(timezone.utc)
        span.set_attribute("app.agreement", meta.get("agreement", False))
        span.set_status(Status(StatusCode.OK))

        # We return the updated record. The worker will save it.
        return email_accord


async def run_classification_pipeline(
    blob_url: str,
    *,
    settings: Optional[dict] = None,
    cost_overrides: Optional[dict] = None, # Legacy support
    clients: Clients | None = None,
) -> EmailRecord:
    import time

    processing_log: list[dict] = []
    stage_timings = {}  # Track timing for each stage

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

    try:
        log("ocr", "start")
        stage_start = time.perf_counter()
        # Enable image extraction only if strategy is 'vision' to save costs/latency
        include_img = (strategy == "vision")
        # Vision uses OCR-rendered page images only (no attachments). Enrichment annotates those page images.
        # Use new enrichment capability for vision strategy
        ocr_result = await ocr_with_mistral(
            pdf_b64,
            clients=clients,
            include_images=include_img,
            enable_vision_enrichment=include_img
        )
        stage_timings["ocr"] = (time.perf_counter() - stage_start) * 1000
        log("ocr", "ok")
    except Exception as ex:
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
        classification_raw = await classify_with_phi4(markdown, strategy=strategy, clients=clients)
        stage_timings["classify"] = (time.perf_counter() - stage_start) * 1000
        log("classify", "ok", f"({stage_timings['classify']:.0f}ms)")
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

    llm_usage = classification_raw.get("usage") if isinstance(classification_raw, dict) else None
    fallback_used = bool(classification_raw.get("fallback_used")) if isinstance(classification_raw, dict) else False
    model_name = classification_raw.get("model") if isinstance(classification_raw, dict) else None

    # Calculate costs with model-aware pricing
    llm_cost = compute_cost_llm(llm_usage, fallback_used=fallback_used, model_name=model_name, overrides=final_overrides)
    # Add extraction cost (uses same model/pricing approx)
    extraction_cost = compute_cost_llm(entities_usage, fallback_used=False, model_name=model_name, overrides=final_overrides) if entities_usage else 0.0

    total_phi4_cost = llm_cost + extraction_cost

    usage = {
        "phi4": llm_usage,
        "phi4_cost_usd": total_phi4_cost, # Aggregate cost
        "phi4_model": classification_raw.get("model") if isinstance(classification_raw, dict) else None,
        "phi4_fallback_used": fallback_used,
        "phi4_context_truncated": bool(classification_raw.get("context_truncated")) if isinstance(classification_raw, dict) else False,
        "extraction_usage": entities_usage, # detailed usage for extraction
        "mistral": {
            "estimated_pages": pages,
            "cost_usd": compute_cost_mistral(pages, overrides=final_overrides),
            "annotations_count": len(mistral_images)
        },
    }

    # Extract metadata from JSON response if present
    response_data = processed.get("raw_response", {})

    from classymail.models import BusinessEntities

    # Extract PII results from classification if present
    pii_detected_val = classification_raw.get("pii_detected", False) if isinstance(classification_raw, dict) else False
    pii_data_val = classification_raw.get("detected_pii") if isinstance(classification_raw, dict) else None
    preprocessing_meta = classification_raw.get("preprocessing_metadata") if isinstance(classification_raw, dict) else None

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
    total_ms = sum(stage_timings.values())
    timing_summary = " | ".join([f"{stage}={ms:.0f}ms" for stage, ms in sorted(stage_timings.items())])
    logger.info(f"[pipeline] STAGE_TIMINGS: {timing_summary} | TOTAL={total_ms:.0f}ms")

    span.set_attribute("app.result_status", status)
    span.set_attribute("app.result_id", record.id)
    span.set_attribute("app.stage_timings", {k: f"{v:.0f}ms" for k, v in stage_timings.items()})
    span.set_status(Status(StatusCode.OK))
    span.end()
    return record
