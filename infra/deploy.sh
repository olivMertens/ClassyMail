#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ClassyMail — Terraform deploy helper (Linux/macOS).
#
# Provisions the full ClassyMail Azure stack via Terraform and applies it to
# the remote subscription: Storage + Event Grid ingestion, Service Bus queue,
# AI Foundry (account + project), Cosmos DB (serverless, vector), Container
# Apps environment with the API + worker apps (KEDA Service Bus scaler), the
# user-assigned managed identity, all RBAC role assignments, the corporate
# tag/policy assignments and — when --github-repo is set — the GitHub OIDC
# CI/CD identity.
#
# Parameters are layered on top of any infra/terraform.tfvars using Terraform
# -var flags (CLI values win, tfvars is never overwritten). The script is
# idempotent — safe to re-run. After a successful apply it discovers the app
# managed identity and verifies/adds only the MISSING RBAC role assignments.
#
# Companion full-from-scratch flow (also builds & pushes the image, writes
# secrets.env and assigns local-dev RBAC): scripts/bootstrap.sh
#
# Usage:
#   bash infra/deploy.sh --container-image myacr.azurecr.io/classymail:latest \
#     --acr-name myacr --acr-resource-group my-acr-rg --detect-local-ip --auto-approve
#
#   # Discover an existing RG and add only the missing role assignments:
#   bash infra/deploy.sh --verify-only --resource-group classymail-rg
#
#   # Dry run:
#   bash infra/deploy.sh --plan-only
# ---------------------------------------------------------------------------
set -euo pipefail

# Resolve the infra directory from the script location so it can be run from
# anywhere (e.g. ./infra/deploy.sh from repo root, or directly).
INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Parameters ────────────────────────────────────────────────────────
TENANT_ID=""
SUBSCRIPTION_ID=""
PREFIX=""
LOCATION=""
RESOURCE_GROUP=""
CONTAINER_IMAGE=""
ACR_NAME=""
ACR_RESOURCE_GROUP=""
GITHUB_REPO=""
GITHUB_ENVIRONMENT=""
ALLOWED_IP_RANGES=""
DETECT_LOCAL_IP=false
ORGANIZATION_NAME=""
COSMOS_USE_RBAC=""
CUSTOM_TAGS_ENABLED=""
TAG_POLICY_ENABLED=""
SECURITY_COST_POLICY_ENABLED=""
TAG_POLICY_SCOPE=""
ENABLE_MODEL_DEPLOYMENTS=""
DEPLOY_OPTIONAL_MODELS=""
DEPLOY_LANGUAGE_SERVICE=""
DEPLOY_DOCUMENT_INTELLIGENCE=""
SKIP_PROVIDER_REGISTRATION=false
VERIFY_ONLY=false
SKIP_ROLE_VERIFICATION=false
PLAN_ONLY=false
AUTO_APPROVE=false

