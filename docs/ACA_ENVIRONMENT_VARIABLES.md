# Azure Container Apps Environment Variables

This document lists all environment variables required for the ClassyMail API and Worker containers running in Azure Container Apps (ACA).

## Mandatory Variables

These variables **must** be configured for the application to function correctly:

### Azure Identity & Authentication

- **`AZURE_CLIENT_ID`** - The client ID of the user-assigned managed identity used for Azure service authentication
  - Example: `fdf02fa5-2cd5-42f9-9b78-5cb7905d94d0`
  - Used for: Authenticating to all Azure services (Storage, Cosmos DB, Service Bus, AI Foundry, etc.)

### Cosmos DB

- **`COSMOS_ENDPOINT`** - The endpoint URL for Azure Cosmos DB
  - Example: `https://email-poc-cosmos-swedencentral.documents.azure.com:443/`
  - Used for: Storing email records, chat history, and metadata

- **`COSMOS_DATABASE_NAME`** - The name of the Cosmos DB database
  - Example: `EmailClassificationDB`
  - Used for: Specifying which database to use

- **`COSMOS_CONTAINER_NAME`** - The name of the main container for email records
  - Example: `emails_classified`
  - Used for: Storing classification results

- **`COSMOS_CHAT_CONTAINER`** - The name of the container for chat history
  - Example: `chat_history`
  - Used for: RAG chat functionality with vector search

### Azure Storage

- **`STORAGE_ACCOUNT_NAME`** - The name of the Azure Storage account (Blob Storage)
  - Example: `emailpocstoswedenc`
  - Used for: Storing PDF files and embeddings

- **`CONTAINER_NAME_PDF`** - The name of the blob container for PDF files
  - Example: `pdfs`
  - Used for: Storing uploaded PDF documents

### Service Bus

- **`SERVICE_BUS_FQDN`** - The fully qualified domain name of the Service Bus namespace
  - Example: `email-poc-sb-swedencentral.servicebus.windows.net`
  - Used for: Queue-based communication between API and Worker

- **`QUEUE_NAME_PDF`** - The name of the Service Bus queue for PDF processing
  - Example: `pdf-emails`
  - Used for: Asynchronous PDF processing workflow

### Azure AI Foundry

- **`AI_ENDPOINT`** - The endpoint URL for Azure AI Foundry (OpenAI models)
  - Example: `https://swedencentral.api.cognitive.microsoft.com/`
  - Used for: Accessing GPT, Phi-4, and Mistral models

- **`AI_API_VERSION`** - The API version for Azure AI Foundry
  - Example: `2024-08-01-preview`
  - Used for: API compatibility

- **`PHI_DEPLOYMENT`** - The deployment name for Phi-4 model
  - Example: `phi-4-document-classification`
  - Used for: Primary classification model

- **`PHI_FALLBACK_DEPLOYMENT`** - The deployment name for fallback Phi-4 model
  - Example: `phi-4-generic`
  - Used for: Fallback when primary deployment is unavailable

- **`MISTRAL_DEPLOYMENT`** - The deployment name for Mistral OCR model
  - Example: `mistral-document-ai-2505`
  - Used for: OCR and document understanding
  - ⚠️ **CRITICAL:** Must be EXACTLY `mistral-document-ai-2505` — typos (e.g., `mistral-ocr-2505`) cause HTTP 500 errors during OCR processing. Verify in Azure AI Foundry → Deployments.

- **`MISTRAL_MODE`** - The deployment mode for Mistral (serverless MaaS)
  - Example: `maas`
  - Used for: Specifying deployment type

### Telemetry

- **`APPLICATIONINSIGHTS_CONNECTION_STRING`** - The connection string for Application Insights
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
  - Note: If not configured, PII detection falls back to LLM-based methods

### Chat & RAG

- **`CHAT_DEPLOYMENT`** - The deployment name for the chat model
  - Example: `gpt-5.2-chat`
  - Used for: RAG-based chat interface
  - Fallback: Uses `PHI_FALLBACK_DEPLOYMENT` if not configured

- **`GPT_DEPLOYMENT`** - The deployment name for GPT models
  - Example: `gpt-5.2`
  - Used for: Advanced GPT-based classification
  - Fallback: Uses `PHI_FALLBACK_DEPLOYMENT` if not configured

- **`OCR_DEPLOYMENT`** - The deployment name for OCR-specific model
  - Example: `mistral-document-ai-2505`
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
  - Example: `G2S Insurance`
  - Default: `ClassyMail`

## Validation Scripts

### PowerShell

```powershell
# validate-aca-env.ps1
$required = @(
    "AZURE_CLIENT_ID",
    "COSMOS_ENDPOINT",
    "COSMOS_DATABASE_NAME",
    "COSMOS_CONTAINER_NAME",
    "COSMOS_CHAT_CONTAINER",
    "STORAGE_ACCOUNT_NAME",
    "CONTAINER_NAME_PDF",
    "SERVICE_BUS_FQDN",
    "QUEUE_NAME_PDF",
    "AI_ENDPOINT",
    "AI_API_VERSION",
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
    "COSMOS_ENDPOINT"
    "COSMOS_DATABASE_NAME"
    "COSMOS_CONTAINER_NAME"
    "COSMOS_CHAT_CONTAINER"
    "STORAGE_ACCOUNT_NAME"
    "CONTAINER_NAME_PDF"
    "SERVICE_BUS_FQDN"
    "QUEUE_NAME_PDF"
    "AI_ENDPOINT"
    "AI_API_VERSION"
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
# API Container
az containerapp show \
  --name email-poc-api \
  --resource-group email-poc-rg \
  --query "properties.template.containers[0].env" \
  -o table

# Worker Container
az containerapp show \
  --name email-poc-worker \
  --resource-group email-poc-rg \
  --query "properties.template.containers[0].env" \
  -o table
```

## Troubleshooting

### Common Issues

1. **Cosmos DB Connection Failed**
   - Verify `COSMOS_ENDPOINT` is correct
   - Ensure managed identity has `Cosmos DB Built-in Data Contributor` role
   - Check `COSMOS_DATABASE_NAME` and `COSMOS_CONTAINER_NAME` exist

2. **Service Bus Connection Failed**
   - Verify `SERVICE_BUS_FQDN` format (must end with `.servicebus.windows.net`)
   - Ensure managed identity has `Azure Service Bus Data Receiver` and `Azure Service Bus Data Sender` roles
   - Check `QUEUE_NAME_PDF` exists in Service Bus namespace

3. **AI Model Connection Failed**
   - Verify `AI_ENDPOINT` is correct
   - Ensure deployment names (`PHI_DEPLOYMENT`, `MISTRAL_DEPLOYMENT`) match Azure AI Foundry deployments
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
