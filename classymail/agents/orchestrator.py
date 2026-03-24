"""Orchestrator agent — fast intent routing.

Analyzes an email and selects the top candidate intents (max 5-6) from the
configured categories.  Does NOT perform final classification.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx
from opentelemetry import trace

from classymail.agents.config import get_agentic_settings, resolve_agent_endpoint
from classymail.agents.models import CandidateIntent, OrchestratorResult
from classymail.core.llm_compat import build_chat_params, extract_message_content
from classymail.services.azure_clients import auth_headers, Clients
from classymail.services.settings_store import get_categories_prompt_text

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_PROMPT_DIR = Path(__file__).parent / "prompts"


def _load_prompt_template(name: str) -> str:
    """Load a prompt template from the prompts/ directory."""
    path = _PROMPT_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def _build_orchestrator_prompt(categories_text: str, max_agents: int, locale: str) -> str:
    lang = {"fr": "French", "en": "English", "de": "German", "es": "Spanish", "it": "Italian"}.get(locale, "English")
    template = _load_prompt_template("orchestrator")
    return template.format(
        categories_text=categories_text,
        max_agents=max_agents,
        lang=lang,
    )


async def run_orchestrator(
    text_markdown: str,
    *,
    settings: dict | None = None,
    clients: Clients | None = None,
    locale: str = "en",
) -> OrchestratorResult:
    """Run the orchestrator agent to select candidate intents."""

    agentic = get_agentic_settings(settings)
    model_key = agentic["orchestrator_model"]
    max_agents = agentic["max_parallel_agents"]
    routing_mode = agentic.get("orchestrator_routing_mode", "balanced")

    endpoint, deployment, api_version = resolve_agent_endpoint(model_key)
    categories_text = get_categories_prompt_text()

    system_prompt = _build_orchestrator_prompt(categories_text, max_agents, locale)
    headers = await auth_headers(clients=clients)
    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    payload: dict = {
        "model": deployment,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_markdown[:12000]},  # cap for routing
        ],
        **build_chat_params(deployment, temperature=0.1, max_output_tokens=800),
    }

    with tracer.start_as_current_span("agentic.orchestrator") as span:
        span.set_attribute("gen_ai.system", "azure_openai")
        span.set_attribute("gen_ai.request.model", deployment)
        span.set_attribute("agentic.routing_mode", routing_mode)

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

        latency_ms = (time.perf_counter() - t0) * 1000
        data = resp.json()
        content = extract_message_content(data.get("choices", [{}])[0].get("message", {})) or "{}"
        usage = data.get("usage", {})

        parsed = json.loads(content)
        candidates = [
            CandidateIntent(**c)
            for c in parsed.get("candidate_intents", [])[:max_agents]
        ]

        routed_model = data.get("model") or deployment

        result = OrchestratorResult(
            candidate_intents=candidates,
            routing_rationale=parsed.get("routing_rationale"),
            model=deployment,
            routed_model=routed_model if routed_model != deployment else None,
            routing_mode=routing_mode if model_key == "model-router" else None,
            tokens=usage,
            latency_ms=round(latency_ms, 1),
        )

        span.set_attribute("agentic.candidates_count", len(candidates))
        span.set_attribute("agentic.routing_latency_ms", round(latency_ms, 1))
        if routed_model != deployment:
            span.set_attribute("agentic.routed_model", routed_model)

        logger.info(
            "[agentic] Orchestrator: %d candidates in %.0fms (model=%s)",
            len(candidates), latency_ms, routed_model,
        )
        return result
