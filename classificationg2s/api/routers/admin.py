from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from classificationg2s.core import config
from classificationg2s.services.azure_clients import Clients, get_clients, get_cosmos_container
import logging

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger("classimail.admin")

class ResetRequest(BaseModel):
    confirm_1: bool
    confirm_2: bool

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
