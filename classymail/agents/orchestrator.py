"""Orchestrator agent — fast intent routing.

Analyzes a document and selects the top candidate intents (max 5-6) from the
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
from classymail.services.settings_store import get_categories_prompt_text, _build_categories_prompt

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_PROMPT_DIR = Path(__file__).parent / "prompts"

# Fallback prompt if .md file fails to load (Docker layer missing, permissions, etc.)
_FALLBACK_ORCHESTRATOR = """You are an expert document classification inspector. Analyze documents with investigator precision, cross-referencing content with EVERY category definition.

AVAILABLE INTENTS:
{categories_text}

METHOD:
1. READ the full document. Identify ALL topics, requests, complaints, questions.
2. For EACH intent, compare its DEFINITION against the content — even indirect matches.
3. Check EXCLUSIONS. Look for HIDDEN intents buried in mixed requests.
4. Consider CONTEXT and TONE: complaints, follow-ups, urgency, forwarded threads.

RULES:
- Select TOP {max_agents} intents. Confidence: 0.9+=explicit, 0.7-0.9=contextual, 0.5-0.7=partial, below 0.3=skip.
- NEVER dismiss as no match without checking EVERY category definition.
- If truly no match, return empty array with detailed rationale.

OUTPUT FORMAT (JSON only, no markdown):
{{
  "candidate_intents": [
    {{"intent": "Category Name", "slug": "category-slug", "confidence": 0.85}}
  ],
  "routing_rationale": "What topics found, which categories matched and why"
}}

LANGUAGE: Respond in {lang}."""


_FALLBACK_SPECIALIZED = """You are a specialized classification agent for the intent: "{intent_name}".

INTENT DEFINITION:
{intent_description}

EXCLUSIONS (this intent must NOT include):
{intent_exclusions}
{tool_instruction}

YOUR TASK:
1. Analyze the document content below.
2. If a search tool is available, call it with key phrases to find reference examples.
3. Determine if the document matches the intent "{intent_name}" based on the definition and any reference examples.
4. Assign a confidence score (0.0-1.0).
5. Provide a brief explanation citing evidence from the document.

OUTPUT FORMAT (JSON only, no markdown):
{{
  "intent": "{intent_name}",
  "is_match": true,
  "confidence": 0.91,
  "explanation": "Brief evidence from the document text"
}}

If the document does NOT match this intent, set is_match=false and confidence < 0.3.

LANGUAGE: Respond in {lang}."""


_FALLBACK_RED_TEAM = """You are an ADVERSARIAL Quality Gate / Red Team reviewer. NEVER trust the agents blindly.

AGENT RESULTS:
{agent_summaries}

ALL AVAILABLE INTENTS:
{categories_text}

YOUR TASK:
1. NEVER assume agents are correct. Challenge every decision.
2. Form your OWN opinion about which intents match BEFORE reviewing agent results.
3. If orchestrator selected 0 candidates, evaluate whether that is correct and explain why.
4. Verify confidence scores are justified by evidence, not just keyword matching.

OUTPUT FORMAT (JSON only, no markdown):
{{
  "validated": true,
  "missed_intents": [],
  "refined_confidences": {{}},
  "justification": "Detailed adversarial review",
  "additional_agents_requested": []
}}

RULES:
- validated=true ONLY if you genuinely agree after challenging.
- missed_intents can be empty if 0 candidates is genuinely correct, but explain why.
- When agent_summaries is empty, independently evaluate against ALL intents.

LANGUAGE: Respond in {lang}."""


def _load_prompt_template(name: str) -> str:
    """Load a prompt template from the prompts/ directory with inline fallback."""
    path = _PROMPT_DIR / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        logger.warning("Failed to load prompt template %s, using fallback", path)
        fallbacks = {
            "orchestrator": _FALLBACK_ORCHESTRATOR,
            "specialized": _FALLBACK_SPECIALIZED,
            "red_team": _FALLBACK_RED_TEAM,
        }
        return fallbacks.get(name, "You are a helpful assistant. Respond in {lang}.")


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
    # Build categories from the settings dict (passed from workflow, read from Cosmos)
    # rather than sync file which doesn't exist in Docker containers
    cats = (settings or {}).get("categories") or []
    categories_text = _build_categories_prompt(cats) if cats else get_categories_prompt_text()

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
