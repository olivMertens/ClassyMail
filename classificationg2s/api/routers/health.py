from __future__ import annotations

from fastapi import APIRouter, HTTPException

from classificationg2s.services.azure_clients import readiness_checks


router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    ready, failures = await readiness_checks()
    if not ready:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "failures": failures})
    return {"status": "ready"}


@router.get("/ready")
async def ready():
    return await readyz()
