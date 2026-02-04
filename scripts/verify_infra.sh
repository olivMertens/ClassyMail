#!/usr/bin/env bash
set -euo pipefail

# Configurable env vars with defaults
RESOURCE_GROUP=${RESOURCE_GROUP:-email-poc-rg}
PREFIX=${PREFIX:-email-poc}
IDENTITY_NAME=${IDENTITY_NAME:-${PREFIX}-id}
COSMOS_ACCOUNT=${COSMOS_ACCOUNT:-${PREFIX}-cosmos}
COSMOS_DB=${COSMOS_DB:-emailsdb}
COSMOS_CONTAINERS=${COSMOS_CONTAINERS:-"emails chat_history vector_cache"}
STORAGE_ACCOUNT=${STORAGE_ACCOUNT:-${PREFIX}st}
SERVICEBUS_NAMESPACE=${SERVICEBUS_NAMESPACE:-${PREFIX}-sbus}
SERVICEBUS_QUEUE=${SERVICEBUS_QUEUE:-pdf-processing-queue}
AI_ACCOUNT=${AI_ACCOUNT:-${PREFIX}-aifoundry}
CONTAINER_APP_API=${CONTAINER_APP_API:-${PREFIX}-api}
CONTAINER_APP_WORKER=${CONTAINER_APP_WORKER:-${PREFIX}-worker}

roles_ok=true

log() { echo -e "$@"; }
info() { log "\033[1;34m[INFO]\033[0m $@"; }
success() { log "\033[1;32m[SUCCESS]\033[0m $@"; }
warn() { log "\033[1;33m[WARN]\033[0m $@"; }
err() { log "\033[1;31m[ERROR]\033[0m $@"; }

info "Checking Azure login..."
az account show >/dev/null 2>&1 || az login >/dev/null
SUB_ID=$(az account show --query id -o tsv)
success "Logged in to subscription: $SUB_ID"

info "Fetching managed identity principalId ($IDENTITY_NAME)..."
PRINCIPAL_ID=$(az identity show -g "$RESOURCE_GROUP" -n "$IDENTITY_NAME" --query principalId -o tsv 2>/dev/null || true)
if [[ -z "$PRINCIPAL_ID" ]]; then
  err "Managed Identity '$IDENTITY_NAME' not found. Run terraform apply first."
  exit 1
fi
success "Managed Identity principalId: $PRINCIPAL_ID"

assign_role(){
  local scope="$1"; local role="$2"; local desc="$3"
  info "Ensuring role '$role' on $desc"
  if az role assignment list --assignee "$PRINCIPAL_ID" --scope "$scope" --query "[?roleDefinitionName=='$role']" -o tsv | grep -q "$role"; then
    success "Role already assigned"
  else
    az role assignment create --assignee "$PRINCIPAL_ID" --role "$role" --scope "$scope" >/dev/null && success "Role assigned" || { err "Failed assigning $role"; roles_ok=false; }
  fi
}

# Resources presence checks
info "Checking resource group: $RESOURCE_GROUP"
az group show -n "$RESOURCE_GROUP" >/dev/null && success "RG exists" || { err "RG missing"; exit 1; }

info "Checking Storage account: $STORAGE_ACCOUNT"
STORAGE_ID=$(az storage account show -g "$RESOURCE_GROUP" -n "$STORAGE_ACCOUNT" --query id -o tsv 2>/dev/null || true)
[[ -n "$STORAGE_ID" ]] && success "Storage exists" || warn "Storage missing"

info "Checking Service Bus namespace: $SERVICEBUS_NAMESPACE"
SB_ID=$(az servicebus namespace show -g "$RESOURCE_GROUP" -n "$SERVICEBUS_NAMESPACE" --query id -o tsv 2>/dev/null || true)
[[ -n "$SB_ID" ]] && success "Service Bus exists" || warn "Service Bus missing"
if [[ -n "$SB_ID" ]]; then
  az servicebus queue show --resource-group "$RESOURCE_GROUP" --namespace-name "$SERVICEBUS_NAMESPACE" -n "$SERVICEBUS_QUEUE" >/dev/null 2>&1 && success "Queue $SERVICEBUS_QUEUE exists" || warn "Queue missing"
