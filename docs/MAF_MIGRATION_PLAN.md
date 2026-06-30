# Microsoft Agent Framework — Migration Plan

> Status: **Plan only — no production code changes.** This document captures
> the exact migration path for two MAF 1.5+ adoptions evaluated against
> ClassyMail's current code (May 2026). Implement deliberately, one PR per
> scope, with the feature-flag patterns described below.

## Why this is a plan, not a PR

Two MAF features were evaluated for adoption:

1. **`agent-framework-orchestrations` — `ConcurrentBuilder`** to replace
   `asyncio.gather` fan-out in `classymail/agents/workflow.py`.
2. **`agent-framework-azure-cosmos` — `CosmosHistoryProvider`** to replace
   manual Cosmos calls in `classymail/services/repository.py` for chat
   history.

Both are non-trivial because:

- Our specialized agents (`#classymail/agents/specialized.py`) are **not
  `agent_framework.Agent` instances**. They are custom Python coroutines
  with per-tier model selection, per-intent AI Search tool injection,
  custom retry/timeout, and custom OTel span attributes consumed by the
  Vue UI Mermaid trace renderer (`#frontend/src/components/EmailDetailModal.vue`).
- The chat history container uses **partition key `/id`** and a flat
  document shape `{role, content, sources, created_at, type}`. MAF expects
  partition key `/session_id` and stores `{message: Message.to_dict()}`.
  The **`sources` field has no native equivalent in MAF**, and is
  consumed by the UI at `#frontend/src/views/DashboardView.vue:850+`.

Neither is a drop-in replacement. Both require a feature-flagged rollout
plus (for history) a data-migration strategy.

---

## Part A — Orchestrations: replace `asyncio.gather` with `ConcurrentBuilder`

> **Update — verified against installed MAF 1.9.0 (June 2026):** orchestrations
> were promoted to **GA/stable (`agent-framework-orchestrations` 1.0.0)**, but this
> is a **separate distribution that is NOT installed under the current pin** —
> `from agent_framework.orchestrations import ConcurrentBuilder` raises
> `ModuleNotFoundError` until you `pip install agent-framework-orchestrations`
> (the `agent_framework.orchestrations` name in core is only a lazy re-export
> shim). **PR-A1's "add the dependency" step below is therefore still required.**
> Once installed it also exposes `SequentialBuilder`, `HandoffBuilder`,
> `MagenticBuilder`, and `GroupChatBuilder`; MAF `Agent` instances satisfy
> `SupportsAgentRun` structurally, so they are valid participants. **Caveat
> unchanged:** `ConcurrentBuilder` still has **no per-participant timeout** in
> 1.9.0 — keep the per-agent `asyncio.wait_for`.

### Current code

`#classymail/agents/workflow.py` contains the only two `asyncio.gather`
fan-out sites for the agentic pipeline:

1. **Step 2 (lines ~92–112)**: parallel execution of specialized
   per-intent agents.
2. **Red Team phase (lines ~188–197)**: parallel execution of
   additional agents requested by the red team verdict.

Each "agent" is a Python coroutine produced by
`#classymail/agents/specialized.py`, not an `agent_framework.Agent`. It
returns a `SpecializedAgentResult` Pydantic model defined in
`#classymail/agents/models.py`.

### Target API (`agent-framework-orchestrations`, now GA/stable in 1.9)

```python
from agent_framework.orchestrations import ConcurrentBuilder

workflow = ConcurrentBuilder(participants=[agent1, agent2, ...]).build()
# workflow.run(...) returns a Workflow execution, not a list.
```

Participants must be MAF `Agent` instances (or `Executor`s).

### Gap analysis

| Concern | Current | MAF `ConcurrentBuilder` |
|--------|---------|--------------------------|
| Participant type | Plain `async def` coroutines | Must be `Agent` / `Executor` |
| Per-agent timeout | `asyncio.wait_for` inside each coro | Not exposed (global only) |
| Per-agent retry | tenacity decorator on tool calls | Not exposed |
| Result ordering | Deterministic via gather | Workflow-event-based; order via correlation |
| OTel span names | `agentic.agent.{slug}`, `agentic.search.{slug}`, `agentic.parallel_agents` consumed by UI | MAF emits `gen_ai.*` / orchestration spans |
| Per-agent tool injection | Tool def built per-slug for `search_{slug}` AI Search index | Would need an `Agent` subclass per intent |

### Recommended approach (feature-flagged, two PRs)

**PR-A1 — scaffolding only (zero behavior change):**

1. Add optional dep: `agent-framework-orchestrations` in
   `[dependency-groups] dev` (NOT in main `dependencies`).
2. Add env flag `AGENTIC_USE_MAF_ORCHESTRATION=false` (default).
3. In `workflow.py`, wrap both `asyncio.gather` calls:

   ```python
   if os.getenv("AGENTIC_USE_MAF_ORCHESTRATION") == "true":
       results = await _run_via_maf(tasks)   # New code path
   else:
       results = await asyncio.gather(*tasks)  # Current behavior
   ```
