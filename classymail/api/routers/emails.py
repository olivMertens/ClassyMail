from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse

from azure.servicebus import ServiceBusMessage
from azure.storage.blob.aio import BlobClient

from classymail.core import config
from classymail.models import EmailListResponse, EmailRecord
from classymail.services.azure_clients import (
    get_cosmos_container,
    get_sb_client,
    get_queue_active_count,
    get_clients,
    Clients,
)
from classymail.services.repository import (
    count_by_status,
    count_reviewed_ready_items,
    export_finetune_jsonl_iter,
    compute_search_text,
    get_average_confidence,
)
from classymail.services.llm_pipeline import analyze_correction
from classymail.services.settings_store import load_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["emails"])


@router.get("/emails", response_model=EmailListResponse)
async def list_emails(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query("all", pattern="^(all|REVIEW_REQUIRED|PROCESSED|ERROR)$"),
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    confidence_filter: Optional[str] = Query(None, pattern="^(lt_10|lt_30|lt_50|lt_85|gt_85|lt_90|gt_90|eq_100|none)$"),
    sort_by: str = Query("timestamp", pattern="^(timestamp|status|processing_time|confidence)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    continuation_token: Optional[str] = Query(None),
    cosmos_container=Depends(get_cosmos_container),
    clients: Clients = Depends(get_clients),
):
    # Validate continuation token
    if continuation_token:
        if len(continuation_token) > 4096:
            raise HTTPException(status_code=400, detail="Invalid continuation token: too long")
        try:
            base64.b64decode(continuation_token + "==", validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid continuation token format")

    try:
        filters = []
        params = {}
        if status != "all":
            filters.append("c.status = @status")
            params["@status"] = status

        # Always filter out non-email documents (like settings) and partial chunks
        filters.append("IS_DEFINED(c.file_url)")
        filters.append("IS_DEFINED(c.status)")

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
                elif confidence_filter == "lt_85":
                    limit = 0.85
                elif confidence_filter == "gt_85":
                    limit = 0.85
                    op = ">="
                elif confidence_filter == "lt_90":
                    limit = 0.9
                elif confidence_filter == "gt_90":
                    limit = 0.9
                    op = ">="
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
                filters.append("IS_DEFINED(c.classification.detected_intents) AND ARRAY_LENGTH(c.classification.detected_intents) > 0")
                filters.append("NOT EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

            elif confidence_filter == "lt_30":
                limit = 0.3
                params["@conf_limit"] = limit
                filters.append("IS_DEFINED(c.classification.detected_intents) AND ARRAY_LENGTH(c.classification.detected_intents) > 0")
                filters.append("NOT EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

            elif confidence_filter == "lt_50":
                limit = 0.5
                params["@conf_limit"] = limit
                filters.append("IS_DEFINED(c.classification.detected_intents) AND ARRAY_LENGTH(c.classification.detected_intents) > 0")
                filters.append("NOT EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

            elif confidence_filter == "lt_85":
                limit = 0.85
                params["@conf_limit"] = limit
                filters.append("IS_DEFINED(c.classification.detected_intents) AND ARRAY_LENGTH(c.classification.detected_intents) > 0")
                filters.append("NOT EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

            elif confidence_filter == "gt_85":
                limit = 0.85
                params["@conf_limit"] = limit
                filters.append("EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

            elif confidence_filter == "lt_90":
                limit = 0.9
                params["@conf_limit"] = limit
                filters.append("IS_DEFINED(c.classification.detected_intents) AND ARRAY_LENGTH(c.classification.detected_intents) > 0")
                filters.append("NOT EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

            elif confidence_filter == "gt_90":
                limit = 0.9
                params["@conf_limit"] = limit
                filters.append("EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

            elif confidence_filter == "eq_100":
                limit = 0.99
                params["@conf_limit"] = limit
                filters.append("EXISTS(SELECT VALUE i FROM i IN c.classification.detected_intents WHERE i.confidence >= @conf_limit)")

            elif confidence_filter == "none":
                # Filter for emails with NO detected intents
                filters.append("((NOT IS_DEFINED(c.classification.detected_intents)) OR (ARRAY_LENGTH(c.classification.detected_intents) = 0))")

        where = " AND ".join(filters)
        query = "SELECT * FROM c"
        if where:
            query += f" WHERE {where}"

        # Sorting logic
        sort_field = "c._ts"  # default
        if sort_by == "status":
            sort_field = "c.status"
        elif sort_by == "processing_time":
            sort_field = "c.processing_time_ms"
        elif sort_by == "confidence":
            # For simpler sorting, use the first intent's confidence or 0
            # Warning: Complex sorting might be slow without composite indexes
            # We'll try sorting by the raw arrays first element if possible, or just skip
            # Cosmos doesn't easily support ORDER BY c.classification.detected_intents[0].confidence
            # So we might just default to timestamp if requested, or client side sort?
            # Let's fallback to _ts for confidence for now to avoid breaking query
            pass

        # Count filtered results for accurate pagination
        count_query = "SELECT VALUE COUNT(1) FROM c"
        if where:
            count_query += f" WHERE {where}"
        filtered_total = 0
        async for item in cosmos_container.query_items(
            count_query,
            parameters=[{"name": k, "value": v} for k, v in params.items()],
        ):
            filtered_total = item
            break

        # Use OFFSET/LIMIT for page-based pagination
        offset = (page - 1) * page_size
        query += f" ORDER BY {sort_field} {order.upper()}"
        query += f" OFFSET {offset} LIMIT {page_size}"

        items: list[EmailRecord] = []
        async for item in cosmos_container.query_items(
            query,
            parameters=[{"name": k, "value": v} for k, v in params.items()],
        ):
            # Add proxy URL for secure blob access via Managed Identity
            item["file_url_proxy"] = f"/api/emails/{item['id']}/file"
            items.append(EmailRecord(**item))

        processed_count = await count_by_status("PROCESSED", clients=clients)
        review_count = await count_by_status("REVIEW_REQUIRED", clients=clients)
        total = processed_count + review_count

        settings = load_settings()
        finetune_min_required = settings.get("finetune_min_examples", 5)
        # Fallback to env if not set in settings (though load_settings defaults to 5)
        if not finetune_min_required:
             finetune_min_required = int(os.getenv("FINETUNE_MIN_EXAMPLES", "5"))

        finetune_reviewed_ready = await count_reviewed_ready_items(clients=clients)
        avg_conf = await get_average_confidence(clients=clients)

        return EmailListResponse(
            items=items,
            total=total,
            filtered_total=filtered_total,
            review_required=review_count,
            processed=processed_count,
            finetune_reviewed_ready=finetune_reviewed_ready,
            finetune_min_required=finetune_min_required,
            finetune_ready=finetune_reviewed_ready >= finetune_min_required,
            continuation_token=None,  # Using OFFSET/LIMIT, not continuation tokens
            average_confidence=avg_conf,
        )
    except Exception as e:
        logger.error(f"Error listing emails: {str(e)}", exc_info=True)
        # Surface the actual error detail so the frontend/admin can diagnose
        # (e.g., Cosmos throttling 429, auth failure, vector policy conflict)
        detail = str(e) if str(e) else "Internal Server Error"
        raise HTTPException(status_code=500, detail=detail)


@router.get("/stats")
async def get_stats(clients: Clients = Depends(get_clients)):

    processed_count = await count_by_status("PROCESSED", clients=clients)
    review_count = await count_by_status("REVIEW_REQUIRED", clients=clients)

    # "Pending" includes items in queue and items in Cosmos marked PENDING or PROCESSING
    db_pending = await count_by_status("PENDING", clients=clients)
    db_processing = await count_by_status("PROCESSING", clients=clients)
    queue_pending = await get_queue_active_count(config.SERVICE_BUS_QUEUE, clients=clients)

    total_emails = processed_count + review_count + db_pending + db_processing + queue_pending

    # Pending = DB PENDING + PROCESSING (queue items are a subset, reported separately as queue_depth).

    pending_total = db_pending + db_processing

    settings = load_settings()
    finetune_min_examples = settings.get("finetune_min_examples", 5)
    # The frontend expects finetune_min_required
    finetune_min_required = finetune_min_examples

    finetune_reviewed_ready = await count_reviewed_ready_items(clients=clients)
    avg_conf = await get_average_confidence(clients=clients)

    return {
        "processed": processed_count,
        "review_required": review_count,
        "pending": pending_total,
        "queue_depth": queue_pending,
        "total": total_emails, # Estimate
        "progress": (processed_count + review_count) / total_emails if total_emails else 0,
        "finetune_reviewed_ready": finetune_reviewed_ready,
        "finetune_min_required": finetune_min_required,
        "finetune_ready": finetune_reviewed_ready >= finetune_min_required,
        "average_confidence": avg_conf
    }


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
    finetune_min_required = min_required or settings.get("finetune_min_examples", 5)

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

        # ── Auto-feed correction to AI Search indexes (best-effort) ──
        if intents and item.get("markdown"):
            try:
                from classymail.agents.tools.ai_search_index import ensure_index, upsert_example
                from classymail.agents.config import SEARCH_ENDPOINT

                if SEARCH_ENDPOINT:
                    markdown = item["markdown"][:8000]
                    old_intents = history_entry.get("previous_intents", [])
                    new_intent_names = [i.get("intent", "") for i in intents]

                    # Find category slugs
                    settings_data = None
                    try:
                        from classymail.services.settings_store import load_settings
                        settings_data = load_settings()
                    except Exception:
                        pass
                    cats = (settings_data or {}).get("categories", [])
                    name_to_slug = {c["name"]: c["slug"] for c in cats if "name" in c and "slug" in c}

                    # Old intents that are NOT in new → negative examples
                    old_names = {i.get("intent", "") for i in old_intents}
                    removed = old_names - set(new_intent_names)
                    reason = payload.get("reason", "")
                    for name in removed:
                        slug = name_to_slug.get(name)
                        if slug:
                            await ensure_index(slug, clients=clients)
                            await upsert_example(
                                slug, markdown,
                                is_positive=False,
                                correction_reason=reason or f"Corrected by user: removed from {name}",
                                label_source="human_corrected",
                                email_id=item_id,
                                clients=clients,
                            )

                    # New intents → positive examples
                    for name in new_intent_names:
                        slug = name_to_slug.get(name)
                        if slug:
                            await ensure_index(slug, clients=clients)
                            await upsert_example(
                                slug, markdown,
                                is_positive=True,
                                label_source="human_corrected",
                                email_id=item_id,
                                clients=clients,
                            )
            except Exception as ex:
                logger.warning("Auto-feed correction to AI Search failed: %s", ex)

        return EmailRecord(**item)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/emails/{item_id}/reinforce")
async def reinforce_email(
    item_id: str,
    cosmos_container=Depends(get_cosmos_container),
    clients: Clients = Depends(get_clients),
):
    """Push the current email's OCR content as a positive example into its
    classified category AI Search indexes.  One-click reinforcement for
    correctly classified emails — tells the agentic pipeline "this is right".
    """
    try:
        item = await cosmos_container.read_item(item=item_id, partition_key=item_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Email not found")

    markdown = item.get("markdown")
    if not markdown:
        raise HTTPException(status_code=400, detail="Email has no OCR content")

    intents = (item.get("classification") or {}).get("detected_intents", [])
    if not intents:
        raise HTTPException(status_code=400, detail="Email has no classification")

    from classymail.agents.tools.ai_search_index import ensure_index, upsert_example
    from classymail.agents.config import SEARCH_ENDPOINT

    if not SEARCH_ENDPOINT:
        return {"status": "disabled", "message": "AI Search not configured"}

    # Load category slugs
    from classymail.services.settings_store import load_settings
    cats = load_settings().get("categories", [])
    name_to_slug = {c["name"]: c["slug"] for c in cats if "name" in c and "slug" in c}

    reinforced = []
    content = markdown[:8000]
    for intent in intents:
        name = intent.get("intent", "")
        slug = name_to_slug.get(name)
        if slug:
            await ensure_index(slug, clients=clients)
            await upsert_example(
                slug, content,
                is_positive=True,
                label_source="human_reinforced",
                email_id=item_id,
                clients=clients,
            )
            reinforced.append(slug)

    return {"status": "ok", "reinforced": reinforced, "count": len(reinforced)}


@router.post("/emails/{item_id}/reprocess")
async def reprocess_email(
    item_id: str,
    payload: Optional[dict] = None,
    cosmos_container=Depends(get_cosmos_container),
    sb_client=Depends(get_sb_client),
):
    """
    Re-enqueue an email for full pipeline reprocessing.

    Optional payload:
    {
        "processing_strategy": "standard" | "reasoning" | "vision" | "agentic"
    }
    If omitted, uses the global default strategy.
    """
    try:
        item = await cosmos_container.read_item(item=item_id, partition_key=item_id)
        blob_url = item.get("file_url")
        if not blob_url:
            raise HTTPException(status_code=400, detail="file_url missing")

        message_data: dict = {"blob_url": blob_url}

        # Optional per-email strategy override
        if payload and payload.get("processing_strategy") in ("standard", "reasoning", "vision", "agentic"):
            message_data["processing_strategy"] = payload["processing_strategy"]

        # Pass locale for language-aware classification
        if payload and payload.get("locale"):
            message_data["locale"] = payload["locale"]

        sender = sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)
        async with sender:
            await sender.send_messages(ServiceBusMessage(json.dumps(message_data)))

        return {
            "status": "enqueued",
            "blob_url": blob_url,
            "processing_strategy": message_data.get("processing_strategy"),
        }
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/emails/batch-reprocess")
async def batch_reprocess_emails(
    payload: dict,
    cosmos_container=Depends(get_cosmos_container),
    sb_client=Depends(get_sb_client),
):
    """
    Re-enqueue multiple emails for full pipeline reprocessing.

    Payload:
    {
        "ids": ["id1", "id2", ...],
        "processing_strategy": "standard" | "reasoning" | "vision" | "agentic"  (optional)
    }
    """
    ids = payload.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="No email ids provided")

    strategy = payload.get("processing_strategy")
    enqueued = []
    errors = []

    sender = sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)
    async with sender:
        for item_id in ids:
            try:
                item = await cosmos_container.read_item(item=item_id, partition_key=item_id)
                blob_url = item.get("file_url")
                if not blob_url:
                    errors.append({"id": item_id, "error": "file_url missing"})
                    continue

                message_data: dict = {"blob_url": blob_url}
                if strategy in ("standard", "reasoning", "vision", "agentic"):
                    message_data["processing_strategy"] = strategy

                await sender.send_messages(ServiceBusMessage(json.dumps(message_data)))
                enqueued.append(item_id)
            except Exception as ex:
                errors.append({"id": item_id, "error": str(ex)})

    return {
        "enqueued": len(enqueued),
        "failed": len(errors),
        "errors": errors,
        "processing_strategy": strategy,
    }


@router.post("/emails/{item_id}/reclassify")
async def reclassify_email(
    item_id: str,
    payload: dict,
    cosmos_container=Depends(get_cosmos_container),
    sb_client=Depends(get_sb_client),
    clients: Clients = Depends(get_clients),
):
    """
    Force reclassification of an email with the current model settings.

    Payload:
    {
        "model": "phi-4" | "gpt-4o-mini",  # Optional: specific model override
        "locale": "en"  # Optional: output language
    }

    Returns classification result directly.
    """
    from classymail.services.llm_pipeline import classify_with_phi4

    try:
        item = await cosmos_container.read_item(item=item_id, partition_key=item_id)
        markdown = item.get("markdown")
        if not markdown:
            raise HTTPException(status_code=400, detail="Item has no markdown content")

        locale = payload.get("locale", "en")

        # Single model reclassification
        result = await classify_with_phi4(markdown, clients=clients, locale=locale)

        # Update item with new classification
        item["classification"] = {
            "detected_intents": result.get("detected_intents", []),
            "global_complexity": result.get("global_complexity"),
            "needs_review": False,
        }
        item["status"] = "PROCESSED"
        item["updated_at"] = datetime.now(timezone.utc).isoformat()
        item["reclassified_with_model"] = result.get("model")

        # Persist PII detection results
        if "pii_detected" in result:
            item["pii_detected"] = result["pii_detected"]
        if "detected_pii" in result:
            item["pii_data"] = result["detected_pii"]
        if "preprocessing_metadata" in result:
            item["preprocessing_metadata"] = result["preprocessing_metadata"]

        await cosmos_container.upsert_item(item)

        return {
            "status": "completed",
            "model": result.get("model"),
            "result": result,
        }

    except Exception as ex:
        logger.exception(f"Reclassify failed for {item_id}: {str(ex)}")
        raise HTTPException(status_code=400, detail=str(ex))


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


def extract_filename(blob_url: str) -> str:
    """Extract PDF filename from blob URL, removing path and SAS tokens."""
    if not blob_url:
        return "unknown.pdf"

    from urllib.parse import urlparse, unquote
    parsed = urlparse(blob_url)
    path = parsed.path

    # Remove leading slashes and container name
    parts = path.strip('/').split('/')
    filename = parts[-1] if parts else "unknown.pdf"

    # Decode URL encoding
    filename = unquote(filename)

    return filename


def extract_visual_proofs(item: dict) -> str:
    """Extract visual proofs (image descriptions) from vision_analysis."""
    vision_items = item.get("vision_analysis") or []
    visual_proofs = []

    for vi in vision_items:
        summary = vi.get("summary") or vi.get("description") or ""
        img_type = vi.get("image_type") or "Image"
        page = (vi.get("page_index") or 0) + 1
        if summary:
            visual_proofs.append(f"[Page {page} - {img_type}: {summary}]")

    if visual_proofs:
        return " | ".join(visual_proofs)

    # Fallback: legacy chunks format
    chunks = item.get("chunks", [])
    for chunk in chunks:
        alt_text = chunk.get("alt_text")
        description = chunk.get("description")
        if alt_text:
            visual_proofs.append(f"[Image: {alt_text}]")
        elif description:
            visual_proofs.append(f"[Image: {description}]")

    return " | ".join(visual_proofs) if visual_proofs else ""


@router.get("/emails/export/csv")
async def export_emails_csv(
    status: str = Query("all", pattern="^(all|REVIEW_REQUIRED|PROCESSED|ERROR)$"),
    format: str = Query("enriched", pattern="^(minimal|enriched)$"),
    cosmos_container=Depends(get_cosmos_container),
):
    """
    Export emails to CSV format with true async streaming.

    Rows are streamed as they arrive from Cosmos DB — no full-dataset buffering.
    This prevents 502 gateway timeouts on large exports.

    Two formats supported:
    - minimal: ID;INTENTIONS;CONFIDENCE_MOYENNE (client ClassyMail compatible)
    - enriched: 12 columns with full audit trail including detection mode and visual proofs

    Args:
        status: Filter by status (all, REVIEW_REQUIRED, PROCESSED, ERROR)
        format: Output format (minimal or enriched)

    Returns:
        CSV file with UTF-8 BOM encoding and semicolon delimiter (streamed)
    """
    import csv
    import io

    logger.info(f"CSV Export request: status={status}, format={format}")

    # Load settings once before streaming starts
    settings = load_settings()
    categories = settings.get("categories") or []
    slug_map = {cat.get("name", ""): cat.get("slug", cat.get("name", "")) for cat in categories}
    csv_export = settings.get("csv_export") or settings.get("csv_export") or {}
    unclassified_label = csv_export.get("unclassified_label", "unclassified")

    # Build query
    filters = ["IS_DEFINED(c.file_url)", "IS_DEFINED(c.status)"]
    params = []
    if status != "all":
        filters.append("c.status = @status")
        params.append({"name": "@status", "value": status})
    where_clause = " AND ".join(filters)
    query_sql = f"SELECT * FROM c WHERE {where_clause} ORDER BY c.created_at DESC"

    def _write_row(writer, buf, row):
        """Write one CSV row and drain the buffer."""
        writer.writerow(row)
        data = buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        return data

    async def _stream_csv():
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=';', quoting=csv.QUOTE_MINIMAL)

        # UTF-8 BOM for Excel compatibility
        yield '\ufeff'

        if format == "minimal":
            yield _write_row(writer, buf, ['ID', 'INTENTIONS', 'CONFIDENCE_MOYENNE'])

            async for item in cosmos_container.query_items(query=query_sql, parameters=params):
                blob_url = item.get("file_url", "")
                pdf_filename = extract_filename(blob_url)

                classification = item.get("classification") or {}
                intents = classification.get("detected_intents") or []

                intent_slugs = []
                confidences = []
                for intent_obj in intents:
                    intent_name = intent_obj.get("intent", "")
                    confidence = intent_obj.get("confidence", 0)
                    slug = slug_map.get(intent_name, intent_name.lower().replace(" ", "_"))
                    intent_slugs.append(slug)
                    confidences.append(confidence)

                intentions_str = ",".join(intent_slugs) if intent_slugs else unclassified_label
                avg_confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
                confidence_pct = f"{round(avg_confidence * 100)}%" if confidences else "N/A"

                yield _write_row(writer, buf, [pdf_filename, intentions_str, confidence_pct])

        else:  # enriched format
            # Build dynamic header based on settings
            header = ['ID', 'INTENTIONS', 'CONFIDENCE_MOYENNE', 'DETAILS_CONFIDENCES', 'MODE_DETECTION']
            if csv_export.get("show_quality", True):
                header.append('QUALITE')
            if csv_export.get("show_model", True):
                header.append('MODELE')
            if csv_export.get("show_justification", True):
                header.append('JUSTIFICATION')
            if csv_export.get("show_visual_proofs", True):
                header.append('PREUVES_VISUELLES')
            if csv_export.get("show_time", True):
                header.append('TEMPS_S')
            if csv_export.get("show_pii", True):
                header.extend(['PII_DETECTE', 'PII_TYPES'])
            if csv_export.get("show_ocr_provider", True):
                header.append('SOURCE_OCR')
            yield _write_row(writer, buf, header)

            async for item in cosmos_container.query_items(query=query_sql, parameters=params):
                blob_url = item.get("file_url", "")
                pdf_filename = extract_filename(blob_url)

                classification = item.get("classification") or {}
                intents = classification.get("detected_intents") or []
                processing_time = item.get("processing_time_ms", "")

                usage = item.get("usage") or {}
                model_name = usage.get("phi4_model") or usage.get("model") or "unknown"
                detection_mode = usage.get("strategy", "standard")

                intent_slugs = []
                confidences = []
                confidence_details = []
                justifications = []

                for intent_obj in intents:
                    intent_name = intent_obj.get("intent", "")
                    confidence = intent_obj.get("confidence", 0)
                    slug = slug_map.get(intent_name, intent_name.lower().replace(" ", "_"))
                    intent_slugs.append(slug)
                    confidences.append(confidence)
                    confidence_details.append(f"{intent_name}: {round(confidence * 100)}%")
                    justifications.append(intent_obj.get("justification", ""))

                intentions_str = ",".join(intent_slugs) if intent_slugs else unclassified_label
                avg_confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
                confidence_pct = f"{round(avg_confidence * 100)}%" if confidences else "N/A"
                details_str = ", ".join(confidence_details) if confidence_details else ""

                if not confidences:
                    quality = "Non classifié"
                elif avg_confidence >= 0.90:
                    quality = "Excellent"
                elif avg_confidence >= 0.85:
                    quality = "Bon"
                else:
                    quality = "À revoir"

                justification_str = " | ".join(j for j in justifications if j) if justifications else ""
                if not justification_str:
                    justification_str = classification.get("classification_reason", "") or ""

                processing_time_s = ""
                if processing_time:
                    try:
                        processing_time_s = round(float(processing_time) / 1000.0, 2)
                    except (ValueError, TypeError):
                        processing_time_s = processing_time

                visual_proofs = extract_visual_proofs(item) if detection_mode == "vision" else ""

                pii_detected = "Oui" if item.get("pii_detected", False) else "Non"
                pii_data = item.get("pii_data") or {}
                pii_types = []
                if pii_data:
                    for key in ['names', 'emails', 'phones', 'addresses', 'contract_ids', 'dates', 'other']:
                        items_list = pii_data.get(key, [])
                        if items_list:
                            pii_types.append(key)
                pii_types_str = ",".join(pii_types) if pii_types else ""

                row = [pdf_filename, intentions_str, confidence_pct, details_str, detection_mode]
                if csv_export.get("show_quality", True):
                    row.append(quality)
                if csv_export.get("show_model", True):
                    row.append(model_name)
                if csv_export.get("show_justification", True):
                    row.append(justification_str)
                if csv_export.get("show_visual_proofs", True):
                    row.append(visual_proofs)
                if csv_export.get("show_time", True):
                    row.append(processing_time_s)
                if csv_export.get("show_pii", True):
                    row.extend([pii_detected, pii_types_str])
                if csv_export.get("show_ocr_provider", True):
                    row.append(item.get("ocr_provider", "mistral_ocr"))

                yield _write_row(writer, buf, row)

    filename = f"emails_export_{format}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        _stream_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
