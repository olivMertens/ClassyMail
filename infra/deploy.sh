#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ClassyMail — Terraform deploy helper (Linux/macOS)
#
# Usage:
#   bash infra/deploy.sh
#   bash infra/deploy.sh --tenant-id <GUID> --subscription-id <GUID>
#   bash infra/deploy.sh --auto-approve
# ---------------------------------------------------------------------------
set -euo pipefail

TENANT_ID=""
SUBSCRIPTION_ID=""
AUTO_APPROVE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tenant-id)       TENANT_ID="$2"; shift 2 ;;
    --subscription-id) SUBSCRIPTION_ID="$2"; shift 2 ;;
    --auto-approve)    AUTO_APPROVE=true; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
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

# ── Fortinet / corporate firewall workaround ──────────────────────────
# The azapi provider v1.x defaults use_msi=true, which makes Terraform
# call the IMDS endpoint (169.254.169.254). Corporate firewalls such as
# FortiGuard IPS block this endpoint, causing a 403 that crashes the
# credential chain. Setting ARM_USE_MSI=false prevents the attempt.
# The same flags are also set in provider blocks in main.tf.
export ARM_USE_MSI="false"
export ARM_USE_OIDC="false"
# ──────────────────────────────────────────────────────────────────────

echo "== Terraform =="
terraform -chdir=infra init -upgrade
terraform -chdir=infra plan -var "subscription_id=$DETECTED_SUB" -out tfplan

if [[ "$AUTO_APPROVE" == true ]]; then
  terraform -chdir=infra apply -auto-approve tfplan
  exit 0
fi

read -rp "Apply this plan? (y/N) " answer
if [[ "$answer" =~ ^[yY](es)?$ ]]; then
  terraform -chdir=infra apply tfplan
else
  echo "Skipped apply."
fi
