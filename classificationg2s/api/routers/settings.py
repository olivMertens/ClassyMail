from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
async def get_settings(request: Request):
    return getattr(request.app.state, "cost_overrides", {})


@router.post("/settings")
async def set_settings(request: Request, payload: dict):
    request.app.state.cost_overrides = payload or {}
    return request.app.state.cost_overrides
