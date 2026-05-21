"""Specialized mono-intent agent — one agent per category.

Each agent receives:
- A system prompt tailored to exactly one intent
- A ``search_reference_examples`` tool for RAG retrieval from its per-intent
  AI Search index — the agent decides whether to call it via tool-calling
- A model chosen by tier (simple/ambiguous/critical)

Agents run in parallel via ``asyncio.gather`` during the fan-out phase.
"""

from __future__ import annotations

import json
import logging
import time

from opentelemetry import trace

from classymail.agents.config import get_agentic_settings, resolve_agent_endpoint
from classymail.agents.models import CandidateIntent, RAGGroundingRef, SpecializedAgentResult
from classymail.agents.orchestrator import _load_prompt_template
from classymail.agents.tools.ai_search_tool import search_intent_index
from classymail.services.openai_client_factory import build_chat_params, extract_message_content, is_reasoning_model
from classymail.services.azure_clients import Clients
from classymail.services.openai_client_factory import get_chat_client

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# ── Tool definition factory for per-intent AI Search ─────────────────

def _build_search_tool(slug: str, intent_name: str) -> dict:
    """Build a contextual tool definition for a specific category index.

    Each agent gets its own tool named ``search_{slug}`` pointing to the
    specific AI Search index ``classymail-intent-{slug}``.
    """
    index = f"classymail-intent-{slug}"
    return {
        "type": "function",
        "function": {
            "name": f"search_{slug.replace('-', '_')}",
            "description": (
                f"Search the AI Search index '{index}' for the '{intent_name}' category. "
                f"Returns previously classified documents similar to the input: "
                f"positive examples (correct matches for '{intent_name}') and "
                f"negative examples (documents wrongly classified as '{intent_name}' with "
                f"correction reasons explaining the mistake). "
                f"Call this tool with key phrases from the document to calibrate your confidence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Key phrases or summary from the email to search for similar examples.",
                    },
                },
                "required": ["query"],
            },
        },
    }


def _select_model_tier(confidence: float, agentic: dict) -> str:
    """Select model based on orchestrator confidence (proxy for complexity).

    High confidence → simple (tier 1), medium → ambiguous (tier 2),
    low → critical (tier 3).
    """
    if confidence >= 0.8:
        return agentic["agent_tier1_model"]
    elif confidence >= 0.5:
        return agentic["agent_tier2_model"]
    else:
        return agentic["agent_tier3_model"]


def _build_specialized_prompt(
    intent_name: str,
    intent_description: str,
    intent_exclusions: str,
    has_search_tool: bool,
    slug: str,
    locale: str,
) -> str:
    lang = {"fr": "French", "en": "English", "de": "German", "es": "Spanish", "it": "Italian"}.get(locale, "English")
    tool_name = f"search_{slug.replace('-', '_')}"
    index_name = f"classymail-intent-{slug}"
    tool_instruction = ""
    if has_search_tool:
        tool_instruction = f"""

TOOL AVAILABLE: {tool_name}
You have access to the AI Search index '{index_name}' dedicated to the "{intent_name}" category.
This index contains previously classified documents. Use this tool to:
- Find similar documents and see how they were classified
- See POSITIVE examples (correct matches) to calibrate your confidence
- See NEGATIVE examples (misclassifications) with REASON explaining why they don't belong
- Weigh [human_verified] and [human_reinforced] sources more heavily than [llm_classified]
Call this tool with key phrases from the email before making your final decision."""

    if not intent_exclusions:
        intent_exclusions = "(none)"

    template = _load_prompt_template("specialized")
    return template.format(
        intent_name=intent_name,
        intent_description=intent_description,
        intent_exclusions=intent_exclusions,
        tool_instruction=tool_instruction,
        lang=lang,
    )


def _find_category(slug: str, settings: dict | None) -> dict:
    """Find a category dict by slug from settings."""
    cats = (settings or {}).get("categories", [])
    for c in cats:
        if c.get("slug") == slug:
            return c
    return {"name": slug, "slug": slug, "description": "", "exclusions": ""}