fi

info "Checking Cosmos account/db/containers"
COSMOS_ID=$(az cosmosdb show -g "$RESOURCE_GROUP" -n "$COSMOS_ACCOUNT" --query id -o tsv 2>/dev/null || true)
if [[ -n "$COSMOS_ID" ]]; then
  success "Cosmos account exists"
  az cosmosdb sql database show -g "$RESOURCE_GROUP" -a "$COSMOS_ACCOUNT" -n "$COSMOS_DB" >/dev/null 2>&1 && success "Database $COSMOS_DB exists" || warn "Database missing"
  for c in $COSMOS_CONTAINERS; do
    az cosmosdb sql container show -g "$RESOURCE_GROUP" -a "$COSMOS_ACCOUNT" -d "$COSMOS_DB" -n "$c" >/dev/null 2>&1 && success "Container $c exists" || warn "Container $c missing"
  done
else
  warn "Cosmos account missing"
fi

info "Checking Cognitive Services account: $AI_ACCOUNT"
AI_ID=$(az cognitiveservices account show -g "$RESOURCE_GROUP" -n "$AI_ACCOUNT" --query id -o tsv 2>/dev/null || true)
[[ -n "$AI_ID" ]] && success "AI Account exists" || warn "AI Account missing"

info "Checking Container Apps"
az containerapp show -g "$RESOURCE_GROUP" -n "$CONTAINER_APP_API" >/dev/null 2>&1 && success "API CA exists" || warn "API CA missing"
az containerapp show -g "$RESOURCE_GROUP" -n "$CONTAINER_APP_WORKER" >/dev/null 2>&1 && success "Worker CA exists" || warn "Worker CA missing"

# Role assignments
if [[ -n "$AI_ID" ]]; then assign_role "$AI_ID" "Cognitive Services User" "Cognitive Services"; fi
if [[ -n "$STORAGE_ID" ]]; then assign_role "$STORAGE_ID" "Storage Blob Data Contributor" "Storage"; fi
if [[ -n "$SB_ID" ]]; then assign_role "$SB_ID" "Azure Service Bus Data Sender" "Service Bus"; assign_role "$SB_ID" "Azure Service Bus Data Receiver" "Service Bus"; fi
if [[ -n "$COSMOS_ID" ]]; then assign_role "$COSMOS_ID" "Cosmos DB Built-in Data Contributor" "Cosmos"; fi
# Optional: ACR if present
ACR_ID=$(az acr list -g "$RESOURCE_GROUP" --query "[0].id" -o tsv 2>/dev/null || true)
if [[ -n "$ACR_ID" ]]; then assign_role "$ACR_ID" "AcrPull" "ACR"; fi

# Placeholder for policy checks
warn "Policy check: TODO - Awaiting policy level details. Add az policy assignment list --resource-group $RESOURCE_GROUP ..."

# Connection checks (lightweight)
if [[ -n "$COSMOS_ID" ]]; then
  info "Listing Cosmos containers (connectivity test)"
  az cosmosdb sql container list -g "$RESOURCE_GROUP" -a "$COSMOS_ACCOUNT" -d "$COSMOS_DB" >/dev/null && success "Cosmos connectivity OK" || warn "Cosmos connectivity failed"
fi
if [[ -n "$STORAGE_ID" ]]; then
  info "Checking storage container existence"
  az storage container list --account-name "$STORAGE_ACCOUNT" --auth-mode login >/dev/null && success "Storage connectivity OK" || warn "Storage connectivity failed"
fi
if [[ -n "$SB_ID" ]]; then
  info "Checking Service Bus permissions (namespaces list)"
  az servicebus namespace list -g "$RESOURCE_GROUP" >/dev/null && success "Service Bus connectivity OK" || warn "Service Bus connectivity failed"
fi

$roles_ok && success "Verification complete" || err "Verification complete with errors"
