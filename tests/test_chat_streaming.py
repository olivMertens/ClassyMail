"""Tests for opt-in chat streaming (SSE).

Covers the pure marker helpers, ``ClassyMailChatAgent.run_stream`` (happy path +
semantic-cache hit), the ``POST /api/chat/stream`` endpoint, and ``run()`` parity
(guards the shared ``_prepare`` refactor — no pre-existing chat tests on main).

Conventions follow tests/test_agentic.py / test_batch_reprocess_api.py:
``unittest.mock`` (AsyncMock/patch), ``asyncio_mode = auto`` (no decorator needed).
The repository/embedding helpers are imported INTO ``classymail.services.chat_agent``
so they are patched by that module path.
"""

from unittest.mock import AsyncMock, patch

import pytest

from classymail.services.chat_agent import (
    _chunk_text,
    _emit_visible,
    _finalize_stream_text,
    agent as chat_agent_singleton,
)

CHAT_MOD = "classymail.services.chat_agent"


# ── Fakes mimicking agent_framework's streaming contract ─────────────


class FakeUpdate:
    """One AgentResponseUpdate: exposes a ``.text`` str accessor (may be empty)."""

    def __init__(self, text: str):
        self.text = text


class FakeStream:
    """Mimics ``agent_framework.ResponseStream``.

    Async-iterable yielding ``FakeUpdate`` objects; also exposes
    ``get_final_response()`` (unused by run_stream, present for contract parity).
    Returned SYNCHRONOUSLY by ``agent.run(..., stream=True)`` — no await.
    """

    def __init__(self, pieces: list[str]):
        self._pieces = pieces

    def __aiter__(self):
        async def _gen():
            for p in self._pieces:
                yield FakeUpdate(p)

        return _gen()

    async def get_final_response(self):
        return "".join(self._pieces)


class FakeAgent:
    """Stands in for the cached agent-framework Agent."""

    def __init__(self, pieces: list[str]):
        self._pieces = pieces

    def run(self, messages, stream: bool = False, **kwargs):
        if stream:
            # ResponseStream is returned synchronously (no await).
            return FakeStream(self._pieces)

        async def _coro():
            return "".join(self._pieces)

        return _coro()


def _patch_prepare_deps(
    *,
    cache_hits=None,
    sources_chunk=None,
    append_spy=None,
    set_cache_spy=None,
):
    """Patch the read/write helpers used by _prepare + the post-flight writes."""
    cache_hits = cache_hits if cache_hits is not None else []
    sources_chunk = sources_chunk if sources_chunk is not None else []
    return [
        patch(f"{CHAT_MOD}.get_chat_history", AsyncMock(return_value=[])),
        patch(f"{CHAT_MOD}.generate_embedding", AsyncMock(return_value=[0.1, 0.2, 0.3])),
        patch(f"{CHAT_MOD}.get_cache_entry", AsyncMock(return_value=cache_hits)),
        patch(f"{CHAT_MOD}.search_chunks_by_vector", AsyncMock(return_value=sources_chunk)),
        patch(f"{CHAT_MOD}.append_chat_history_entry", append_spy or AsyncMock()),
        patch(f"{CHAT_MOD}.set_cache_entry", set_cache_spy or AsyncMock()),
    ]


async def _collect(agen):
    return [evt async for evt in agen]


# ── Pure helpers ─────────────────────────────────────────────────────


class TestEmitVisible:
    def test_holds_back_tail_when_no_marker(self):
        # Holds back len("<!--")-1 = 3 trailing chars in case a marker forms next.
        assert _emit_visible("Hello wor", 0) == (6, "Hello ")

    def test_nothing_to_emit_for_short_buffer(self):
        # Buffer shorter than the held-back tail yields no visible delta yet.
        assert _emit_visible("Hi", 0) == (0, "")

    def test_freezes_at_marker(self):
        buf = "Answer.<!-- ACTIONS: a -->"
        emitted, delta = _emit_visible(buf, 0)
        assert emitted == buf.index("<!--")
        assert "<!--" not in delta
        assert delta == "Answer."

    def test_split_marker_never_leaks(self):
        # Marker arriving across delta boundaries: "<!" then "--".
        e1, d1 = _emit_visible("Answer<!", 0)
        e2, d2 = _emit_visible("Answer<!--", e1)
        assert "<" not in d1 and "<" not in d2
        assert d1 + d2 == "Answer"