def _is_index_enabled(slug: str, agentic: dict) -> bool:
    """Check if the AI Search index is enabled for this category in settings."""
    enabled_indexes = agentic.get("enabled_indexes", {})
    # Default: all indexes enabled if the setting doesn't exist
    if not enabled_indexes:
        return True
    return enabled_indexes.get(slug, True)


def _format_tool_result(refs: list[RAGGroundingRef]) -> str:
    """Format RAG results as a structured tool response for the LLM."""
    if not refs:
        return "No reference examples found for this query."

    positive = [r for r in refs if r.is_positive][:3]
    negative = [r for r in refs if not r.is_positive][:2]

    lines = []
    if positive:
        lines.append("POSITIVE EXAMPLES (emails correctly classified as this intent):")
        for r in positive:
            lines.append(f"  [{r.source}] relevance={r.score:.2f}")
            if r.content_snippet:
                lines.append(f"  > {r.content_snippet}")
    if negative:
        lines.append("")
        lines.append("NEGATIVE EXAMPLES (emails WRONGLY classified as this intent):")
        for r in negative:
            lines.append(f"  [{r.source}] relevance={r.score:.2f}")
            if r.content_snippet:
                lines.append(f"  > {r.content_snippet}")
            if r.correction_reason:
                lines.append(f"  REASON: {r.correction_reason}")

    if not positive and not negative:
        return "Reference examples found but none with clear positive/negative labels."

    return "\n".join(lines)


