"""Safety/correctness guarantees of the agentic workflow and settings persistence."""

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from classymail.agents.models import (
    CandidateIntent,
    OrchestratorResult,
    RedTeamVerdict,
    SpecializedAgentResult,
)

CATEGORIES = [
    {"name": "Billing", "slug": "billing", "description": "x", "exclusions": ""},
    {"name": "Tech", "slug": "tech", "description": "y", "exclusions": ""},
    {"name": "Legal", "slug": "legal", "description": "z", "exclusions": ""},
]
SETTINGS = {"agentic": {"enabled": True, "red_team_threshold": 0.7}, "categories": CATEGORIES}


def _agent(slug: str, conf: float, match: bool = True) -> SpecializedAgentResult:
    return SpecializedAgentResult(
        intent=slug.title(), slug=slug, is_match=match, confidence=conf,
        model="m", tokens={"total_tokens": 1},
    )


def _orch(*slugs: str) -> OrchestratorResult:
    return OrchestratorResult(
        candidate_intents=[CandidateIntent(intent=s.title(), slug=s, confidence=0.9) for s in slugs],
        model="m", tokens={"total_tokens": 1},
    )


async def _run(orch, agents, red_team=None, red_team_exc=None):
    from classymail.agents.workflow import classify_agentic

    rt = AsyncMock()
    if red_team_exc:
        rt.side_effect = red_team_exc
    else:
        rt.return_value = red_team or RedTeamVerdict(validated=True, model="m", tokens={})
    with (
        patch("classymail.agents.workflow.run_orchestrator", new_callable=AsyncMock, return_value=orch),
        patch("classymail.agents.workflow.run_specialized_agent", new_callable=AsyncMock) as sa,
        patch("classymail.agents.workflow.run_red_team", rt),
    ):
        sa.side_effect = agents
        result = await classify_agentic("doc", settings=SETTINGS)
    return result, sa, rt


class TestReviewDecision:
    @pytest.mark.asyncio
    async def test_strong_label_does_not_hide_weak_label(self):
        # 0.95 vs 0.5: no Red Team trigger, yet the accepted 0.5 label still needs review
        result, _, _ = await _run(_orch("billing", "tech"), [_agent("billing", 0.95), _agent("tech", 0.5)])
        assert {d["intent"] for d in result["detected_intents"]} == {"Billing", "Tech"}
        assert result["needs_review"] is True

    @pytest.mark.asyncio
    async def test_all_strong_labels_no_review(self):
        result, _, rt = await _run(_orch("billing"), [_agent("billing", 0.95)])
        rt.assert_not_awaited()
        assert result["needs_review"] is False

    @pytest.mark.asyncio
    async def test_red_team_rejection_forces_review(self):
        verdict = RedTeamVerdict(validated=False, model="m", tokens={})
        result, _, _ = await _run(_orch("billing"), [_agent("billing", 0.6)], red_team=verdict)
        assert result["needs_review"] is True

    @pytest.mark.asyncio
    async def test_red_team_failure_keeps_partial_results(self):
        result, _, _ = await _run(
            _orch("billing"), [_agent("billing", 0.6)], red_team_exc=RuntimeError("429"),
        )
        assert result["detected_intents"][0]["intent"] == "Billing"
        assert result["needs_review"] is True

    @pytest.mark.asyncio
    async def test_failed_agent_forces_review(self):
        result, _, _ = await _run(
            _orch("billing", "tech"), [_agent("billing", 0.95), RuntimeError("boom")],
        )
        assert result["needs_review"] is True


class TestRefinementsAndExtraAgents:
    def test_invalid_refinements_ignored(self):
        from classymail.agents.workflow import _apply_refinements

        agents = [_agent("billing", 0.8), _agent("tech", 0.4), _agent("legal", 0.5)]
        applied = _apply_refinements(agents, {"billing": 1.5, "tech": float("nan"), "legal": "0.9", "ghost": 0.1})
        assert applied == 1
        assert [a.confidence for a in agents] == [0.8, 0.4, 0.9]
        assert all(math.isfinite(a.confidence) for a in agents)

    def test_non_dict_refinements_ignored(self):
        from classymail.agents.workflow import _apply_refinements

        assert _apply_refinements([_agent("billing", 0.8)], ["billing"]) == 0

    @pytest.mark.asyncio
    async def test_extra_agents_deduped_on_canonical_slug(self):
        verdict = RedTeamVerdict(
            validated=False, model="m", tokens={},
            missed_intents=["legal", "Legal ", "billing", "unknown"],
            additional_agents_requested=["legal"],
        )
        _, sa, _ = await _run(
            _orch("billing"), [_agent("billing", 0.5), _agent("legal", 0.8)], red_team=verdict,
        )
        extra_slugs = [call.args[1].slug for call in sa.await_args_list[1:]]
        assert extra_slugs == ["legal"]


