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

# 4. Terraform Validation (if infra/ files changed)
$tfChanged = git diff --cached --name-only -- 'infra/*.tf' 2>$null
if (-not $tfChanged) {
    $tfChanged = git diff origin/main --name-only -- 'infra/*.tf' 2>$null
}
if ($tfChanged) {
    Write-Host "Terraform files changed — running validation..."
    pwsh scripts/validate_terraform.ps1 -SkipInit:$false
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Terraform validation failed."
        exit 1
    }
} else {
    Write-Host "No Terraform changes detected, skipping validation." -ForegroundColor DarkGray
}

Write-Host "All checks passed!" -ForegroundColor Green
exit 0
