from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from classymail.core import config
from classymail.core.monitoring import get_queue_metrics, get_system_health_score
from classymail.services.azure_clients import Clients, get_clients, blob_id_from_url
import logging
import uuid
import json
import os
from datetime import datetime, timezone, timedelta
from azure.servicebus import ServiceBusMessage, ServiceBusSubQueue
from classymail.services.messages import extract_blob_url
from classymail.services.azure_clients import readiness_checks, get_cosmos_container as azure_get_cosmos_container
from classymail.services.repository import (
    search_email_records,
    get_latest_errors,
    get_stats_summary,
    get_top_intents,
    get_low_confidence_items,
    get_processing_stats_by_day,
    get_seed_examples_for_synthesis,
    save_synthetic_record
)
from classymail.services.generator import generate_email_pdf, generate_synthetic_from_seeds
from classymail.services.settings_store import load_settings
from azure.monitor.query.aio import LogsQueryClient
from azure.monitor.query import LogsQueryStatus

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger("ClassyMail.admin")

class ResetRequest(BaseModel):
    confirm_1: bool
    confirm_2: bool


class SimulateFlowRequest(BaseModel):
    use_aoai: bool = False


class AppInsightLog(BaseModel):
    timestamp: datetime
    message: str
    severity_level: int | None
    type: str # Trace or Exception
    properties: dict | None


class LogsResponse(BaseModel):
    items: list[AppInsightLog]


class DeadLetterMessage(BaseModel):
    message_id: str | None = None
    delivery_count: int | None = None
    dead_letter_reason: str | None = None
    dead_letter_error_description: str | None = None
    blob_url: str | None = None
    blob_id: str | None = None
    enqueued_time_utc: datetime | None = None
    sequence_number: int | None = None
    processing_log: list[dict] | None = None


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


class UIConfigResponse(BaseModel):
    show_info_modal: bool
    show_developer_tab: bool
    organization_name: str | None = None
    environment: str | None = None


class QueueMetricsResponse(BaseModel):
    """Queue metrics response."""
    active_message_count: int
    dead_letter_count: int
    scheduled_message_count: int
    transfer_message_count: int
    total_message_count: int
    size_in_bytes: int | None = None
    updated_at: str | None = None
    error: str | None = None


class HealthScoreResponse(BaseModel):
    """System health score response."""
    score: float
    status: str
    factors: dict


class GenerateSyntheticRequest(BaseModel):
    target_count: int = 50

@router.post("/generate-synthetic", status_code=status.HTTP_200_OK)
async def generate_synthetic_data(
    req: GenerateSyntheticRequest,
    clients: Clients = Depends(get_clients)
):
    """
    Generate synthetic data to reach the target count for fine-tuning.
    Uses existing processed examples from Cosmos DB as seeds.
    """
    try:
        # 1. Get current count (from stats or just proceed)
        # We assume caller checked stats, but we can prevent over-generation if needed.

        # 2. Fetch seed examples
        seeds = await get_seed_examples_for_synthesis(limit=20, clients=clients)
        if not seeds:
            raise HTTPException(
                status_code=400,
                detail="No processed emails found to use as seed data. Upload and process at least 1 email via the Upload page before generating synthetic data."
            )

        # 3. Generate synthetic data
        # We limit generation to avoid timeouts.
        # Generating 50 items might take too long for one request.
        # Ideally this should be a background job, but for demo we do a small batch synchronously.
        count_to_generate = min(req.target_count, 10) # Safety cap for sync request

        generated_items = await generate_synthetic_from_seeds(seed_examples=seeds, count=count_to_generate)

        # 4. Save items
        saved_count = 0
        for item in generated_items:
            await save_synthetic_record(item, clients=clients)
            saved_count += 1

        return {
            "status": "success",
            "generated_count": saved_count,
            "message": f"Generated {saved_count} synthetic items based on {len(seeds)} seeds."
        }

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        logger.error(f"Failed to generate synthetic data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ui-config", response_model=UIConfigResponse)
async def get_ui_config():
    """Returns UI feature flags based on environment variables."""
    return UIConfigResponse(
        show_info_modal=config.UI_SHOW_INFO_MODAL,
        show_developer_tab=config.UI_SHOW_DEVELOPER_TAB,
        organization_name=getattr(config, "ORGANIZATION_NAME", None),
        environment=getattr(config, "AZURE_ENV", None),
    )


