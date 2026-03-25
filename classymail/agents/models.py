"""Pydantic contracts for agentic classification I/O."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ── Orchestrator ─────────────────────────────────────────────────────


class CandidateIntent(BaseModel):
    """A single candidate intent selected by the orchestrator."""

    intent: str
    slug: str
    confidence: float = Field(ge=0.0, le=1.0)


class OrchestratorResult(BaseModel):
    """Output of the orchestrator agent (router)."""

    candidate_intents: List[CandidateIntent] = Field(default_factory=list)
    routing_rationale: Optional[str] = None
    model: Optional[str] = None
    routed_model: Optional[str] = None  # Actual model when using model-router
    routing_mode: Optional[str] = None  # balanced | cost | quality
    tokens: Optional[dict] = None
    latency_ms: Optional[float] = None


# ── Specialized Agent ────────────────────────────────────────────────


class RAGGroundingRef(BaseModel):
    """A single RAG grounding reference from AI Search."""

    doc_id: str
    score: float
    label: str
    source: str = "llm_classified"  # llm_classified | human_verified | human_corrected | human_reinforced
    content_snippet: Optional[str] = None  # First ~300 chars of the email
    is_positive: bool = True  # True = correct match, False = known misclassification
    correction_reason: Optional[str] = None  # Why this was a wrong classification


class SpecializedAgentResult(BaseModel):
    """Output of a single specialized (mono-intent) agent."""

    intent: str
    slug: str
    is_match: bool
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: Optional[str] = None
    rag_grounding: List[RAGGroundingRef] = Field(default_factory=list)
    model: Optional[str] = None
    tokens: Optional[dict] = None
    latency_ms: Optional[float] = None
    search_index: Optional[str] = None
    retrieval_mode: Optional[str] = None
    tool_called: bool = False


class RedTeamVerdict(BaseModel):
    """Output of the Red Team / Quality Gate agent."""

    validated: bool = True  # True = pass-through, False = refinement needed
    missed_intents: List[str] = Field(default_factory=list)
    refined_confidences: Optional[dict] = None  # intent_slug -> new confidence
    justification: Optional[str] = None
    additional_agents_requested: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    tokens: Optional[dict] = None
    latency_ms: Optional[float] = None


# ── Aggregated Result ────────────────────────────────────────────────


class AgentTrace(BaseModel):
    """Trace of a single agent execution for observability."""

    agent_type: str  # orchestrator | specialized | red_team
    intent: Optional[str] = None
    model: str
    routed_model: Optional[str] = None
    tokens: Optional[dict] = None
    latency_ms: Optional[float] = None
    confidence: Optional[float] = None
    search_index: Optional[str] = None
    retrieval_mode: Optional[str] = None
    rag_hits: int = 0
    tool_called: bool = False


class AgenticClassificationResult(BaseModel):
    """Full agentic classification result with provenance traces.

    Compatible with the existing ``ClassificationResult`` schema — the pipeline
    converts this into a ``ClassificationResult`` before persisting.
    """

    detected_intents: list = Field(default_factory=list)  # List[ClassificationIntent dict]
    global_complexity: Optional[str] = None
    needs_review: bool = False
    classification_reason: Optional[str] = None
    subject: Optional[str] = None
    sender: Optional[str] = None
    raw_response: Optional[dict] = None

    # Agentic-specific fields
    orchestrator_result: Optional[OrchestratorResult] = None
    agent_results: List[SpecializedAgentResult] = Field(default_factory=list)
    red_team_verdict: Optional[RedTeamVerdict] = None
    agent_traces: List[AgentTrace] = Field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    parallel_latency_ms: Optional[float] = None
