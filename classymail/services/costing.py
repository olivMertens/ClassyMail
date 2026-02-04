from __future__ import annotations

from typing import Optional

from classymail.core import config


def compute_cost_llm(usage: Optional[dict], *, fallback_used: bool, overrides: Optional[dict] = None) -> Optional[float]:
    if not usage:
        return None
    overrides = overrides or {}

    prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("inputTokens") or 0
    completion = usage.get("completion_tokens") or usage.get("output_tokens") or usage.get("outputTokens") or 0

    if fallback_used:
        cin = overrides.get("fallback_input_per_1k", config.FALLBACK_COST_PER_1K_INPUT)
        cout = overrides.get("fallback_output_per_1k", config.FALLBACK_COST_PER_1K_OUTPUT)
    else:
        cin = overrides.get("phi4_input_per_1k", config.PHI4_COST_PER_1K_INPUT)
        cout = overrides.get("phi4_output_per_1k", config.PHI4_COST_PER_1K_OUTPUT)

    return (prompt / 1000.0) * cin + (completion / 1000.0) * cout


def compute_cost_mistral(pages: int, overrides: Optional[dict] = None) -> float:
    overrides = overrides or {}
    cost_per_1k_pages = overrides.get("mistral_per_1k_pages", config.MISTRAL_OCR_COST_PER_1K_PAGES)
    return (pages / 1000.0) * cost_per_1k_pages