@router.post("/debug/simulate-flow")
async def simulate_flow(
    request: SimulateFlowRequest,
    clients: Clients = Depends(get_clients)
):
    """
    Simulates a complete flow by creating and uploading a realistic French insurance email PDF.

    Features:
    - Generates a random insurance email from templates
    - Optionally uses AOAI to enhance realism (based on request param or auto-detect)
    - Uploads to Blob Storage with dated folder structure
    - Creates PENDING record for immediate UI feedback
    - Triggers worker via Service Bus

    Returns the item_id (blob path) to track via /api/emails/{id}.
    """
    try:
        # Use AOAI if explicitly requested or auto-detect if available
        use_aoai = request.use_aoai or bool(os.getenv("AZURE_OPENAI_ENDPOINT"))

        logger.info("[SIMULATION] Starting E2E simulation flow with realistic email")

        # 1. Generate Realistic Email PDF (with AOAI if available)
        logger.info("[SIMULATION] Step 1: Generating realistic French insurance email PDF")
        pdf_bytes, category, subject = generate_email_pdf(use_aoai=use_aoai)
        aoai_status = "enhanced" if use_aoai else "template"
        logger.info(f"[SIMULATION] Generated {aoai_status} PDF: {len(pdf_bytes)} bytes, Category: {category}")

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
                "subject": f"[TEST] {subject}",
                "created_at": pending_start,
                "updated_at": pending_start,
                "markdown": None,
                "classification": None,
                "test_mode": True,
                "expected_category": category,
                "processing_log": [{"ts": pending_start, "stage": "simulation", "event": "e2e_test_email"}]
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
            "blob_url": blob_url,
            "test_mode": True,
            "expected_category": category,
            "generated_subject": subject
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
                blob_id = blob_id_from_url(blob_url) if blob_url else None
                processing_log = None
                if blob_id:
                    try:
                        await clients.ensure_cosmos_container()
                        doc = await clients.cosmos_container.read_item(item=blob_id, partition_key=blob_id)
                        processing_log = doc.get("processing_log")
                    except Exception:
                        processing_log = None

                messages.append(
                    DeadLetterMessage(
                        message_id=getattr(m, "message_id", None),
                        delivery_count=getattr(m, "delivery_count", None),
                        dead_letter_reason=getattr(m, "dead_letter_reason", None),
                        dead_letter_error_description=getattr(m, "dead_letter_error_description", None),
                        blob_url=blob_url,
                        blob_id=blob_id,
                        enqueued_time_utc=getattr(m, "enqueued_time_utc", None),
                        sequence_number=getattr(m, "sequence_number", None),
                        processing_log=processing_log,
                    )
                )
    except Exception as ex:
        logger.exception("Failed to peek dead-letter queue: %s", ex)
        raise HTTPException(status_code=500, detail=f"Failed to peek dead-letter queue: {ex}") from ex

    return DeadLetterSummary(count=len(messages), messages=messages)


@router.get("/version")
async def version():
    env_version = os.getenv("APP_VERSION")
    return {"version": env_version or "unknown"}


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def diagnostics(clients: Clients = Depends(get_clients)):
    ok, readiness = await readiness_checks(clients=clients, deep=True)
    settings = load_settings()
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
        "chat_deployment": config.CHAT_DEPLOYMENT,
        "adversarial_model": settings.get("adversarial_model"),
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


@router.get("/stats/processing")
async def processing_stats(days: int = 7, clients: Clients = Depends(get_clients)):
    days = max(1, min(days, 30))
    stats = await get_processing_stats_by_day(days=days, clients=clients)
    return stats


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


@router.get("/telemetry/logs", response_model=LogsResponse)
async def get_app_insights_logs(days: int = 1, limit: int = 50, clients: Clients = Depends(get_clients)):
    """
    Fetches recent traces and exceptions from Application Insights via Log Analytics.
    """
    workspace_id = config.LOG_ANALYTICS_WORKSPACE_ID
    if not workspace_id:
        # Fallback if not configured: return empty (or error if critical, but UI should handle it)
        logger.warning("LOG_ANALYTICS_WORKSPACE_ID not set. Cannot fetch logs.")
        return LogsResponse(items=[])

    try:
        query = f"""
        union AppTraces, AppExceptions
        | where TimeGenerated > ago({days}d)
        | project TimeGenerated, Message, SeverityLevel, Type, Properties
        | order by TimeGenerated desc
        | take {limit}
        """

        async with LogsQueryClient(clients.credential) as client:
            response = await client.query_workspace(
                workspace_id=workspace_id,
                query=query,
                timespan=timedelta(days=days)
            )

        if response.status == LogsQueryStatus.FAILURE:
            logger.error(f"Logs query failed: {response.partial_error}")
            raise HTTPException(status_code=502, detail="Logs query failed")

        logs = []
        for table in response.tables:
            for row in table.rows:
                # row is a mapped object or list depending on SDK version, usually list in python if not strictly typed
                # Columns: TimeGenerated, Message, SeverityLevel, Type, Properties
