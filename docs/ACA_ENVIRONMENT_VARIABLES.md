# Azure Container Apps Environment Variables



This document lists all environment variables required for the ClassyMail API and Worker containers running in Azure Container Apps (ACA).



## Mandatory Variables



These variables **must** be configured for the application to function correctly:



### Azure Identity & Authentication



- **`AZURE_CLIENT_ID`** - The client ID of the user-assigned managed identity used for Azure service authentication

  - Example: `00000000-0000-0000-0000-000000000000`

  - Used for: Authenticating to all Azure services (Storage, Cosmos DB, Service Bus, AI Foundry, etc.)



### Cosmos DB



- **`AZURE_COSMOS_ENDPOINT`** - The endpoint URL for Azure Cosmos DB

  - Example: `https://<prefix>-cosmos-swedencentral.documents.azure.com:443/`

  - Used for: Storing email records, chat history, and metadata



- **`AZURE_COSMOS_DB`** - The name of the Cosmos DB database

  - Example: `emailsdb`

  - Used for: Specifying which database to use



- **`AZURE_COSMOS_CONTAINER`** - The name of the main container for email records

  - Example: `emails`

  - Used for: Storing classification results



- **`AZURE_COSMOS_CHAT_CONTAINER`** - The name of the container for chat history

  - Example: `chat_history`

  - Used for: RAG chat functionality with vector search



### Azure Storage



- **`AZURE_STORAGE_ACCOUNT_URL`** - The blob endpoint URL for the Azure Storage account

  - Example: `https://<prefix>stoswedenc.blob.core.windows.net/`

  - Used for: Storing PDF files and embeddings



- **`AZURE_STORAGE_CONTAINER`** - The name of the blob container for PDF files

  - Example: `pdf-inputs`

  - Used for: Storing uploaded PDF documents



### Service Bus



- **`AZURE_SERVICE_BUS_FQDN`** - The fully qualified domain name of the Service Bus namespace

  - Example: `<prefix>-sb-swedencentral.servicebus.windows.net`

  - Used for: Queue-based communication between API and Worker



- **`AZURE_SERVICE_BUS_QUEUE`** - The name of the Service Bus queue for PDF processing

  - Example: `pdf-processing-queue`

  - Used for: Asynchronous PDF processing workflow



### Microsoft AI Foundry



- **`AZURE_AI_ENDPOINT`** - The endpoint URL for Microsoft AI Foundry (OpenAI models)

  - Example: `https://classymail-aifoundry.cognitiveservices.azure.com/`

  - Used for: Accessing GPT, Phi-4, and Mistral models

  - Rating: `PHI_ENDPOINT` and `MISTRAL_ENDPOINT` fall back to this value if not set



- **`AZURE_AI_API_VERSION`** - The API version for Microsoft AI Foundry

  - Example: `2024-08-01-preview`

  - Used for: API compatibility



- **`PHI_DEPLOYMENT`** - The deployment name for Phi-4 model

  - Example: `phi-4-document-classification`

  - Used for: Primary classification model



- **`PHI_FALLBACK_DEPLOYMENT`** - The deployment name for fallback Phi-4 model

  - Example: `phi-4-generic`

  - Used for: Fallback when primary deployment is unavailable



- **`MISTRAL_DEPLOYMENT`** - The deployment name for Mistral OCR model

  - Example: `mistral-document-ai-2512`

  - Used for: OCR and document understanding

  - ⚠️ **CRITICAL:** Must be EXACTLY `mistral-document-ai-2512` — typos (e.g., `mistral-ocr-2505`) cause HTTP 500 errors during OCR processing. Verify in Microsoft AI Foundry → Deployments.



- **`MISTRAL_MODE`** - The deployment mode for Mistral (serverless MaaS)

  - Example: `maas`

  - Used for: Specifying deployment type



### Telemetry



- **`APPLICATIONINSIGHTS_CONNECTION_STRING`** - The connection string for Apply Insights

  - Example: `InstrumentationKey=...;IngestionEndpoint=...`

  - Used for: Telemetry, logging, and monitoring



- **`LOG_ANALYTICS_WORKSPACE_ID`** - The workspace ID for Log Analytics

  - Example: `12345678-1234-1234-1234-123456789012`

  - Used for: Advanced log querying



- **`OTEL_SERVICE_NAME`** - The service name for OpenTelemetry

  - Example: `classymail-api` or `classymail-worker`

  - Used for: Service identification in telemetry



## Optional Variables



These variables provide additional functionality but are not required for core operations:



### Azure AI Language (PII Detection)



