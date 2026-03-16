#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Bootstrap ClassyMail deployment in a new Azure tenant from scratch.
#
# Automated end-to-end deployment script that provisions all Azure infrastructure,
# builds and pushes the container image, and verifies the deployment.
# This script is IDEMPOTENT — safe to re-run.
#
# Usage:
#   bash scripts/bootstrap.sh
#   bash scripts/bootstrap.sh --prefix classymail-dev --location swedencentral
#   bash scripts/bootstrap.sh --tenant-id <GUID> --subscription-id <GUID>
#   bash scripts/bootstrap.sh --skip-image-build --skip-frontend-build
#
# Prerequisites:
#   - Azure CLI, Terraform, Node.js, uv
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Defaults
TENANT_ID=""
SUBSCRIPTION_ID=""
PREFIX="classymail-dev"
LOCATION="swedencentral"
ACR_NAME=""
ACR_RESOURCE_GROUP=""
IMAGE_TAG="v1"
SKIP_FRONTEND_BUILD=false
SKIP_PROVIDER_REGISTRATION=false
SKIP_IMAGE_BUILD=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tenant-id)                TENANT_ID="$2"; shift 2 ;;
    --subscription-id)          SUBSCRIPTION_ID="$2"; shift 2 ;;
    --prefix)                   PREFIX="$2"; shift 2 ;;
    --location)                 LOCATION="$2"; shift 2 ;;
    --acr-name)                 ACR_NAME="$2"; shift 2 ;;
    --acr-resource-group)       ACR_RESOURCE_GROUP="$2"; shift 2 ;;
    --image-tag)                IMAGE_TAG="$2"; shift 2 ;;
    --skip-frontend-build)      SKIP_FRONTEND_BUILD=true; shift ;;
    --skip-provider-registration) SKIP_PROVIDER_REGISTRATION=true; shift ;;
    --skip-image-build)         SKIP_IMAGE_BUILD=true; shift ;;
    --dry-run)                  DRY_RUN=true; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ─────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────

write_step() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "[$1] $2"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

require_cmd() {
  if ! command -v "$1" &>/dev/null; then
    echo "Required command not found: $1. $2" >&2
    exit 1
  fi
}

test_azure_login() {
  az account show -o json &>/dev/null
}

# ─────────────────────────────────────────────────────────────────────
# Step 0: Validate Prerequisites
# ─────────────────────────────────────────────────────────────────────

write_step "0/9" "Validating prerequisites"

require_cmd az        "Install: https://learn.microsoft.com/cli/azure/install-azure-cli"
require_cmd terraform "Install: https://developer.hashicorp.com/terraform/install"
require_cmd node      "Install: https://nodejs.org/"
require_cmd uv        "Install: https://docs.astral.sh/uv/getting-started/installation/"

HAS_DOCKER=false
if command -v docker &>/dev/null; then
  HAS_DOCKER=true
else
  echo "  Docker not found — will use ACR remote build (az acr build)"
fi

echo "  All prerequisites OK"

# ─────────────────────────────────────────────────────────────────────
# Step 1: Azure Authentication
# ─────────────────────────────────────────────────────────────────────

write_step "1/9" "Azure authentication"

if ! test_azure_login; then
  if [[ -n "$TENANT_ID" ]]; then
    echo "  Logging in to tenant $TENANT_ID..."
    az login --tenant "$TENANT_ID" >/dev/null
  else
    echo "  Logging in (interactive)..."
    az login >/dev/null
  fi
else
  CURRENT_TENANT=$(az account show --query tenantId -o tsv)
  if [[ -n "$TENANT_ID" && "$CURRENT_TENANT" != "$TENANT_ID" ]]; then
    echo "  Switching to tenant $TENANT_ID..."
    az login --tenant "$TENANT_ID" >/dev/null
  else
    echo "  Already logged in to tenant $CURRENT_TENANT"
  fi
fi

if [[ -n "$SUBSCRIPTION_ID" ]]; then
  az account set --subscription "$SUBSCRIPTION_ID" >/dev/null
fi