# Create dictionary safely
                data = {c.name: row[i] for i, c in enumerate(table.columns)}

                # Parse properties if string
                props = data.get("Properties")
                if isinstance(props, str) and props:
                    try:
                        props = json.loads(props)
                    except ValueError:
                        pass
                elif not isinstance(props, dict):
                    props = {}

                logs.append(AppInsightLog(
                    timestamp=data["TimeGenerated"],
                    message=data.get("Message") or data.get("OuterMessage") or "No message", # AppExceptions use OuterMessage sometimes? No, unified schema usually.
                    severity_level=data.get("SeverityLevel"),
                    type=data.get("Type"),
                    properties=props
                ))

        return LogsResponse(items=logs)

    except Exception as e:
        logger.error(f"Failed to query Log Analytics: {e}")
        # Return empty list or raise? UI needs robustness.
        # Ensure we don't break the UI panel if creds are wrong.
        return LogsResponse(items=[])


@router.get("/test-phi4")
async def test_phi4_connection(clients: Clients = Depends(get_clients)):
    """Test Phi-4 model connection"""
    try:
        import httpx
        from classymail.services.azure_clients import auth_headers

        if not config.PHI_ENDPOINT:
             return { "status": "error", "error": "PHI_ENDPOINT not configured", "model": config.PHI_DEPLOYMENT }

        headers = await auth_headers(clients, model_type="openai")
        endpoint = f"{config.PHI_ENDPOINT.rstrip('/')}/openai/deployments/{config.PHI_DEPLOYMENT}/chat/completions?api-version={config.AI_API_VERSION}"

        payload = {
            "messages": [{"role": "user", "content": "Say 'Connection OK'"}],
            "max_tokens": 10,
            "temperature": 0
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            if response.is_error:
                error_detail = response.text
                logger.error(f"Phi-4 error response: {error_detail}")
                return { "status": "error", "error": f"HTTP {response.status_code}: {error_detail}", "model": config.PHI_DEPLOYMENT }

            data = response.json()

        return {
            "status": "success",
            "model": config.PHI_DEPLOYMENT,
            "response": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
            "status_code": response.status_code
        }
    except Exception as e:
        logger.error(f"Phi-4 connection test failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "model": config.PHI_DEPLOYMENT
        }


@router.get("/blob-info")
async def blob_info(blob_url: str, clients: Clients = Depends(get_clients)):
    """Check blob existence, return container/blob info and SAS."""
    from azure.storage.blob.aio import BlobClient
    from urllib.parse import urlparse

    parsed = urlparse(blob_url)
    container = parsed.path.lstrip('/').split('/')[0] if parsed.path else ''
    blob_name = '/'.join(parsed.path.lstrip('/').split('/')[1:]) if parsed.path else ''
    exists = False
    try:
        blob_client = BlobClient.from_blob_url(blob_url, credential=clients.credential)
        exists = await blob_client.exists()
    except Exception as e:
        return {"error": str(e), "container": container, "blob": blob_name, "exists": exists}

    return {"container": container, "blob": blob_name, "exists": exists, "sas_url": None}


@router.get("/test-mistral-ocr")
async def test_mistral_ocr_connection(clients: Clients = Depends(get_clients)):
    """Test Mistral OCR connection"""
    try:
        import httpx
        from classymail.services.azure_clients import auth_headers

        if not config.MISTRAL_ENDPOINT:
            return { "status": "error", "error": "MISTRAL_ENDPOINT not configured in environment", "model": config.MISTRAL_DEPLOYMENT }

        headers = await auth_headers(clients, model_type="mistral")

        # Handle full URL vs base URL
        base_mistral = config.MISTRAL_ENDPOINT.rstrip("/")
        if base_mistral.endswith("/providers/mistral/azure/ocr"):
            endpoint = base_mistral
        else:
            endpoint = f"{base_mistral}/providers/mistral/azure/ocr"
        if "?" not in endpoint:
            endpoint = f"{endpoint}?api-version={config.MISTRAL_API_VERSION}"

        # Minimal test payload: 1x1 PNG data URI
        one_px_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAuMBg4eM8sYAAAAASUVORK5CYII="
        payload = {
            "model": config.MISTRAL_DEPLOYMENT,
            "document": {
                "type": "image_url",
                "image_url": f"data:image/png;base64,{one_px_png}"
            },
            "include_image_base64": False
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            if response.is_error:
                error_detail = response.text
                logger.error(f"Mistral OCR error response: {error_detail}")
                return { "status": "error", "error": f"HTTP {response.status_code}: {error_detail}", "model": config.MISTRAL_DEPLOYMENT }
            data = response.json()

        return {
            "status": "success",
            "model": config.MISTRAL_DEPLOYMENT,
            "pages_returned": len(data.get("pages", [])),
            "status_code": response.status_code
        }
    except Exception as e:
        logger.error(f"Mistral OCR connection test failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "model": config.MISTRAL_DEPLOYMENT
        }


@router.get("/test-gpt")
async def test_gpt_connection(model: str | None = None, clients: Clients = Depends(get_clients)):
    """
    Test GPT connection (defaults to configured fallback, or specific model).
    Enhanced to test gpt-5-nano, gpt-5-mini, gpt-4.1-nano and other models.
    """
    try:
        import httpx
        from classymail.services.azure_clients import auth_headers

        # Use PHI_ENDPOINT as fallback if GPT endpoint not configured
        gpt_endpoint = getattr(config, "GPT_ENDPOINT", config.PHI_ENDPOINT)

        if not gpt_endpoint:
             return { "status": "error", "error": "GPT_ENDPOINT/PHI_ENDPOINT not configured", "model": "unknown" }

        # Determine deployment name - prefer configured fallback if None
        if model:
             # Trust the caller (admin) to test specific models like gpt5-nano, gpt-4o, etc
            gpt_deployment = model
        else:
            gpt_deployment = getattr(config, "GPT_DEPLOYMENT", config.PHI_FALLBACK_DEPLOYMENT)

        api_version = config.AI_API_VERSION

        headers = await auth_headers(clients, model_type="openai")
        endpoint = f"{gpt_endpoint.rstrip('/')}/openai/deployments/{gpt_deployment}/chat/completions?api-version={api_version}"

        # Base payload
        payload = {
            "messages": [{"role": "user", "content": "Say 'GPT Connection OK'"}],
            "max_tokens": 10,
        }

        # Some models don't support temperature parameter
        if model not in ["gpt-5-nano", "gpt-4.1-nano"]:
            payload["temperature"] = 0

        logger.info(f"[TEST-GPT] Testing {gpt_deployment} at {endpoint}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            if response.is_error:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_message = error_json.get("error", {}).get("message", error_detail)
                except Exception:
                    error_message = error_detail

                logger.error(f"GPT error response for {gpt_deployment}: {error_message}")
                return {
                    "status": "error",
                    "error": f"HTTP {response.status_code}: {error_message}",
                    "model": gpt_deployment,
                    "endpoint": gpt_endpoint,
                    "deployment": gpt_deployment,
                    "details": "Check if deployment exists in Azure AI Foundry and has proper RBAC permissions"
                }
            data = response.json()

        return {
            "status": "success",
            "model": gpt_deployment,
            "endpoint": gpt_endpoint,
            "response": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
            "usage": data.get("usage"),
            "api_version": api_version,
            "status_code": response.status_code
        }
    except Exception as e:
        logger.error(f"GPT connection test failed for {model}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "model": model or getattr(config, "GPT_DEPLOYMENT", config.PHI_FALLBACK_DEPLOYMENT)
        }


@router.get("/test-language-service")
async def test_language_service(clients: Clients = Depends(get_clients)):
    """
    Test Azure AI Language service connection for PII detection.
    """
    try:
        import httpx
        from classymail.services.azure_clients import auth_headers

        language_endpoint = getattr(config, "AZURE_LANGUAGE_ENDPOINT", None)

        if not language_endpoint:
            return {
                "status": "not_configured",
                "message": "AZURE_LANGUAGE_ENDPOINT not configured (optional service)"
            }

        api_version = "2023-04-01"
        headers = await auth_headers(clients, model_type="cognitive")
        headers["Content-Type"] = "application/json"

        endpoint = f"{language_endpoint.rstrip('/')}/language/:analyze-text?api-version={api_version}"

        # Test payload for PII detection
        payload = {
            "kind": "PiiEntityRecognition",
            "parameters": {
                "modelVersion": "latest"
            },
            "analysisInput": {
                "documents": [
                    {
                        "id": "1",
                        "language": "fr",
                        "text": "Test de connexion"
                    }
                ]
            }
        }

        logger.info(f"[TEST-LANGUAGE] Testing Azure AI Language at {endpoint}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint, json=payload, headers=headers)

            if response.is_error:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_message = error_json.get("error", {}).get("message", error_detail)
                except Exception:
                    error_message = error_detail

                logger.error(f"Language service error response: {error_message}")
                return {
                    "status": "error",
                    "error": f"HTTP {response.status_code}: {error_message}",
                    "endpoint": language_endpoint,
                    "details": "Check if Language service is deployed and has proper RBAC permissions (Cognitive Services Language Reader)"
                }

            data = response.json()
            documents = data.get("results", {}).get("documents", [])
            categories_detected = len(documents[0].get("entities", [])) if documents else 0

        return {
            "status": "success",
            "endpoint": language_endpoint,
            "categories_detected": categories_detected,
            "api_version": api_version,
            "status_code": response.status_code,
            "message": "Azure AI Language service is accessible"
        }
    except Exception as e:
        logger.error(f"Language service connection test failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "endpoint": getattr(config, "AZURE_LANGUAGE_ENDPOINT", "not configured")
        }


@router.get("/validate-aca-env")
async def validate_aca_environment():
    """
    Validate Azure Container Apps environment variables.
    Returns status of required and optional variables for operational visibility.
    """
    try:
        required_vars = [
            "AZURE_CLIENT_ID",
            "COSMOS_ENDPOINT",
            "COSMOS_DATABASE_NAME",
            "COSMOS_CONTAINER_NAME",
            "COSMOS_CHAT_CONTAINER",
            "STORAGE_ACCOUNT_NAME",
            "CONTAINER_NAME_PDF",
            "SERVICE_BUS_FQDN",
            "QUEUE_NAME_PDF",
            "AI_ENDPOINT",
            "AI_API_VERSION",
            "PHI_DEPLOYMENT",
            "PHI_FALLBACK_DEPLOYMENT",
            "MISTRAL_DEPLOYMENT",
            "MISTRAL_MODE",
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "LOG_ANALYTICS_WORKSPACE_ID",
            "OTEL_SERVICE_NAME"
        ]

        optional_vars = [
            "AZURE_LANGUAGE_ENDPOINT",
            "CHAT_DEPLOYMENT",
            "GPT_DEPLOYMENT",
            "OCR_DEPLOYMENT",
            "UI_SHOW_INFO_MODAL",
            "UI_SHOW_DEVELOPER_TAB",
            "ORGANIZATION_NAME"
        ]

        def check_var(var_name: str) -> dict:
            value = os.getenv(var_name)
            present = value is not None and value != ""
            masked_value = None
            if present and value:
                # Mask sensitive values (show first 20 chars)
                masked_value = value[:20] + "..." if len(value) > 20 else value
            return {
                "name": var_name,
                "present": present,
                "value": masked_value
            }

        required_status = [check_var(var) for var in required_vars]
        optional_status = [check_var(var) for var in optional_vars]

        all_required_present = all(item["present"] for item in required_status)
        missing_required = [item["name"] for item in required_status if not item["present"]]

        return {
            "status": "ok" if all_required_present else "missing_required",
            "required": required_status,
            "optional": optional_status,
            "all_required_present": all_required_present,
            "missing_required": missing_required,
            "summary": {
                "required_count": len(required_vars),
                "required_present": sum(1 for item in required_status if item["present"]),
                "optional_count": len(optional_vars),
                "optional_present": sum(1 for item in optional_status if item["present"])
            }
        }
    except Exception as e:
        logger.error(f"ACA environment validation failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/metrics/queue", response_model=QueueMetricsResponse)
async def queue_metrics(clients: Clients = Depends(get_clients)):
    """
    Get Service Bus queue metrics including message counts.

    Provides visibility into:
    - Active message count (pending processing)
    - Dead letter queue count (failed messages)
    - Scheduled message count
    - Total message count
    """
    metrics = await get_queue_metrics(
        sb_client=clients.sb_client,
        credential=clients.credential,
    )
    return QueueMetricsResponse(**metrics)


@router.get("/metrics/health", response_model=HealthScoreResponse)
async def health_score(clients: Clients = Depends(get_clients)):
    """
    Get overall system health score (0-100).

    Factors:
    - Queue backlog
    - Dead letter queue size
    - Recent error count
    - Processing success rate
    """
    # Get queue metrics
    queue_metrics_data = await get_queue_metrics(
        sb_client=clients.sb_client,
        credential=clients.credential,
    )

    # Get error statistics (using latest errors as proxy)
    try:
        errors = await get_latest_errors(limit=100, clients=clients)
        error_count = len(errors)
    except Exception:
        error_count = 0

    # Get total count from stats
    try:
        stats = await get_stats_summary(clients=clients)
        total_count = stats.get("total", 0)
    except Exception:
        total_count = 0

    # Calculate health score
    health = get_system_health_score(
        queue_metrics=queue_metrics_data,
        error_count=error_count,
        total_count=max(total_count, 1),  # Avoid division by zero
    )

    return HealthScoreResponse(**health)