4. Implement `_run_via_maf` as a stub that raises `NotImplementedError`
   until PR-A2.
5. Tests: add a unit test that confirms the flag-off path is unchanged.

**PR-A2 — implement MAF path (still flag-off in prod):**

1. Refactor each specialized coroutine into an `Agent` subclass exposing
   the same `SpecializedAgentResult` shape (custom output adapter).
2. Implement `_run_via_maf` using `ConcurrentBuilder`.
3. Add OTel span translation layer so the UI trace renderer keeps
   working (preserve `agentic.parallel.latency_ms` and per-agent
   attributes). Validate against `EmailDetailModal.vue` Mermaid render.
4. Add integration tests covering: ordering, per-agent failure, token
   aggregation, OTel spans.
5. Document the env flag in `#docs/LOCAL_DEVELOPMENT.md` and
   `#docs/ENV_REFERENCE.md`.

**Canary rollout (post-merge):**

- Day 1–2: `AGENTIC_USE_MAF_ORCHESTRATION=true` on **staging only**.
  Smoke test full pipeline + UI traces.
- Day 3–5: 5% of prod traffic via container app revision split.
- Day 6+: full cutover if span/UI/latency parity confirmed.
- Rollback: flip the env var and revert the revision split — no code
  redeploy needed.

### Files touched (per PR)

PR-A1 (~70 LOC):
- `pyproject.toml`
- `classymail/agents/workflow.py`
- `tests/test_agentic.py` (flag-off regression)

PR-A2 (~300 LOC):
- `classymail/agents/concurrent_orchestration.py` (new)
- `classymail/agents/workflow.py` (route flag-on path)
- `classymail/agents/specialized.py` (Agent subclass wrapper)
- `tests/test_concurrent_orchestration.py` (new)

### Risks not yet mitigated

- MAF `ConcurrentBuilder` does NOT expose per-agent timeout. We currently
  rely on per-agent `asyncio.wait_for`. **Mitigation:** keep our timeout
  inside the per-intent Agent's `_run` method.
- MAF emits its own OTel spans. If they don't carry the
  `agentic.parallel.latency_ms` attribute the UI reads, the Mermaid flow
  diagram in `EmailDetailModal.vue` will render empty. **Mitigation:**
  add an OTel span processor that copies MAF attributes into our
  namespace until the UI is updated.

---

## Part B — Chat history: replace manual Cosmos with `CosmosHistoryProvider`

> **Update — verified against installed MAF 1.9.0 (June 2026):** `HistoryProvider`,
> `AgentSession`, and `SessionContext` are now **in-core** (`agent-framework-core==1.9.0`),
> with built-in `InMemoryHistoryProvider` / `FileHistoryProvider`. The **`sources`
> "no native equivalent" blocker below is resolved**: `Message` exposes
> `additional_properties` (a `MutableMapping`) — a clean, first-class carrier for the
> `sources` round-trip (no need to overload `Message.metadata`). `CosmosHistoryProvider`
> (`agent-framework-azure-cosmos`) remains **Beta** — mind the `allowed_checkpoint_types=`
> pickle guard (added 1.1.0) if custom types land in `session.state`. Note also:
> `OpenAIChatClient` sets `STORES_BY_DEFAULT=True`, so the Azure OpenAI Responses API
> already persists turn state server-side (via `previous_response_id`) when you pass
> `session=` — a transient-multi-turn alternative to Cosmos, though it won't carry
> `sources` for the UI, so the dual-store rationale still holds.

### Current schema (DO NOT CHANGE under existing container)

**Container:** `chat_history` (config: `AZURE_COSMOS_CHAT_CONTAINER`).
**Partition key:** `/id` (composite `{session_id}:{ISO_timestamp}`).

Document shape — `#classymail/services/repository.py:682-694`:

```json
{
  "id": "{session_id}:{iso_timestamp}",
  "session_id": "<string>",
  "role": "user" | "assistant",
  "content": "<string>",
  "sources": [
    {
      "parent_id": "<string>",
      "subject": "<string>",
      "chunk_index": 0,
      "content": "<string>",
      "distance": 0.0
    }
  ],
  "created_at": "<iso8601>",
  "type": "chat_history"
}
```

### MAF schema (`agent-framework-azure-cosmos` 1.6.0)

**Partition key:** `/session_id`.

```json
{
  "id": "<uuid>",
  "session_id": "<string>",
  "sort_key": 0,
  "source_id": "azure_cosmos_history",
  "message": { "...": "Message.to_dict() output" }
}
```

No native `sources` field. UI reads `sources` from `/api/chat` response,
which `#classymail/services/chat_agent.py` populates from
`get_chat_history()` for cached responses
(`#classymail/services/chat_agent.py:547-562`).

### Two incompatibilities

1. **Partition key.** `/id` vs `/session_id`. A single container cannot
   serve both — Cosmos rejects schema mismatch on writes.
