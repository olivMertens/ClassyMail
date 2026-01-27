from __future__ import annotations

import re
import uuid
import logging
import json
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, UploadFile, Depends
from azure.core.exceptions import AzureError
from azure.servicebus import ServiceBusMessage

from classificationg2s.core import config
from classificationg2s.services.azure_clients import Clients, get_clients, blob_id_from_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload")
async def upload_pdfs(files: list[UploadFile] = File(...), clients: Clients = Depends(get_clients)):
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Max 10 fichiers")

    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    container = config.BLOB_CONTAINER_INPUT
    results = []

    container_client = clients.blob_service_client.get_container_client(container)
    try:
        await container_client.create_container()
    except Exception:
        pass

    # Batch sender for Service Bus
    sb_sender = clients.sb_client.get_queue_sender(queue_name=config.SERVICE_BUS_QUEUE)

    async with sb_sender:
        for f in files:
            status = "uploaded"
            error = None

            if not f.filename.lower().endswith(".pdf") or f.content_type not in (
                "application/pdf",
                "application/octet-stream",
            ):
                status, error = "error", "invalid_type"
            else:
                f.file.seek(0, 2)
                size = f.file.tell()
                f.file.seek(0)
                if size > config.MAX_UPLOAD_SIZE:
                    status, error = "error", "too_large"

            if status == "error":
                results.append({"name": f.filename, "status": status, "error": error})
                continue

            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", f.filename)
            safe_name = safe_name[-120:]
            unique_name = f"{uuid.uuid4()}-{safe_name}"
            blob_name = f"uploads/{today}/{unique_name}"
            blob_client = container_client.get_blob_client(blob_name)
            try:
                await blob_client.upload_blob(f.file, overwrite=True, content_type="application/pdf")
                blob_url = blob_client.url
                results.append({"name": f.filename, "status": status, "blob_url": blob_url})

                # Create PENDING status for immediate UI feedback (Discovery)
                try:
                    await clients.ensure_cosmos_container()
                    pending_id = blob_id_from_url(blob_url)
                    pending_start = datetime.now(timezone.utc).isoformat()
                    # Minimal fields to satisfy UI. Worker will upsert/overwrite full record later.
                    pending_doc = {
                        "id": pending_id,
                        "file_url": blob_url,
                        "status": "PENDING",
                        "subject": f"{f.filename} (Processing...)",
                        "created_at": pending_start,
                        "updated_at": pending_start,
                        "markdown": None,
                        "classification": None,
                        "processing_log": [{"ts": pending_start, "stage": "upload", "event": "pending_manual_trigger"}]
                    }
                    await clients.cosmos_container.upsert_item(pending_doc)
                except Exception as e:
                    logger.warning(f"Failed to create pending record for {f.filename}: {e}")

                # Manual Trigger for reliability
                message_payload = {"blob_url": blob_client.url}
                await sb_sender.send_messages(ServiceBusMessage(json.dumps(message_payload)))

            except AzureError as e:
                logger.error(f"Azure Storage Upload Failed for {f.filename}: {str(e)}")
                results.append({"name": f.filename, "status": "error", "error": f"Storage Error: {type(e).__name__}"})
            except Exception:
                logger.exception(f"Unexpected error uploading {f.filename}")
                results.append({"name": f.filename, "status": "error", "error": "Internal Server Error"})

    return {"results": results, "count": len([r for r in results if r["status"] == "uploaded"]) }