class TestFinalizeStreamText:
    def test_parses_actions_and_strips_marker(self):
        content, actions = _finalize_stream_text("Done.<!-- ACTIONS: a|b|c -->")
        assert content == "Done."
        assert actions == ["a", "b", "c"]

    def test_no_marker_passthrough(self):
        content, actions = _finalize_stream_text("Plain answer.")
        assert content == "Plain answer."
        assert actions == []

    def test_partial_marker_stripped_no_actions(self):
        # Cut at first "<!--" so a malformed/partial trailing marker never shows.
        content, actions = _finalize_stream_text("Answer <!-- ACTIO")
        assert content == "Answer"
        assert actions == []


class TestChunkText:
    def test_chunks_fixed_size(self):
        assert _chunk_text("abcdefghij", 4) == ["abcd", "efgh", "ij"]

    def test_empty(self):
        assert _chunk_text("") == []


# ── run_stream ───────────────────────────────────────────────────────


class TestRunStream:
    async def test_happy_path_streams_clean_deltas(self):
        fake_agent = FakeAgent(["Hello", " world.", "<!-- ACTIONS: View|Retry -->"])
        append_spy = AsyncMock()
        set_cache_spy = AsyncMock()
        patches = _patch_prepare_deps(
            sources_chunk=[{
                "parent_id": "e1", "subject": "S", "chunk_index": 0,
                "content": "c", "distance": 0.1,
            }],
            append_spy=append_spy,
            set_cache_spy=set_cache_spy,
        )
        with patch.object(chat_agent_singleton, "_get_or_create_agent", return_value=fake_agent):
            for p in patches:
                p.start()
            try:
                events = await _collect(chat_agent_singleton.run_stream(
                    [{"role": "user", "content": "hi"}],
                    clients=object(), session_id="s1", locale="en",
                ))
            finally:
                for p in patches:
                    p.stop()

        deltas = [e["text"] for e in events if e["type"] == "delta"]
        done = [e for e in events if e["type"] == "done"][-1]
        joined = "".join(deltas)

        # Marker is never visible in the streamed deltas.
        assert "<!--" not in joined and "ACTIONS" not in joined
        assert joined == "Hello world."
        # Terminal event carries clean content + parsed actions + sources.
        assert done["content"] == "Hello world."
        assert done["suggested_actions"] == ["View", "Retry"]
        assert len(done["sources"]) == 1
        # History persisted (user + assistant); assistant content is RAW (marker kept).
        assert append_spy.await_count == 2
        assert "<!-- ACTIONS:" in append_spy.await_args_list[1].args[2]
        # Semantic cache updated with the RAW content for cross-endpoint consistency.
        set_cache_spy.assert_awaited_once()
        assert "<!-- ACTIONS:" in set_cache_spy.await_args.args[2]

    async def test_cache_hit_streams_clean_and_skips_set(self):
        cached = [{
            "response": "Cached answer.<!-- ACTIONS: Open -->",
            "sources": [{"parent_id": "e9"}],
        }]
        append_spy = AsyncMock()
        set_cache_spy = AsyncMock()
        patches = _patch_prepare_deps(
            cache_hits=cached, append_spy=append_spy, set_cache_spy=set_cache_spy,
        )
        with patch.object(chat_agent_singleton, "_get_or_create_agent", return_value=FakeAgent([])):
            for p in patches:
                p.start()
            try:
                events = await _collect(chat_agent_singleton.run_stream(
                    [{"role": "user", "content": "q"}],
                    clients=object(), session_id="s2", locale="en",
                ))
            finally:
                for p in patches:
                    p.stop()

        deltas = "".join(e["text"] for e in events if e["type"] == "delta")
        done = [e for e in events if e["type"] == "done"][-1]

        assert "<!--" not in deltas
        assert deltas == "Cached answer."
        assert done["content"] == "Cached answer."
        assert done["suggested_actions"] == ["Open"]
        assert done["sources"] == [{"parent_id": "e9"}]
        # Cache hit appends user + assistant turns to history...
        assert append_spy.await_count == 2
        # ...but never re-writes the cache entry.
        set_cache_spy.assert_not_awaited()


