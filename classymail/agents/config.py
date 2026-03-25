"""Agent-level configuration — model tiering, feature flags, thresholds."""

from __future__ import annotations

import os


# ── Env-var overrides (fallback to AI Foundry primary endpoint) ──────

SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")  # https://xxx.search.windows.net
SEARCH_ADMIN_KEY = os.getenv("AZURE_SEARCH_ADMIN_KEY")  # optional — prefer MI

# Default agentic settings (merged with settings_store at runtime)
AGENTIC_DEFAULTS: dict = {
    "enabled": False,
    "orchestrator_model": "gpt-4.1-nano",
    "orchestrator_routing_mode": "balanced",
    "orchestrator_model_subset": [],
    "agent_tier1_model": "gpt-4.1-nano",
    "agent_tier2_model": "gpt-4.1-mini",
    "agent_tier3_model": "gpt-4.1",
    "red_team_model": "gpt-4.1",
    "red_team_threshold": 0.7,
    "red_team_conflict_delta": 0.15,
    "max_parallel_agents": 6,
    "retrieval_mode": "semantic",
    "search_top_k": 5,
    "reasoning_effort": "none",  # none | low | medium | high (for gpt-5 family)
    "enabled_indexes": {},  # Per-category: {slug: true/false}. Empty = all enabled
}


def get_agentic_settings(settings: dict | None = None) -> dict:
    """Merge agentic defaults with user settings."""
    base = AGENTIC_DEFAULTS.copy()
    if settings and "agentic" in settings and isinstance(settings["agentic"], dict):
        base.update(settings["agentic"])
    return base


def resolve_agent_endpoint(model_key: str) -> tuple[str, str, str]:
    """Resolve a model key to (endpoint, deployment, api_version).

    Delegates to the existing ``resolve_model_config`` in llm_pipeline
    so all model aliases work consistently.
    """
    from classymail.services.llm_pipeline import resolve_model_config

    return resolve_model_config(model_key)
