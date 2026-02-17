#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Generate secrets.env from Azure resource discovery (no Terraform needed).
#
# Usage:
#   bash scripts/write_secrets_env.sh --resource-group email-poc-rg
#   bash scripts/write_secrets_env.sh --prefix email-poc --force
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RESOURCE_GROUP=""
PREFIX="email-poc"
OUT_FILE="secrets.env"
FORCE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resource-group|-g) RESOURCE_GROUP="$2"; shift 2 ;;
    --prefix)            PREFIX="$2"; shift 2 ;;
    --out-file)          OUT_FILE="$2"; shift 2 ;;
    --force)             FORCE=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

OUT_PATH="$REPO_ROOT/$OUT_FILE"

if [[ -f "$OUT_PATH" && "$FORCE" == false ]]; then
  echo "Le fichier '$OUT_PATH' existe deja. Relancez avec --force pour l'ecraser." >&2
  exit 1
fi

# Check Azure CLI
if ! command -v az &>/dev/null; then
  echo "az introuvable. Installez Azure CLI puis relancez ce script." >&2
  exit 1
fi

if ! az account show -o json &>/dev/null; then
  echo "Impossible de lire le contexte Azure. Lancez d'abord 'az login'." >&2
  exit 1
fi

# Discover resource group
get_rg() {
  if [[ -n "$RESOURCE_GROUP" ]]; then
    echo "$RESOURCE_GROUP"
    return
  fi
  local found
  found=$(az group list --query "[?starts_with(name, '$PREFIX')].name | [0]" -o tsv 2>/dev/null || echo "")
  if [[ -z "$found" ]]; then
    echo "Resource group introuvable. Passez --resource-group <nom> (ou ajustez --prefix)." >&2
    exit 1
  fi
  echo "$found"
}

# Helper: get first match or empty
get_first() {
  eval "$1" 2>/dev/null | tr -d '[:space:]' || echo ""
}

RG=$(get_rg)

# ── Discover resources ──

IDENTITY_NAME=$(get_first "az identity list -g '$RG' --query '[0].name' -o tsv")
APP_CLIENT_ID=""
if [[ -n "$IDENTITY_NAME" ]]; then
  APP_CLIENT_ID=$(get_first "az identity show -g '$RG' -n '$IDENTITY_NAME' --query clientId -o tsv")
fi

SB_NAMESPACE=$(get_first "az servicebus namespace list -g '$RG' --query '[0].name' -o tsv")
SERVICE_BUS_FQDN=""
SERVICE_BUS_QUEUE=""
if [[ -n "$SB_NAMESPACE" ]]; then
  SERVICE_BUS_FQDN="${SB_NAMESPACE}.servicebus.windows.net"
  SERVICE_BUS_QUEUE=$(get_first "az servicebus queue list -g '$RG' --namespace-name '$SB_NAMESPACE' --query '[0].name' -o tsv")
fi

STORAGE_ACCOUNT_NAME=$(get_first "az storage account list -g '$RG' --query '[0].name' -o tsv")
STORAGE_ACCOUNT_URL=""
if [[ -n "$STORAGE_ACCOUNT_NAME" ]]; then
  STORAGE_ACCOUNT_URL=$(get_first "az storage account show -g '$RG' -n '$STORAGE_ACCOUNT_NAME' --query primaryEndpoints.blob -o tsv")
fi
STORAGE_CONTAINER="pdf-inputs"

COSMOS_ACCOUNT=$(get_first "az cosmosdb list -g '$RG' --query '[0].name' -o tsv")
COSMOS_ENDPOINT=""
COSMOS_DB="emailsdb"
COSMOS_CONTAINER="emails"
if [[ -n "$COSMOS_ACCOUNT" ]]; then
  COSMOS_ENDPOINT=$(get_first "az cosmosdb show -g '$RG' -n '$COSMOS_ACCOUNT' --query documentEndpoint -o tsv")
  DB=$(get_first "az cosmosdb sql database list -g '$RG' -a '$COSMOS_ACCOUNT' --query '[0].name' -o tsv")
  [[ -n "$DB" ]] && COSMOS_DB="$DB"
  CT=$(get_first "az cosmosdb sql container list -g '$RG' -a '$COSMOS_ACCOUNT' -d '$COSMOS_DB' --query '[0].name' -o tsv")
  [[ -n "$CT" ]] && COSMOS_CONTAINER="$CT"
