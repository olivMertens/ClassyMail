# Local Development Guide

> 📋 **Consolidated Guide**: This document combines setup, running, building, and deployment instructions for local development.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation & Setup](#installation--setup)
3. [Running Locally](#running-locally)
4. [Build & Deploy](#build--deploy)
5. [Testing & Validation](#testing--validation)
6. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Python 3.12** (uv powered, recommended)
- **Node 18+** (for frontend)
- **Azure CLI** (`az`) logged in (for RBAC) or `AZURE_STORAGE_ACCOUNT_KEY`
- **Docker** (optional, for container builds)
- **Terraform** (optional, if deploying infrastructure)

## Installation & Setup

### Option A: uv (Recommended)

```bash
# Install dependencies
uv sync --frozen --extra dev

# For specific Python version
uv lock --python 3.12
uv sync --python 3.12
```

### Option B: pip

```bash
pip install -r requirements.txt
```

### Frontend Setup

```bash
cd frontend
npm install
```

---

## Running Locally

### 1. Configure Environment Variables

Create `secrets.env` in the project root (NOT committed):

```dotenv
# Azure Services (Terraform outputs)
AZURE_CLIENT_ID=<YOUR_MANAGED_IDENTITY_CLIENT_ID>  # Managed Identity Client ID
AZURE_SERVICE_BUS_FQDN=<namespace>.servicebus.windows.net
AZURE_SERVICE_BUS_QUEUE=pdf-processing-queue
AZURE_STORAGE_ACCOUNT_URL=https://<storage>.blob.core.windows.net/
AZURE_STORAGE_CONTAINER=pdf-inputs
AZURE_COSMOS_ENDPOINT=https://<cosmos>.documents.azure.com:443/
AZURE_COSMOS_DB=emailsdb
AZURE_COSMOS_CONTAINER=emails

# Microsoft AI Foundry
AZURE_AI_ENDPOINT=https://<aifoundry>.cognitiveservices.azure.com/
MISTRAL_ENDPOINT=${AZURE_AI_ENDPOINT}
MISTRAL_DEPLOYMENT=mistral-document-ai-2512  # ⚠️ CRITICAL: Must be EXACTLY this name — typos cause HTTP 500 errors
MISTRAL_MODE=maas
PHI_ENDPOINT=${AZURE_AI_ENDPOINT}
PHI_DEPLOYMENT=Phi-4
PHI_FALLBACK_DEPLOYMENT=gpt-4o-mini
EMBEDDING_DEPLOYMENT=text-embedding-3-small
CHAT_DEPLOYMENT=gpt-5.2-chat

# Observability (Azure)
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...;IngestionEndpoint=https://...
LOG_ANALYTICS_WORKSPACE_ID=<YOUR_LOG_ANALYTICS_WORKSPACE_ID>
OTEL_SERVICE_NAME=classymail-api

# UI Configuration (Optional)
UI_SHOW_INFO_MODAL=true
UI_SHOW_DEVELOPER_TAB=true
ORGANIZATION_NAME=ClassyMail  # or ClassyMail, ClassyMail (default)
MAX_UPLOAD_SIZE=10  # MB

# Optional: Anonymization
ANONYMIZER_DEPLOYMENT=gpt-4o
ANONYMIZER_MAX_TOKENS=6000

# Security Note: Do NOT set AZURE_AI_KEY or AZURE_COSMOS_KEY in production
# Use DefaultAzureCredential with Managed Identity for authentication
```

### 2. Load Environment Variables

#### PowerShell

```powershell
Get-Content .\secrets.env | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
  $k, $v = $_ -split '=', 2
  [Environment]::SetEnvironmentVariable($k, $v)
}
```

#### Bash (Linux/macOS)

```bash
export $(grep -v '^#' secrets.env | xargs)
```

### 3. Build Frontend

```bash
cd frontend
npm run build
cd ..
```

### 4. Start API Server

```bash
# Run API only (no worker) - default port 8000
uv run uvicorn main:app --reload

# Run API + worker in same process (dev mode)
$env:ENABLE_WORKER = "true"
uv run uvicorn main:app --reload
```

Open: `http://127.0.0.1:8000/`

### 5. Verify Health

```bash
# Check API health
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz

# Check diagnostics
curl http://127.0.0.1:8000/api/admin/diagnostics
```

---

## Build & Deploy

### UI Dependency (Vue Runtime)

The UI requires Vue runtime **before building Docker**:

**Windows (PowerShell):**
```powershell
.\scripts\fetch_vue_runtime.ps1
```

**Linux/macOS:**
```bash
bash ./scripts/fetch_vue_runtime.sh
```

### Build Docker Image (Manual)

```bash
# Set variables
$env:ACR_NAME = "<acrname>"
$env:IMAGE_NAME = "classymail-agent"
$env:TAG = "local"

# Get ACR login server
$REGISTRY = az acr show --name $env:ACR_NAME --query loginServer -o tsv

# Login to ACR
az acr login --name $env:ACR_NAME

# Build and push
docker build -t $REGISTRY/$env:IMAGE_NAME:$env:TAG .
docker push $REGISTRY/$env:IMAGE_NAME:$env:TAG
```

### Build Using Scripts

**PowerShell:**
```powershell
.\scripts\build_acr.ps1 -AcrName $env:ACR_NAME -ImageName $env:IMAGE_NAME -Tag $env:TAG
```

**Bash:**
```bash
./scripts/build_acr.sh -a $ACR_NAME -i $IMAGE_NAME -t $TAG
```

### Deploy to Azure Container Apps (Without CI)

```bash
$REGISTRY = az acr show --name $ACR_NAME --query loginServer -o tsv

# Update API Container App
az containerapp update -n $IMAGE_NAME -g $RESOURCE_GROUP `
  --image $REGISTRY/$IMAGE_NAME:$TAG

# Update Worker Container App (with ENABLE_WORKER=true)
az containerapp update -n $WORKER_APP_NAME -g $RESOURCE_GROUP `
  --image $REGISTRY/$IMAGE_NAME:$TAG `
  --set-env-vars ENABLE_WORKER=true
```

### Registry Managed Identity Setup (Optional)

```bash
$IDENTITY_ID = az identity show -g $RESOURCE_GROUP -n $IDENTITY_NAME --query id -o tsv

az containerapp registry set `
  --name $IMAGE_NAME `
  --resource-group $RESOURCE_GROUP `
  --server $REGISTRY `
  --identity $IDENTITY_ID
```

---

## Testing & Validation

### Lint & Format

```bash
# Run linter
uv run ruff check .

# Run tests
uv run pytest -q
```

### Pre-Commit Hooks

```bash
# Install hooks (once)
uv run pre-commit install

# Run manually
uv run pre-commit run --all-files
```

### Upload & Pipeline Test

#### Via UI
- Navigate to Upload tab
- Drop PDF file

#### Via API
```bash
curl -X POST http://localhost:8000/api/upload \
  -F "files=@./dataset/pdf/sample.pdf"
```

### Generate Test PDFs

```bash
# Generate 25 test emails
python scripts/generate_dummy_pdfs.py --count 25 --out ./dataset_emails_hardcore
```

### Upload Test PDFs to Azure Blob

#### PowerShell
```powershell
$datePath = Get-Date -Format "yyyy/MM/dd"
az storage blob upload-batch `
  --auth-mode login `
  --account-name $storageAccountName `
  --destination pdf-inputs `
  --destination-path "uploads/$datePath/" `
  --source .\dataset_emails_hardcore `
  --pattern "*.pdf" `
  --content-type application/pdf
```

#### Bash
```bash
az storage blob upload-batch \
  --auth-mode login \
  --account-name $storageAccountName \
  --destination pdf-inputs \
  --destination-path "uploads/$(date +%Y/%m/%d)/" \
  --source ./dataset_emails_hardcore \
  --pattern "*.pdf" \
  --content-type application/pdf
```

---

## Troubleshooting

### "Upload Failed: 500 Internal Server Error"

**Symptom:** Upload fails with 500 error

**Cause:** Storage Account firewall blocks connections

**Solution:**
```hcl
# In infra/main.tf
resource "azurerm_storage_account" "st" {
    # ...
    public_network_access_enabled = true
    # ...
}
```

Even with public access, data remains protected by RBAC (`Storage Blob Data Contributor`).

### "System Error" (Cosmos DB)

**Symptom:** Error mentioning `enable_cross_partition_query`

**Cause:** Deprecated argument in recent SDK

**Solution:** Update backend code (already fixed in recent `main` branch)

### Mistral OCR Access Errors

**Symptom:** `500 Internal Server Error` on Mistral OCR

**Cause:** Local auth disabled on AI Foundry resource

**Solution:**
```bash
az resource update \
  --resource-group <prefix>-rg \
  --name <prefix>-aifoundry \
  --resource-type Microsoft.CognitiveServices/accounts \
  --set properties.disableLocalAuth=false
```

### Email Details API

Each email exposes `id` (Cosmos key, visible in dashboard card footer `#abcdef`).

**API:**
```bash
# Get email details
curl http://localhost:8000/api/emails/{id}
```

Returns: `file_url`, `file_url_sas`, `markdown`, `classification`

**Chatbot:**
- `get_email_by_id` returns `_links.view` and `_links.api`
- Responses render markdown (bold/italic visible in UI)

### Required Configurations

Ensure these environment variables exist:
- `AZURE_STORAGE_ACCOUNT_URL`
- `BLOB_CONTAINER_INPUT`

For private storage, set either:
- `AZURE_STORAGE_ACCOUNT_KEY` (not recommended), OR
- RBAC: `Storage Blob Data Reader` + `Contributor` roles

### Diagnostic Tools

**Pipeline Diagnostics & Error Checking:**

The `diagnose_pipeline.py` script provides comprehensive diagnostics for the PDF processing pipeline and quick access to Cosmos DB error records.

```bash
# Test full pipeline with local PDF (OCR + Classification)
python scripts/diagnose_pipeline.py --pdf dataset/pdf/test.pdf

# Test SAS generation for blob URL
python scripts/diagnose_pipeline.py --blob https://storage.blob.core.windows.net/container/file.pdf

# Show recent ERROR records from Cosmos DB
python scripts/diagnose_pipeline.py --show-errors

# Show 10 ERROR records without processing logs
python scripts/diagnose_pipeline.py --show-errors --limit 10 --no-log
```

**Use cases:**
- Verify OCR and classification endpoints are accessible
- Test token counting and model selection logic
- Check blob access with managed identity
- Quickly identify failed email processing jobs
- Debug processing pipeline errors with full logs

---

## Quick Reference

### Common Commands

```bash
# Start app (API + Worker)
uv run uvicorn main:app --reload

# Build frontend
cd frontend && npm run build && cd ..

# Run tests
uv run pytest

# Lint code
uv run ruff check .

# Generate test data
python scripts/generate_dummy_pdfs.py --count 50
```

### Useful Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/healthz`, `/health` | Health check |
| `/readyz`, `/ready` | Readiness check |
| `/api/admin/diagnostics` | System diagnostics |
| `/api/admin/deadletter` | Dead letter queue |
| `/api/admin/blob-info?blob_url=...` | Blob information |
| `/api/emails` | List emails |
| `/api/emails/{id}` | Email details |

---

## See Also

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [INFRASTRUCTURE.md](INFRASTRUCTURE.md) - Terraform deployment
- [TESTING_EMAIL_GENERATION.md](TESTING_EMAIL_GENERATION.md) - Test data generation
- [CICD_GITHUB.md](CICD_GITHUB.md) - CI/CD pipeline
