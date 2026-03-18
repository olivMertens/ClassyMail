#!/usr/bin/env bash
set -euo pipefail

MI_CLIENT_ID="${1:-}" # Managed Identity client ID
STORAGE_ACCOUNT_NAME="${2:-}" # Storage account name

if [[ -z "$MI_CLIENT_ID" || -z "$STORAGE_ACCOUNT_NAME" ]]; then
  echo "Usage: $0 <managed-identity-client-id> <storage-account-name>" >&2
  exit 1
fi

STORAGE_ID="$(az storage account show --name "$STORAGE_ACCOUNT_NAME" --query id -o tsv)"

az role assignment create \
  --assignee "$MI_CLIENT_ID" \
  --role "Storage Blob Data Reader" \
  --scope "$STORAGE_ID"