- **`AZURE_LANGUAGE_ENDPOINT`** - The endpoint URL for Azure AI Language service

  - Example: `https://swedencentral.api.cognitive.microsoft.com/`

  - Used for: Optional Azure AI Language PII detection (alternative to LLM-based PII)

  - Rating: If not configured, PII detection falls back to LLM-based methods



### Azure Document Intelligence (OCR Fallback)



- **`AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT`** - The endpoint URL for Azure Document Intelligence

  - Example: `https://classymail-doc-intelligence.cognitiveservices.azure.com/`

  - Used for: OCR fallback when Mistral OCR fails (timeout, quota, circuit breaker)

  - Rating: If not configured, OCR failures raise `OCRFailed` without fallback. Requires `deploy_document_intelligence=true` in Terraform.

- **`DOC_INTELLIGENCE_API_VERSION`** - API version for Document Intelligence REST API

  - Default: `2024-11-30`



### Azure AI Content Understanding (Opt-in OCR Provider — PoC, default-off)



- **`OCR_PROVIDER`** - Selects the primary OCR provider

  - Default: `mistral` (current behavior; Document Intelligence fallback unchanged)

  - Set to `content_understanding` to route the primary OCR pass through Azure AI Content Understanding

- **`CONTENT_UNDERSTANDING_ENDPOINT`** - Endpoint URL for the Content Understanding (Foundry) resource

  - Example: `https://classymail-foundry.cognitiveservices.azure.com/`

  - Used for: opt-in OCR via async analyze + poll → Markdown. Only read when `OCR_PROVIDER=content_understanding`.

- **`CONTENT_UNDERSTANDING_ANALYZER_ID`** - Prebuilt or custom analyzer id

  - Default: `prebuilt-documentSearch` (RAG-optimized markdown extraction)

- **`CONTENT_UNDERSTANDING_API_VERSION`** - API version for the Content Understanding REST API

  - Default: `2025-11-01`

- **`CONTENT_UNDERSTANDING_KEY`** - Optional key-based auth (Managed Identity preferred)



### Chat & RAG



- **`CHAT_DEPLOYMENT`** - The deployment name for the chat model

  - Example: `gpt-5.2-chat`

  - Used for: RAG-based chat interface

  - Fallback: Uses `PHI_FALLBACK_DEPLOYMENT` if not configured



- **`CHAT_API_VERSION`** - API version for the chat agent (RAG assistant)

  - Example: `preview` (default)

  - Used for: The chat agent talks to the Azure OpenAI **v1 surface** (`{endpoint}/openai/v1/`) via `agent_framework`'s `OpenAIChatClient`. This surface only accepts the literal value `preview` (or `v1`). Dated versions such as `2024-08-01-preview` return `400 "API version not supported"`.

  - Note: Keep this **independent** from `AZURE_AI_API_VERSION` (`2024-08-01-preview`), which is used by the deployment-based clients (embeddings, Phi, vision) on the classic surface. Do not set `CHAT_API_VERSION` to a dated version.



- **`CHAT_STREAMING`** - Opt-in token-by-token streaming for the RAG chat assistant (SSE)

  - Example: `false` (default)

  - Values: `true` / `false` (parsed as `os.getenv("CHAT_STREAMING", "false").lower() == "true"`)

  - Used for: When `true`, the frontend calls `POST /api/chat/stream` and renders the answer incrementally via Server-Sent Events for lower perceived latency. When `false` (default), the UI uses the single-shot `POST /api/chat` JSON response — byte-for-byte the current behavior.

  - Note: Exposed through `/api/admin/ui-config` as `chat_streaming`; the streaming endpoint always exists but the frontend only uses it when the flag is on. Both paths share the same grounding, chat history, and semantic cache, so cached answers stay consistent across endpoints.



- **`CHAT_REASONING_EFFORT`** - Opt-in reasoning effort for the chat agent (Agent Framework 1.9)

  - Example: `` (empty = **off**, default) · valid: `minimal` \| `low` \| `medium` \| `high`

  - Used for: When set, forwarded to `agent.run(options={"reasoning": {"effort": ...}})` via `OpenAIChatOptions.reasoning`. Only meaningful for reasoning-capable deployments; invalid values are ignored (logged) rather than sent. Empty keeps the current behavior unchanged.



- **`CHAT_HISTORY_COMPACTION`** - Opt-in token-aware chat-history compaction (Agent Framework 1.9)

  - Example: `false` (default) · set `true` to enable

  - Used for: When `true`, the full chat history is fed to the agent and the framework's `ContextWindowCompactionStrategy` trims it to a token budget using the built-in `CharacterEstimatorTokenizer` (no extra dependency). When `false`, the legacy fixed last-10-turns window is used.



