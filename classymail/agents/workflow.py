"""Agentic classification workflow — orchestrator → fan-out → fan-in → red team.

Entry point: ``classify_agentic()`` — replaces ``classify_with_phi4()`` when
``processing_strategy == "agentic"``.
"""

from __future__ import annotations

import asyncio
import logging
import time

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from classymail.agents.config import get_agentic_settings
from classymail.agents.models import (
    AgentTrace,
    AgenticClassificationResult,
    CandidateIntent,
    SpecializedAgentResult,
)
from classymail.agents.orchestrator import run_orchestrator
from classymail.agents.red_team import needs_red_team, run_red_team
from classymail.agents.specialized import run_specialized_agent
from classymail.services.azure_clients import Clients
from classymail.services.email_preprocessing import (
    extract_sender_from_markdown,
    extract_subject_from_markdown,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def _sum_tokens(usage: dict | None) -> int:
    if not usage:
        return 0
    return int(usage.get("total_tokens", 0))


async def classify_agentic(
    text_markdown: str,
    *,
    settings: dict | None = None,
    clients: Clients | None = None,
    locale: str = "en",
) -> dict:
    """Run the full agentic classification pipeline.

    Workflow:
    1. Orchestrator selects top candidate intents
    2. Specialized agents run in parallel (fan-out / fan-in)
    3. Red Team conditionally reviews results
    4. Aggregate into final classification dict

    Returns a dict compatible with ``process_agent_response()`` in
    ``llm_pipeline.py``.
    """
    agentic = get_agentic_settings(settings)
    traces: list[AgentTrace] = []
    total_tokens = 0

    with tracer.start_as_current_span("agentic.orchestrate") as root_span:
        root_span.set_attribute("agentic.enabled", True)
        pipeline_t0 = time.perf_counter()

        # ── Step 1: Orchestrator ─────────────────────────────────────
        orchestrator_result = await run_orchestrator(
            text_markdown,
            settings=settings,
            clients=clients,
            locale=locale,
        )

        traces.append(AgentTrace(
            agent_type="orchestrator",
            model=orchestrator_result.model or "unknown",
            routed_model=orchestrator_result.routed_model,
            tokens=orchestrator_result.tokens,
            latency_ms=orchestrator_result.latency_ms,
        ))
        total_tokens += _sum_tokens(orchestrator_result.tokens)

        candidates = orchestrator_result.candidate_intents

        root_span.set_attribute("agentic.candidates_count", len(candidates))

        # ── Step 2: Parallel agents (fan-out / fan-in) ───────────────
        agent_results: list[SpecializedAgentResult] = []
        parallel_ms = 0.0
        if candidates:
            with tracer.start_as_current_span("agentic.parallel_agents") as par_span:
                par_span.set_attribute("agentic.parallel.agent_count", len(candidates))
                par_t0 = time.perf_counter()

                tasks = [
                    run_specialized_agent(
                        text_markdown,
                        candidate,
                        settings=settings,
                        clients=clients,
                        locale=locale,
                    )
                    for candidate in candidates
                ]
                agent_results = await asyncio.gather(
                    *tasks, return_exceptions=False
                )

                parallel_ms = (time.perf_counter() - par_t0) * 1000
                par_span.set_attribute("agentic.parallel.latency_ms", round(parallel_ms, 1))

        for ar in agent_results:
            traces.append(AgentTrace(
                agent_type="specialized",
                intent=ar.slug,
                model=ar.model or "unknown",
                tokens=ar.tokens,
                latency_ms=ar.latency_ms,
                confidence=ar.confidence,
                search_index=ar.search_index,
                retrieval_mode=ar.retrieval_mode,
                rag_hits=len(ar.rag_grounding),
            ))
            total_tokens += _sum_tokens(ar.tokens)

        # ── Step 3: Red Team (conditional) ───────────────────────────
        # Trigger Red Team if: confidence is low/conflicting OR if orchestrator found 0 candidates
        red_team_verdict = None
        trigger_red_team = needs_red_team(agent_results, agentic) or not candidates
        if trigger_red_team:
            red_team_verdict = await run_red_team(
                text_markdown,
                agent_results,
                settings=settings,
                clients=clients,
                locale=locale,
            )
            traces.append(AgentTrace(
                agent_type="red_team",
                model=red_team_verdict.model or "unknown",
                tokens=red_team_verdict.tokens,
                latency_ms=red_team_verdict.latency_ms,
            ))
            total_tokens += _sum_tokens(red_team_verdict.tokens)

            root_span.set_attribute("agentic.red_team.triggered", True)
            root_span.set_attribute("agentic.red_team.validated", red_team_verdict.validated)

            # Apply confidence refinements from Red Team
            if red_team_verdict.refined_confidences:
                for ar in agent_results:
                    if ar.slug in red_team_verdict.refined_confidences:
                        ar.confidence = float(red_team_verdict.refined_confidences[ar.slug])

            # ── Step 3b: Launch agents for Red Team missed intents ────
            missed_slugs = set(red_team_verdict.missed_intents or [])
            requested_slugs = set(red_team_verdict.additional_agents_requested or [])
            all_extra_slugs = (missed_slugs | requested_slugs) - {ar.slug for ar in agent_results}

            if all_extra_slugs:
                cats = (settings or {}).get("categories") or []
                cat_by_slug = {c.get("slug"): c for c in cats if c.get("slug")}
                extra_candidates = []
                for slug in all_extra_slugs:
                    cat = cat_by_slug.get(slug)
                    if cat:
                        extra_candidates.append(CandidateIntent(
                            intent=cat["name"],
                            slug=slug,
                            confidence=0.5,
                        ))

                if extra_candidates:
                    logger.info("[agentic] Red Team requested %d extra agents: %s",
                                len(extra_candidates), [c.slug for c in extra_candidates])
                    extra_tasks = [
                        run_specialized_agent(
                            text_markdown, candidate,
                            settings=settings, clients=clients, locale=locale,
                        )
                        for candidate in extra_candidates
                    ]
                    extra_results: list[SpecializedAgentResult] = await asyncio.gather(
                        *extra_tasks, return_exceptions=False
                    )
                    for ar in extra_results:
                        traces.append(AgentTrace(
                            agent_type="specialized",
                            intent=ar.slug,
                            model=ar.model or "unknown",
                            tokens=ar.tokens,
                            latency_ms=ar.latency_ms,
                            confidence=ar.confidence,
                            search_index=ar.search_index,
                            retrieval_mode=ar.retrieval_mode,
                            rag_hits=len(ar.rag_grounding),
                        ))
                        total_tokens += _sum_tokens(ar.tokens)
                    agent_results.extend(extra_results)
        else:
            root_span.set_attribute("agentic.red_team.triggered", False)

        # ── Step 4: Aggregate ────────────────────────────────────────
        with tracer.start_as_current_span("agentic.aggregation") as agg_span:
            matched = [ar for ar in agent_results if ar.is_match and ar.confidence > 0.3]
            matched.sort(key=lambda r: r.confidence, reverse=True)

            detected_intents = [
                {
                    "intent": ar.intent,
                    "confidence": ar.confidence,
                    "justification": ar.explanation,
                }
                for ar in matched
            ]

            max_conf = max((ar.confidence for ar in matched), default=0.0)
            needs_review = max_conf < agentic.get("red_team_threshold", 0.7) if matched else True

            agg_span.set_attribute("agentic.matched_intents", len(matched))
            agg_span.set_attribute("agentic.max_confidence", round(max_conf, 3))
            agg_span.set_attribute("agentic.needs_review", needs_review)

        classification_reason = None
        if not detected_intents:
            classification_reason = "No specialized agent matched any intent with sufficient confidence"
            if red_team_verdict and red_team_verdict.justification:
                classification_reason += f". Red Team: {red_team_verdict.justification}"

        # Extract subject and sender from the document text (same as non-agentic path)
        subject = extract_subject_from_markdown(text_markdown) or None
        sender = extract_sender_from_markdown(text_markdown) or None

        result = AgenticClassificationResult(
            detected_intents=detected_intents,
            global_complexity="Complex" if len(detected_intents) > 1 else "Simple",
            needs_review=needs_review,
            classification_reason=classification_reason,
            subject=subject,
            sender=sender,
            orchestrator_result=orchestrator_result,
            agent_results=agent_results,
            red_team_verdict=red_team_verdict,
            agent_traces=traces,
            total_tokens=total_tokens,
            parallel_latency_ms=round(parallel_ms, 1),
        )

        pipeline_ms = (time.perf_counter() - pipeline_t0) * 1000
        root_span.set_attribute("agentic.total_tokens", total_tokens)
        root_span.set_attribute("agentic.total_latency_ms", round(pipeline_ms, 1))
        root_span.set_status(Status(StatusCode.OK))

        logger.info(
            "[agentic] Pipeline complete: %d intents, %d agents, red_team=%s, "
            "tokens=%d, %.0fms",
            len(detected_intents), len(agent_results),
            "yes" if red_team_verdict else "no",
            total_tokens, pipeline_ms,
        )

        return _build_result_dict(result, agentic_settings=agentic)


def _build_result_dict(result: AgenticClassificationResult, agentic_settings: dict | None = None) -> dict:
    """Convert AgenticClassificationResult to the dict format expected by
    ``process_agent_response`` and ``pipeline.py``.
    """
    d: dict = {
        "detected_intents": result.detected_intents,
        "global_complexity": result.global_complexity,
        "needs_review": result.needs_review,
        "classification_reason": result.classification_reason,
        "subject": result.subject,
        "sender": result.sender,
        "agentic": True,
        "usage": {
            "total_tokens": result.total_tokens,
            "prompt_tokens": sum(
                (t.tokens or {}).get("prompt_tokens", 0) for t in result.agent_traces
            ),
            "completion_tokens": sum(
                (t.tokens or {}).get("completion_tokens", 0) for t in result.agent_traces
            ),
        },
        "agent_traces": [t.model_dump() for t in result.agent_traces],
        "parallel_latency_ms": result.parallel_latency_ms,
        # Snapshot of the agentic settings used for this classification
        "agentic_settings": {
            "orchestrator_model": (agentic_settings or {}).get("orchestrator_model", "unknown"),
            "agent_tier1_model": (agentic_settings or {}).get("agent_tier1_model", "unknown"),
            "agent_tier2_model": (agentic_settings or {}).get("agent_tier2_model", "unknown"),
            "agent_tier3_model": (agentic_settings or {}).get("agent_tier3_model", "unknown"),
            "red_team_model": (agentic_settings or {}).get("red_team_model", "unknown"),
            "red_team_threshold": (agentic_settings or {}).get("red_team_threshold", 0.7),
            "max_parallel_agents": (agentic_settings or {}).get("max_parallel_agents", 6),
            "retrieval_mode": (agentic_settings or {}).get("retrieval_mode", "semantic"),
            "reasoning_effort": (agentic_settings or {}).get("reasoning_effort", "none"),
        },
    }
    if result.orchestrator_result:
        d["model"] = result.orchestrator_result.model
    if result.red_team_verdict:
        d["red_team"] = result.red_team_verdict.model_dump()
    return d