async def run_specialized_agent(
    text_markdown: str,
    candidate: CandidateIntent,
    *,
    settings: dict | None = None,
    clients: Clients | None = None,
    locale: str = "en",
) -> SpecializedAgentResult:
    """Run a single specialized agent for one intent.

    The agent uses tool-calling: the LLM decides whether to invoke the
    ``search_reference_examples`` tool to query the per-intent AI Search
    index. The tool is only offered if the index is enabled for this
    category in UI settings (``agentic.enabled_indexes``).
    """

    agentic = get_agentic_settings(settings)
    model_key = _select_model_tier(candidate.confidence, agentic)
    endpoint, deployment, api_version = resolve_agent_endpoint(model_key)

    category = _find_category(candidate.slug, settings)
    retrieval_mode = agentic.get("retrieval_mode", "semantic")
    top_k = agentic.get("search_top_k", 5)
    index_enabled = _is_index_enabled(candidate.slug, agentic)

    with tracer.start_as_current_span(f"agentic.agent.{candidate.slug}") as span:
        span.set_attribute("gen_ai.request.model", deployment)
        span.set_attribute("agentic.intent", candidate.slug)
        span.set_attribute("agentic.index_enabled", index_enabled)

        system_prompt = _build_specialized_prompt(
            intent_name=category.get("name", candidate.intent),
            intent_description=category.get("description", ""),
            intent_exclusions=category.get("exclusions", ""),
            has_search_tool=index_enabled,
            slug=candidate.slug,
            locale=locale,
        )

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_markdown[:8000]},
        ]

        # Build contextual tool for this specific category index
        tool_name = f"search_{candidate.slug.replace('-', '_')}"
        search_tool = _build_search_tool(candidate.slug, category.get("name", candidate.intent))

        chat_client = await get_chat_client(endpoint, api_version, clients=clients)
        chat_params = build_chat_params(deployment, temperature=0.1, max_output_tokens=500)

        extra: dict = {}
        if is_reasoning_model(deployment):
            extra["reasoning_effort"] = agentic.get("reasoning_effort", "none")

        first_extra = dict(extra)
        if index_enabled:
            first_extra["tools"] = [search_tool]
            # Force the LLM to call the search tool — mandatory RAG grounding
            first_extra["tool_choice"] = {"type": "function", "function": {"name": tool_name}}
        else:
            first_extra["response_format"] = {"type": "json_object"}

        t0 = time.perf_counter()
        rag_refs: list[RAGGroundingRef] = []
        total_usage: dict = {}

        # ── First LLM call (may produce tool_call or direct answer) ──
        completion = await chat_client.chat.completions.create(
            model=deployment,
            messages=messages,
            timeout=60.0,
            **chat_params,
            **first_extra,
        )
        data = completion.model_dump()
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        total_usage = data.get("usage", {}) or {}

        # ── Handle tool call loop (max 1 round) ─────────────────
        tool_calls = message.get("tool_calls") or []
        if tool_calls and index_enabled:
            span.add_event("tool_call", {"tool": tool_name, "index": f"classymail-intent-{candidate.slug}"})

            for tc in tool_calls:
                fn_name = (tc.get("function") or {}).get("name", "")
                # Accept the contextual tool name (search_billing_inquiry)
                # or the generic fallback (search_reference_examples)
                if not fn_name.startswith("search_"):
                    continue

                # Parse tool arguments
                try:
                    args = json.loads(tc["function"].get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {"query": text_markdown[:500]}

                query = args.get("query", text_markdown[:500])

                # Execute the actual AI Search retrieval
                rag_refs = await search_intent_index(
                    query,
                    candidate.slug,
                    retrieval_mode=retrieval_mode,
                    top_k=top_k,
                    clients=clients,
                )

                tool_result = _format_tool_result(rag_refs)

                # Append assistant message + tool result, then re-call LLM.
                # Strip None fields (refusal/audio/annotations) which Azure may
                # reject when echoing the assistant message back.
                assistant_msg = {
                    "role": message.get("role", "assistant"),
                    "content": message.get("content"),
                    "tool_calls": message.get("tool_calls"),
                }
                assistant_msg = {k: v for k, v in assistant_msg.items() if v is not None}
                messages.append(assistant_msg)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result,
                })

            # Second LLM call with tool results — no tools, force JSON
            second_extra = dict(extra)
            second_extra["response_format"] = {"type": "json_object"}
            completion2 = await chat_client.chat.completions.create(
                model=deployment,
                messages=messages,
                timeout=60.0,
                **chat_params,
                **second_extra,
            )
            data2 = completion2.model_dump()
            message = data2.get("choices", [{}])[0].get("message", {})

            # Merge usage
            usage2 = data2.get("usage", {}) or {}
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                total_usage[k] = total_usage.get(k, 0) + usage2.get(k, 0)

        elif index_enabled and not tool_calls:
            logger.warning(
                "[agentic] Agent %s: tool_choice was required but LLM returned no tool call",
                candidate.slug,
            )
            span.add_event("tool_call_skipped", {"reason": "llm_ignored_required_tool"})

        latency_ms = (time.perf_counter() - t0) * 1000
        content = extract_message_content(message) or "{}"

        parsed = json.loads(content)
        tool_was_called = bool(tool_calls) and index_enabled
        result = SpecializedAgentResult(
            intent=parsed.get("intent", candidate.intent),
            slug=candidate.slug,
            is_match=parsed.get("is_match", False),
            confidence=float(parsed.get("confidence", 0.0)),
            explanation=parsed.get("explanation"),
            rag_grounding=rag_refs,
            model=deployment,
            tokens=total_usage,
            latency_ms=round(latency_ms, 1),
            search_index=f"classymail-intent-{candidate.slug}" if index_enabled else None,
            retrieval_mode=retrieval_mode if index_enabled else None,
            tool_called=tool_was_called,
        )

        span.set_attribute("agentic.confidence", result.confidence)
        span.set_attribute("agentic.is_match", result.is_match)
        span.set_attribute("agentic.rag_hits", len(rag_refs))
        span.set_attribute("agentic.tool_called", tool_was_called)
        if index_enabled:
            span.set_attribute("agentic.search_index", f"classymail-intent-{candidate.slug}")
            span.set_attribute("agentic.retrieval_mode", retrieval_mode)

        logger.info(
            "[agentic] Agent %s: match=%s conf=%.2f in %.0fms (model=%s, rag=%d, tool=%s)",
            candidate.slug, result.is_match, result.confidence, latency_ms,
            deployment, len(rag_refs), "yes" if rag_refs else "no",
        )
        return result
