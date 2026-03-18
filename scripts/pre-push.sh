#!/bin/sh
# scripts/pre-push.sh
# Run this before pushing to ensure quality.
# To install as git hook:
#   ln -s ../../scripts/pre-push.sh .git/hooks/pre-push

echo " Running pre-push checks..."

# 1. Linting with Ruff
echo "Running Ruff..."
if ! uv run ruff check .; then
    echo "Ruff failed. Please fix lint errors."
    exit 1
fi

# 2. Tests (Fast check)
echo "Running Smoke Tests..."
if ! uv run pytest -q tests/test_smoke.py; then
    echo "Tests failed."
    exit 1
fi

# 3. Mermaid Validation
echo "Validating Mermaid diagrams..."
if ! uv run python scripts/validate_mermaid.py docs/*.md README.md; then
    echo "Mermaid validation failed. Fix diagram syntax."
    exit 1
fi

# 4. Terraform Validation (if infra/ files changed)
TF_CHANGED=$(git diff --cached --name-only -- 'infra/*.tf' 2>/dev/null)
if [[ -z "$TF_CHANGED" ]]; then
    TF_CHANGED=$(git diff origin/main --name-only -- 'infra/*.tf' 2>/dev/null)
fi
if [[ -n "$TF_CHANGED" ]]; then
    echo "Terraform files changed — running validation..."
    if ! bash scripts/validate_terraform.sh; then
        echo "Terraform validation failed."
        exit 1
    fi
else
    echo "No Terraform changes detected, skipping validation."
fi

echo "All checks passed!"
exit 0
