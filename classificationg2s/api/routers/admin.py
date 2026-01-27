from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from classificationg2s.core import config
from classificationg2s.services.azure_clients import Clients, get_clients, blob_id_from_url
import logging
import uuid
import json
import os
from datetime import datetime, timezone
from fpdf import FPDF
from azure.servicebus import ServiceBusMessage, ServiceBusSubQueue
from classificationg2s.services.messages import extract_blob_url
from classificationg2s.services.azure_clients import readiness_checks, get_cosmos_container as azure_get_cosmos_container
from classificationg2s.services.repository import (
    search_email_records,
    get_latest_errors,
    get_stats_summary,
    get_top_intents,
    get_low_confidence_items,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger("classimail.admin")

class ResetRequest(BaseModel):
    confirm_1: bool
    confirm_2: bool


class DeadLetterMessage(BaseModel):
    message_id: str | None = None
    delivery_count: int | None = None
    dead_letter_reason: str | None = None
    dead_letter_error_description: str | None = None
    blob_url: str | None = None
    blob_id: str | None = None
    enqueued_time_utc: datetime | None = None
    sequence_number: int | None = None


class DeadLetterSummary(BaseModel):
    count: int
    messages: list[DeadLetterMessage]


class DiagnosticsResponse(BaseModel):
    env: dict
    readiness: dict
    ok: bool


class SearchResponse(BaseModel):
    items: list[dict]


class ErrorsResponse(BaseModel):
    items: list[dict]


class StatsSummaryResponse(BaseModel):
    total: int
    pending: int
    processing: int
    processed: int
    error: int
    review_required: int
    average_confidence: float


class IntentsResponse(BaseModel):
    items: list[dict]


class LowConfidenceResponse(BaseModel):
    items: list[dict]

@router.post("/debug/simulate-flow")
async def simulate_flow(clients: Clients = Depends(get_clients)):
    """
    Simulates a complete flow by creating and uploading a dummy PDF.
    Returns the item_id (blob path) to track via /api/emails/{id}.
    """
    try:
        logger.info("[SIMULATION] Starting simulation flow")

        # 1. Generate Dummy PDF
        logger.info("[SIMULATION] Step 1: Generating dummy PDF")
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("helvetica", size=12)
        pdf.cell(text=f"Simulation Request - {datetime.now(timezone.utc)}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(text="Subject: Test Invoice for Simulation", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(text="This is a generated PDF to verify the end-to-End flow.", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(text="Reference: SIM-12345", new_x="LMARGIN", new_y="NEXT")

        pdf_bytes = pdf.output() # Returns bytearray in recent fpdf2
        logger.info(f"[SIMULATION] Generated PDF: {len(pdf_bytes)} bytes")

        # 2. Upload to Blob Storage (use dated folder structure like upload.py)
        logger.info("[SIMULATION] Step 2: Uploading to Blob Storage")
        container_client = clients.blob_service_client.get_container_client(config.BLOB_CONTAINER_INPUT)

        # Use dated folder structure to match upload.py behavior
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y/%m/%d")
        filename = f"simulation_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
        blob_name = f"uploads/{today}/{filename}"

        logger.info(f"[SIMULATION] Blob path: {blob_name}")
        blob_client = container_client.get_blob_client(blob_name)

        await blob_client.upload_blob(bytes(pdf_bytes), overwrite=True)
        blob_url = blob_client.url
        logger.info(f"[SIMULATION] Upload complete: {blob_url}")

        # 3. Construct ID and Create PENDING record (like upload.py)
        item_id = blob_id_from_url(blob_url)
        logger.info(f"[SIMULATION] Generated item_id: {item_id}")

        # Create PENDING record for immediate UI feedback
        logger.info("[SIMULATION] Step 3: Creating PENDING record in Cosmos DB")
        try:
            await clients.ensure_cosmos_container()
            pending_start = datetime.now(timezone.utc).isoformat()
            pending_doc = {
                "id": item_id,
                "file_url": blob_url,
                "status": "PENDING",
                "subject": "Simulation Test (Processing...)",
                "created_at": pending_start,
                "updated_at": pending_start,
                "markdown": None,
                "classification": None,
                "processing_log": [{"ts": pending_start, "stage": "simulation", "event": "pending_manual_trigger"}]
            }
            await clients.cosmos_container.upsert_item(pending_doc)
            logger.info(f"[SIMULATION] PENDING record created: {item_id}")
        except Exception as e:
            logger.error(f"[SIMULATION] Failed to create pending record: {e}")

        # 4. Trigger Worker Manually
        logger.info("[SIMULATION] Step 4: Sending message to Service Bus")
        sender = clients.sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)
        async with sender:
            message_payload = {"blob_url": blob_url}
            await sender.send_messages(ServiceBusMessage(json.dumps(message_payload)))
            logger.info(f"[SIMULATION] Message sent to queue: {config.SERVICE_BUS_QUEUE}")

        logger.info(f"[SIMULATION] ✓ Flow complete. Track with item_id: {item_id}")
        return {
            "status": "uploaded_and_queued",
            "item_id": item_id,
            "blob_url": blob_url
        }

    except Exception as e:
        logger.error(f"[SIMULATION] ✗ Simulation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/debug/connectivity")
async def check_connectivity(clients: Clients = Depends(get_clients)):
    """
    Performs active write/delete tests to verify permissions and connectivity for Storage and Cosmos DB.
    """
    results = {
        "storage_upload": "pending",
        "cosmos_write": "pending",
        "servicebus_connect": "pending"
    }

    # 1. Test Storage Upload/Delete
    try:
        container_client = clients.blob_service_client.get_container_client(config.BLOB_CONTAINER_INPUT)
        test_blob_name = f"debug-test-{uuid.uuid4()}.txt"
        test_blob = container_client.get_blob_client(test_blob_name)

        # Upload
        await test_blob.upload_blob(b"debug connectivity check", overwrite=True)
        # Delete
        await test_blob.delete_blob()
        results["storage_upload"] = "ok"
    except Exception as e:
        results["storage_upload"] = str(e)

    # 2. Test Cosmos Write/Delete
    try:
        container = await azure_get_cosmos_container(clients)
        test_id = f"debug-{uuid.uuid4()}"
        test_item = {"id": test_id, "type": "debug_check", "timestamp": str(uuid.uuid4())}

        # Create
        await container.create_item(test_item)
        # Delete
        await container.delete_item(item=test_id, partition_key=test_id)
        results["cosmos_write"] = "ok"
    except Exception as e:
        results["cosmos_write"] = str(e)

    # 3. Test Service Bus Sender Creation
    try:
        sender = clients.sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)
        async with sender:
            pass # Just opening the link verifies connectivity/auth
        results["servicebus_connect"] = "ok"
    except Exception as e:
        results["servicebus_connect"] = str(e)

    return results

