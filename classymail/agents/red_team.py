"""Red Team / Quality Gate agent — second critical opinion.

Activated conditionally when:
- max confidence < threshold (default 0.7)
- top-2 agents conflict (delta < 0.15)
- zero intents matched
"""

from __future__ import annotations

import json
import logging
import time

import httpx
from opentelemetry import trace

from classymail.agents.config import get_agentic_settings, resolve_agent_endpoint
from classymail.agents.models import RedTeamVerdict, SpecializedAgentResult
from classymail.agents.orchestrator import _load_prompt_template
from classymail.core.llm_compat import build_chat_params, extract_message_content
from classymail.services.azure_clients import auth_headers, Clients
from classymail.services.settings_store import get_categories_prompt_text, _build_categories_prompt

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def needs_red_team(
    agent_results: list[SpecializedAgentResult],
    agentic: dict,
) -> bool:
    """Determine whether the Red Team agent should be activated."""
    threshold = agentic.get("red_team_threshold", 0.7)
    delta = agentic.get("red_team_conflict_delta", 0.15)

    matched = [r for r in agent_results if r.is_match]

    # No intents matched at all
    if not matched:
        return True

    # Max confidence is too low
    max_conf = max(r.confidence for r in matched)
    if max_conf < threshold:
        return True

    # Top-2 conflict
    if len(matched) >= 2:
        sorted_confs = sorted([r.confidence for r in matched], reverse=True)
        if (sorted_confs[0] - sorted_confs[1]) < delta:
            return True

    return False


def _build_red_team_prompt(
    agent_summaries: str,
    categories_text: str,
    locale: str,
) -> str:
    lang = {"fr": "French", "en": "English", "de": "German", "es": "Spanish", "it": "Italian"}.get(locale, "English")
    template = _load_prompt_template("red_team")
    return template.format(
        agent_summaries=agent_summaries,
        categories_text=categories_text,
        lang=lang,
    )


async def run_red_team(
    text_markdown: str,
    agent_results: list[SpecializedAgentResult],
    *,
    settings: dict | None = None,
    clients: Clients | None = None,
    locale: str = "en",
) -> RedTeamVerdict:
    """Run the Red Team quality gate agent."""

    agentic = get_agentic_settings(settings)
    model_key = agentic["red_team_model"]
    endpoint, deployment, api_version = resolve_agent_endpoint(model_key)

    categories_text = _build_categories_prompt((settings or {}).get("categories") or []) or get_categories_prompt_text()

    # Build summary of agent results
    summaries = []
    for r in agent_results:
        summaries.append(
            f"- Intent: {r.intent} (slug={r.slug}) | match={r.is_match} | "
            f"confidence={r.confidence:.2f} | explanation: {r.explanation or 'N/A'}"
        )
    agent_summaries = "\n".join(summaries) if summaries else "(no agent results)"

    system_prompt = _build_red_team_prompt(agent_summaries, categories_text, locale)
    headers = await auth_headers(clients=clients)
    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    payload: dict = {
        "model": deployment,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_markdown[:8000]},
        ],
        **build_chat_params(deployment, temperature=0.2, max_output_tokens=800),
    }

    with tracer.start_as_current_span("agentic.red_team") as span:
        span.set_attribute("gen_ai.request.model", deployment)
        span.set_attribute("agentic.agent_results_count", len(agent_results))

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

        latency_ms = (time.perf_counter() - t0) * 1000
        data = resp.json()
        content = extract_message_content(data.get("choices", [{}])[0].get("message", {})) or "{}"
        usage = data.get("usage", {})

        parsed = json.loads(content)
        verdict = RedTeamVerdict(
            validated=parsed.get("validated", True),
            missed_intents=parsed.get("missed_intents", []),
            refined_confidences=parsed.get("refined_confidences"),
            justification=parsed.get("justification"),
            additional_agents_requested=parsed.get("additional_agents_requested", []),
            model=deployment,
            tokens=usage,
            latency_ms=round(latency_ms, 1),
        )

        trigger_reason = "low_confidence"
        matched = [r for r in agent_results if r.is_match]
        if not matched:
            trigger_reason = "no_match"
        elif len(matched) >= 2:
            sorted_c = sorted([r.confidence for r in matched], reverse=True)
            if (sorted_c[0] - sorted_c[1]) < agentic.get("red_team_conflict_delta", 0.15):
                trigger_reason = "conflict"

        span.set_attribute("agentic.trigger_reason", trigger_reason)
        span.set_attribute("agentic.red_team.validated", verdict.validated)
        if verdict.additional_agents_requested:
            span.set_attribute("agentic.additional_agents", verdict.additional_agents_requested)

        logger.info(
            "[agentic] Red Team: validated=%s trigger=%s missed=%s in %.0fms",
            verdict.validated, trigger_reason, verdict.missed_intents, latency_ms,
        )
        return verdict