class TestRedTeamParsing:
    def test_missing_validated_is_not_approval(self):
        from classymail.agents.red_team import _parse_verdict_payload

        assert _parse_verdict_payload('{"justification": "ok"}').get("validated") is not True

    @pytest.mark.parametrize("raw", ["not json", "[1, 2]", ""])
    def test_malformed_output_not_validated(self, raw):
        from classymail.agents.red_team import _parse_verdict_payload

        assert _parse_verdict_payload(raw)["validated"] is False


class TestToolArguments:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ('{"query": "  invoice 42 "}', "invoice 42"),
            ('{"query": ""}', "DOC"),
            ('{"query": 7}', "DOC"),
            ("{bad", "DOC"),
            ('["x"]', "DOC"),
            (None, "DOC"),
        ],
    )
    def test_tool_query(self, raw, expected):
        from classymail.agents.specialized import _tool_query

        assert _tool_query(raw, "DOC") == expected

    def test_tool_query_bounded(self):
        from classymail.agents.specialized import _tool_query

        assert len(_tool_query('{"query": "' + "a" * 2000 + '"}', "DOC")) == 500


class TestSpecializedToolLoop:
    @pytest.mark.asyncio
    async def test_unexpected_tool_rejected_and_answered(self):
        from classymail.agents import specialized

        first = MagicMock()
        first.model_dump.return_value = {
            "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "search_other", "arguments": "{}"}},
            ]}}],
            "usage": {"total_tokens": 1},
        }
        second = MagicMock()
        second.model_dump.return_value = {
            "choices": [{"message": {"content": '{"is_match": true, "confidence": 0.8}'}}],
            "usage": {"total_tokens": 1},
        }
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=[first, second])
        search = AsyncMock(return_value=[])

        with (
            patch.object(specialized, "get_chat_client", AsyncMock(return_value=client)),
            patch.object(specialized, "resolve_agent_endpoint", return_value=("e", "gpt-4.1", "v")),
            patch.object(specialized, "_is_index_enabled", return_value=True),
            patch.object(specialized, "search_intent_index", search),
        ):
            result = await specialized.run_specialized_agent(
                "doc", CandidateIntent(intent="Billing", slug="billing", confidence=0.9), settings=SETTINGS,
            )

        search.assert_not_awaited()
        assert result.tool_called is False
        sent = client.chat.completions.create.await_args_list[1].kwargs["messages"]
        assert [m["role"] for m in sent].count("assistant") == 1
        assert any(m.get("role") == "tool" and m.get("tool_call_id") == "c1" for m in sent)


class TestSettingsPersistence:
    def _client(self, clients):
        from classymail.api.routers import settings as router_mod
        from classymail.services.azure_clients import get_clients

        app = FastAPI()
        app.include_router(router_mod.router)
        app.dependency_overrides[get_clients] = lambda: clients
        return TestClient(app)

    def test_cosmos_failure_is_reported(self, tmp_path):
        container = MagicMock()
        container.upsert_item = AsyncMock(side_effect=RuntimeError("403"))
        clients = MagicMock(cosmos_container=container)
        with patch("classymail.services.settings_store.DATA_FILE", tmp_path / "s.json"):
            res = self._client(clients).post("/api/settings", json={"processing_strategy": "agentic"})
        assert res.status_code == 503
        assert "Cosmos" in res.json()["detail"]

    def test_save_without_cosmos_succeeds(self, tmp_path):
        clients = MagicMock(cosmos_container=None)
        with patch("classymail.services.settings_store.DATA_FILE", tmp_path / "s.json"):
            res = self._client(clients).post("/api/settings", json={"processing_strategy": "agentic"})
        assert res.status_code == 200
        assert res.json()["processing_strategy"] == "agentic"