- **`CHAT_COMPACTION_MAX_TOKENS`** - Context-window token budget for history compaction

  - Example: `12000` (default)

  - Used for: `max_context_window_tokens` passed to `ContextWindowCompactionStrategy`. Only read when `CHAT_HISTORY_COMPACTION=true`.



- **`CHAT_COMPACTION_MAX_OUTPUT_TOKENS`** - Reserved output-token budget for history compaction

  - Example: `2000` (default)

  - Used for: `max_output_tokens` passed to `ContextWindowCompactionStrategy`. Only read when `CHAT_HISTORY_COMPACTION=true`.



- **`GPT_DEPLOYMENT`** - The deployment name for GPT models

  - Example: `gpt-5.2`

  - Used for: Advanced GPT-based classification

  - Fallback: Uses `PHI_FALLBACK_DEPLOYMENT` if not configured



- **`OCR_DEPLOYMENT`** - The deployment name for OCR-specific model

  - Example: `mistral-document-ai-2512`

  - Used for: OCR fallback

  - Fallback: Uses `MISTRAL_DEPLOYMENT` if not configured



### UI Features



- **`UI_SHOW_INFO_MODAL`** - Show information modal on first visit

  - Example: `true` or `false`

  - Default: `true`



- **`UI_SHOW_DEVELOPER_TAB`** - Show developer options in Settings

  - Example: `true` or `false`

  - Default: `true`



- **`ORGANIZATION_NAME`** - Organization name displayed in UI

  - Example: `My Company`

  - Default: `ClassyMail`

  - Rating: tagged deployments set this to `ClassyMail` (see [CUSTOMIZATION.md](CUSTOMIZATION.md))



## Validation Scripts



### PowerShell



```powershell

# validate-aca-env.ps1

$required = @(

    "AZURE_CLIENT_ID",

    "AZURE_COSMOS_ENDPOINT",

    "AZURE_COSMOS_DB",

    "AZURE_COSMOS_CONTAINER",

    "AZURE_COSMOS_CHAT_CONTAINER",

    "AZURE_STORAGE_ACCOUNT_URL",

    "AZURE_STORAGE_CONTAINER",

    "AZURE_SERVICE_BUS_FQDN",

    "AZURE_SERVICE_BUS_QUEUE",

    "AZURE_AI_ENDPOINT",

    "AZURE_AI_API_VERSION",

    "PHI_DEPLOYMENT",

    "PHI_FALLBACK_DEPLOYMENT",

    "MISTRAL_DEPLOYMENT",

    "MISTRAL_MODE",

    "APPLICATIONINSIGHTS_CONNECTION_STRING",

    "LOG_ANALYTICS_WORKSPACE_ID",

    "OTEL_SERVICE_NAME"

)



$optional = @(

    "AZURE_LANGUAGE_ENDPOINT",

    "CHAT_DEPLOYMENT",

    "GPT_DEPLOYMENT",

    "OCR_DEPLOYMENT",

    "UI_SHOW_INFO_MODAL",

    "UI_SHOW_DEVELOPER_TAB",

    "ORGANIZATION_NAME"

)



Write-Host "=== Required Variables ===" -ForegroundColor Cyan

$missing = @()

foreach ($var in $required) {

    if (Test-Path env:$var) {

        $value = (Get-Item env:$var).Value

        $masked = if ($value.Length -gt 20) { $value.Substring(0, 20) + "..." } else { $value }

        Write-Host "✓ $var = $masked" -ForegroundColor Green

    } else {

        Write-Host "✗ $var = <NOT SET>" -ForegroundColor Red

        $missing += $var

    }

}



Write-Host "`n=== Optional Variables ===" -ForegroundColor Cyan

foreach ($var in $optional) {

    if (Test-Path env:$var) {

        $value = (Get-Item env:$var).Value

        $masked = if ($value.Length -gt 20) { $value.Substring(0, 20) + "..." } else { $value }

        Write-Host "○ $var = $masked" -ForegroundColor Yellow

    } else {

        Write-Host "○ $var = <not configured>" -ForegroundColor Gray

    }

}



if ($missing.Count -gt 0) {

    Write-Host "`n✗ VALIDATION FAILED: Missing $($missing.Count) required variable(s)" -ForegroundColor Red

    Write-Host "Missing: $($missing -join ', ')" -ForegroundColor Red

    exit 1

} else {

    Write-Host "`n✓ VALIDATION PASSED: All required variables are set" -ForegroundColor Green

    exit 0

}

```



### Bash



```bash