usage() {
  cat <<'EOF'
ClassyMail Terraform deploy helper.

Options:
  --tenant-id <guid>                     Azure AD tenant (defaults to current CLI context)
  --subscription-id <guid>               Azure subscription (defaults to current CLI context)
  --prefix <name>                        Resource-name prefix (TF default: classymail)
  --location <region>                    Azure region (TF default: swedencentral)
  --resource-group <name>                Existing RG for discovery/verify (default: <prefix>-rg)
  --container-image <ref>                Image for API + worker Container Apps (required by TF)
  --acr-name <name>                      ACR to grant AcrPull (and AcrPush to CI/CD)
  --acr-resource-group <name>            ACR resource group (used with --acr-name)
  --github-repo <owner/repo>             Create GitHub OIDC CI/CD identity
  --github-environment <name>            GitHub environment for the OIDC subject claim
  --allowed-ip-ranges <csv>              Comma-separated IPs/CIDRs for the Cosmos firewall
  --detect-local-ip                      Add this machine's public IP to the Cosmos firewall
  --organization-name <name>             Organization name shown in the UI
  --cosmos-use-rbac <true|false>         Cosmos data-plane via Entra RBAC (TF default: true)
  --custom-tags-enabled <true|false>     Apply corporate tags (TF default: true)
  --tag-policy-enabled <true|false>      Mandatory-tag auto-fill policy (TF default: true)
  --security-cost-policy-enabled <bool>  SecurityControl/CostControl policy (TF default: true)
  --tag-policy-scope <resource_group|subscription>   Policy scope (TF default: resource_group)
  --enable-model-deployments <bool>      Deploy Phi-4 + Mistral OCR (TF default: false)
  --deploy-optional-models <bool>        Deploy optional models (TF default: false)
  --deploy-language-service <bool>       Deploy Azure AI Language (TF default: false)
  --deploy-document-intelligence <bool>  Deploy Document Intelligence (TF default: false)
  --skip-provider-registration           Skip Azure resource-provider registration
  --verify-only                          Discovery mode: verify/add roles only, no Terraform
  --skip-role-verification               Skip the post-apply role verification
  --plan-only                            Run init + plan only (dry run)
  --auto-approve                         Apply without the confirmation prompt
  -h, --help                             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tenant-id)                    TENANT_ID="$2"; shift 2 ;;
    --subscription-id)              SUBSCRIPTION_ID="$2"; shift 2 ;;
    --prefix)                       PREFIX="$2"; shift 2 ;;
    --location)                     LOCATION="$2"; shift 2 ;;
    --resource-group)               RESOURCE_GROUP="$2"; shift 2 ;;
    --container-image)              CONTAINER_IMAGE="$2"; shift 2 ;;
    --acr-name)                     ACR_NAME="$2"; shift 2 ;;
    --acr-resource-group)           ACR_RESOURCE_GROUP="$2"; shift 2 ;;
    --github-repo)                  GITHUB_REPO="$2"; shift 2 ;;
    --github-environment)           GITHUB_ENVIRONMENT="$2"; shift 2 ;;
    --allowed-ip-ranges)            ALLOWED_IP_RANGES="$2"; shift 2 ;;
    --detect-local-ip)              DETECT_LOCAL_IP=true; shift ;;
    --organization-name)            ORGANIZATION_NAME="$2"; shift 2 ;;
    --cosmos-use-rbac)              COSMOS_USE_RBAC="$2"; shift 2 ;;
    --custom-tags-enabled)          CUSTOM_TAGS_ENABLED="$2"; shift 2 ;;
    --tag-policy-enabled)           TAG_POLICY_ENABLED="$2"; shift 2 ;;
    --security-cost-policy-enabled) SECURITY_COST_POLICY_ENABLED="$2"; shift 2 ;;
    --tag-policy-scope)             TAG_POLICY_SCOPE="$2"; shift 2 ;;
    --enable-model-deployments)     ENABLE_MODEL_DEPLOYMENTS="$2"; shift 2 ;;
    --deploy-optional-models)       DEPLOY_OPTIONAL_MODELS="$2"; shift 2 ;;
    --deploy-language-service)      DEPLOY_LANGUAGE_SERVICE="$2"; shift 2 ;;
    --deploy-document-intelligence) DEPLOY_DOCUMENT_INTELLIGENCE="$2"; shift 2 ;;
    --skip-provider-registration)   SKIP_PROVIDER_REGISTRATION=true; shift ;;
    --verify-only)                  VERIFY_ONLY=true; shift ;;
    --skip-role-verification)       SKIP_ROLE_VERIFICATION=true; shift ;;
    --plan-only)                    PLAN_ONLY=true; shift ;;
    --auto-approve)                 AUTO_APPROVE=true; shift ;;
    -h|--help)                      usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