2. **`sources` field.** Must be stuffed into `Message.metadata` and
   marshalled back out in the chat response.

### Recommended approach (one PR, dual-write/dual-read)

**PR-B (scoped, feature-flagged):**

1. Add dep `agent-framework-azure-cosmos` in main `dependencies`
   (provider is invoked from prod code path).
2. Provision a **new** Cosmos container `chat_history_v2` via
   `#infra/main.tf` (terraform) with partition key `/session_id`. Do NOT
   touch the existing `chat_history` container.
3. Subclass `CosmosHistoryProvider` to inject/extract `sources` via
   `Message.metadata["sources"]`. Name: `ClassyMailHistoryProvider`.
4. Add env flag `CHAT_USE_MAF_HISTORY=false` (default).
5. In `#classymail/services/chat_agent.py`:
   - **Read**: when flag is on, read from MAF provider; on miss, fall
     back to legacy reader (dual-read for transition).
   - **Write**: when flag is on, dual-write (legacy + MAF) for a defined
     transition window so rollback stays possible.
6. Keep `#classymail/api/routers/chat.py` response shape unchanged —
   `ChatResponse.sources` continues to be populated from
   `message.metadata["sources"]`.
7. Backfill script (`#scripts/migrate_chat_history.py`): copies legacy
   docs into v2 with `sources` mapped into metadata. Idempotent and
   batched. Provide a `--dry-run` mode.
8. Tests:
   - Unit: `ClassyMailHistoryProvider` round-trips `sources`.
   - Integration: dual-read prefers v2; falls back to legacy when v2
     empty; legacy entries still rendered with sources in UI.
   - E2E: open the chat panel, verify `chatSources.value` populated.

**Canary rollout:**

- Stage 1: deploy with `CHAT_USE_MAF_HISTORY=false`. No behavior change.
- Stage 2: run backfill script in staging; flip flag to `true` on
  staging; verify UI sources render.
- Stage 3: run backfill in prod; flip flag in 5% canary; verify; full
  cutover.
- Stage 4 (later cleanup PR): remove dual-write, drop legacy container,
  remove flag.

### Files touched

- `pyproject.toml`, `requirements.txt`, `uv.lock`
- `classymail/services/chat_history_provider.py` (new — `ClassyMailHistoryProvider`)
- `classymail/services/chat_agent.py` (read/write routing on flag)
- `classymail/services/azure_clients.py` (provision v2 container client)
- `infra/main.tf` (add `chat_history_v2` container)
- `scripts/migrate_chat_history.py` (new — backfill)
- `tests/test_chat_history_provider.py` (new)
- `docs/LOCAL_DEVELOPMENT.md` + `docs/ENV_REFERENCE.md` (env flag)

### Risks not yet mitigated

- **`sources` round-trip via metadata** is non-standard. If a future MAF
  release schema-validates `Message.metadata`, our payload may be
  rejected. **Mitigation:** pin `agent-framework-azure-cosmos` to a
  specific minor; review on each MAF bump.
- **Backfill cost.** Cross-partition reads from the legacy container are
  expensive. **Mitigation:** run backfill off-peak; cap RU consumption
  via SDK throttling.
- **Session-id continuity.** Frontend persists session IDs in
  `localStorage`. v2 partition is `/session_id`, so the existing
  localStorage IDs work unchanged — verified at
  `#frontend/src/views/DashboardView.vue:74-78`.

---

## Decision matrix

| Adoption | Net value | Risk | Recommend now? |
|----------|-----------|------|----------------|
| Orchestrations `ConcurrentBuilder` | Observability + future workflow patterns | High (rewrites hot path of every email; UI Mermaid trace depends on current spans) | ❌ No — schedule as PR-A1 + PR-A2 with the canary plan above |
| `CosmosHistoryProvider` | Aligns with MAF samples; less custom code long-term | High (new container, backfill, `sources` round-trip via metadata) | ❌ No — schedule as PR-B with backfill script + canary |
| DevUI launcher | Local debugging | Zero (dev-only) | ✅ Already shipped — PR #44 |

## Execution checklist (when greenlit)

- [ ] Open PR-A1 (orchestrations scaffolding, flag-off).
- [ ] Open PR-B (history dual-write/dual-read, flag-off, backfill script).
- [ ] Stage-only flip of `AGENTIC_USE_MAF_ORCHESTRATION=true`; verify
      latency, traces, UI Mermaid.
- [ ] Stage backfill of `chat_history_v2`; flip
      `CHAT_USE_MAF_HISTORY=true`; verify chat sources render.
- [ ] Open PR-A2 (orchestrations implementation behind flag).
- [ ] 5% prod canary on both flags via container app revision split.
- [ ] Full cutover; later PR removes flags + legacy code paths + drops
      legacy Cosmos container.

---

**Evidence gathered:** see prior session checkpoints and the explore
agent reports archived in
`#~/.copilot/session-state/6cd6973b-364f-49d3-ab51-ec2eb74dbf70/`.