#!/bin/bash

# validate-aca-env.sh



required=(

    "AZURE_CLIENT_ID"

    "AZURE_COSMOS_ENDPOINT"

    "AZURE_COSMOS_DB"

    "AZURE_COSMOS_CONTAINER"

    "AZURE_COSMOS_CHAT_CONTAINER"

    "AZURE_STORAGE_ACCOUNT_URL"

    "AZURE_STORAGE_CONTAINER"

    "AZURE_SERVICE_BUS_FQDN"

    "AZURE_SERVICE_BUS_QUEUE"

    "AZURE_AI_ENDPOINT"

    "AZURE_AI_API_VERSION"

    "PHI_DEPLOYMENT"

    "PHI_FALLBACK_DEPLOYMENT"

    "MISTRAL_DEPLOYMENT"

    "MISTRAL_MODE"

    "APPLICATIONINSIGHTS_CONNECTION_STRING"

    "LOG_ANALYTICS_WORKSPACE_ID"

    "OTEL_SERVICE_NAME"

)



optional=(

    "AZURE_LANGUAGE_ENDPOINT"

    "CHAT_DEPLOYMENT"

    "GPT_DEPLOYMENT"

    "OCR_DEPLOYMENT"

    "UI_SHOW_INFO_MODAL"

    "UI_SHOW_DEVELOPER_TAB"

    "ORGANIZATION_NAME"

)



echo "=== Required Variables ==="

missing=()

for var in "${required[@]}"; do

    if [ -n "${!var}" ]; then

        value="${!var}"

        masked="${value:0:20}..."

        echo "✓ $var = $masked"

    else

        echo "✗ $var = <NOT SET>"

        missing+=("$var")

    fi

done



echo ""

echo "=== Optional Variables ==="

for var in "${optional[@]}"; do

    if [ -n "${!var}" ]; then

        value="${!var}"

        masked="${value:0:20}..."

        echo "○ $var = $masked"

    else

        echo "○ $var = <not configured>"

    fi

done



if [ ${#missing[@]} -gt 0 ]; then

    echo ""

    echo "✗ VALIDATION FAILED: Missing ${#missing[@]} required variable(s)"

    echo "Missing: ${missing[*]}"

    exit 1

else

    echo ""

    echo "✓ VALIDATION PASSED: All required variables are set"

    exit 0

fi

```



## Terraform Configuration



All environment variables are automatically configured in Terraform ([infra/main.tf](../infra/main.tf)):



- **API Container**: Lines 570-660

- **Worker Container**: Lines 770-820



## Deployment Verification



After deploying with Terraform, verify environment variables are set correctly:



```bash

# API Container (replace <prefix> with your deployment prefix, e.g. classymail)

az containerapp show \

  --name <prefix>-api \

  --resource-group <prefix>-rg \

  --query "properties.template.containers[0].env" \

  -o table



# Worker Container

az containerapp show \

  --name <prefix>-worker \

  --resource-group <prefix>-rg \

  --query "properties.template.containers[0].env" \

  -o table

```



## Troubleshooting



### Common Issues



1. **Cosmos DB Connection Failed**

   - Verify `AZURE_COSMOS_ENDPOINT` is correct

   - Ensure managed identity has **Custom App Role** (`readMetadata` + CRUD) at Account scope (or built-in `Data Contributor` as fallback)

   - Check `AZURE_COSMOS_DB` and `AZURE_COSMOS_CONTAINER` exist



2. **Service Bus Connection Failed**

   - Verify `AZURE_SERVICE_BUS_FQDN` format (must end with `.servicebus.windows.net`)

   - Ensure managed identity has the `Azure Service Bus Data Owner` role

   - Check `AZURE_SERVICE_BUS_QUEUE` exists in Service Bus namespace



3. **AI Model Connection Failed**

   - Verify `AZURE_AI_ENDPOINT` is correct

   - Ensure deployment names (`PHI_DEPLOYMENT`, `MISTRAL_DEPLOYMENT`) match Microsoft AI Foundry deployments

   - Check managed identity has `Cognitive Services User` role



4. **Language Service Not Available**

   - This is optional - check if `AZURE_LANGUAGE_ENDPOINT` is configured

   - If configured, ensure managed identity has `Cognitive Services Language Reader` role

   - PII detection will fall back to LLM-based methods if not available



## Related Documentation



- [Infrastructure Overview](INFRASTRUCTURE.md)

- [Architecture Diagrams](ARCHITECTURE.md)

- [Local Development Setup](LOCAL_DEVELOPMENT.md)

- [RBAC Audit](RBAC_AUDIT.md)
