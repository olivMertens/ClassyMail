# ClassyMail – Agentic Classification Architecture

> Microsoft Agent Framework GA 1.0 — Multi-agent email classification with orchestrator, specialized agents, per-intent AI Search indexes, and quality gate.

## 1. Objective

Build a **scalable, FinOps-friendly agentic architecture** for email classification:

- **1 business intent = 1 specialized agent**
- **Intelligent orchestration** via custom routing (not fan-out-all)
- **Per-intent Azure AI Search indexes** with semantic ranking & human-reinforced labels
- **Parallel execution** of specialized agents (`asyncio.gather` / Agent Framework fan-out)
- **Quality control loop (Red Team / Quality Gate)**
- **Differentiated model selection per role** (UI-selectable for orchestrator)

## 2. Architecture Principles

| Principle | Rule |
|---|---|
| Single Responsibility | Each agent is expert on exactly one intent |
| Execution cap | Maximum **5–6 specialized agents** called per email |
| Prompt / Model decoupling | Prompt defines the role; model is UI-selectable per tier |
| Code-first | Agents are versioned, testable, observable, replaceable |
| DI pattern | All agents receive `Clients` via dependency injection — no import-by-value |
| Parallel-first | Specialized agents run concurrently via fan-out/fan-in |
| Observable | Every agent call is an OTel span with model, tokens, latency, confidence |

## 3. Logical Architecture

```text
Email entrant
   |
   v
Agent Orchestrator (Expert Inspector)
   |  model: UI-selectable (gpt-4.1-nano | gpt-4.1-mini | model-router)
   |  Analyzes document against EVERY category definition
   |  Cross-references content, context, tone, hidden intents
   |
   +-- Selects top candidate intents (or 0 if genuinely none match)
   |
   v
 ┌──────────── Fan-Out (parallel) ────────────┐
 |                                              |
 Agent-Intent-1    Agent-Intent-2    Agent-Intent-N
 |  +-- prompt     |  +-- prompt     |  +-- prompt
 |  +-- AI Search  |  +-- AI Search  |  +-- AI Search
 |  |   index-1    |  |   index-2    |  |   index-N
 |  +-- model      |  +-- model      |  +-- model
 |  |   (tiered)   |  |   (tiered)   |  |   (tiered)
 └──────────── Fan-In (aggregate) ────────────┘
   |
   v
Agent Red Team / Adversarial Quality Gate
   |  triggered if: 0 candidates from orchestrator | max_confidence < 0.7 | top-2 conflict
   |  model: robust / different (UI-selectable)
   |
   +-- Challenges every decision adversarially
   +-- Detects missed intents
   +-- Requests extra specialized agents for missed intents
   |   (those agents actually run and their results are added)
   |
   v
Subject + Sender extraction (from markdown, independent of LLM)
   |
   v
Final classification decision (traceable, explainable)
```

## 4. Workflow Pattern Selection

### Why Custom Routing (not GroupChat / Magentic)

