from __future__ import annotations

from fastapi import APIRouter
from classificationg2s.services.settings_store import load_settings, save_settings
from classificationg2s.core import config


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
    }


@router.post("/settings")
async def set_settings(payload: dict):
    save_settings(payload)
    return payload