require_cmd() {
  if ! command -v "$1" &>/dev/null; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

require_cmd az
require_cmd terraform

# ── Discovery + idempotent role verification ──────────────────────────
# Given an existing resource group, confirm it exists, discover the app
# user-assigned managed identity ('<prefix>-id') and the key resources, then
# verify each expected RBAC role assignment and add ONLY the missing ones.
# Cosmos DB data-plane access uses a Terraform-managed custom SQL role, so it
# is verified and reported (warn) rather than created here.
#
# Canonical role list (source: docs/RBAC_AUDIT.md + infra/main.tf):
#   Storage Blob Data Contributor        -> storage account      (always)
#   Azure Service Bus Data Receiver      -> Service Bus namespace (always)
#   Azure Service Bus Data Sender        -> Service Bus namespace (always)
#   Cognitive Services User              -> AI Foundry account    (always)
#   AcrPull                              -> Container Registry    (if present)
#   Cognitive Services Language Reader   -> Language service      (if present)
#   Cosmos SQL custom role (data-plane)  -> Cosmos DB account     (verify/warn)
PRINCIPAL_ID=""
ROLE_ADDED=0
ROLE_PRESENT=0
ROLE_SKIPPED=0
ROLE_FAILED=0

ensure_role() {
  local scope="$1" role="$2" desc="$3"
  if [[ -z "$scope" ]]; then
    echo "  [skip] $desc absent - '$role' not applicable"
    ROLE_SKIPPED=$((ROLE_SKIPPED + 1))
    return 0
  fi
  local existing
  existing=$(az role assignment list --assignee "$PRINCIPAL_ID" --scope "$scope" \
    --query "[?roleDefinitionName=='$role'] | [0].id" -o tsv 2>/dev/null || true)
  if [[ -n "$existing" ]]; then
    echo "  [ok]  '$role' already on $desc"
    ROLE_PRESENT=$((ROLE_PRESENT + 1))
    return 0
  fi
  echo "  [add] '$role' -> $desc"
  if az role assignment create --assignee-object-id "$PRINCIPAL_ID" \
      --assignee-principal-type ServicePrincipal --role "$role" --scope "$scope" -o none 2>/dev/null; then
    ROLE_ADDED=$((ROLE_ADDED + 1))
  else
    echo "  WARNING: failed to add '$role' on $desc" >&2
    ROLE_FAILED=$((ROLE_FAILED + 1))
  fi
  return 0
}

verify_roles() {
  local rg="$1" prefix="$2" strict="$3"
  echo ""
  echo "== Discovery & role verification =="
  echo "  Resource group : $rg"

  if ! az group show -n "$rg" -o none 2>/dev/null; then
    if [[ "$strict" == true ]]; then echo "Resource group '$rg' not found." >&2; exit 1; fi
    echo "  WARNING: resource group '$rg' not found - skipping role verification." >&2
    return 0
  fi
  echo "  [ok]  resource group exists"

  # Derived resource names — must match the naming in infra/main.tf.
  local clean_prefix identity_name storage_name sb_namespace cosmos_name ai_name
  clean_prefix="${prefix//[-_]/}"
  identity_name="${prefix}-id"
  storage_name="${clean_prefix}st"
  sb_namespace="${prefix}-sbus"
  cosmos_name="${prefix}-cosmos"
  ai_name="${prefix}-aifoundry"

  PRINCIPAL_ID=$(az identity show -g "$rg" -n "$identity_name" --query principalId -o tsv 2>/dev/null || true)
  if [[ -z "$PRINCIPAL_ID" ]]; then
    if [[ "$strict" == true ]]; then echo "Managed identity '$identity_name' not found in '$rg'." >&2; exit 1; fi
    echo "  WARNING: managed identity '$identity_name' not found - skipping role verification." >&2
    return 0
  fi
  echo "  [ok]  identity '$identity_name' principalId: $PRINCIPAL_ID"

  # Resource scopes (empty => resource absent => role skipped).
  local storage_id sb_id ai_id cosmos_id lang_id acr_id
  storage_id=$(az storage account show -g "$rg" -n "$storage_name" --query id -o tsv 2>/dev/null || true)
  sb_id=$(az servicebus namespace show -g "$rg" -n "$sb_namespace" --query id -o tsv 2>/dev/null || true)
  ai_id=$(az cognitiveservices account show -g "$rg" -n "$ai_name" --query id -o tsv 2>/dev/null || true)
  cosmos_id=$(az cosmosdb show -g "$rg" -n "$cosmos_name" --query id -o tsv 2>/dev/null || true)
  lang_id=$(az cognitiveservices account list -g "$rg" --query "[?kind=='TextAnalytics'] | [0].id" -o tsv 2>/dev/null || true)

  if [[ -n "$ACR_NAME" ]]; then
    if [[ -n "$ACR_RESOURCE_GROUP" ]]; then
      acr_id=$(az acr show -n "$ACR_NAME" -g "$ACR_RESOURCE_GROUP" --query id -o tsv 2>/dev/null || true)
    else
      acr_id=$(az acr show -n "$ACR_NAME" --query id -o tsv 2>/dev/null || true)
    fi
  else
    acr_id=$(az acr list -g "$rg" --query "[0].id" -o tsv 2>/dev/null || true)
  fi

  ROLE_ADDED=0; ROLE_PRESENT=0; ROLE_SKIPPED=0; ROLE_FAILED=0
  ensure_role "$storage_id" "Storage Blob Data Contributor"   "Storage ($storage_name)"
  ensure_role "$sb_id"      "Azure Service Bus Data Receiver" "Service Bus ($sb_namespace)"
  ensure_role "$sb_id"      "Azure Service Bus Data Sender"   "Service Bus ($sb_namespace)"
  ensure_role "$ai_id"      "Cognitive Services User"         "AI Foundry ($ai_name)"
  ensure_role "$acr_id"     "AcrPull"                         "Container Registry"
  if [[ -n "$lang_id" ]]; then
    ensure_role "$lang_id" "Cognitive Services Language Reader" "Language service"
  fi

  # Cosmos DB data-plane: Terraform owns the custom SQL role — verify & warn only.
  if [[ -n "$cosmos_id" ]]; then
    local cosmos_match
    cosmos_match=$(az cosmosdb sql role assignment list --account-name "$cosmos_name" \
      --resource-group "$rg" --query "[?principalId=='$PRINCIPAL_ID'] | [0].id" -o tsv 2>/dev/null || true)
    if [[ -n "$cosmos_match" ]]; then
      echo "  [ok]  Cosmos SQL data-plane role present ($cosmos_name)"
    else
      echo "  WARNING: Cosmos SQL data-plane role MISSING on $cosmos_name - run 'terraform apply' (Terraform-managed custom role)." >&2
    fi
  else
    echo "  [skip] Cosmos account absent - data-plane role not applicable"
  fi

  echo "  Summary: $ROLE_ADDED added, $ROLE_PRESENT present, $ROLE_SKIPPED skipped, $ROLE_FAILED failed"
  if [[ "$ROLE_FAILED" -gt 0 ]]; then
    echo "  WARNING: Some role assignments could not be created - need Owner/User Access Administrator." >&2
  fi
  return 0
}

show_out() {
  local label="$1" key="$2" val
  val=$(terraform "-chdir=$INFRA_DIR" output -raw "$key" 2>/dev/null || true)
  if [[ -n "$val" ]]; then printf "  %-26s %s\n" "$label" "$val"; fi
  return 0
}

# ── Azure login ───────────────────────────────────────────────────────
echo "== Azure login =="
if [[ -z "$TENANT_ID" ]]; then
  CURRENT_TENANT=$(az account show --query tenantId -o tsv 2>/dev/null || true)
  if [[ -n "$CURRENT_TENANT" ]]; then
    echo "Already logged in to tenant $CURRENT_TENANT. Skipping interactive login."
    TENANT_ID="$CURRENT_TENANT"
  else
    read -rp "Tenant ID (GUID) (leave blank to use default): " TENANT_ID
  fi
fi

if [[ -n "$TENANT_ID" ]]; then
  CURRENT_TENANT=$(az account show --query tenantId -o tsv 2>/dev/null || true)
  if [[ "$CURRENT_TENANT" == "$TENANT_ID" ]]; then
    echo "Already logged in to requested tenant."
  else
    echo "Parameters request specific Tenant $TENANT_ID. Attempting login (may prompt)..."
    az login --tenant "$TENANT_ID" >/dev/null
  fi
else
  if az account show &>/dev/null; then
    echo "Already logged in. Skipping login."
  else
    az login >/dev/null
  fi
fi

# ── Azure subscription ────────────────────────────────────────────────
echo "== Azure subscription =="
if [[ -z "$SUBSCRIPTION_ID" ]]; then
  read -rp "Subscription ID (GUID) (leave blank to use current): " SUBSCRIPTION_ID
fi

if [[ -n "$SUBSCRIPTION_ID" ]]; then
  az account set --subscription "$SUBSCRIPTION_ID" >/dev/null
fi

DETECTED_SUB=$(az account show --query id -o tsv | tr -d '[:space:]')
if [[ -z "$DETECTED_SUB" ]]; then
  echo "Could not detect subscription from Azure CLI. Run 'az account show' to verify you're logged in." >&2
  exit 1
fi

echo "Using subscription: $DETECTED_SUB"

# Effective prefix / resource group used by discovery & post-apply verification.
EFFECTIVE_PREFIX="${PREFIX:-classymail}"
if [[ -z "$RESOURCE_GROUP" ]]; then RESOURCE_GROUP="${EFFECTIVE_PREFIX}-rg"; fi

# ── Verify-only / discovery mode: skip Terraform entirely ─────────────
if [[ "$VERIFY_ONLY" == true ]]; then
  verify_roles "$RESOURCE_GROUP" "$EFFECTIVE_PREFIX" true
  echo ""
  echo "Verification complete."
  exit 0
fi

# ── Register required resource providers ──────────────────────────────
if [[ "$SKIP_PROVIDER_REGISTRATION" != true ]]; then
  echo "== Resource providers =="
  for p in \
    Microsoft.Storage \
    Microsoft.ServiceBus \
    Microsoft.DocumentDB \
    Microsoft.CognitiveServices \
    Microsoft.App \
    Microsoft.EventGrid \
    Microsoft.Insights \
    Microsoft.OperationalInsights \
    Microsoft.ManagedIdentity \
    Microsoft.ContainerRegistry; do
    state=$(az provider show --namespace "$p" --query registrationState -o tsv 2>/dev/null || true)
    if [[ "$state" == "Registered" ]]; then
      echo "  already registered: $p"
    else
      echo "  registering: $p ..."
      az provider register --namespace "$p" >/dev/null || true
    fi
  done
  echo "  Providers registered (propagation may take 1-5 min)."
fi

# ── Fortinet / corporate firewall workaround ──────────────────────────
# The azapi provider v1.x defaults use_msi=true, which makes Terraform call
# the IMDS endpoint (169.254.169.254). Corporate firewalls such as FortiGuard
# IPS block this endpoint, causing a 403 that crashes the credential chain.
# Setting ARM_USE_MSI=false prevents the attempt. The same flags are also set
# in provider blocks in main.tf.
export ARM_USE_MSI="false"
export ARM_USE_OIDC="false"

# ── Build the Terraform -var arguments from supplied parameters ───────
# Only explicitly-provided values are passed; everything else falls back to
# terraform.tfvars (if present) or the variable defaults in the .tf files.
VAR_ARGS=(-var "subscription_id=$DETECTED_SUB")
add_var() { VAR_ARGS+=(-var "$1=$2"); }

[[ -n "$PREFIX" ]]             && add_var prefix "$PREFIX"
[[ -n "$LOCATION" ]]          && add_var location "$LOCATION"
[[ -n "$ACR_NAME" ]]          && add_var acr_name "$ACR_NAME"
[[ -n "$ACR_RESOURCE_GROUP" ]] && add_var acr_resource_group "$ACR_RESOURCE_GROUP"
[[ -n "$GITHUB_REPO" ]]       && add_var github_repo "$GITHUB_REPO"
[[ -n "$GITHUB_ENVIRONMENT" ]] && add_var github_environment "$GITHUB_ENVIRONMENT"
[[ -n "$ORGANIZATION_NAME" ]] && add_var organization_name "$ORGANIZATION_NAME"
[[ -n "$TAG_POLICY_SCOPE" ]]  && add_var tag_policy_scope "$TAG_POLICY_SCOPE"

# Boolean toggles — pass only when supplied, so Terraform defaults win otherwise.
[[ -n "$COSMOS_USE_RBAC" ]]              && add_var cosmos_use_rbac "$COSMOS_USE_RBAC"
[[ -n "$CUSTOM_TAGS_ENABLED" ]]          && add_var custom_tags_enabled "$CUSTOM_TAGS_ENABLED"
[[ -n "$TAG_POLICY_ENABLED" ]]           && add_var tag_policy_enabled "$TAG_POLICY_ENABLED"
[[ -n "$SECURITY_COST_POLICY_ENABLED" ]] && add_var security_cost_policy_enabled "$SECURITY_COST_POLICY_ENABLED"
[[ -n "$ENABLE_MODEL_DEPLOYMENTS" ]]     && add_var enable_model_deployments "$ENABLE_MODEL_DEPLOYMENTS"
[[ -n "$DEPLOY_OPTIONAL_MODELS" ]]       && add_var deploy_optional_models "$DEPLOY_OPTIONAL_MODELS"
[[ -n "$DEPLOY_LANGUAGE_SERVICE" ]]      && add_var deploy_language_service "$DEPLOY_LANGUAGE_SERVICE"
[[ -n "$DEPLOY_DOCUMENT_INTELLIGENCE" ]] && add_var deploy_document_intelligence "$DEPLOY_DOCUMENT_INTELLIGENCE"

# Cosmos DB firewall allow-list (optionally including the local public IP).
IPS=()
if [[ -n "$ALLOWED_IP_RANGES" ]]; then
  IFS=',' read -ra _ips <<< "$ALLOWED_IP_RANGES"
  for i in "${_ips[@]}"; do
    i="$(echo "$i" | tr -d '[:space:]')"
    [[ -n "$i" ]] && IPS+=("$i")
  done
fi
if [[ "$DETECT_LOCAL_IP" == true ]]; then
  MYIP=$(curl -fsS --max-time 5 https://ifconfig.me/ip 2>/dev/null | tr -d '[:space:]' || true)
  if [[ -n "$MYIP" ]]; then
    echo "  detected local public IP: $MYIP"
    IPS+=("$MYIP")
  else
    echo "  WARNING: could not auto-detect public IP (continuing without it)." >&2
  fi
fi
if [[ ${#IPS[@]} -gt 0 ]]; then
  HCL='['
  for i in "${IPS[@]}"; do HCL+="\"$i\","; done
  HCL="${HCL%,}]"
  add_var allowed_ip_ranges "$HCL"
fi

# container_image is REQUIRED by Terraform (validation rejects ""). Resolve it
# from the flag, else from terraform.tfvars, else fall back to a placeholder.
TFVARS_PATH="$INFRA_DIR/terraform.tfvars"
TFVARS_HAS_IMAGE=false
if [[ -f "$TFVARS_PATH" ]] && grep -Eq '^[[:space:]]*container_image[[:space:]]*=[[:space:]]*"[^"]+"' "$TFVARS_PATH"; then
  TFVARS_HAS_IMAGE=true
fi
if [[ -n "$CONTAINER_IMAGE" ]]; then
  add_var container_image "$CONTAINER_IMAGE"
elif [[ "$TFVARS_HAS_IMAGE" == false ]]; then
  PLACEHOLDER='mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
  echo "WARNING: No --container-image supplied and terraform.tfvars has no container_image." >&2
  echo "WARNING: Using placeholder '$PLACEHOLDER'. Build & push your image, then re-run with --container-image." >&2
  add_var container_image "$PLACEHOLDER"
fi

# ── Terraform init / plan / apply ─────────────────────────────────────
echo "== Terraform =="
terraform "-chdir=$INFRA_DIR" init -upgrade

terraform "-chdir=$INFRA_DIR" plan "${VAR_ARGS[@]}" -out tfplan

if [[ "$PLAN_ONLY" == true ]]; then
  echo "Plan only — skipping apply."
  exit 0
fi

if [[ "$AUTO_APPROVE" != true ]]; then
  read -rp "Apply this plan? (y/N) " answer
  if [[ ! "$answer" =~ ^[yY](es)?$ ]]; then
    echo "Skipped apply."
    exit 0
  fi
fi

terraform "-chdir=$INFRA_DIR" apply tfplan

# ── Surface the key outputs (endpoints, identity, CI/CD secrets) ──────
echo ""
echo "== Deployment outputs =="
show_out "AI Foundry endpoint"        "AI_ENDPOINT"
show_out "Cosmos endpoint"            "AZURE_COSMOS_ENDPOINT"
show_out "Service Bus FQDN"           "AZURE_SERVICE_BUS_FQDN"
show_out "Service Bus queue"          "AZURE_SERVICE_BUS_QUEUE"
show_out "Storage blob URL"           "AZURE_STORAGE_ACCOUNT_URL"
show_out "Storage container"          "AZURE_STORAGE_CONTAINER"
show_out "App identity clientId"      "APP_ID_CLIENT_ID"
show_out "Language endpoint"          "LANGUAGE_ENDPOINT"
show_out "Doc Intelligence endpoint"  "DOCUMENT_INTELLIGENCE_ENDPOINT"

# Best-effort: public API URL of the api Container App.
API_FQDN=$(az containerapp list -g "$RESOURCE_GROUP" \
  --query "[?contains(name, 'api')].properties.configuration.ingress.fqdn | [0]" -o tsv 2>/dev/null || true)
if [[ -n "$API_FQDN" ]]; then
  printf "  %-26s https://%s\n" "API URL" "$API_FQDN"
fi

# CI/CD OIDC identity (only when github_repo was set).
if [[ -n "$GITHUB_REPO" ]]; then
  echo ""
  echo "  GitHub Actions OIDC — set these as repository secrets:"
  show_out "AZURE_CLIENT_ID" "CICD_CLIENT_ID"
  show_out "AZURE_TENANT_ID" "CICD_TENANT_ID"
  printf "  %-26s %s\n" "AZURE_SUBSCRIPTION_ID" "$DETECTED_SUB"
  echo "  (details: docs/CICD_GITHUB.md)"
fi

# ── Post-apply discovery + role verification (adds only missing) ──────
if [[ "$SKIP_ROLE_VERIFICATION" != true ]]; then
  verify_roles "$RESOURCE_GROUP" "$EFFECTIVE_PREFIX" false
fi

echo ""
echo "Deployment complete."
if [[ -z "$CONTAINER_IMAGE" && "$TFVARS_HAS_IMAGE" == false ]]; then
  echo "NOTE: A placeholder image was deployed. Re-run with --container-image <registry/repo:tag> once your image is pushed."
fi
