from __future__ import annotations

from fastapi import APIRouter, Depends
from classificationg2s.services.settings_store import load_settings, save_settings, save_settings_async
from classificationg2s.core import config
from classificationg2s.services.azure_clients import Clients, get_clients

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
async def get_settings():
    return load_settings()


@router.get("/settings/defaults")
async def get_settings_defaults():
    return {
        "phi4_input_per_1k": config.PHI4_COST_PER_1K_INPUT,
        "phi4_output_per_1k": config.PHI4_COST_PER_1K_OUTPUT,
        "mistral_per_1k_pages": config.MISTRAL_OCR_COST_PER_1K_PAGES,
        "ocr_max_attempts": getattr(config, "MISTRAL_OCR_MAX_ATTEMPTS", 3),
    }


@router.get("/settings/organization")
async def get_organization():
    """Get the organization/destination name for branding"""
    return {"name": config.ORGANIZATION_NAME}



@router.post("/settings")
async def set_settings(payload: dict, clients: Clients = Depends(get_clients)):
    save_settings(payload)
    try:
        await save_settings_async(payload, clients=clients)
    except Exception:
        pass
    return payload
