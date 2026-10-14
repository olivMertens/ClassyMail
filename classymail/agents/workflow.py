"""Agentic classification workflow — orchestrator → fan-out → fan-in → red team.

Entry point: ``classify_agentic()`` — replaces ``classify_with_phi4()`` when
``processing_strategy == "agentic"``.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from classymail.agents.config import get_agentic_settings
from classymail.agents.models import (
    AgentTrace,
    AgenticClassificationResult,
    CandidateIntent,
    RedTeamVerdict,
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


MATCH_CONFIDENCE_FLOOR = 0.3


def _coerce_confidence(value: object) -> float | None:
    """Return a finite confidence in [0, 1], or None when the value is unusable."""
    if isinstance(value, bool):
        return None
    try:
        conf = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(conf) or conf < 0.0 or conf > 1.0:
        return None
    return conf


def _apply_refinements(agent_results: list[SpecializedAgentResult], refined: object) -> int:
    """Apply Red Team confidence refinements to known slugs only; return the number applied."""
    if not isinstance(refined, dict):
        return 0
    by_norm = {str(k).replace("_", "-"): v for k, v in refined.items()}
    applied = 0
    for ar in agent_results:
        if ar.error:
            continue
        raw = by_norm.get(ar.slug.replace("_", "-"))
        if raw is None:
            continue
        conf = _coerce_confidence(raw)
        if conf is None:
            logger.warning("[agentic] Ignoring invalid Red Team refinement slug=%s value=%r", ar.slug, raw)
            continue
        ar.confidence = conf
        applied += 1
    return applied


def _review_reasons(
    agent_results: list[SpecializedAgentResult],
    matched: list[SpecializedAgentResult],
    review_threshold: float,
    red_team_verdict,
) -> list[str]:
    """Per-label review decision: one strong label must not hide weak labels, failures or a rejection."""
    reasons: list[str] = []
    if not matched:
        reasons.append("no_match")
    weak = [ar.slug for ar in matched if ar.confidence < review_threshold]
    if weak:
        reasons.append("low_confidence:" + ",".join(weak))
    failed = [ar.slug for ar in agent_results if ar.error]
    if failed:
        reasons.append("agent_failed:" + ",".join(failed))
    if red_team_verdict is not None and not red_team_verdict.validated:
        reasons.append("red_team_not_validated")
    return reasons


def _failure_placeholder(candidate: CandidateIntent, exc: BaseException) -> SpecializedAgentResult:
    """Build a non-blocking placeholder result for a failed specialized agent.

    Keeps the UI Mermaid trace continuous (per-slug entry preserved) while
    surfacing the error inline. ``confidence=0.0`` + ``is_match=False`` means
    downstream aggregation naturally drops the failed intent.
    """
    return SpecializedAgentResult(
        intent=candidate.intent,
        slug=candidate.slug,
        is_match=False,
        confidence=0.0,
        explanation=None,
        rag_grounding=[],
        model=None,
        tokens=None,
        latency_ms=None,
        search_index=None,
        retrieval_mode=None,
        tool_called=False,
        error=f"{type(exc).__name__}: {exc}",
    )


def _settle_fanout(
    candidates: list[CandidateIntent],
    settled: list,
) -> tuple[list[SpecializedAgentResult], int]:
    """Convert gather(return_exceptions=True) output into results + failure count.

    Logs each failure with full stack context so AppInsights / OTel keeps the
    diagnostic signal.
    """
    results: list[SpecializedAgentResult] = []
    failed = 0
    for candidate, outcome in zip(candidates, settled, strict=True):
        if isinstance(outcome, BaseException):
            failed += 1
            logger.exception(
                "[agentic] specialized agent failed slug=%s: %s",
                candidate.slug, outcome, exc_info=outcome,
            )
            results.append(_failure_placeholder(candidate, outcome))
        else:
            results.append(outcome)
    return results, failed


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
                    *tasks, return_exceptions=True
                )
                agent_results, failed_count = _settle_fanout(candidates, agent_results)

                parallel_ms = (time.perf_counter() - par_t0) * 1000
                par_span.set_attribute("agentic.parallel.latency_ms", round(parallel_ms, 1))
                par_span.set_attribute("agentic.parallel.failed_count", failed_count)

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
                tool_called=ar.tool_called,
                triggered_by="orchestrator",
            ))
            total_tokens += _sum_tokens(ar.tokens)

        # ── Step 3: Red Team (conditional) ───────────────────────────
        # Trigger Red Team if: confidence is low/conflicting OR if orchestrator found 0 candidates
        red_team_verdict = None
        trigger_red_team = needs_red_team(agent_results, agentic) or not candidates
        if trigger_red_team:
            try:
                red_team_verdict = await run_red_team(
                    text_markdown,
                    agent_results,
                    settings=settings,
                    clients=clients,
                    locale=locale,
                )
            except Exception as exc:  # keep partial results; force human review instead
                logger.exception("[agentic] Red Team failed: %s", exc)
                red_team_verdict = RedTeamVerdict(
                    validated=False,
                    justification=f"Red Team unavailable ({type(exc).__name__})",
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

            refined_count = _apply_refinements(agent_results, red_team_verdict.refined_confidences)
            root_span.set_attribute("agentic.red_team.refinements_applied", refined_count)

            # ── Step 3b: Launch agents for Red Team missed intents ────
            requested = [
                s for s in [*(red_team_verdict.missed_intents or []),
                            *(red_team_verdict.additional_agents_requested or [])]
                if isinstance(s, str) and s.strip()
            ]
            cats = (settings or {}).get("categories") or []
            # Index by normalised slug (underscores→hyphens) for LLM tolerance
            cat_by_norm = {
                c["slug"].replace("_", "-"): c
                for c in cats if isinstance(c, dict) and c.get("slug") and c.get("name")
            }
            seen = {ar.slug.replace("_", "-") for ar in agent_results}
            extra_candidates = []
            # Dedup on the canonical slug, preserving the Red Team order for determinism.
            for slug in requested:
                cat = cat_by_norm.get(slug.strip().replace("_", "-"))
                if not cat:
                    continue
                canonical = cat["slug"].replace("_", "-")
                if canonical in seen:
                    continue
                seen.add(canonical)
                extra_candidates.append(CandidateIntent(
                    intent=cat["name"],
                    slug=cat["slug"],
                    confidence=0.5,
                ))
            max_extra = int(agentic.get("max_parallel_agents", 6) or 6)
            if len(extra_candidates) > max_extra:
                logger.warning("[agentic] Red Team requested %d extra agents; capped to %d",
                               len(extra_candidates), max_extra)
                extra_candidates = extra_candidates[:max_extra]

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
                extra_results_raw = await asyncio.gather(
                    *extra_tasks, return_exceptions=True
                )
                extra_results, extra_failed = _settle_fanout(
                    extra_candidates, extra_results_raw
                )
                if extra_failed:
                    root_span.set_attribute(
                        "agentic.red_team.extra_failed_count", extra_failed
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
                        tool_called=ar.tool_called,
                        triggered_by="red_team",
                    ))
                    total_tokens += _sum_tokens(ar.tokens)
                agent_results.extend(extra_results)
        else:
            root_span.set_attribute("agentic.red_team.triggered", False)

        # ── Step 4: Aggregate ────────────────────────────────────────
        with tracer.start_as_current_span("agentic.aggregation") as agg_span:
            matched = [
                ar for ar in agent_results
                if ar.is_match and not ar.error and ar.confidence > MATCH_CONFIDENCE_FLOOR
            ]
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
            review_reasons = _review_reasons(
                agent_results, matched, agentic.get("red_team_threshold", 0.7), red_team_verdict,
            )
            needs_review = bool(review_reasons)

            agg_span.set_attribute("agentic.matched_intents", len(matched))
            agg_span.set_attribute("agentic.max_confidence", round(max_conf, 3))
            agg_span.set_attribute("agentic.needs_review", needs_review)
            if review_reasons:
                agg_span.set_attribute("agentic.review_reasons", review_reasons)

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