fi

AI_ENDPOINT=$(get_first "az cognitiveservices account list -g '$RG' --query \"[?kind=='AIServices'].properties.endpoint | [0]\" -o tsv")
if [[ -z "$AI_ENDPOINT" ]]; then
  AI_ENDPOINT=$(get_first "az cognitiveservices account list -g '$RG' --query '[0].properties.endpoint' -o tsv")
fi

# API public URL
API_FQDN=$(get_first "az containerapp list -g '$RG' --query \"[?contains(name, 'api')].properties.configuration.ingress.fqdn | [0]\" -o tsv")
if [[ -z "$API_FQDN" ]]; then
  API_FQDN=$(get_first "az containerapp list -g '$RG' --query \"[?properties.configuration.ingress.fqdn!=null].properties.configuration.ingress.fqdn | [0]\" -o tsv")
fi
API_BASE_URL=""
[[ -n "$API_FQDN" ]] && API_BASE_URL="https://$API_FQDN"

AI_API_VERSION="2024-08-01-preview"
AI_SCOPE="https://cognitiveservices.azure.com/.default"

# Application Insights
APP_INSIGHTS_NAME=$(get_first "az resource list -g '$RG' --resource-type 'Microsoft.Insights/components' --query '[0].name' -o tsv")
APP_INSIGHTS_CONN_STR=""
if [[ -n "$APP_INSIGHTS_NAME" ]]; then
  APP_INSIGHTS_CONN_STR=$(get_first "az resource show -g '$RG' -n '$APP_INSIGHTS_NAME' --resource-type 'Microsoft.Insights/components' --query properties.ConnectionString -o tsv")
fi

# Log Analytics
LOG_WORKSPACE_NAME=$(get_first "az monitor log-analytics workspace list -g '$RG' --query '[0].name' -o tsv")
LOG_WORKSPACE_ID=""
if [[ -n "$LOG_WORKSPACE_NAME" ]]; then
  LOG_WORKSPACE_ID=$(get_first "az monitor log-analytics workspace show -g '$RG' -n '$LOG_WORKSPACE_NAME' --query customerId -o tsv")
fi

# Azure AI Language (optional)
LANGUAGE_ENDPOINT=$(get_first "az cognitiveservices account list -g '$RG' --query \"[?kind=='TextAnalytics'].properties.endpoint | [0]\" -o tsv")

# ── Write secrets.env ──

cat > "$OUT_PATH" << ENVEOF
# =============================================================================
# Fichier local (NE PAS COMMITTER) — ignore par .gitignore
# Genere via scripts/write_secrets_env.sh
# Date: $(date '+%Y-%m-%d %H:%M:%S')
# =============================================================================

# --- CORE AZURE RESOURCES ---

# Managed Identity (User Assigned) — clientId
AZURE_CLIENT_ID=$APP_CLIENT_ID

# Service Bus
AZURE_SERVICE_BUS_FQDN=$SERVICE_BUS_FQDN
AZURE_SERVICE_BUS_QUEUE=$SERVICE_BUS_QUEUE

# Blob Storage
AZURE_STORAGE_ACCOUNT_URL=$STORAGE_ACCOUNT_URL
AZURE_STORAGE_CONTAINER=$STORAGE_CONTAINER

# Cosmos DB
AZURE_COSMOS_ENDPOINT=$COSMOS_ENDPOINT
AZURE_COSMOS_DB=$COSMOS_DB
AZURE_COSMOS_CONTAINER=$COSMOS_CONTAINER
AZURE_COSMOS_CHAT_CONTAINER=chat_history
AZURE_COSMOS_CACHE_CONTAINER=vector_cache

# --- AI MODEL ENDPOINTS ---

# Main AI Foundry Endpoint
AZURE_AI_ENDPOINT=$AI_ENDPOINT
AI_API_VERSION=$AI_API_VERSION
AI_SCOPE=$AI_SCOPE

# Mistral OCR Model
MISTRAL_ENDPOINT=$AI_ENDPOINT
MISTRAL_DEPLOYMENT=mistral-document-ai-2505
MISTRAL_MODE=maas
MISTRAL_API_VERSION=2024-05-01-preview

