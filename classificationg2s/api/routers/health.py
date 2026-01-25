from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends

from classificationg2s.services.azure_clients import readiness_checks, get_clients, Clients


router = APIRouter(tags=["health"])


async def _health():
    return {"status": "ok"}


router.get("/healthz")(_health)
router.get("/health")(_health)


async def _ready(clients: Clients = Depends(get_clients)):
    ready, failures = await readiness_checks(clients=clients, deep=False)
    if not ready:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "failures": failures})
    return {"status": "ready"}


async def _ready_deep(clients: Clients = Depends(get_clients)):
    ready, failures = await readiness_checks(clients=clients, deep=True)
    if not ready:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "failures": failures})
    return {"status": "ready", "mode": "deep"}


router.get("/readyz")(_ready)
router.get("/ready")(_ready)
router.get("/readyz/deep")(_ready_deep)
router.get("/ready/deep")(_ready_deep)
