# Agentic Classification And Retrieval

## Implemented Workflow

Select the `agentic` processing strategy in Settings. The canonical workflow is
[#classymail/agents/workflow.py](../classymail/agents/workflow.py):

1. The orchestrator selects candidate intents.
2. Specialized per-intent agents run concurrently through `asyncio.gather`.
3. Aggregation collects matches and failures. Failed agents produce non-matching
   placeholders rather than silently disappearing from the trace.
4. The Red Team conditionally reviews the result and can request additional agents or
   refine confidence. Its verdict contributes to the review decision.
5. The final output uses the application's classification schema and agent trace.

Human review is required for no matches, weak matched labels, failed agents or an
unvalidated Red Team verdict. A strong label does not erase a weak one. These are
guardrails, not proof of classification correctness.

Owners: [orchestrator.py](../classymail/agents/orchestrator.py),
[specialized.py](../classymail/agents/specialized.py),
[red_team.py](../classymail/agents/red_team.py),
[models.py](../classymail/agents/models.py). The UI trace is displayed by
[EmailDetailModal.vue](../frontend/src/components/EmailDetailModal.vue).

![Agentic settings](assets/setttingsagenticpipeline.png)
![Agentic trace](assets/spotlightmermaidagentic.png)

These captures use the local frontend bundle and synthetic fixtures, with model
selections checked against repository defaults. Scores, timings, and retrieval
results are illustrative, not live Azure measurements.

## Settings

Defaults are in [#classymail/agents/config.py](../classymail/agents/config.py) and
[settings_store.py](../classymail/services/settings_store.py). Saved values override
defaults; new model aliases do not automatically migrate old saved settings.

| Setting | Default |
| --- | --- |
| Orchestrator / tier 1 | `gpt-6-luna` |
| Tier 2 | `gpt-5.4-mini` |
| Tier 3 / Red Team | `gpt-6-sol` |
| `max_parallel_agents` | 6 |
| `red_team_threshold` | 0.7 |
| `red_team_conflict_delta` | 0.15 |
| `retrieval_mode` | `semantic` |
| `search_top_k` | 5 |
| `reasoning_effort` | `none` |
| `enabled_indexes` | Empty map: all categories enabled |

The orchestrator also supports `model-router` configuration. Check deployment support
and permissions for your endpoint before selecting it. Deployment resolution and
reasoning-parameter handling are described in [models](MODELS.md).

## Per-Category AI Search

Each category uses an index named `classymail-intent-{slug}`. Specialized agents retrieve
positive and negative text examples to ground decisions. AI Search is distinct from the
Cosmos vector retrieval used by chat. Configure `AZURE_SEARCH_ENDPOINT` and the identity's
search access; an admin key is an optional code path, not required when identity works.

| Method | Route |
| --- | --- |
| GET | `/api/admin/ai-search/indexes` |
| POST | `/api/admin/ai-search/indexes/ensure` |
| POST | `/api/admin/ai-search/indexes/ensure-all` |
| DELETE | `/api/admin/ai-search/indexes/{slug}` |
| GET / POST | `/api/admin/ai-search/indexes/{slug}/examples` |
| DELETE | `/api/admin/ai-search/indexes/{slug}/examples/{doc_id}` |

Use Settings to manage indexes/examples, or consult request schemas in `/openapi.json`.
Example records include `content`, `is_positive`, `label_source` and optional
`correction_reason`. Submit readable text or OCR Markdown, not PDF bytes.

Sources: [ai_search_index.py](../classymail/agents/tools/ai_search_index.py),
[ai_search_tool.py](../classymail/agents/tools/ai_search_tool.py),
[admin routes](../classymail/api/routers/admin/ai_search.py).

Ensuring an existing index is intended to preserve it; it is not a schema migration.
Adding examples can create duplicates. The [seed script](../scripts/seed_ai_search.py)
can populate sample data but writes to configured indexes and calls embedding services;
inspect its taxonomy and endpoint before running it.

Corrections/reinforcement populate reference examples, not model weights. Poor labels or
sensitive examples can harm results or expose data. Validate on held-out reviewed emails
before treating a retrieval update as an improvement. See
[integration](INTEGRATION.md#feedback-and-retrieval) and
[privacy](PII_ANONYMIZATION_AND_USER_CORRECTIONS.md).

## Validation And Boundaries

Regression tests live in [test_agentic.py](../tests/test_agentic.py). The workflow remains
application-managed; MAF orchestration and Cosmos history-provider migration are not
implemented setup steps. Do not enable flags or install dependencies from an old migration
proposal expecting an existing code path.
