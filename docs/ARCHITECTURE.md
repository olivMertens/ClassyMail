# Architecture

## Overview

[![ClassyMail architecture](assets/classymail-architecture.png)](assets/classymail-architecture.svg)

Editable source: [classymail-architecture.drawio](assets/classymail-architecture.drawio).
The asset includes optional components and a separately marked roadmap; it is not an
inventory of a live subscription. Maintain the source and both exports together using
the repository's architecture-diagram-author skill and CAE flat icons.

## Runtime Flow

1. `POST /api/upload` validates PDFs and writes them to Blob Storage. The current
   [upload route](../classymail/api/routers/upload.py) does not directly create the email
   record or send a Service Bus message.
2. Event Grid BlobCreated delivery sends the blob URL toward the Service Bus queue.
   The [webhook adapter](../classymail/api/routers/webhook.py) can also handle Event Grid
   event batches at `/webhook/ingest`; it is not a generic email-ingestion API.
3. The [worker](../classymail/services/worker.py) consumes queue messages and runs the
   [processing pipeline](../classymail/services/pipeline.py).
4. OCR extracts Markdown using the selected provider. A configured standalone Document
   Intelligence endpoint provides fallback. Classification uses standard, reasoning,
   vision or [agentic](AGENTIC_CLASSIFICATION.md) behavior according to settings.
5. Records, classification metadata and usage are stored in Cosmos DB. The Vue UI queries
   the API for results, review and export. Chat retrieves context and keeps history/cache
   through application repository functions.

## Ownership

| Area | Source |
| --- | --- |
| FastAPI assembly and lifespan | [#classymail/app.py](../classymail/app.py) |
| Azure client lifecycle and DI | [#classymail/services/azure_clients.py](../classymail/services/azure_clients.py) |
| Queue worker entry point | [#classymail/worker_main.py](../classymail/worker_main.py) |
| Processing and OCR/model calls | [#classymail/services/pipeline.py](../classymail/services/pipeline.py), [llm_pipeline.py](../classymail/services/llm_pipeline.py) |
| Cosmos persistence and exports | [#classymail/services/repository.py](../classymail/services/repository.py) |
| Chat tools/history integration | [#classymail/services/chat_agent.py](../classymail/services/chat_agent.py) |
| Infrastructure and identity | [#infra/main.tf](../infra/main.tf) |
| Runtime defaults | [#classymail/core/config.py](../classymail/core/config.py), [settings_store.py](../classymail/services/settings_store.py) |

API and worker use one container image with different entry points. KEDA scales the
worker from Service Bus queue demand. Local integrated-worker mode is a development
convenience, not the two-app deployment topology.

## Implemented Versus Proposed

Microsoft Agent Framework is used by the chat implementation. Classification fan-out
is application-controlled `asyncio.gather`, not a migration to `ConcurrentBuilder`.
Chat history is persisted through the application's repository, not
`CosmosHistoryProvider`. Old migration proposals are not setup requirements.

Content Understanding is an implemented opt-in OCR provider; default selection remains
Mistral. The architecture asset's separately labeled preview roadmap is not implemented
by virtue of appearing in that image. Exact model aliases and feature flags are in
[models](MODELS.md), not frozen into a claimed live resource list.

## Security And Observability

Azure clients support identity-based access; optional key paths also exist. Prefer
managed identity in Azure and inspect actual RBAC/network configuration before assuming
resources are private. The presence of PII detection, prompts or telemetry does not
establish compliance or eliminate prompt-injection risk.

OpenTelemetry initialization is in [telemetry.py](../classymail/core/telemetry.py).
API and worker traces help identify queue, OCR and model latency; sensitive payload
capture and retention require review. See [deployment](DEPLOY_FROM_SCRATCH.md) for
identity/configuration and [data and privacy](PII_ANONYMIZATION_AND_USER_CORRECTIONS.md)
for export limitations.
