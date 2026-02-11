#!/usr/bin/env bash
# scripts/validate_terraform.sh
# Validates Terraform configuration: fmt, validate, and optional security checks.
# Usage: bash scripts/validate_terraform.sh [--fix] [--skip-init]
#
# Exit codes:
#   0 = all checks passed
#   1 = one or more checks failed

set -uo pipefail

INFRA_DIR="${INFRA_DIR:-$(cd "$(dirname "$0")/../infra" && pwd)}"
FIX=false
SKIP_INIT=false
FAILED=false

for arg in "$@"; do
    case $arg in
        --fix) FIX=true ;;
        --skip-init) SKIP_INIT=true ;;
    esac
done

info()    { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
ok()      { echo -e "\033[1;32m[OK]\033[0m    $*"; }
warn()    { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
fail()    { echo -e "\033[1;31m[FAIL]\033[0m  $*"; FAILED=true; }

echo ""
echo "========================================"
echo " Terraform Validation Suite"
echo "========================================"
echo " Directory: $INFRA_DIR"
echo ""

# --- 1. Check terraform installed ---
info "Checking Terraform installation..."
TF_VERSION=$(terraform version 2>&1 | head -1) || { fail "Terraform not installed"; exit 1; }
ok "Terraform: $TF_VERSION"

# --- 2. Format check ---
info "Checking Terraform formatting..."
if $FIX; then
    terraform fmt -recursive "$INFRA_DIR" >/dev/null 2>&1 && ok "Formatting fixed" || fail "terraform fmt failed"
else
    FMT_OUTPUT=$(terraform fmt -check -recursive -diff "$INFRA_DIR" 2>&1)
    if [[ $? -ne 0 ]]; then
        fail "Terraform files are not formatted. Run with --fix or: terraform fmt -recursive infra/"
        echo "$FMT_OUTPUT"
    else
        ok "All .tf files properly formatted"
    fi
fi

# --- 3. Init ---
pushd "$INFRA_DIR" > /dev/null || exit 1

if ! $SKIP_INIT; then
    info "Running terraform init -backend=false ..."
    INIT_OUTPUT=$(terraform init -backend=false -input=false -no-color 2>&1)
    if [[ $? -ne 0 ]]; then
        fail "terraform init failed:"
        echo "$INIT_OUTPUT"
    else
        ok "terraform init succeeded"
    fi
else
    info "Skipping init (--skip-init)"
fi

# --- 4. Validate ---
info "Running terraform validate..."
VALIDATE_OUTPUT=$(terraform validate -no-color 2>&1)
if [[ $? -ne 0 ]]; then
    fail "terraform validate failed:"
    echo "$VALIDATE_OUTPUT"
else
    ok "terraform validate passed"
fi

# --- 5. Anti-pattern checks ---
info "Checking for known Terraform anti-patterns..."

# 5a. azurerm_cosmosdb_sql_container (no vector support)
if grep -rn 'azurerm_cosmosdb_sql_container' "$INFRA_DIR"/*.tf 2>/dev/null; then
    warn "Found azurerm_cosmosdb_sql_container (no vectorEmbeddingPolicy support). Consider azapi_resource."
fi

# 5b. Hardcoded secrets
if grep -rPn '(password|secret|api_key)\s*=\s*"[^"]{8,}' "$INFRA_DIR"/*.tf 2>/dev/null; then
    fail "Potential hardcoded secrets found!"
fi

# 5c. tfvars.example
if [[ -f "$INFRA_DIR/terraform.tfvars.example" ]]; then
    ok "terraform.tfvars.example present"
else
    warn "No terraform.tfvars.example found"
fi

# 5d. .gitignore check
GITIGNORE="$(dirname "$INFRA_DIR")/.gitignore"
if [[ -f "$GITIGNORE" ]]; then
    if grep -q 'terraform\.tfvars' "$GITIGNORE" 2>/dev/null; then
        ok ".gitignore covers terraform.tfvars"
    else
        warn "terraform.tfvars may not be in .gitignore"
    fi
fi

# 5e. tfstate tracked
if git -C "$(dirname "$INFRA_DIR")" ls-files --error-unmatch "infra/terraform.tfstate" >/dev/null 2>&1; then
    fail "terraform.tfstate is tracked by git! Remove with: git rm --cached infra/terraform.tfstate"
fi

popd > /dev/null || true

# --- Summary ---
echo ""
echo "========================================"
if $FAILED; then
    fail "Terraform validation FAILED."
    exit 1
else
    ok "All Terraform validation checks passed!"
    exit 0
fi