@router.post("/reset", status_code=status.HTTP_200_OK)
async def reset_environment(
    req: ResetRequest,
    clients: Clients = Depends(get_clients),
):
    """
    DANGER: Resets the environment by deleting all input blobs and Cosmos DB records.
    Requires double confirmation.
    """
    if not (req.confirm_1 and req.confirm_2):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Double confirmation required."
        )

    deleted_blobs = 0
    deleted_records = 0
    errors = []

    # 1. Delete Blobs
    try:
        container_client = clients.blob_service_client.get_container_client(config.BLOB_CONTAINER_INPUT)
        async for blob in container_client.list_blobs():
            await container_client.delete_blob(blob.name)
            deleted_blobs += 1
    except Exception as e:
        logger.error(f"Failed to delete blobs: {e}")
        errors.append(f"Storage: {str(e)}")

    # 2. Delete Cosmos Records
    # Efficient deletion: recreate container or delete by query?
    # Recreating needs management SDK (slower, permissions). Deleting items is safer for data-plane.
    try:
        container = await azure_get_cosmos_container(clients)
        # Fetch all IDs first (cheaper query)
        query = "SELECT c.id, c.id as partitionKey FROM c"
        # Note: Using backend-for-frontend pattern, simple iteration is fine for POC size.
        # For production, we'd use Bulk execution or stored procedure.
        items = [x async for x in container.query_items(query)]

        for item in items:
            await container.delete_item(item=item["id"], partition_key=item["partitionKey"])
            deleted_records += 1

    except Exception as e:
        logger.error(f"Failed to clean Cosmos DB: {e}")
        errors.append(f"DB: {str(e)}")

    # 3. Purge Dead Letter Queue (Service Bus)
    deleted_dlq = 0
    try:
        # Use short timeout to drain
        if clients.sb_client:
            receiver = clients.sb_client.get_queue_receiver(
                queue_name=config.SERVICE_BUS_QUEUE,
                sub_queue=ServiceBusSubQueue.DEAD_LETTER,
                prefetch_count=50,
            )
            async with receiver:
                while True:
                    messages = await receiver.receive_messages(max_message_count=50, max_wait_time=2)
                    if not messages:
                        break
                    for msg in messages:
                        await receiver.complete_message(msg)
                        deleted_dlq += 1
    except Exception as e:
        logger.error(f"Failed to purge DLQ: {e}")
        errors.append(f"Service Bus DLQ: {str(e)}")

    if errors:
        return {
            "status": "partial_success",
            "deleted_blobs": deleted_blobs,
            "deleted_records": deleted_records,
            "deleted_dlq": deleted_dlq,
            "errors": errors
        }

    return {
        "status": "success",
        "deleted_blobs": deleted_blobs,
        "deleted_records": deleted_records,
        "deleted_dlq": deleted_dlq
    }