DETECTED_SUB=$(az account show --query id -o tsv | tr -d '[:space:]')
DETECTED_TENANT=$(az account show --query tenantId -o tsv | tr -d '[:space:]')
DETECTED_SUB_NAME=$(az account show --query name -o tsv | tr -d '[:space:]')

echo "  Tenant:       $DETECTED_TENANT"
echo "  Subscription: $DETECTED_SUB ($DETECTED_SUB_NAME)"

# ─────────────────────────────────────────────────────────────────────
# Step 2: Register Resource Providers
# ─────────────────────────────────────────────────────────────────────

if [[ "$SKIP_PROVIDER_REGISTRATION" == false ]]; then
  write_step "2/9" "Registering Azure resource providers"

  PROVIDERS=(
    "Microsoft.Storage"
    "Microsoft.ServiceBus"
    "Microsoft.DocumentDB"
    "Microsoft.CognitiveServices"
    "Microsoft.App"
    "Microsoft.EventGrid"
    "Microsoft.Insights"
    "Microsoft.OperationalInsights"
    "Microsoft.ManagedIdentity"
    "Microsoft.ContainerRegistry"
  )

  for p in "${PROVIDERS[@]}"; do
    STATE=$(az provider show --namespace "$p" --query registrationState -o tsv 2>/dev/null || echo "NotRegistered")
    if [[ "$STATE" == "Registered" ]]; then
      echo "  Already registered: $p"
    else
      if [[ "$DRY_RUN" == false ]]; then
        echo "  Registering: $p ..."
        az provider register --namespace "$p" >/dev/null
      else
        echo "  [dry-run] Would register: $p"
      fi
    fi
  done

  echo "  All providers registered (propagation may take 1-5 min)"
else
  write_step "2/9" "Skipping resource provider registration (--skip-provider-registration)"
fi

# ─────────────────────────────────────────────────────────────────────
# Step 3: Create ACR (if needed)
# ─────────────────────────────────────────────────────────────────────

write_step "3/9" "Container Registry setup"

# Default ACR name: strip dashes from prefix + "acr"
if [[ -z "$ACR_NAME" ]]; then
  ACR_NAME="${PREFIX//-/}acr"
fi
if [[ -z "$ACR_RESOURCE_GROUP" ]]; then
  ACR_RESOURCE_GROUP="${PREFIX}-acr-rg"
fi

ACR_EXISTS=$(az acr show --name "$ACR_NAME" --resource-group "$ACR_RESOURCE_GROUP" --query name -o tsv 2>/dev/null || echo "")
if [[ -n "$ACR_EXISTS" ]]; then
  echo "  ACR '$ACR_NAME' already exists in '$ACR_RESOURCE_GROUP'"
else
  # Check if ACR exists in another RG
  ACR_ANY_RG=$(az acr show --name "$ACR_NAME" --query name -o tsv 2>/dev/null || echo "")
  if [[ -n "$ACR_ANY_RG" ]]; then
    ACTUAL_RG=$(az acr show --name "$ACR_NAME" --query resourceGroup -o tsv)
    echo "  ACR '$ACR_NAME' found in resource group '$ACTUAL_RG'"
    ACR_RESOURCE_GROUP="$ACTUAL_RG"
  else
    if [[ "$DRY_RUN" == false ]]; then
      echo "  Creating ACR '$ACR_NAME' in '$ACR_RESOURCE_GROUP' ($LOCATION)..."
      az group create --name "$ACR_RESOURCE_GROUP" --location "$LOCATION" --output none 2>/dev/null || true
      az acr create --name "$ACR_NAME" --resource-group "$ACR_RESOURCE_GROUP" --sku Basic --admin-enabled false --output none
      echo "  ACR created"
    else
      echo "  [dry-run] Would create ACR '$ACR_NAME' in '$ACR_RESOURCE_GROUP'"
    fi
  fi
fi

CONTAINER_IMAGE="${ACR_NAME}.azurecr.io/classymail-agent:${IMAGE_TAG}"
echo "  Image target: $CONTAINER_IMAGE"

