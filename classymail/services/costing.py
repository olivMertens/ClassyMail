from __future__ import annotations

from typing import Optional

from classymail.core import config


# Model pricing map (per 1K tokens) - Azure OpenAI / Foundry pricing as of 2025-2026
# Prices vary by region; these are global averages. Override via env vars for precision.
MODEL_PRICING = {
    # SLMs (Small Language Models)
    "phi-4": (0.000107, 0.00043),

    # GPT-4o family
    "gpt-4o": (0.0025, 0.010),
    "gpt-4o-mini": (0.00015, 0.0006),

    # GPT-4.1 family
    "gpt-4.1": (0.002, 0.008),
    "gpt-4.1-nano": (0.0001, 0.0004),
    "gpt-4.1-mini": (0.0004, 0.0016),

    # GPT-5 family
    "gpt-5.1": (0.00125, 0.010),
    "gpt-5-nano": (0.00005, 0.0004),
    "gpt-5-mini": (0.0004, 0.0016),
    "gpt-5": (0.002, 0.008),

    # Kimi (Moonshot AI via Foundry)
    "kimi-k2.5": (0.0006, 0.003),
}


def compute_cost_llm(
    usage: Optional[dict],
    *,
    fallback_used: bool,
    model_name: Optional[str] = None,
    overrides: Optional[dict] = None
) -> Optional[float]:
    """
    Calculate LLM cost based on token usage and model pricing.

    Args:
        usage: Token usage dict with prompt_tokens/completion_tokens
        fallback_used: Whether fallback model was used (GPT-4o-mini typically)
        model_name: Model identifier (e.g., 'phi-4', 'gpt-4o-mini')
        overrides: Manual price overrides (phi4_input_per_1k, etc.)

    Returns:
        Cost in USD, or None if usage is missing
    """
    if not usage:
        return None
    overrides = overrides or {}

    prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("inputTokens") or 0
    completion = usage.get("completion_tokens") or usage.get("output_tokens") or usage.get("outputTokens") or 0

    # Determine pricing based on model or fallback flag
    if fallback_used:
        # Fallback typically uses gpt-4o-mini or configured fallback
        cin = overrides.get("fallback_input_per_1k", config.FALLBACK_COST_PER_1K_INPUT)
        cout = overrides.get("fallback_output_per_1k", config.FALLBACK_COST_PER_1K_OUTPUT)

        # If fallback costs are 0 (default), use gpt-4o-mini pricing as reasonable estimate
        if cin == 0 and cout == 0 and config.PHI_FALLBACK_DEPLOYMENT:
            fallback_model_key = config.PHI_FALLBACK_DEPLOYMENT.lower().replace("_", "-")
            cin, cout = MODEL_PRICING.get(fallback_model_key, (0.00015, 0.0006))
    else:
        # Try to use model-specific pricing if model_name provided
        if model_name:
            model_key = model_name.lower().replace("_", "-").replace("phi4", "phi-4").replace("gpt4o", "gpt-4o")
            cin, cout = MODEL_PRICING.get(model_key, (config.PHI4_COST_PER_1K_INPUT, config.PHI4_COST_PER_1K_OUTPUT))
        else:
            # Fall back to env var config (Phi-4 by default)
            cin = overrides.get("phi4_input_per_1k", config.PHI4_COST_PER_1K_INPUT)
            cout = overrides.get("phi4_output_per_1k", config.PHI4_COST_PER_1K_OUTPUT)

    return (prompt / 1000.0) * cin + (completion / 1000.0) * cout


def compute_cost_mistral(pages: int, overrides: Optional[dict] = None) -> float:
    overrides = overrides or {}
    cost_per_1k_pages = overrides.get("mistral_per_1k_pages", config.MISTRAL_OCR_COST_PER_1K_PAGES)
    return (pages / 1000.0) * cost_per_1k_pages


def compute_cost_di(pages: int, overrides: Optional[dict] = None) -> float:
    """Calculate Document Intelligence OCR cost based on pages processed."""
    overrides = overrides or {}
    cost_per_1k_pages = overrides.get("di_per_1k_pages", config.DI_OCR_COST_PER_1K_PAGES)
    return (pages / 1000.0) * cost_per_1k_pages


def compute_cost_content_understanding(pages: int, overrides: Optional[dict] = None) -> float:
    """Calculate Azure AI Content Understanding OCR cost based on pages processed."""
    overrides = overrides or {}
    cost_per_1k_pages = overrides.get("cu_per_1k_pages", config.CU_OCR_COST_PER_1K_PAGES)
    return (pages / 1000.0) * cost_per_1k_pages
