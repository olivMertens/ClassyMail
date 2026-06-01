"""Tests for agentic classification pipeline.

Covers: models, orchestrator, specialized agent, red team, workflow, settings.
"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from classymail.agents.models import (
    AgenticClassificationResult,
    AgentTrace,
    CandidateIntent,
    OrchestratorResult,
    RedTeamVerdict,
    SpecializedAgentResult,
)
from classymail.agents.config import get_agentic_settings, AGENTIC_DEFAULTS
from classymail.agents.red_team import needs_red_team


# ── Models ───────────────────────────────────────────────────────────


class TestAgenticModels:
    def test_candidate_intent(self):
        c = CandidateIntent(intent="Billing", slug="billing", confidence=0.9)
        assert c.confidence == 0.9

    def test_orchestrator_result_empty(self):
        r = OrchestratorResult()
        assert r.candidate_intents == []
        assert r.model is None

    def test_specialized_agent_result(self):
        r = SpecializedAgentResult(
            intent="Test",
            slug="test",
            is_match=True,
            confidence=0.85,
            explanation="Found keyword",
        )
        assert r.is_match
        assert r.rag_grounding == []

    def test_red_team_verdict_defaults(self):
        v = RedTeamVerdict()
        assert v.validated is True
        assert v.missed_intents == []

    def test_agent_trace(self):
        t = AgentTrace(agent_type="specialized", model="gpt-4.1-nano", intent="billing")
        assert t.rag_hits == 0

    def test_agentic_result_full(self):
        r = AgenticClassificationResult(
            detected_intents=[{"intent": "Billing", "confidence": 0.9, "justification": "x"}],
            global_complexity="Simple",
            needs_review=False,
            total_tokens=500,
        )
        assert len(r.detected_intents) == 1
        assert r.total_tokens == 500


# ── Config ───────────────────────────────────────────────────────────


class TestAgenticConfig:
    def test_defaults(self):
        cfg = get_agentic_settings(None)
        assert cfg["orchestrator_model"] == "gpt-4.1-nano"
        assert cfg["enabled"] is False

    def test_merge_user_settings(self):
        user = {"agentic": {"enabled": True, "orchestrator_model": "model-router"}}
        cfg = get_agentic_settings(user)
        assert cfg["enabled"] is True
        assert cfg["orchestrator_model"] == "model-router"
        # Defaults still present for non-overridden keys
        assert cfg["red_team_threshold"] == 0.7

    def test_no_agentic_key(self):
        user = {"processing_strategy": "standard"}
        cfg = get_agentic_settings(user)
        assert cfg == AGENTIC_DEFAULTS


# ── Red Team Trigger Logic ───────────────────────────────────────────


class TestNeedsRedTeam:
    def _make_result(self, slug, is_match, confidence):
        return SpecializedAgentResult(
            intent=slug, slug=slug, is_match=is_match, confidence=confidence,
        )

    def test_no_match(self):
        results = [self._make_result("a", False, 0.2)]
        assert needs_red_team(results, AGENTIC_DEFAULTS) is True

    def test_low_confidence(self):
        results = [self._make_result("a", True, 0.5)]
        assert needs_red_team(results, AGENTIC_DEFAULTS) is True

    def test_high_confidence_no_conflict(self):
        results = [
            self._make_result("a", True, 0.95),
            self._make_result("b", True, 0.3),
        ]
        assert needs_red_team(results, AGENTIC_DEFAULTS) is False

    def test_conflict(self):
        results = [
            self._make_result("a", True, 0.82),
            self._make_result("b", True, 0.78),
        ]
        # delta = 0.04 < 0.15 → conflict
        assert needs_red_team(results, AGENTIC_DEFAULTS) is True

    def test_empty_results(self):
        assert needs_red_team([], AGENTIC_DEFAULTS) is True


# ── Specialized Agent Tool-Calling ───────────────────────────────────


class TestSpecializedAgentTools:
    def test_index_enabled_default(self):
        from classymail.agents.specialized import _is_index_enabled
        # No enabled_indexes setting → all enabled by default
        assert _is_index_enabled("billing-inquiry", AGENTIC_DEFAULTS) is True

    def test_index_disabled_by_setting(self):
        from classymail.agents.specialized import _is_index_enabled
        agentic = {**AGENTIC_DEFAULTS, "enabled_indexes": {"billing-inquiry": False, "tech": True}}
        assert _is_index_enabled("billing-inquiry", agentic) is False
        assert _is_index_enabled("tech", agentic) is True
        # Unlisted category → default True
        assert _is_index_enabled("other", agentic) is True

    def test_search_tool_definition_contextual(self):
        from classymail.agents.specialized import _build_search_tool
        tool = _build_search_tool("billing-inquiry", "Billing inquiry")
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "search_billing_inquiry"
        assert "classymail-intent-billing-inquiry" in tool["function"]["description"]
        assert "Billing inquiry" in tool["function"]["description"]
        assert "query" in tool["function"]["parameters"]["properties"]

    def test_search_tool_slug_with_hyphens(self):
        from classymail.agents.specialized import _build_search_tool
        tool = _build_search_tool("technical-support", "Technical support")
        assert tool["function"]["name"] == "search_technical_support"
        assert "classymail-intent-technical-support" in tool["function"]["description"]

    def test_format_tool_result_empty(self):
        from classymail.agents.specialized import _format_tool_result
        assert "No reference examples found" in _format_tool_result([])

    def test_format_tool_result_with_refs(self):
        from classymail.agents.specialized import _format_tool_result
        from classymail.agents.models import RAGGroundingRef
        refs = [
            RAGGroundingRef(doc_id="1", score=0.9, label="billing", source="human_verified",
                            content_snippet="Invoice #123", is_positive=True),
            RAGGroundingRef(doc_id="2", score=0.7, label="billing", source="human_corrected",
                            content_snippet="Password reset", is_positive=False,
                            correction_reason="NOT billing"),
        ]
        result = _format_tool_result(refs)
        assert "POSITIVE EXAMPLES" in result
        assert "NEGATIVE EXAMPLES" in result
        assert "Invoice #123" in result
        assert "NOT billing" in result

    def test_prompt_has_tool_instruction_when_enabled(self):
        from classymail.agents.specialized import _build_specialized_prompt
        prompt = _build_specialized_prompt("Billing", "Invoice questions", "", True, "billing-inquiry", "en")
        assert "search_billing_inquiry" in prompt
        assert "classymail-intent-billing-inquiry" in prompt
        assert "TOOL AVAILABLE" in prompt

    def test_prompt_no_tool_when_disabled(self):
        from classymail.agents.specialized import _build_specialized_prompt
        prompt = _build_specialized_prompt("Billing", "Invoice questions", "", False, "billing-inquiry", "en")
        assert "search_billing_inquiry" not in prompt
        assert "TOOL AVAILABLE" not in prompt


# ── Settings Store Agentic Block ─────────────────────────────────────


class TestSettingsStoreAgentic:
    def test_default_settings_has_agentic(self):
        from classymail.services.settings_store import DEFAULT_SETTINGS
        assert "agentic" in DEFAULT_SETTINGS
        assert DEFAULT_SETTINGS["agentic"]["orchestrator_model"] == "gpt-4.1-nano"
        assert "enabled_indexes" in DEFAULT_SETTINGS["agentic"]

    def test_strategy_agentic_accepted(self):
        from classymail.services.settings_store import save_settings, load_settings
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            tmp = Path(f.name)

        try:
            with patch("classymail.services.settings_store.DATA_FILE", tmp):
                settings = {"processing_strategy": "agentic", "categories": []}
                save_settings(settings)
                loaded = load_settings()
                assert loaded["processing_strategy"] == "agentic"
        finally:
            tmp.unlink(missing_ok=True)

    def test_agentic_defaults_merged_on_load(self):
        from classymail.services.settings_store import load_settings
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"processing_strategy": "agentic"}, f)
            tmp = Path(f.name)

        try:
            with patch("classymail.services.settings_store.DATA_FILE", tmp):
                loaded = load_settings()
                assert "agentic" in loaded
                assert loaded["agentic"]["orchestrator_model"] == "gpt-4.1-nano"
                assert loaded["agentic"]["max_parallel_agents"] == 6
        finally:
            tmp.unlink(missing_ok=True)


# ── Workflow (classify_agentic) ──────────────────────────────────────


class TestClassifyAgentic:
    @pytest.mark.asyncio
    async def test_classify_agentic_no_candidates(self):
        """When orchestrator returns no candidates, Red Team fires then result has empty intents."""
        empty_orch = OrchestratorResult(candidate_intents=[], model="gpt-4.1-nano")
        rt_verdict = RedTeamVerdict(
            validated=True, justification="No match is correct", model="gpt-4.1",
            tokens={"total_tokens": 50},
        )

        with (
            patch("classymail.agents.workflow.run_orchestrator", new_callable=AsyncMock) as mock_orch,
            patch("classymail.agents.workflow.run_red_team", new_callable=AsyncMock) as mock_rt,
        ):
            mock_orch.return_value = empty_orch
            mock_rt.return_value = rt_verdict

            from classymail.agents.workflow import classify_agentic
            result = await classify_agentic("Test email", settings={"agentic": {"enabled": True}})

            assert result["detected_intents"] == []
            assert result.get("agentic") is True
            mock_rt.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_classify_agentic_full_flow(self):
        """Full flow: orchestrator → 2 agents → no red team (high confidence)."""
        orch_result = OrchestratorResult(
            candidate_intents=[
                CandidateIntent(intent="Billing", slug="billing", confidence=0.9),
                CandidateIntent(intent="Tech", slug="tech", confidence=0.6),
            ],
            model="gpt-4.1-nano",
            tokens={"total_tokens": 100},
        )

        agent1 = SpecializedAgentResult(
            intent="Billing", slug="billing", is_match=True, confidence=0.92,
            explanation="Invoice mentioned", model="gpt-4.1-nano",
            tokens={"total_tokens": 200},
        )
        agent2 = SpecializedAgentResult(
            intent="Tech", slug="tech", is_match=False, confidence=0.15,
            model="gpt-4.1-nano", tokens={"total_tokens": 150},
        )

        with (
            patch("classymail.agents.workflow.run_orchestrator", new_callable=AsyncMock) as mock_orch,
            patch("classymail.agents.workflow.run_specialized_agent", new_callable=AsyncMock) as mock_agent,
        ):
            mock_orch.return_value = orch_result
            mock_agent.side_effect = [agent1, agent2]

            from classymail.agents.workflow import classify_agentic
            result = await classify_agentic(
                "Invoice for $500",
                settings={
                    "agentic": {"enabled": True, "red_team_threshold": 0.7},
                    "categories": [
                        {"name": "Billing", "slug": "billing", "description": "x", "exclusions": ""},
                        {"name": "Tech", "slug": "tech", "description": "y", "exclusions": ""},
                    ],
                },
            )

            assert len(result["detected_intents"]) == 1
            assert result["detected_intents"][0]["intent"] == "Billing"
            assert result["detected_intents"][0]["confidence"] == 0.92
            assert result.get("agentic") is True
            assert result["usage"]["total_tokens"] == 450  # 100 + 200 + 150

    @pytest.mark.asyncio
    async def test_classify_agentic_red_team_triggered(self):
        """Red team is triggered when max confidence is below threshold."""
        orch_result = OrchestratorResult(
            candidate_intents=[
                CandidateIntent(intent="Billing", slug="billing", confidence=0.5),
            ],
            model="gpt-4.1-nano",
            tokens={"total_tokens": 100},
        )

        agent1 = SpecializedAgentResult(
            intent="Billing", slug="billing", is_match=True, confidence=0.55,
            model="gpt-4.1-nano", tokens={"total_tokens": 200},
        )

        red_team = RedTeamVerdict(
            validated=True,
            justification="Classification looks reasonable despite low confidence",
            model="gpt-4.1", tokens={"total_tokens": 300},
        )

        with (
            patch("classymail.agents.workflow.run_orchestrator", new_callable=AsyncMock) as mock_orch,
            patch("classymail.agents.workflow.run_specialized_agent", new_callable=AsyncMock) as mock_agent,
            patch("classymail.agents.workflow.run_red_team", new_callable=AsyncMock) as mock_rt,
        ):
            mock_orch.return_value = orch_result
            mock_agent.return_value = agent1
            mock_rt.return_value = red_team

            from classymail.agents.workflow import classify_agentic
            result = await classify_agentic(
                "Ambiguous email",
                settings={"agentic": {"enabled": True, "red_team_threshold": 0.7}},
            )

            mock_rt.assert_called_once()
            assert "red_team" in result
            assert result["usage"]["total_tokens"] == 600


# ── Pipeline Routing ─────────────────────────────────────────────────


class TestPipelineRouting:
    def test_import_classify_agentic(self):
        """classify_agentic is importable from pipeline."""
        from classymail.services.pipeline import classify_agentic  # noqa: F401


class TestFanoutResilience:
    """One specialized agent crash must not lose the other agents' results."""

    @pytest.mark.asyncio
    async def test_partial_failure_yields_placeholder(self):
        orch_result = OrchestratorResult(
            candidate_intents=[
                CandidateIntent(intent="Billing", slug="billing", confidence=0.9),
                CandidateIntent(intent="Tech", slug="tech", confidence=0.7),
            ],
            model="gpt-4.1-nano",
            tokens={"total_tokens": 50},
        )
        good = SpecializedAgentResult(
            intent="Billing", slug="billing", is_match=True, confidence=0.95,
            model="gpt-4.1-nano", tokens={"total_tokens": 100},
        )

        async def _side_effect(text, candidate, **_):
            if candidate.slug == "billing":
                return good
            raise RuntimeError("AI Search 503")

        with (
            patch("classymail.agents.workflow.run_orchestrator", new_callable=AsyncMock) as mock_orch,
            patch("classymail.agents.workflow.run_specialized_agent", side_effect=_side_effect),
            patch("classymail.agents.workflow.run_red_team", new_callable=AsyncMock) as mock_rt,
        ):
            mock_orch.return_value = orch_result
            mock_rt.return_value = RedTeamVerdict(validated=True, model="gpt-4.1", tokens={"total_tokens": 0})

            from classymail.agents.workflow import classify_agentic
            result = await classify_agentic(
                "Billing question with a broken tech agent",
                settings={
                    "agentic": {"enabled": True, "red_team_threshold": 0.7},
                    "categories": [
                        {"name": "Billing", "slug": "billing", "description": "x", "exclusions": ""},
                        {"name": "Tech", "slug": "tech", "description": "y", "exclusions": ""},
                    ],
                },
            )

        # Surviving agent still drives the classification:
        assert any(
            d.get("intent") == "Billing" and d.get("confidence") == 0.95
            for d in result["detected_intents"]
        )
        # Tech (failed) appears in traces as a specialized entry with confidence=0
        tech_traces = [
            t for t in result.get("agent_traces", [])
            if t.get("agent_type") == "specialized" and t.get("intent") == "tech"
        ]
        assert tech_traces and tech_traces[0].get("confidence") == 0.0

    def test_failure_placeholder_shape(self):
        from classymail.agents.workflow import _failure_placeholder
        cand = CandidateIntent(intent="Billing", slug="billing", confidence=0.9)
        placeholder = _failure_placeholder(cand, RuntimeError("boom"))
        assert placeholder.slug == "billing"
        assert placeholder.is_match is False
        assert placeholder.confidence == 0.0
        assert placeholder.error == "RuntimeError: boom"
