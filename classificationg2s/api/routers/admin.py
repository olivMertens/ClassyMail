from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from classificationg2s.core import config
from classificationg2s.services.azure_clients import Clients, get_clients, get_cosmos_container, blob_id_from_url
import logging
import uuid
import json
from datetime import datetime, timezone
from fpdf import FPDF
from azure.servicebus import ServiceBusMessage

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger("classimail.admin")

class ResetRequest(BaseModel):
    confirm_1: bool
    confirm_2: bool

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
        container = await get_cosmos_container(clients)
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
        container = await get_cosmos_container(clients)
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

    if errors:
        return {
            "status": "partial_success",
            "deleted_blobs": deleted_blobs,
            "deleted_records": deleted_records,
            "errors": errors
        }

    return {
        "status": "success",
        "deleted_blobs": deleted_blobs,
        "deleted_records": deleted_records
    }