After analyzing the [Agent Framework GA 1.0 workflow samples](https://github.com/microsoft/agent-framework/tree/main/python/samples/03-workflows), the best pattern for ClassyMail is:

| Pattern | Fit | Reason |
|---|---|---|
| **ConcurrentBuilder (fan-out/fan-in)** | **Best for specialized agents** | Parallel dispatch to N intent agents, aggregate results |
| **Multi-Selection Edge Group** | **Best for orchestrator routing** | Orchestrator selects which agents to activate (like email triage sample) |
| **Edge Condition** | Good for Red Team trigger | Conditional activation based on confidence scores |
| Sequential | Not ideal | Too slow for N agents — latency = sum(all agents) |
| GroupChat | Overkill | Agents don't need to discuss; they each produce an independent verdict |
| Magentic | Overkill | Planning overhead not justified for classification |
| Handoff | Not ideal | No need for specialist-to-specialist routing |

**Selected pattern**: `WorkflowBuilder` with:
1. Orchestrator as `start_executor`
2. `add_multi_selection_edge_group()` to fan-out from orchestrator to selected intent agents
3. `add_fan_in_edges()` to aggregate intent agent results
4. `add_edge(..., condition=...)` for conditional Red Team activation

### Agent Framework Integration

```python
from agent_framework import WorkflowBuilder, AgentExecutor
from agent_framework.orchestrations import ConcurrentBuilder

# Orchestrator selects intents → fan-out to selected agents → fan-in → optional Red Team
workflow = (
    WorkflowBuilder(start_executor=orchestrator)
    .add_multi_selection_edge_group(
        orchestrator_result,
        [agent_intent_1, agent_intent_2, ..., agent_intent_N],
        selection_func=select_candidate_agents,  # top 5-6
    )
    .add_fan_in_edges(
        [agent_intent_1, ..., agent_intent_N],
        aggregator,
    )
    .add_edge(aggregator, red_team, condition=needs_quality_gate)
    .add_edge(aggregator, finalize, condition=lambda r: not needs_quality_gate(r))
    .add_edge(red_team, finalize)
    .build()
)
```

## 5. Agent Roles

### 5.1 Agent Orchestrator (Router)

**Responsibility**: Quickly understand global email content, identify the most probable candidate intents, limit execution to 5-6 agents max.

**Does NOT**: Perform final classification or fine-grained business logic.

**Model selection** (UI-configurable via Settings):

| Option | Use Case | Cost |
|---|---|---|
| `gpt-4.1-nano` | Default — fast, cheap, good for clear routing | Lowest |
| `gpt-4.1-mini` | Better for ambiguous emails with subtle signals | Medium |
| `gpt-4o-mini` | Legacy — good quality/cost balance | Medium |
| `gpt-5-nano` | Reasoning-capable routing (complex multi-intent) | Low-Medium |
| **`model-router`** | Azure AI Model Router — auto-selects optimal LLM per prompt | Variable (FinOps-optimized) |

> **Note**: Phi-4 is **not** recommended as orchestrator — it's optimized for deep classification, not fast routing. The default is `gpt-4.1-nano`.

#### Model Router — Azure AI Intelligent Routing

The [Model Router](https://learn.microsoft.com/azure/foundry/openai/concepts/model-router) is a trained language model that **dynamically routes each prompt to the most appropriate underlying LLM** in real-time. It analyzes prompt complexity, reasoning requirements, and task type — then selects the optimal model from a pool of up to 18 models (version `2025-11-18`).

**How it works for ClassyMail orchestration**:
- Deploy `model-router` as a single deployment on the Foundry resource
- The router automatically selects the best model for each orchestrator call
- Simple routing prompts → routed to cheap models (gpt-4.1-nano, gpt-5-nano)
- Complex multi-intent prompts → routed to capable models (gpt-4.1, gpt-5-mini)
- No need to deploy underlying models separately (except Claude models)

**Routing Modes** (UI-selectable):

| Mode | Behavior | Best For |
|---|---|---|
| **Balanced** (default) | Considers quality within 1-2% of best model, picks cheapest | General orchestration |
| **Cost** | Broader quality band (5-6%), picks most cost-effective | High-volume batch processing |
| **Quality** | Always selects highest-quality model, ignores cost | Critical/sensitive emails |

**Model Subset** (optional, configurable in settings):
Restrict the router to a subset of underlying models. Example for ClassyMail orchestrator:
```json
["gpt-4.1-nano", "gpt-4.1-mini", "gpt-4.1", "gpt-5-nano", "o4-mini"]
```
This prevents routing to expensive models (gpt-5, claude-opus) for simple routing tasks.

**Supported underlying models** (v2025-11-18):
`gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano`, `o4-mini`, `gpt-5-nano`, `gpt-5-mini`, `gpt-5`, `gpt-5-chat`, `gpt-5.2`, `gpt-5.2-chat`, `DeepSeek-V3.1`, `DeepSeek-V3.2`, `gpt-oss-120b`, `llama4-maverick`, `grok-4`, `grok-4-fast`, `claude-haiku-4-5`, `claude-sonnet-4-5`, `claude-opus-4-1`, `claude-opus-4-6`

**Region requirement**: East US 2 or Sweden Central (Global Standard or Data Zone Standard).

**Agentic support**: Model Router officially supports agentic scenarios including tool calling — validated for Agent Framework orchestrations.

**Output contract**:

```json
{
  "candidate_intents": [
    { "intent": "natural_event", "confidence": 0.82 },
    { "intent": "home_certificate", "confidence": 0.64 }
  ],
  "routing_rationale": "Flooding keywords + claim declaration pattern detected",
  "model": "gpt-4.1-nano",
  "routed_model": "gpt-4.1-nano",
  "routing_mode": "balanced",
  "tokens": { "input": 450, "output": 120 },
  "latency_ms": 180
}
```

### 5.2 Specialized Agents (ClassyMail Agents)

> **Golden rule**: 1 business description = 1 agent

**Structure per agent**:

- **Prompt**: Highly constrained, mono-intent, stable over time
- **Tools**: Per-intent AI Search index with semantic ranking (human-reinforced labels)
- **Model**: Chosen per agent tier (UI-configurable):
  - Tier 1: Simple intents — `gpt-4.1-nano`
  - Tier 2: Ambiguous intents — `gpt-4.1-mini`
  - Tier 3: Critical intents — `gpt-4.1` or `gpt-5-mini`

**RAG Grounding — How Agents Learn from Examples**:

Each agent queries its dedicated AI Search index and receives two types of references:

- **POSITIVE examples** — Emails correctly classified as this intent (from `human_verified` / `human_reinforced` sources). Used to calibrate confidence.
- **NEGATIVE examples** — Emails that were **wrongly** classified as this intent (from `human_corrected` source), with `correction_reason` explaining the mistake. Teaches the agent what to avoid.

The prompt instructs agents to weigh `[human_verified]` and `[human_reinforced]` sources more heavily than `[llm_classified]`.

**Standardized output**:

```json
{
  "intent": "natural_event",
  "is_match": true,
  "confidence": 0.91,
  "explanation": "Explicit mentions of flooding and claim declaration",
  "rag_grounding": [
    {
      "doc_id": "email-2024-1234",
      "score": 0.94,
      "label": "natural_event",
      "source": "human_reinforced",
      "content_snippet": "I received a claim for water damage due to...",
      "is_positive": true,
      "correction_reason": null
    },
    {
      "doc_id": "email-2024-5678",
      "score": 0.72,
      "label": "natural_event",
      "source": "human_corrected",
      "content_snippet": "Please send me the insurance certificate...",
      "is_positive": false,
      "correction_reason": "NOT natural_event — this is a document request"
    }
  ],
  "model": "gpt-4.1-nano",
  "tokens": { "input": 800, "output": 200 },
  "latency_ms": 320
}
```

### 5.3 Azure AI Search — Per-Intent Indexes

**Architecture**: One AI Search index per intent/category label, with semantic ranking and human-reinforced vectorized documents.

#### Index Structure

Each index follows a standard schema:

```json
{
  "name": "classymail-intent-{slug}",
  "fields": [
    { "name": "id", "type": "Edm.String", "key": true },
    { "name": "email_id", "type": "Edm.String", "filterable": true },
    { "name": "content", "type": "Edm.String", "searchable": true },
    { "name": "label", "type": "Edm.String", "filterable": true },
    { "name": "label_source", "type": "Edm.String", "filterable": true },
    { "name": "confidence_original", "type": "Edm.Double" },
    { "name": "human_verified", "type": "Edm.Boolean", "filterable": true },
    { "name": "correction_reason", "type": "Edm.String" },
    { "name": "content_vector", "type": "Collection(Edm.Single)", "dimensions": 1536, "vectorSearchProfile": "default-profile" },
    { "name": "created_at", "type": "Edm.DateTimeOffset", "filterable": true, "sortable": true }
  ],
  "vectorSearch": {
    "algorithms": [{ "name": "hnsw", "kind": "hnsw" }],
    "profiles": [{ "name": "default-profile", "algorithm": "hnsw" }]
  },
  "semantic": {
    "configurations": [{
      "name": "default-semantic",
      "prioritizedFields": {
        "contentFields": [{ "fieldName": "content" }]
      }
    }]
  }
}
```

#### Label Sources

| Source | Description | Trust Level |
|---|---|---|
| `llm_classified` | Original LLM classification output | Medium |
| `human_verified` | User confirmed classification via UI | High |
| `human_corrected` | User changed the classification (with reason) | Highest |
| `human_reinforced` | Expert-curated training example | Highest |
| `fine_tune_dataset` | From anonymized fine-tuning dataset | High |

#### UI Integration

The Settings page will show:

- **Per-category toggle**: Enable/disable AI Search index for each category
- **Index stats**: Document count, last indexed date, human-verified ratio
- **Reindex button**: Rebuild index from Cosmos DB classification history
- **Ranked retrieval**: UI selector for retrieval mode:
  - `vector` — pure vector similarity (fastest)
  - `hybrid` — vector + keyword (balanced)
  - `semantic` — vector + keyword + semantic ranker (highest quality)

#### Terraform Resources

```hcl
# Azure AI Search — per-intent indexes with semantic ranking
resource "azurerm_search_service" "classymail" {
  name                = "${var.prefix}-search"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  sku                 = "basic"  # Supports semantic ranking
  semantic_search_sku = "standard"

  identity {
    type = "SystemAssigned"
  }
}

# Model Router deployment — intelligent prompt-level model selection
resource "azapi_resource" "model_router" {
  count     = var.deploy_model_router ? 1 : 0
  type      = "Microsoft.CognitiveServices/accounts/deployments@2025-06-01"
  name      = "model-router"
  parent_id = azapi_resource.ai_services.id

  body = {
    sku = {
      name     = "GlobalStandard"
      capacity = 250  # 250K TPM
    }
    properties = {
      model = {
        format  = "OpenAI"
        name    = "model-router"
        version = "2025-11-18"
      }
      # Routing mode and model subset configured via API at runtime
      # based on UI settings (balanced | cost | quality)
    }
  }
}
```

> **Note**: Model Router routing mode (`balanced`/`cost`/`quality`) and model subset are configured at **request time** via the API, not at deployment time. The UI settings map to request parameters sent with each orchestrator call.

### 5.4 Agent Red Team / Quality Gate

**Role**: Second critical opinion — activated conditionally.

**Trigger conditions** (configurable in UI):

- `max_confidence < 0.7` across all specialized agents
- Top-2 agents conflict: `|confidence_1 - confidence_2| < 0.15`
- Critical intent detected (user-flagged categories)
- Zero intents matched

**Responsibilities**:

- Verify if an important intent was missed
- Detect ambiguities the orchestrator may have missed
- Challenge the specialized agents' conclusions

**Actions**:

- Validate the decision (pass-through)
- Propose 1-2 additional agents to run
- Refine confidence scores with justification

**Model**: More robust or different model (UI-selectable) — called only when triggered (FinOps control).

## 6. Execution Workflow (Step by Step)

### Step 1 — Reception

Email received by the ClassyMail pipeline (blob upload or Service Bus message).

### Step 2 — Orchestration

The orchestrator agent analyzes the email and selects the top 5-6 best candidate intents from the configured categories. Model and routing parameters are UI-configurable.

### Step 3 — Parallel Agent Execution (Fan-Out)

Selected agents run concurrently via `asyncio.gather` / Agent Framework `ConcurrentBuilder`:

- Each agent uses its specialized prompt
- Each agent queries its dedicated AI Search index (with semantic ranking)
- Each agent returns a verdict + score + RAG grounding references

### Step 4 — Aggregation (Fan-In)

Results from all parallel agents are collected and merged into a unified classification result.

### Step 5 — Red Team (Conditional)

Quality gate activated based on configurable trigger thresholds. Can propose refinement or additional agent runs.

### Step 6 — Final Decision

Aggregate results into a single, traceable, explainable output with full provenance (which agents ran, which indexes queried, which models used).

## 7. OpenTelemetry Observability

### Span Hierarchy

```text
pipeline.classification
  |
  +-- agentic.orchestrate                     # Full orchestration span
  |     |
  |     +-- agentic.orchestrator              # Router agent
  |     |     +-- gen_ai.system: azure_openai
  |     |     +-- gen_ai.request.model: gpt-4.1-nano (or model-router)
  |     |     +-- agentic.routed_model: gpt-4.1-nano  # actual model used (model-router)
  |     |     +-- agentic.routing_mode: balanced       # model-router mode
  |     |     +-- agentic.candidates_count: 5
  |     |     +-- agentic.routing_latency_ms: 180
  |     |
  |     +-- agentic.parallel_agents           # Fan-out parent span
  |     |     |
  |     |     +-- agentic.agent.natural_event  # Per-agent spans (parallel)
  |     |     |     +-- gen_ai.request.model: gpt-4.1-nano
  |     |     |     +-- agentic.intent: natural_event
  |     |     |     +-- agentic.confidence: 0.91
  |     |     |     +-- agentic.rag_hits: 3
  |     |     |     +-- agentic.search_index: classymail-intent-natural-event
  |     |     |     +-- agentic.retrieval_mode: semantic
  |     |     |
  |     |     +-- agentic.agent.home_certificate
  |     |     |     +-- ...
  |     |     |
  |     |     +-- agentic.agent.general_inquiry
  |     |           +-- ...
  |     |
  |     +-- agentic.aggregation               # Fan-in
  |     |     +-- agentic.matched_intents: 2
  |     |     +-- agentic.max_confidence: 0.91
  |     |     +-- agentic.needs_red_team: false
  |     |
  |     +-- agentic.red_team                   # Conditional
  |           +-- gen_ai.request.model: gpt-4.1
  |           +-- agentic.trigger_reason: low_confidence
  |           +-- agentic.additional_agents: ["liability"]
  |
  +-- pipeline.embedding
  +-- pipeline.entity_extraction
```

### Key Metrics

| Metric | Description |
|---|---|
| `agentic.orchestrator.latency_ms` | Time to route (orchestrator only) |
| `agentic.parallel.latency_ms` | Wall-clock time for parallel agent execution |
| `agentic.parallel.agent_count` | Number of agents dispatched |
| `agentic.total_tokens` | Sum of all agent tokens (input + output) |
| `agentic.total_cost_usd` | Estimated total cost for the agentic pipeline |
| `agentic.red_team.triggered` | Boolean — whether quality gate was activated |
| `agentic.search.index_hits` | Total RAG documents retrieved across all agents |

## 8. Model Selection Strategy

### Model Tiering (UI-Configurable)

| Role | Default Model | Alternatives (UI dropdown) | Objective |
|---|---|---|---|
| Orchestrator | `gpt-4.1-nano` | `gpt-4.1-mini`, `gpt-4o-mini`, `gpt-5-nano`, **`model-router`** (Balanced/Cost/Quality) | Fast routing, minimal cost |
| Agent Tier 1 (simple) | `gpt-4.1-nano` | `gpt-4o-mini`, `phi-4` | Clear cases, high volume |
| Agent Tier 2 (ambiguous) | `gpt-4.1-mini` | `gpt-4o-mini`, `gpt-4.1` | Ambiguities |
| Agent Tier 3 (critical) | `gpt-4.1` | `gpt-5-mini`, `gpt-5.2-chat` | Business sensitivity |
| Red Team | `gpt-4.1` | `gpt-5-mini`, `gpt-5.2-chat`, `kimi-k2.5` | Blind spot detection |

### Settings Integration

New fields in `settings_store.py` / `DEFAULT_SETTINGS`:

```python
"agentic": {
    "enabled": False,                          # Feature flag (opt-in)
    "orchestrator_model": "gpt-4.1-nano",      # UI-selectable (or "model-router")
    "orchestrator_routing_mode": "balanced",    # balanced | cost | quality (model-router only)
    "orchestrator_model_subset": [],            # Empty = all models; restrict for cost control
    "agent_tier1_model": "gpt-4.1-nano",       # Simple intents
    "agent_tier2_model": "gpt-4.1-mini",       # Ambiguous intents
    "agent_tier3_model": "gpt-4.1",            # Critical intents
    "red_team_model": "gpt-4.1",               # Quality gate model
    "red_team_threshold": 0.7,                 # Min confidence to skip red team
    "red_team_conflict_delta": 0.15,           # Top-2 delta to trigger red team
    "max_parallel_agents": 6,                  # Max agents in fan-out
    "retrieval_mode": "semantic",              # vector | hybrid | semantic
    "search_top_k": 5,                         # RAG docs per agent query
}
```

## 9. Feature Flag: `strategy = "agentic"`

### Processing Strategy Enum

Current values: `standard | reasoning | vision`

New value: **`agentic`** — activates the multi-agent workflow.

### Backward Compatibility

| Strategy | Pipeline |
|---|---|
| `standard` | Existing `classify_with_phi4()` — single LLM call (Phi-4 primary, gpt-4o-mini fallback) |
| `reasoning` | Existing — step-by-step prompt variant |
| `vision` | Existing — includes image descriptions |
| **`agentic`** | **New** — orchestrator → parallel agents → optional red team |

The `pipeline.py` routing:

```python
if strategy == "agentic":
    classification_raw = await classify_agentic(
        markdown, clients=clients, locale=locale, settings=settings
    )
else:
    classification_raw = await classify_with_phi4(
        markdown, strategy=strategy, clients=clients, locale=locale
    )
```

### UI Integration

The Settings page strategy dropdown adds "Agentic (Multi-Agent)" as a fourth option. When selected, the agentic configuration panel becomes visible with:

- Orchestrator model dropdown
- Agent tier model dropdowns (Tier 1/2/3)
- Red Team model dropdown + threshold sliders
- Per-category AI Search index toggles
- Retrieval mode selector (vector / hybrid / semantic)

## 10. Phased Adoption

### Phase 1 — Prompt + RAG with seeded data (CURRENT)

- Mono-intent agents with fan-out/fan-in via `asyncio.gather`
- Orchestrator with `gpt-4.1-nano` (or model-router)
- Feature flag `strategy = "agentic"` in Settings UI
- Azure AI Search deployed with 5 per-intent indexes
- 35 sample emails seeded (5 positive + 2 negative per category)
- Positive examples: `human_verified`, `human_reinforced`, `llm_classified`
- Negative examples: `human_corrected` with `correction_reason`
- Full OTel span hierarchy implemented
- Red Team quality gate with configurable thresholds
- UI panel for model selection, retrieval mode, thresholds

### Phase 2 — Production feedback loop

- Index real classified emails from Cosmos DB into AI Search
- User corrections in the UI feed back as `human_corrected` negative examples
- User validations feed back as `human_verified` positive examples
- Growing RAG corpus improves accuracy incrementally
- A/B testing: `standard` vs `agentic` on same email set

### Phase 3 — Fine-tuning + optimization

- Cost/precision dashboard comparison
- Fine-tune trigger thresholds based on production data
- Optional: fine-tune specialized models on collected labeled data
- Optional: model-router subset tuning per deployment profile

## 11. Current State

### `main` branch (standard pipeline)

- Single `classify_with_phi4()` in [classymail/services/llm_pipeline.py](classymail/services/llm_pipeline.py)
- Monolithic system prompt with ALL categories in a single call
- Token-budget-based model selection (primary vs. fallback)
- No agent orchestration — 1 LLM call = full classification
- Vector search in Cosmos DB only

### `feature/agentic-classification` branch (implemented)

- **Orchestrator** ([classymail/agents/orchestrator.py](classymail/agents/orchestrator.py)): UI-selectable model (`gpt-4.1-nano`, `model-router`, etc.)
- **Specialized agents** ([classymail/agents/specialized.py](classymail/agents/specialized.py)): Run in parallel via `asyncio.gather`, tier-based model selection
- **RAG grounding** ([classymail/agents/tools/ai_search_tool.py](classymail/agents/tools/ai_search_tool.py)): Per-intent AI Search with positive + negative examples
- **Red Team** ([classymail/agents/red_team.py](classymail/agents/red_team.py)): Conditional quality gate (confidence < 0.7, conflict, no match)
- **Workflow** ([classymail/agents/workflow.py](classymail/agents/workflow.py)): `classify_agentic()` entry point
- **Pipeline routing** ([classymail/services/pipeline.py](classymail/services/pipeline.py)): `strategy="agentic"` dispatches to the agentic workflow
- **Settings** ([classymail/services/settings_store.py](classymail/services/settings_store.py)): Full `agentic` config block with model tiers, thresholds, retrieval mode
- **UI** ([frontend/src/views/SettingsView.vue](frontend/src/views/SettingsView.vue)): Agentic config panel with model dropdowns, sliders, retrieval mode
- **Infra** ([infra/main.tf](infra/main.tf)): AI Search + Model Router + RBAC + `AZURE_SEARCH_ENDPOINT` env var
- **Seed data** ([scripts/seed_ai_search.py](scripts/seed_ai_search.py)): 35 sample emails seeded across 5 indexes
- **Tests** ([tests/test_agentic.py](tests/test_agentic.py)): 21 unit tests

## 12. Implemented File Structure

```text
classymail/
  agents/
    __init__.py              # Package marker
    config.py                # AGENTIC_DEFAULTS, AZURE_SEARCH_ENDPOINT, model resolution
    models.py                # Pydantic contracts: OrchestratorResult, SpecializedAgentResult,
                             #   RedTeamVerdict, AgenticClassificationResult, AgentTrace,
                             #   RAGGroundingRef (with content_snippet, is_positive, correction_reason)
    orchestrator.py          # Router agent — selects top 5-6 candidate intents
    specialized.py           # Mono-intent agent factory — tier-based model, per-intent RAG prompt
    red_team.py              # Quality gate — conditional trigger (low confidence, conflict, no match)
    workflow.py              # classify_agentic() — orchestrator → asyncio.gather → red team → aggregate
    tools/
      __init__.py
      ai_search_tool.py      # Per-intent AI Search retrieval (vector/hybrid/semantic)
                             #   Returns content_snippet + is_positive + correction_reason

scripts/
  seed_ai_search.py          # Deploy AI Search + create indexes + upload 35 sample emails
                             #   (5 positive + 2 negative per category, with embeddings)

tests/
  test_agentic.py            # 21 unit tests (models, config, red team logic, workflow mocks)

infra/
  main.tf                   # + azurerm_search_service + model-router deployment + RBAC
```

## 13. Integration Points

| Component | Integration |
|---|---|
| `pipeline.py` | Routes to `classify_agentic()` when `strategy="agentic"` |
| `settings_store.py` | New `agentic` settings block (models, thresholds, retrieval mode) |
| `repository.py` | Feeds classification history to AI Search indexer |
| `azure_clients.py` | New `SearchIndexClient` in `Clients` (DI pattern) |
| `config.py` | New env vars: `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_ADMIN_KEY` |
| `chat_agent.py` | Reclassify handoff respects `strategy="agentic"` |
| `models.py` | `AgenticClassificationResult` extends `ClassificationResult` with agent traces |
| `SettingsView.vue` | Agentic config panel: model dropdowns, index toggles, retrieval mode |
| `infra/main.tf` | Azure AI Search resource + RBAC for managed identity |

## 14. Decisions Made

| # | Decision | Rationale |
|---|---|---|
| 1 | **Parallel execution** (fan-out/fan-in) | Latency = max(agents) instead of sum(agents) |
| 2 | **Red Team conditional** (threshold-based) | FinOps: avoid calling robust model on every email |
| 3 | **Custom routing** via `WorkflowBuilder` | More control than GroupChat/Magentic, matches the "select top-N intents" pattern |
| 4 | **Feature flag** (`strategy="agentic"`) | Backward compatible — existing pipeline untouched |
| 5 | **Phi-4 NOT default orchestrator** | Phi-4 excels at deep classification, not fast routing; `gpt-4.1-nano` is 10x faster |
| 6 | **Dedicated AI Search** (not Cosmos vector) | Per-intent indexes with semantic ranking > Cosmos VectorDistance; human-reinforced labels need structured indexing |
| 7 | **UI-selectable models** per role | Different deployments need different cost/quality tradeoffs |
| 8 | **AzureOpenAIResponsesClient** (not AzureAIAgent) | Lightweight, no server-side lifecycle — recommended by Agent Framework for orchestrations |
| 9 | **Model Router as orchestrator option** | Built-in FinOps optimization — router auto-selects cheapest model within quality band per prompt |
| 10 | **Positive + negative RAG examples** | Negative examples with correction reasons teach agents what NOT to match — reducing false positives |
| 11 | **Seeded per-intent indexes** | 35 sample emails (5 positive + 2 negative per category) provide immediate RAG grounding from day one |

## 15. Deployed Resources (email-poc-rg, swedencentral)

| Resource | Name | SKU | Details |
|---|---|---|---|
| Azure AI Search | `email-poc-search` | Basic + Semantic Standard | 5 per-intent indexes, 35 documents |
| Model Router | `model-router` on `email-poc-aifoundry` | GlobalStandard 125K TPM | v2025-11-18, 18 underlying models |

### Seeded Indexes

| Index | Positive | Negative | Total |
|---|---|---|---|
| `classymail-intent-billing-inquiry` | 5 (invoice, refund, payment plan, balance, dispute) | 2 (password reset, address change) | 7 |
| `classymail-intent-technical-support` | 5 (app crash, printer, API error, CSV bug, mobile freeze) | 2 (invoice request, feedback) | 7 |
| `classymail-intent-account-management` | 5 (closure, upgrade, contact change, registration, 2FA) | 2 (charge question, UI bug) | 7 |
| `classymail-intent-document-request` | 5 (COI, tax statement, employment letter, attestation, audit docs) | 2 (cancellation, download error) | 7 |
| `classymail-intent-general-inquiry` | 5 (roadmap, feedback, partnership, privacy, referral) | 2 (hacked account, annual statement) | 7 |
