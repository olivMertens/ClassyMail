# LOCAL_RUN

## Prerequisites

- Python 3.11 or 3.12 (Azure SDK wheels may not be available for Python 3.13 yet)
- One of: `uv`, Poetry, or pip

## Install

### Option A: uv (recommended)

```bash
uv lock
uv sync
```

If you have multiple Python versions installed and want to be explicit:

```bash
uv lock --python 3.12
uv sync --python 3.12
```

### Option B: pip

```bash
pip install -r requirements.txt
```

## Configure environment

Create a local `secrets.env` (NOT committed). Minimal variables:

```dotenv
AI_ENDPOINT=https://<your-ai-endpoint>.cognitiveservices.azure.com/
AZURE_SERVICE_BUS_FQDN=<namespace>.servicebus.windows.net
AZURE_SERVICE_BUS_QUEUE=pdf-processing-queue
AZURE_STORAGE_ACCOUNT_URL=https://<storage>.blob.core.windows.net/
AZURE_STORAGE_CONTAINER=pdf-inputs
AZURE_COSMOS_ENDPOINT=https://<cosmos>.documents.azure.com:443/
AZURE_COSMOS_DB=emailsdb
AZURE_COSMOS_CONTAINER=emails

# Optional if using key-based Cosmos (not recommended)
# AZURE_COSMOS_KEY=

# Models (can be the same as AI_ENDPOINT)
MISTRAL_ENDPOINT=$AI_ENDPOINT
PHI_ENDPOINT=$AI_ENDPOINT
PHI_DEPLOYMENT=phi-4

# Optional fallback
PHI_FALLBACK_DEPLOYMENT=gpt-4o-mini
```

Then load it before running:

### PowerShell

```powershell
Get-Content .\secrets.env | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
  $k, $v = $_ -split '=', 2
  [Environment]::SetEnvironmentVariable($k, $v)
}
```

## Run

### API + worker in one process

```bash
uv run uvicorn main:app --reload
```

Then open: `http://127.0.0.1:8000/`

## Notes

- The app uses `DefaultAzureCredential` / Entra ID. For local dev, `az login` is typically the easiest path.
- If you don’t have Azure resources yet, run Terraform first (see `docs/TERRAFORM.md`).
