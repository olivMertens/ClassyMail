from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, UploadFile, Depends

from classificationg2s.core import config
from classificationg2s.services.azure_clients import get_blob_service_client


router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload")
async def upload_pdfs(files: list[UploadFile] = File(...), blob_service_client=Depends(get_blob_service_client)):
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Max 10 fichiers")

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

        if status == "error":
            results.append({"name": f.filename, "status": status, "error": error})
            continue

        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", f.filename)
        safe_name = safe_name[-120:]
        unique_name = f"{uuid.uuid4()}-{safe_name}"
        blob_name = f"uploads/{today}/{unique_name}"
        blob_client = container_client.get_blob_client(blob_name)
        await blob_client.upload_blob(f.file, overwrite=True, content_type="application/pdf")
        results.append({"name": f.filename, "status": status, "blob_url": blob_client.url})

    return {"results": results, "count": len([r for r in results if r["status"] == "uploaded"]) }
