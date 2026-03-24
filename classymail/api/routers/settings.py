from __future__ import annotations

from fastapi import APIRouter, Depends
from classymail.services.settings_store import load_settings, save_settings, save_settings_async
from classymail.core import config
from classymail.services.azure_clients import Clients, get_clients

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


@router.get("/settings/agentic-prompt")
async def get_agentic_prompt():
    """Return the orchestrator system prompt (read-only preview for the UI)."""
    from classymail.agents.orchestrator import _build_orchestrator_prompt
    from classymail.services.settings_store import get_categories_prompt_text
    from classymail.agents.config import get_agentic_settings

    settings = load_settings()
    agentic = get_agentic_settings(settings)
    categories_text = get_categories_prompt_text()
    max_agents = agentic.get("max_parallel_agents", 6)

    prompt = _build_orchestrator_prompt(categories_text, max_agents, "en")
    return {
        "prompt": prompt,
        "model": agentic.get("orchestrator_model", "gpt-4.1-nano"),
        "max_agents": max_agents,
        "categories_count": len(settings.get("categories", [])),
    }



@router.post("/settings")
async def set_settings(payload: dict, clients: Clients = Depends(get_clients)):
    save_settings(payload)
    try:
        await save_settings_async(payload, clients=clients)
    except Exception:
        pass
    return payload