# Phi-4 Classification Model
PHI_ENDPOINT=$AI_ENDPOINT
PHI_DEPLOYMENT=phi-4

# Fallback Model (long context)
PHI_FALLBACK_ENDPOINT=$AI_ENDPOINT
PHI_FALLBACK_DEPLOYMENT=gpt-4o-mini

# --- RAG & EMBEDDINGS (Optional) ---

# Embedding Model
EMBEDDING_ENDPOINT=$AI_ENDPOINT
EMBEDDING_DEPLOYMENT=text-embedding-3-small
EMBEDDING_API_VERSION=$AI_API_VERSION

# Chat Model (RAG)
CHAT_ENDPOINT=$AI_ENDPOINT
CHAT_DEPLOYMENT=gpt-5.2-chat
CHAT_API_VERSION=$AI_API_VERSION

# Vision Model
VISION_ENDPOINT=$AI_ENDPOINT
VISION_DEPLOYMENT=gpt-4o-mini
VISION_API_VERSION=$AI_API_VERSION

# --- PII DETECTION & ANONYMIZATION (Optional) ---

# Azure AI Language (Native PII Detection)
AZURE_LANGUAGE_ENDPOINT=$LANGUAGE_ENDPOINT

# Anonymization Model
ANONYMIZER_ENDPOINT=$AI_ENDPOINT
ANONYMIZER_DEPLOYMENT=gpt-4o-mini
ANONYMIZER_API_VERSION=$AI_API_VERSION
ANONYMIZER_PROMPT_VERSION=v1
ANONYMIZER_MAX_TOKENS=6000

# --- TELEMETRY & OBSERVABILITY ---

# Application Insights
APPLICATIONINSIGHTS_CONNECTION_STRING=$APP_INSIGHTS_CONN_STR

# Log Analytics
LOG_ANALYTICS_WORKSPACE_ID=$LOG_WORKSPACE_ID

# OpenTelemetry
OTEL_SERVICE_NAME=classymail-api
OTEL_RESOURCE_ATTRIBUTES=service.namespace=classymail
AZURE_MONITOR_ENABLE_GENAI_TRACES=true

# --- CONFIGURATION (Defaults) ---

AZURE_REGION=swedencentral
AZURE_PREFERRED_DATA_ZONE=eu-central
COSMOS_QUERY_MAX_LIMIT=100
PHI_PRIMARY_MAX_INPUT_TOKENS=8000
PHI_FALLBACK_MAX_INPUT_TOKENS=120000
PHI_RESERVED_OUTPUT_TOKENS=1000

# Cost Tracking
PHI4_COST_PER_1K_INPUT=0.000107
PHI4_COST_PER_1K_OUTPUT=0.00043
MISTRAL_OCR_COST_PER_1K_PAGES=1.0
FALLBACK_COST_PER_1K_INPUT=0.00015
FALLBACK_COST_PER_1K_OUTPUT=0.0006

# OCR Configuration
MISTRAL_OCR_MAX_ATTEMPTS=3
REVIEW_CONFIDENCE_THRESHOLD=0.85

# --- WORKER CONFIGURATION ---

WORKER_CONCURRENCY=30
WORKER_LOCK_RENEWAL_DURATION=3600
MISTRAL_RPM=30
MISTRAL_TPM=60000
PHI_RPM=60
PHI_TPM=80000
CHAT_RPM=60
CHAT_TPM=80000

# --- UI CONFIGURATION ---

UI_SHOW_INFO_MODAL=true
UI_SHOW_DEVELOPER_TAB=true
ORGANIZATION_NAME=ClassyMail
MAX_UPLOAD_SIZE=10
UPLOAD_MAX_BYTES=10485760

# --- ENVIRONMENT ---

AZURE_ENV=development
PORT=8000
API_BASE_URL=$API_BASE_URL

# --- TESTING (Local Development) ---

# Azure OpenAI (for scripts/generate_dummy_pdfs.py --use-aoai)
AZURE_OPENAI_ENDPOINT=$AI_ENDPOINT
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2024-10-01-preview
AZURE_OPENAI_SCOPE=https://cognitiveservices.azure.com/.default
AZURE_OPENAI_TIMEOUT=30
# AZURE_OPENAI_API_KEY=  # Optional: for key-based auth
ENVEOF

echo "OK: secrets.env ecrit dans '$OUT_PATH'"