# ── Endpoint ─────────────────────────────────────────────────────────


class TestChatStreamEndpoint:
    def test_post_chat_stream_emits_sse(self):
        from fastapi.testclient import TestClient

        from classymail.app import app
        from classymail.services.azure_clients import get_clients

        async def fake_run_stream(messages, clients, session_id=None, locale="en"):
            yield {"type": "delta", "text": "Hi"}
            yield {
                "type": "done",
                "content": "Hi",
                "sources": [{"parent_id": "e1"}],
                "suggested_actions": ["A"],
            }

        app.dependency_overrides[get_clients] = lambda: object()
        try:
            with patch.object(chat_agent_singleton, "run_stream", fake_run_stream):
                # No `with TestClient(...)` so the lifespan (which requires Azure
                # env) does not run; the dependency override supplies clients.
                client = TestClient(app)
                resp = client.post(
                    "/api/chat/stream",
                    json={"messages": [{"role": "user", "content": "hi"}], "session_id": "s"},
                )
        finally:
            app.dependency_overrides.pop(get_clients, None)

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.text
        assert 'data: {"delta": "Hi"}' in body
        assert "event: done" in body
        assert '"content": "Hi"' in body
        assert '"parent_id": "e1"' in body

    def test_post_chat_stream_rejects_empty_messages(self):
        from fastapi.testclient import TestClient

        from classymail.app import app
        from classymail.services.azure_clients import get_clients

        app.dependency_overrides[get_clients] = lambda: object()
        try:
            client = TestClient(app)
            resp = client.post("/api/chat/stream", json={"messages": []})
        finally:
            app.dependency_overrides.pop(get_clients, None)

        assert resp.status_code == 400


# ── run() parity (guards the _prepare refactor) ──────────────────────


class TestRunParity:
    async def test_run_strips_marker_and_persists_raw(self):
        fake_agent = FakeAgent(["Answer text.<!-- ACTIONS: Open|Close -->"])
        append_spy = AsyncMock()
        set_cache_spy = AsyncMock()
        patches = _patch_prepare_deps(
            sources_chunk=[{"parent_id": "e2", "subject": "x", "chunk_index": 1,
                            "content": "c", "distance": 0.2}],
            append_spy=append_spy,
            set_cache_spy=set_cache_spy,
        )
        with patch.object(chat_agent_singleton, "_get_or_create_agent", return_value=fake_agent):
            for p in patches:
                p.start()
            try:
                result = await chat_agent_singleton.run(
                    [{"role": "user", "content": "hi"}],
                    clients=object(), session_id="s3", locale="en",
                )
            finally:
                for p in patches:
                    p.stop()

        # Returned content is CLEAN; actions parsed; sources present.
        assert result["content"] == "Answer text."
        assert result["suggested_actions"] == ["Open", "Close"]
        assert len(result["sources"]) == 1
        # Persisted/cached content is RAW (marker kept) — matches run_stream.
        assert "<!-- ACTIONS:" in append_spy.await_args_list[1].args[2]
        assert "<!-- ACTIONS:" in set_cache_spy.await_args.args[2]

    async def test_run_cache_hit_returns_cached_without_set(self):
        cached = [{"response": "Cached raw.<!-- ACTIONS: Go -->", "sources": [{"parent_id": "e7"}]}]
        append_spy = AsyncMock()
        set_cache_spy = AsyncMock()
        patches = _patch_prepare_deps(
            cache_hits=cached, append_spy=append_spy, set_cache_spy=set_cache_spy,
        )
        with patch.object(chat_agent_singleton, "_get_or_create_agent", return_value=FakeAgent([])):
            for p in patches:
                p.start()
            try:
                result = await chat_agent_singleton.run(
                    [{"role": "user", "content": "q"}],
                    clients=object(), session_id="s4", locale="en",
                )
            finally:
                for p in patches:
                    p.stop()

        # run() cache-hit returns the RAW cached string (documented legacy quirk).
        assert result["content"] == "Cached raw.<!-- ACTIONS: Go -->"
        assert result["sources"] == [{"parent_id": "e7"}]
        assert append_spy.await_count == 2
        set_cache_spy.assert_not_awaited()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