# ─────────────────────────────────────────────────────────────────────
# Step 4: Create terraform.tfvars (first pass — placeholder image)
# ─────────────────────────────────────────────────────────────────────

write_step "4/9" "Terraform configuration"

TFVARS_PATH="$REPO_ROOT/infra/terraform.tfvars"

# Detect public IP for Cosmos firewall
MY_IP=$(curl -s --max-time 5 https://ifconfig.me 2>/dev/null || echo "")

TFVARS_CONTENT="# Auto-generated by bootstrap.sh on $(date '+%Y-%m-%d %H:%M:%S')
subscription_id = \"$DETECTED_SUB\"

# Placeholder image — updated after ACR push (Step 7)
container_image = \"mcr.microsoft.com/azuredocs/containerapps-helloworld:latest\"

# Container Registry
acr_name           = \"$ACR_NAME\"
acr_resource_group = \"$ACR_RESOURCE_GROUP\"

# Naming
prefix   = \"$PREFIX\"
location = \"$LOCATION\"

# Security & Auth
cosmos_use_rbac = true

# Models: deploy manually via Azure AI Foundry portal
enable_model_deployments = false
deploy_language_service  = false

# Policies (set to false if your tenant restricts custom policy creation)
tag_policy_enabled             = true
security_cost_policy_enabled   = true

# Network: allow your IP for Cosmos DB local dev access
$(if [[ -n "$MY_IP" ]]; then echo "allowed_ip_ranges = [\"$MY_IP\"]"; else echo "# allowed_ip_ranges = [\"YOUR.PUBLIC.IP\"]  # Could not auto-detect"; fi)
"

if [[ -f "$TFVARS_PATH" ]]; then
  echo "  terraform.tfvars already exists — backing up to terraform.tfvars.bak"
  cp "$TFVARS_PATH" "${TFVARS_PATH}.bak"
fi

if [[ "$DRY_RUN" == false ]]; then
  echo "$TFVARS_CONTENT" > "$TFVARS_PATH"
  echo "  terraform.tfvars written"
else
  echo "  [dry-run] Would write terraform.tfvars"
fi

# ─────────────────────────────────────────────────────────────────────
# Step 5: Terraform — first apply (placeholder image)
# ─────────────────────────────────────────────────────────────────────

write_step "5/9" "Terraform init + plan + apply (pass 1 — placeholder image)"

if [[ "$DRY_RUN" == false ]]; then
  pushd "$REPO_ROOT/infra" > /dev/null

  terraform init -upgrade
  terraform plan -var "subscription_id=$DETECTED_SUB" -out tfplan
  terraform apply tfplan

  echo "  Infrastructure provisioned"

  # Capture AI endpoint output
  AI_EP=$(terraform output -raw AI_ENDPOINT 2>/dev/null || echo "")
  if [[ -n "$AI_EP" ]]; then
    echo "  AI endpoint: $AI_EP"
  fi

  popd > /dev/null
else
  echo "  [dry-run] Would run terraform init + plan + apply"
fi

# ─────────────────────────────────────────────────────────────────────
# Step 6: Build Frontend + Container Image
# ─────────────────────────────────────────────────────────────────────

if [[ "$SKIP_IMAGE_BUILD" == false ]]; then
  write_step "6/9" "Building frontend and container image"

  # 6a: Frontend
  if [[ "$SKIP_FRONTEND_BUILD" == false ]]; then
    echo "  Building frontend..."
    pushd "$REPO_ROOT/frontend" > /dev/null
    npm install --silent 2>&1 >/dev/null || true
    npm run build
    popd > /dev/null
    echo "  Frontend built"
  fi

  # 6b: Vue runtime
  echo "  Fetching Vue runtime..."
  bash "$REPO_ROOT/scripts/fetch_vue_runtime.sh"

  # 6c: Build & push image
  echo "  Building and pushing container image..."
  pushd "$REPO_ROOT" > /dev/null

  if [[ "$HAS_DOCKER" == true ]]; then
    # Local build + push
    az acr login --name "$ACR_NAME" >/dev/null
    docker build -t "$CONTAINER_IMAGE" .
    docker push "$CONTAINER_IMAGE"
  else
    # Remote build via ACR
    az acr build --registry "$ACR_NAME" --image "classymail-agent:$IMAGE_TAG" .
  fi

  popd > /dev/null
  echo "  Image pushed: $CONTAINER_IMAGE"
else
  write_step "6/9" "Skipping image build (--skip-image-build)"
fi

# ─────────────────────────────────────────────────────────────────────
# Step 7: Terraform — second apply (real image)
# ─────────────────────────────────────────────────────────────────────

if [[ "$SKIP_IMAGE_BUILD" == false ]]; then
  write_step "7/9" "Terraform apply (pass 2 — real container image)"

  # Update terraform.tfvars with real image
  sed -i.bak2 "s|container_image = \"[^\"]*\"|container_image = \"$CONTAINER_IMAGE\"|" "$TFVARS_PATH"

  if [[ "$DRY_RUN" == false ]]; then
    pushd "$REPO_ROOT/infra" > /dev/null
    terraform plan -var "subscription_id=$DETECTED_SUB" -out tfplan
    terraform apply tfplan
    echo "  Container Apps updated with real image"
    popd > /dev/null
  else
    echo "  [dry-run] Would run terraform apply with real image"
  fi
else
  write_step "7/9" "Skipping second Terraform apply (no image change)"
fi

# ─────────────────────────────────────────────────────────────────────
# Step 8: Generate secrets.env + assign local RBAC
# ─────────────────────────────────────────────────────────────────────

write_step "8/9" "Local development setup"

RG_NAME="${PREFIX}-rg"

# Generate secrets.env
echo "  Generating secrets.env..."
bash "$REPO_ROOT/scripts/write_secrets_env.sh" \
  --resource-group "$RG_NAME" \
  --prefix "$PREFIX" \
  --force

# Derive resource names from prefix
CLEAN_PREFIX="${PREFIX//-/}"
STORAGE_ACCOUNT_NAME="${CLEAN_PREFIX}st"
SERVICEBUS_NAMESPACE="${PREFIX}-sbus"
COSMOS_ACCOUNT_NAME="${PREFIX}-cosmos"

# Assign local dev RBAC
echo "  Assigning local RBAC roles..."
bash "$REPO_ROOT/scripts/assign_local_dev_roles.sh" \
  --prefix "$PREFIX" \
  --storage-account "$STORAGE_ACCOUNT_NAME" \
  --servicebus-namespace "$SERVICEBUS_NAMESPACE" \
  --cosmos-account "$COSMOS_ACCOUNT_NAME" \
  --resource-group "$RG_NAME"

echo "  Local development configured"

# ─────────────────────────────────────────────────────────────────────
# Step 9: Verify
# ─────────────────────────────────────────────────────────────────────

write_step "9/9" "Verification"

echo "  Running verify-mvp-setup.sh..."
bash "$REPO_ROOT/scripts/verify-mvp-setup.sh" "$RG_NAME" || true

# ─────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  BOOTSTRAP COMPLETE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Prefix:          $PREFIX"
echo "  Resource Group:  $RG_NAME"
echo "  Location:        $LOCATION"
echo "  ACR:             $ACR_NAME"
echo "  Image:           $CONTAINER_IMAGE"
echo ""
echo "  MANUAL STEP REQUIRED:"
echo "  Deploy AI models in Azure AI Foundry:"
echo "    1. Go to https://ai.azure.com/"
echo "    2. Select project: ${PREFIX}-project"
echo "    3. Deploy these models:"
echo "       - phi-4             (Standard)   <- classification"
echo "       - mistral-document-ai-2512 (MaaS) <- OCR"
echo "       - text-embedding-3-small (Standard) <- embeddings"
echo ""
echo "  After deploying models, verify:"
echo "    uv run python scripts/list_deployments.py"
echo ""
echo "  Run locally:"
echo "    uv run uvicorn classymail.app:app --reload --port 8000"
echo ""
echo "  Full guide: docs/DEPLOY_FROM_SCRATCH.md"
echo ""
