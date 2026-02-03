from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse

from azure.servicebus import ServiceBusMessage
from azure.storage.blob.aio import BlobClient

from classificationg2s.core import config
from classificationg2s.models import EmailListResponse, EmailRecord
from classificationg2s.services.azure_clients import (
    get_cosmos_container,
    get_sb_client,
    get_clients,
    Clients,
)
from classificationg2s.services.repository import (
    count_by_status,
    count_reviewed_ready_items,
    export_finetune_jsonl_iter,
    compute_search_text,
    get_average_confidence,
)
from classificationg2s.services.llm_pipeline import analyze_correction
from classificationg2s.services.settings_store import load_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["emails"])


@router.get("/emails", response_model=EmailListResponse)
async def list_emails(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query("all", pattern="^(all|REVIEW_REQUIRED|PROCESSED|ERROR)$"),
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    confidence_filter: Optional[str] = Query(None, pattern="^(lt_10|lt_30|lt_50|lt_90|eq_100)$"),
    continuation_token: Optional[str] = Query(None),
    cosmos_container=Depends(get_cosmos_container),
    clients: Clients = Depends(get_clients),
):
    try:
        filters = []
        params = {}
        if status != "all":
            filters.append("c.status = @status")
            params["@status"] = status

        # Search filter
        if search:
            filters.append("IS_DEFINED(c.search_text) AND CONTAINS(c.search_text, @search)")
            params["@search"] = search

        # Category/Intent filter
        # If category is provided, we check if ANY intent matches that category.
        # If confidence_filter is ALSO provided, we check for that specific category's confidence.
        if category:
            params["@category"] = category

            if confidence_filter:
                limit = 1.0
                op = "<"
                if confidence_filter == "lt_10":
                    limit = 0.1
                elif confidence_filter == "lt_30":
                    limit = 0.3
                elif confidence_filter == "lt_50":
                    limit = 0.5
                elif confidence_filter == "lt_90":
                    limit = 0.9
                elif confidence_filter == "eq_100":
                    limit = 0.99
                    op = ">="

                params["@conf_limit"] = limit
                # Check for specific intent AND confidence
                filters.append(f"EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.intent = @category AND i.confidence {op} @conf_limit)")
            else:
                 # Just category existence
                filters.append("EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.intent = @category)")

        # Confidence filter ONLY (no category specific)
        # Assuming:
        # "less than X" -> Max confidence of any intent is < X (i.e. NO intent is >= X)
        # "100%" -> At least one intent is >= 0.99
        elif confidence_filter:
            limit = 1.0
            if confidence_filter == "lt_10":
                limit = 0.1
                # "All intents < 0.1" <=> "Not Exists intent >= 0.1"
                # Also ensure detected_intents exists and has items? Or just 0 items is fine?
                # Usually we want items that HAVE intents but they are low.
                params["@conf_limit"] = limit
                filters.append("IS_DEFINED(c.classification.detected_intents) AND ARRAYS_LENGTH(c.classification.detected_intents) > 0")
                filters.append("NOT EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

            elif confidence_filter == "lt_30":
                limit = 0.3
                params["@conf_limit"] = limit
                filters.append("IS_DEFINED(c.classification.detected_intents) AND ARRAYS_LENGTH(c.classification.detected_intents) > 0")
                filters.append("NOT EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

            elif confidence_filter == "lt_50":
                limit = 0.5
                params["@conf_limit"] = limit
                filters.append("IS_DEFINED(c.classification.detected_intents) AND ARRAYS_LENGTH(c.classification.detected_intents) > 0")
                filters.append("NOT EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

            elif confidence_filter == "lt_90":
                limit = 0.9
                params["@conf_limit"] = limit
                filters.append("IS_DEFINED(c.classification.detected_intents) AND ARRAYS_LENGTH(c.classification.detected_intents) > 0")
                filters.append("NOT EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

            elif confidence_filter == "eq_100":
                limit = 0.99
                params["@conf_limit"] = limit
                filters.append("EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

        where = " AND ".join(filters)
        query = "SELECT * FROM c"
        if where:
            query += f" WHERE {where}"
        query += " ORDER BY c._ts DESC"

        items_iter = cosmos_container.query_items(
            query,
            parameters=[{"name": k, "value": v} for k, v in params.items()],
            max_item_count=page_size,
        )
        pages = items_iter.by_page(continuation_token=continuation_token)
        items: list[EmailRecord] = []
        next_token: str | None = None
        async for page_items in pages:
            async for item in page_items:
                # Add proxy URL for secure blob access via Managed Identity
                item["file_url_proxy"] = f"/api/emails/{item['id']}/file"
                items.append(EmailRecord(**item))
            next_token = pages.continuation_token
            break

        processed_count = await count_by_status("PROCESSED", clients=clients)
        review_count = await count_by_status("REVIEW_REQUIRED", clients=clients)
        total = processed_count + review_count

        settings = load_settings()
        finetune_min_required = settings.get("finetune_min_examples", 50)
        # Fallback to env if not set in settings (though load_settings defaults to 50)
        if not finetune_min_required:
             finetune_min_required = int(os.getenv("FINETUNE_MIN_EXAMPLES", "50"))

        finetune_reviewed_ready = await count_reviewed_ready_items(clients=clients)
        avg_conf = await get_average_confidence(clients=clients)

        return EmailListResponse(
            items=items,
            total=total,
            review_required=review_count,
            processed=processed_count,
            finetune_reviewed_ready=finetune_reviewed_ready,
            finetune_min_required=finetune_min_required,
            finetune_ready=finetune_reviewed_ready >= finetune_min_required,
            continuation_token=next_token,
            average_confidence=avg_conf,
        )
    except Exception as e:
        logger.error(f"Error listing emails: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/stats")
async def get_stats(clients: Clients = Depends(get_clients)):

    processed_count = await count_by_status("PROCESSED", clients=clients)
    review_count = await count_by_status("REVIEW_REQUIRED", clients=clients)
    total = processed_count + review_count

    settings = load_settings()
    finetune_min_examples = settings.get("finetune_min_examples", 50)
    # The frontend expects finetune_min_required
    finetune_min_required = finetune_min_examples

    finetune_reviewed_ready = await count_reviewed_ready_items(clients=clients)
    avg_conf = await get_average_confidence(clients=clients)

    return {
        "processed": processed_count,
        "review_required": review_count,
        "total": total,
        "progress": (processed_count / total) if total else 0,
        "finetune_reviewed_ready": finetune_reviewed_ready,
        "finetune_min_required": finetune_min_required,
        "finetune_ready": finetune_reviewed_ready >= finetune_min_required,
        "average_confidence": avg_conf
    }


@router.get("/emails/{item_id}", response_model=EmailRecord)
async def get_email(item_id: str, cosmos_container=Depends(get_cosmos_container), clients: Clients = Depends(get_clients)):

    try:
        item = await cosmos_container.read_item(item=item_id, partition_key=item_id)
        # item["file_url_sas"] = removed (use proxy)
        item["file_url_proxy"] = f"/api/emails/{item_id}/file"
        return EmailRecord(**item)
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")


@router.patch("/emails/{item_id}", response_model=EmailRecord)
async def patch_email(item_id: str, payload: dict, cosmos_container=Depends(get_cosmos_container), clients: Clients = Depends(get_clients)):

    try:
        item = await cosmos_container.read_item(item=item_id, partition_key=item_id)

        # Determine status (allow forcing INVALID/IGNORED via payload or default to PROCESSED)
        new_status = payload.get("status", "PROCESSED")

        # History tracking
        current_classification = item.get("classification") or {}
        history_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_intents": current_classification.get("detected_intents", []),
            "previous_status": item.get("status"),
            "updated_by": "user",
            "correction_reason": payload.get("reason"),
            "llm_feedback": None
        }

        if intents := payload.get("intents"):
             # Call LLM Analysis if there is a reason and a change
            if payload.get("reason") and item.get("markdown"):
                 try:
                     insight = await analyze_correction(
                         text_markdown=item.get("markdown"),
                         old_intents=current_classification.get("detected_intents", []),
                         new_intents=intents,
                         reason=payload.get("reason"),
                         clients=clients
                     )
                     history_entry["llm_feedback"] = insight
                 except Exception:
                     pass # Don't block save on analysis failure

            item["classification"] = {
                "detected_intents": intents,
                "needs_review": False,
            }
            if payload.get("global_complexity"):
                item["classification"]["global_complexity"] = payload.get("global_complexity")

            item["status"] = new_status
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            item["reviewed"] = True
            item["reviewed_at"] = datetime.now(timezone.utc).isoformat()

            if reason := payload.get("reason"):
                item["correction_reason"] = reason

        elif new_status == "INVALID":
             item["status"] = "INVALID"
             item["reviewed"] = True
             item["reviewed_at"] = datetime.now(timezone.utc).isoformat()

        # Update History
        if "classification_history" not in item:
            item["classification_history"] = []
        item["classification_history"].append(history_entry)

        if item.get("search_text") is None:
            item["search_text"] = compute_search_text(item.get("markdown"))
        await cosmos_container.upsert_item(item)
        return EmailRecord(**item)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/emails/{item_id}/reprocess")
async def reprocess_email(item_id: str, cosmos_container=Depends(get_cosmos_container), sb_client=Depends(get_sb_client)):

    try:
        item = await cosmos_container.read_item(item=item_id, partition_key=item_id)
        blob_url = item.get("file_url")
        if not blob_url:
            raise HTTPException(status_code=400, detail="file_url missing")

        sender = sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)
        async with sender:
            await sender.send_messages(ServiceBusMessage(json.dumps({"blob_url": blob_url})))

        return {"status": "enqueued", "blob_url": blob_url}
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/emails/{item_id}/reclassify")
async def reclassify_email(
    item_id: str,
    payload: dict,
    cosmos_container=Depends(get_cosmos_container),
    sb_client=Depends(get_sb_client),
    clients: Clients = Depends(get_clients),
):
    """
    Run adversarial classification comparison or force reclassification with specific model.

    Payload:
    {
        "model": "phi-4" | "gpt-4o-mini" | "both",  # Legacy single/dual selection
        "models": ["phi-4", "gpt5-nano"],  # List of specific models to compare
        "mode": "sync" | "async"  # sync = wait for result, async = enqueue (default: sync)
    }

    Returns:
    - If mode="sync": Returns classification result(s) directly
    - If mode="async": Returns status with job ID for polling
    """
    from classificationg2s.services.llm_pipeline import classify_with_phi4, classify_comparison

    try:
        item = await cosmos_container.read_item(item=item_id, partition_key=item_id)
        markdown = item.get("markdown")
        if not markdown:
            raise HTTPException(status_code=400, detail="Item has no markdown content")

        model = payload.get("model")
        models = payload.get("models")
        mode = payload.get("mode", "sync")

        # Determine operation mode
        is_comparison = False
        target_models = []

        if models and isinstance(models, list) and len(models) > 0:
            is_comparison = True
            target_models = models
        elif model == "both":
            is_comparison = True
            target_models = ["phi-4", "gpt-4o-mini"]
        elif not model:
            # Default to comparison if nothing specified
            is_comparison = True
            target_models = ["phi-4", "gpt-4o-mini"]

        if mode not in ("sync", "async"):
            raise HTTPException(status_code=400, detail="mode must be 'sync' or 'async'")

        # SYNC MODE: Execute classification immediately and return results
        if mode == "sync":
            if is_comparison:
                # Run generic comparison
                comparison_result = await classify_comparison(markdown, models=target_models, clients=clients)

                # Save comparison results to item
                if not item.get("comparison_results"):
                    item["comparison_results"] = []

                meta = comparison_result.get("comparison_meta", {})
                comparison_record = {
                    "executed_at": meta.get("executed_at", datetime.now(timezone.utc).isoformat()),
                    "model_results": comparison_result.get("model_results"),
                    "agreement": meta.get("agreement"),
                    "confidence_delta": meta.get("confidence_delta"),
                    "processing_time_ms": meta.get("elapsed_ms"),
                    "mode": "sync",
                    # Legacy fields mapping for backward compatibility if older UI accesses them directly
                    "phi4": comparison_result.get("phi4"),
                    "gpt4o_mini": comparison_result.get("gpt4o_mini")
                }
                item["comparison_results"].append(comparison_record)
                item["updated_at"] = datetime.now(timezone.utc).isoformat()
                await cosmos_container.upsert_item(item)

                return {
                    "status": "completed",
                    "mode": "sync",
                    "models": target_models,
                    "result": comparison_result,
                }

            else:
                # Single model classification
                # Note: Currently restricts to configured Phi-4 logic for "single" mode overwrite
                # To support generic single model overwrite, we would need to adapt classify_with_phi4 logic
                result = await classify_with_phi4(markdown, clients=clients)

                # Update item with new classification
                item["classification"] = {
                    "detected_intents": result.get("detected_intents", []),
                    "global_complexity": result.get("global_complexity"),
                    "needs_review": False,  # Will be re-evaluated on save
                }
                item["status"] = "PROCESSED"
                item["updated_at"] = datetime.now(timezone.utc).isoformat()
                item["reclassified_with_model"] = model
                await cosmos_container.upsert_item(item)

                return {
                    "status": "completed",
                    "mode": "sync",
                    "model": model,
                    "result": result,
                }

        # ASYNC MODE: Enqueue message to Service Bus worker
        else:
            sender = sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)
            message_data = {
                "blob_url": item.get("file_url"),
                "reclassify_mode": "comparison" if is_comparison else "single",
                "model": model, # Legacy field
                "models": target_models, # New field
                "item_id": item_id,
            }
            async with sender:
                await sender.send_messages(ServiceBusMessage(json.dumps(message_data)))

            return {
                "status": "enqueued",
                "mode": "async",
                "models": target_models,
                "item_id": item_id,
                "message": f"Reclassification enqueued for {item_id}",
            }

    except Exception as ex:
        logger.exception(f"Reclassify failed for {item_id}: {str(ex)}")
        raise HTTPException(status_code=400, detail=str(ex))



@router.get("/emails/export")
async def export_emails_csv(cosmos_container=Depends(get_cosmos_container)):
    import csv
    import io

    # Count total emails first for filename
    count_query = "SELECT VALUE COUNT(1) FROM c"
    count_result = cosmos_container.query_items(count_query)
    total_emails = 0
    async for count in count_result:
        total_emails = count
        break

    # Generate dynamic filename with timestamp and count
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"classimail_export_{timestamp}_{total_emails}emails.csv"

    async def row_iter():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "id",
                "text_ocr",
                "category_detected",
                "processing_time",
                "precision",
                "model_name",
                "explanation"
            ]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        query = "SELECT * FROM c ORDER BY c._ts DESC"
        it = cosmos_container.query_items(query)
        async for item in it:
            # ID cleaning: filename without pdf
            file_url = item.get("file_url", "")
            clean_id = file_url.split("/")[-1].replace(".pdf", "") if file_url else item.get("id")

            # Classification info
            classification = item.get("classification") or {}
            intents = classification.get("detected_intents") or []
            if intents:
                top_intent = intents[0].get("intent")
                confidence = intents[0].get("confidence")
                explanation = intents[0].get("justification")
            else:
                top_intent = "Unknown"
                confidence = 0.0
                explanation = classification.get("classification_reason", "")

            # Processing Time
            proc_time_ms = item.get("processing_time_ms")
            proc_time_str = f"{proc_time_ms / 1000:.2f}s" if proc_time_ms else "N/A"

            # Model Used (default to phi4 if not recorded)
            model = item.get("reclassified_with_model") or "phi4"

            writer.writerow(
                [
                    clean_id,
                    item.get("markdown", ""),
                    top_intent,
                    proc_time_str,
                    confidence,
                    model,
                    explanation
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    return StreamingResponse(
        row_iter(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/emails/{item_id}/file")
async def download_email_file(item_id: str, clients: Clients = Depends(get_clients)):
    """Proxy endpoint to stream PDF files using Managed Identity authentication."""
    logger.info(f"[PDF Proxy] Request for item_id={item_id}")
    try:
        await clients.ensure_cosmos_container()
        logger.debug(f"[PDF Proxy] Fetching metadata from Cosmos for item_id={item_id}")
        item = await clients.cosmos_container.read_item(item=item_id, partition_key=item_id)
        blob_url = item.get("file_url")
        if not blob_url:
            logger.error(f"[PDF Proxy] No file_url found in Cosmos record for item_id={item_id}")
            raise HTTPException(status_code=404, detail="No file_url on record")

        logger.info(f"[PDF Proxy] Streaming blob via Managed Identity: {blob_url}")
        blob_client = BlobClient.from_blob_url(blob_url, credential=clients.credential)

        try:
            downloader = await blob_client.download_blob()
        except Exception as blob_err:
            logger.error(f"[PDF Proxy] Failed to access blob at {blob_url}: {blob_err}", exc_info=True)
            raise HTTPException(status_code=404, detail=f"Blob not accessible: {str(blob_err)}")

        content_type = getattr(getattr(downloader, 'properties', None), 'content_settings', None)
        if content_type:
            content_type = content_type.content_type
        else:
            content_type = "application/pdf"

        logger.debug(f"[PDF Proxy] Content-Type={content_type}")

        async def iter_chunks():
            chunk_count = 0
            try:
                async for chunk in downloader.chunks():
                    chunk_count += 1
                    yield chunk
                logger.info(f"[PDF Proxy] Successfully streamed {chunk_count} chunks for item_id={item_id}")
            except Exception as stream_err:
                logger.error(f"[PDF Proxy] Stream interrupted at chunk {chunk_count} for item_id={item_id}: {stream_err}")
                raise

        disposition = f"inline; filename={blob_url.split('/')[-1].split('?')[0]}"
        return StreamingResponse(iter_chunks(), media_type=content_type, headers={"Content-Disposition": disposition})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[PDF Proxy] Unexpected error for item_id={item_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/emails/export-finetune-jsonl")
async def export_emails_finetune_jsonl(
    anonymize: bool = Query(True),
    include_unreviewed: bool = Query(False),
    max_examples: Optional[int] = Query(None, ge=1),
    taxonomy_version: str = Query("v1"),
    include_metadata: bool = Query(False),
    min_required: Optional[int] = Query(None, ge=1),
    split: str = Query("all", pattern="^(all|train|test)$"),
    test_split_ratio: float = Query(0.2, ge=0.0, le=1.0),
    clients: Clients = Depends(get_clients),
):
    settings = load_settings()
    finetune_min_required = min_required or settings.get("finetune_min_examples", 50)

    finetune_reviewed_ready = await count_reviewed_ready_items(clients=clients)
    if not include_unreviewed and finetune_reviewed_ready < finetune_min_required:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Not enough reviewed examples to export fine-tuning dataset.",
                "reviewed_ready": finetune_reviewed_ready,
                "min_required": finetune_min_required,
            },
        )

    filename = f"fine_tune_{split}_{taxonomy_version}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    return StreamingResponse(
        export_finetune_jsonl_iter(
            clients=clients,
            anonymize=anonymize,
            include_unreviewed=include_unreviewed,
            max_examples=max_examples,
            taxonomy_version=taxonomy_version,
            include_metadata=include_metadata,
            split_mode=split,
            test_ratio=test_split_ratio
        ),
        media_type="application/jsonl",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
