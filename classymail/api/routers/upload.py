from __future__ import annotations

import re
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, UploadFile, Depends
from azure.core.exceptions import AzureError

from classymail.core import config
# from classymail.core.rate_limit import limiter  # TODO: Re-enable for rate limiting
from classymail.services.azure_clients import get_blob_service_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload")
# @limiter.limit("20/hour")  # TODO: Re-enable once slowapi integration is completed
async def upload_pdfs(
    files: list[UploadFile] = File(...),
    blob_service_client=Depends(get_blob_service_client),
):
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Max 20 files per batch")

    # Enforce 100MB total batch size
    total_size = 0
    for f in files:
        f.file.seek(0, 2)
        total_size += f.file.tell()
        f.file.seek(0)
    if total_size > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Total batch size exceeds 100MB")

    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    container = config.BLOB_CONTAINER_INPUT
    results = []

    container_client = blob_service_client.get_container_client(container)
    try:
        await container_client.create_container()
    except Exception:
        pass

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
            else:
                # Validate PDF magic bytes
                magic = f.file.read(4)
                f.file.seek(0)
                if not magic.startswith(b"%PDF"):
                    status, error = "error", "invalid_pdf_format"

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
            results.append({"name": f.filename, "status": status, "blob_url": blob_client.url})
            logger.info(f"Uploaded {f.filename} → {blob_client.url} (Event Grid will enqueue)")
        except AzureError as e:
            logger.error(f"Azure Storage Upload Failed for {f.filename}: {str(e)}")
            results.append({"name": f.filename, "status": "error", "error": f"Storage Error: {type(e).__name__}"})
        except Exception:
            logger.exception(f"Unexpected error uploading {f.filename}")
            results.append({"name": f.filename, "status": "error", "error": "Internal Server Error"})

    return {"results": results, "count": len([r for r in results if r["status"] == "uploaded"]) }
