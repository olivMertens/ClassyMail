from __future__ import annotations

from fastapi import APIRouter
from classificationg2s.services.settings_store import load_settings, save_settings


router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
async def get_settings():
    return load_settings()


@router.post("/settings")
async def set_settings(payload: dict):
    save_settings(payload)
    return payload
