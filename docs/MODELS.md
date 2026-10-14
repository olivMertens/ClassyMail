# Models, OCR And Chat Configuration

## Deployment Aliases

The names below are repository defaults, not proof of service availability or pricing.
Use actual deployment aliases for the configured endpoint, including case. Saved settings
and deployed environment variables can retain older selections.

| Role | Repository default |
| --- | --- |
| Standard classification | `phi-4` in Python/settings; Terraform provisions the `Phi-4` alias |
| Long-context fallback | `gpt-5.4-mini` |
| Category assessment | `gpt-6-luna` |
| Agentic orchestrator / tier 1 | `gpt-6-luna` |
| Agentic tier 2 | `gpt-5.4-mini` |
| Agentic tier 3 / Red Team | `gpt-6-sol` |
| Anonymization / vision | `gpt-5.4-mini` |
| Chat | `gpt-6-sol` |
| Embeddings | `text-embedding-3-small` |
| Mistral OCR | `mistral-document-ai-2512` |

Owners: [#classymail/core/config.py](../classymail/core/config.py),
[settings_store.py](../classymail/services/settings_store.py),
[agents/config.py](../classymail/agents/config.py) and
[#infra/main.tf](../infra/main.tf). Check Terraform's deployment flags and SKU/capacity
before applying. Existing GPT-4.1/GPT-5.1 configurations are supported as legacy selections;
the code does not establish retirement dates or continued regional availability.

`PHI_ENDPOINT` defaults to `AZURE_AI_ENDPOINT`. Fallback, anonymizer, embedding, vision
and chat endpoints default to the primary endpoint unless separately configured.
`PHI_DEPLOYMENT` and `PHI_FALLBACK_DEPLOYMENT` control the corresponding deployments.
Context budgets are configurable through `PHI_PRIMARY_MAX_INPUT_TOKENS`,
`PHI_FALLBACK_MAX_INPUT_TOKENS` and `PHI_RESERVED_OUTPUT_TOKENS`; they are application
limits, not authoritative model context-window specifications.

## Client Compatibility

[openai_client_factory.py](../classymail/services/openai_client_factory.py) owns client
selection and compatible chat parameters. Reasoning-capable models do not necessarily
accept the same temperature, token-limit or reasoning-effort options as other models.
Do not assume that every GPT-family deployment supports `reasoning_effort=none`.

[llm_pipeline.py](../classymail/services/llm_pipeline.py) resolves model selections and
classification calls. UI discovery comes from `/api/admin/deployments`; verify the
actual deployment, credentials and API surface when an alias fails.

## OCR And Processing Strategies

`ocr_provider=mistral` is the default. `content_understanding` selects the implemented
opt-in Azure AI Content Understanding provider and requires
`CONTENT_UNDERSTANDING_ENDPOINT`. Its analyzer/API settings are
`CONTENT_UNDERSTANDING_ANALYZER_ID` and `CONTENT_UNDERSTANDING_API_VERSION`.

Document Intelligence is the fallback when configured through
`AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT`. Use a standalone Document Intelligence resource;
do not assume a generic Foundry endpoint serves its REST API. Terraform's
`deploy_document_intelligence` flag provisions the optional resource and injects its
endpoint. `DOC_INTELLIGENCE_API_VERSION` defaults to `2024-11-30`.

OCR outputs Markdown for classification. Provider selection is separate from processing
strategy: `standard`, `reasoning`, `vision` and `agentic` choose classification behavior.
Vision is implemented, not a placeholder; image conversion and extra calls can change
latency and costs. Measure representative PDFs rather than treating old timing estimates
or fixed token multipliers as benchmarks.

Owners: [pipeline.py](../classymail/services/pipeline.py),
[llm_pipeline.py](../classymail/services/llm_pipeline.py) (including Content Understanding).
Provider behavior is covered by the OCR tests in [tests](../tests).

## Chat And Optional Features

[chat_agent.py](../classymail/services/chat_agent.py) uses Microsoft Agent Framework with
the Azure OpenAI v1 surface. Set `CHAT_API_VERSION=preview`, independently of the dated
`AZURE_AI_API_VERSION` used by deployment-based clients. Configure `CHAT_ENDPOINT` and
`CHAT_DEPLOYMENT` as needed.

| Variable | Behavior |
| --- | --- |
| `CHAT_STREAMING` | Default false; enables the frontend SSE path `/api/chat/stream` |
| `CHAT_REASONING_EFFORT` | Empty by default; optional effort for compatible deployments |
| `CHAT_HISTORY_COMPACTION` | Default false; enables token-budget history compaction |
| `CHAT_COMPACTION_MAX_TOKENS` | Default 12000 |
| `CHAT_COMPACTION_MAX_OUTPUT_TOKENS` | Default 2000 |

Single-response chat uses `POST /api/chat`. Chat history and semantic cache use the
application repository; they are not a `CosmosHistoryProvider` migration.
Streaming tests are in [test_chat_streaming.py](../tests/test_chat_streaming.py).

## Availability And Training

Consult the current service catalog for your subscription and region before creating
deployments or scheduling fine-tuning. Model discovery, deployment availability,
invocation permission and fine-tuning eligibility are different checks. This guide does
not promise that the default aliases are deployable everywhere.

Training-data preparation belongs in
[data and privacy](PII_ANONYMIZATION_AND_USER_CORRECTIONS.md); price assumptions and
their limitations belong in [costs](COSTS_LOGIC.md).
