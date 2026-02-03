# scripts/pre-push.ps1
Write-Host "Running pre-push checks..." -ForegroundColor Cyan

# 1. Linting with Ruff
Write-Host "Running Ruff..."
uv run ruff check .
if ($LASTEXITCODE -ne 0) {
    Write-Error "Ruff failed. Please fix lint errors."
    exit 1
}

# 2. Tests
Write-Host "Running Smoke Tests..."
uv run pytest -q tests/test_smoke.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "Tests failed."
    exit 1
}

# 3. I18N Check
Write-Host "Verifying I18N Locales..."
python scripts/check_i18n.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "I18N verification failed. Locales are not synchronized."
    exit 1
}

Write-Host "All checks passed!" -ForegroundColor Green
exit 0