@router.post("/purge-dlq", status_code=status.HTTP_200_OK)
async def purge_dlq(clients: Clients = Depends(get_clients)):
    """
    Purges just the Dead Letter Queue (Service Bus).
    """
    deleted_dlq = 0

    try:
        # Use short timeout to drain
        if clients.sb_client:
            receiver = clients.sb_client.get_queue_receiver(
                queue_name=config.SERVICE_BUS_QUEUE,
                sub_queue=ServiceBusSubQueue.DEAD_LETTER,
                prefetch_count=50,
            )
            async with receiver:
                while True:
                    messages = await receiver.receive_messages(max_message_count=50, max_wait_time=2)
                    if not messages:
                        break
                    for msg in messages:
                        await receiver.complete_message(msg)
                        deleted_dlq += 1
    except Exception as e:
        logger.error(f"Failed to purge DLQ: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to purge DLQ: {str(e)}")

    return {
        "status": "success",
        "deleted_dlq": deleted_dlq
    }


@router.get("/deadletter", response_model=DeadLetterSummary)
async def deadletter_summary(clients: Clients = Depends(get_clients)):
    """Peek the dead-letter queue and return a summary for admin UI."""
    if not clients.sb_client:
        raise HTTPException(status_code=503, detail="Service Bus client not initialized")

    try:
        messages: list[DeadLetterMessage] = []
        async with clients.sb_client.get_queue_receiver(
            queue_name=config.SERVICE_BUS_QUEUE,
            sub_queue=ServiceBusSubQueue.DEAD_LETTER,
            max_wait_time=5,
        ) as receiver:
            peeked = await receiver.peek_messages(max_message_count=10)
            for m in peeked:
                body_bytes = b"".join([b for b in m.body])
                try:
                    payload = json.loads(body_bytes.decode())
                except Exception:
                    payload = {"raw": body_bytes.decode(errors="ignore")}
                blob_url = extract_blob_url(payload)
                messages.append(
                    DeadLetterMessage(
                        message_id=getattr(m, "message_id", None),
                        delivery_count=getattr(m, "delivery_count", None),
                        dead_letter_reason=getattr(m, "dead_letter_reason", None),
                        dead_letter_error_description=getattr(m, "dead_letter_error_description", None),
                        blob_url=blob_url,
                        blob_id=blob_id_from_url(blob_url) if blob_url else None,
                        enqueued_time_utc=getattr(m, "enqueued_time_utc", None),
                        sequence_number=getattr(m, "sequence_number", None),
                    )
                )
    except Exception as ex:
        logger.exception("Failed to peek dead-letter queue: %s", ex)
        raise HTTPException(status_code=500, detail=f"Failed to peek dead-letter queue: {ex}") from ex

    return DeadLetterSummary(count=len(messages), messages=messages)


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def diagnostics(clients: Clients = Depends(get_clients)):
    ok, readiness = await readiness_checks(clients=clients, deep=True)
    env = {
        "subscription_id": os.getenv("AZURE_SUBSCRIPTION_ID"),
        "tenant_id": os.getenv("AZURE_TENANT_ID"),
        "resource_group": os.getenv("AZURE_RESOURCE_GROUP"),
        "app_version": os.getenv("APP_VERSION"),
        "service_bus_fqdn": config.SERVICE_BUS_FQDN,
        "service_bus_queue": config.SERVICE_BUS_QUEUE,
        "storage_account_url": config.BLOB_ACCOUNT_URL,
        "storage_container": config.BLOB_CONTAINER_INPUT,
        "cosmos_endpoint": config.COSMOS_ENDPOINT,
        "cosmos_db": config.COSMOS_DB,
        "cosmos_container": config.COSMOS_CONTAINER,
        "cosmos_query_max_limit": getattr(config, "COSMOS_QUERY_MAX_LIMIT", None),
        "ai_endpoint": config.MISTRAL_ENDPOINT or config.PHI_ENDPOINT,
        "mistral_deployment": config.MISTRAL_DEPLOYMENT,
        "phi_deployment": config.PHI_DEPLOYMENT,
    }
    return DiagnosticsResponse(env=env, readiness=readiness, ok=ok)


