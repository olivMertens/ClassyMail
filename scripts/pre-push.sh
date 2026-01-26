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

echo "All checks passed!"
exit 0
