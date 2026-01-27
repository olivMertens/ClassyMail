from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from classificationg2s.core import config
from classificationg2s.services.azure_clients import Clients, get_clients, get_cosmos_container
import logging
import uuid

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger("classimail.admin")

class ResetRequest(BaseModel):
    confirm_1: bool
    confirm_2: bool

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
