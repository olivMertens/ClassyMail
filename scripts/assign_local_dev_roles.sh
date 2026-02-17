#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Assign RBAC roles to the current Azure CLI user for local development.
#
# Usage:
#   bash scripts/assign_local_dev_roles.sh
#   bash scripts/assign_local_dev_roles.sh --prefix email-poc-test
#   bash scripts/assign_local_dev_roles.sh --prefix myapp --resource-group myapp-rg
# ---------------------------------------------------------------------------
set -euo pipefail

PREFIX="email-poc"
STORAGE_ACCOUNT_NAME=""
SERVICEBUS_NAMESPACE=""
COSMOS_ACCOUNT_NAME=""
AI_ACCOUNT_NAME=""
RESOURCE_GROUP=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)               PREFIX="$2"; shift 2 ;;
    --storage-account)      STORAGE_ACCOUNT_NAME="$2"; shift 2 ;;
    --servicebus-namespace) SERVICEBUS_NAMESPACE="$2"; shift 2 ;;
    --cosmos-account)       COSMOS_ACCOUNT_NAME="$2"; shift 2 ;;
    --ai-account)           AI_ACCOUNT_NAME="$2"; shift 2 ;;
    --resource-group|-g)    RESOURCE_GROUP="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Derive defaults from prefix if not explicitly set
[[ -z "$RESOURCE_GROUP" ]]       && RESOURCE_GROUP="${PREFIX}-rg"
[[ -z "$STORAGE_ACCOUNT_NAME" ]] && STORAGE_ACCOUNT_NAME="${PREFIX//-/}st"
[[ -z "$SERVICEBUS_NAMESPACE" ]] && SERVICEBUS_NAMESPACE="${PREFIX}-sbus"
[[ -z "$COSMOS_ACCOUNT_NAME" ]]  && COSMOS_ACCOUNT_NAME="${PREFIX}-cosmos"
[[ -z "$AI_ACCOUNT_NAME" ]]      && AI_ACCOUNT_NAME="${PREFIX}-aifoundry"

echo "Assigning RBAC roles for local development..."
echo ""

# Get current user's object ID
echo "Getting current Azure CLI user..."
CURRENT_USER=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)
if [[ -z "$CURRENT_USER" ]]; then
  echo "Failed to get current user. Make sure you're logged in with 'az login'" >&2
  exit 1
fi
echo "Current user object ID: $CURRENT_USER"
echo ""

# Storage roles
echo "Assigning Storage roles..."
STORAGE_ID=$(az storage account show --name "$STORAGE_ACCOUNT_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv 2>/dev/null || echo "")

if [[ -n "$STORAGE_ID" ]]; then
  echo "  - Storage Blob Data Contributor"
  az role assignment create --assignee "$CURRENT_USER" --role "Storage Blob Data Contributor" --scope "$STORAGE_ID" 2>/dev/null || true
  echo "Storage roles assigned"
else
  echo "  Storage account not found or not accessible"
fi
echo ""

# Service Bus roles
echo "Assigning Service Bus roles..."
SB_ID=$(az servicebus namespace show --name "$SERVICEBUS_NAMESPACE" --resource-group "$RESOURCE_GROUP" --query id -o tsv 2>/dev/null || echo "")

if [[ -n "$SB_ID" ]]; then
  echo "  - Azure Service Bus Data Owner"
  az role assignment create --assignee "$CURRENT_USER" --role "Azure Service Bus Data Owner" --scope "$SB_ID" 2>/dev/null || true
  echo "Service Bus roles assigned"
else
  echo "  Service Bus namespace not found or not accessible"
fi
echo ""

# Cosmos DB roles
echo "Assigning Cosmos DB roles..."
COSMOS_ID=$(az cosmosdb show --name "$COSMOS_ACCOUNT_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv 2>/dev/null || echo "")

if [[ -n "$COSMOS_ID" ]]; then
  echo "  - Cosmos DB Built-in Data Contributor (data plane, local dev)"
  ROLE_DEF_ID="00000000-0000-0000-0000-000000000002"
  az cosmosdb sql role assignment create \
    --account-name "$COSMOS_ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --role-definition-id "$ROLE_DEF_ID" \
    --principal-id "$CURRENT_USER" \
    --scope "/" 2>/dev/null || true
  echo "Cosmos DB roles assigned"
else
  echo "  Cosmos DB account not found or not accessible"
fi
echo ""

# AI Foundry roles
echo "Assigning AI Foundry roles..."
AI_ID=$(az cognitiveservices account show --name "$AI_ACCOUNT_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv 2>/dev/null || echo "")

if [[ -n "$AI_ID" ]]; then
  echo "  - Cognitive Services User"
  az role assignment create --assignee "$CURRENT_USER" --role "Cognitive Services User" --scope "$AI_ID" 2>/dev/null || true
  echo "AI Foundry roles assigned"
else
  echo "  AI Foundry account not found or not accessible"
fi
echo ""

echo "RBAC role assignment complete!"
echo ""
echo "Note: Role assignments may take a few minutes to propagate."
echo "   If you get authorization errors, wait 2-3 minutes and try again."
echo ""
echo "You can now run: uv run python scripts/test_e2e_local.py"