@router.get("/search", response_model=SearchResponse)
async def search_emails(q: str, limit: int = 5, clients: Clients = Depends(get_clients)):
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query too short")
    limit = min(max(limit, 1), config.COSMOS_QUERY_MAX_LIMIT)

    items = await search_email_records(q, limit=limit, clients=clients)
    return SearchResponse(items=items)


@router.get("/errors/latest", response_model=ErrorsResponse)
async def latest_errors(limit: int = 5, clients: Clients = Depends(get_clients)):
    limit = min(max(limit, 1), config.COSMOS_QUERY_MAX_LIMIT)
    items = await get_latest_errors(limit=limit, clients=clients)
    return ErrorsResponse(items=items)


@router.get("/stats/summary", response_model=StatsSummaryResponse)
async def stats_summary(clients: Clients = Depends(get_clients)):
    summary = await get_stats_summary(clients=clients)
    return StatsSummaryResponse(**summary)


@router.get("/intents/top", response_model=IntentsResponse)
async def top_intents(limit: int = 5, clients: Clients = Depends(get_clients)):
    limit = min(max(limit, 1), config.COSMOS_QUERY_MAX_LIMIT)
    items = await get_top_intents(limit=limit, clients=clients)
    return IntentsResponse(items=items)


@router.get("/low-confidence", response_model=LowConfidenceResponse)
async def low_confidence(limit: int = 5, intent: str | None = None, clients: Clients = Depends(get_clients)):
    limit = min(max(limit, 1), config.COSMOS_QUERY_MAX_LIMIT)
    items = await get_low_confidence_items(limit=limit, intent=intent, clients=clients)
    return LowConfidenceResponse(items=items)
