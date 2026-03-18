# scripts/validate_terraform.ps1
# Validates Terraform configuration: fmt, validate, and optional security checks.
# Usage: pwsh scripts/validate_terraform.ps1 [-Fix] [-SkipInit]
#
# Exit codes:
#   0 = all checks passed
#   1 = one or more checks failed

param(
    [switch]$Fix,       # Auto-fix formatting issues
    [switch]$SkipInit,  # Skip terraform init (faster if already initialized)
    [string]$InfraDir   # Override infra directory (default: infra/)
)

$ErrorActionPreference = "Continue"
$script:failed = $false

function Info($msg)  { Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Ok($msg)    { Write-Host "[OK]    $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Fail($msg)  { Write-Host "[FAIL]  $msg" -ForegroundColor Red; $script:failed = $true }

# Determine infra directory
if (-not $InfraDir) {
    $InfraDir = Join-Path $PSScriptRoot ".." "infra"
}
$InfraDir = Resolve-Path $InfraDir -ErrorAction Stop

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Terraform Validation Suite" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Directory: $InfraDir"
Write-Host ""

# --- 1. Check terraform is installed ---
Info "Checking Terraform installation..."
$tfVersion = terraform version 2>&1 | Select-Object -First 1
if ($LASTEXITCODE -ne 0) {
    Fail "Terraform is not installed or not in PATH."
    exit 1
}
Ok "Terraform: $tfVersion"

# --- 2. Format check ---
Info "Checking Terraform formatting..."
if ($Fix) {
    terraform fmt -recursive $InfraDir 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok "Formatting fixed (auto-fix mode)" }
    else { Fail "terraform fmt -recursive failed" }
} else {
    $fmtOutput = terraform fmt -check -recursive -diff $InfraDir 2>&1
    if ($LASTEXITCODE -ne 0) {
        Fail "Terraform files are not formatted. Run with -Fix or: terraform fmt -recursive infra/"
        Write-Host $fmtOutput -ForegroundColor Yellow
    } else {
        Ok "All .tf files properly formatted"
    }
}

# --- 3. Init (required for validate) ---
Push-Location $InfraDir
try {
    if (-not $SkipInit) {
        Info "Running terraform init -backend=false ..."
        $initOutput = terraform init -backend=false -input=false -no-color 2>&1
        if ($LASTEXITCODE -ne 0) {
            Fail "terraform init failed:"
            Write-Host ($initOutput | Out-String) -ForegroundColor Red
        } else {
            Ok "terraform init succeeded"
        }
    } else {
        Info "Skipping init (--SkipInit)"
    }

    # --- 4. Validate ---
    Info "Running terraform validate..."
    $validateOutput = terraform validate -no-color 2>&1
    if ($LASTEXITCODE -ne 0) {
        Fail "terraform validate failed:"
        Write-Host ($validateOutput | Out-String) -ForegroundColor Red
    } else {
        Ok "terraform validate passed"
    }

    # --- 5. Check for deprecated resources / known issues ---
    Info "Checking for known Terraform anti-patterns..."

    # 5a. Warn if azurerm_cosmosdb_sql_container is used (no vector support)
    $cosmosContainerUsage = Select-String -Path "$InfraDir\*.tf" -Pattern 'azurerm_cosmosdb_sql_container' -SimpleMatch 2>$null
    if ($cosmosContainerUsage) {
        Warn "Found azurerm_cosmosdb_sql_container usage (does not support vectorEmbeddingPolicy):"
        $cosmosContainerUsage | ForEach-Object { Write-Host "  $($_.Filename):$($_.LineNumber) - $($_.Line.Trim())" -ForegroundColor Yellow }
        Warn "Consider migrating to azapi_resource for containers that need vector search."
    }

    # 5b. Check for hardcoded secrets
    $secretPatterns = @('password\s*=\s*"[^"]+(?<!var\.)', 'secret\s*=\s*"[^"]+(?<!var\.)', 'api_key\s*=\s*"[^"]+')
    foreach ($pattern in $secretPatterns) {
        $matches = Select-String -Path "$InfraDir\*.tf" -Pattern $pattern 2>$null
        if ($matches) {
            Fail "Potential hardcoded secret found:"
            $matches | ForEach-Object { Write-Host "  $($_.Filename):$($_.LineNumber) - $($_.Line.Trim())" -ForegroundColor Red }
        }
    }

    # 5c. Ensure common_tags is used on all resources (heuristic)
    $resourceBlocks = Select-String -Path "$InfraDir\*.tf" -Pattern '^\s*resource\s+"(azurerm_|azapi_)' 2>$null
    $noTags = Select-String -Path "$InfraDir\*.tf" -Pattern '^\s*resource\s+"azurerm_' 2>$null |
        ForEach-Object {
            $file = $_.Path; $line = $_.LineNumber
            $content = Get-Content $file
            # Simple heuristic: check next 15 lines for 'tags'
            $block = $content[($line-1)..([Math]::Min($line+14, $content.Length-1))] -join "`n"
            if ($block -notmatch 'tags\s*=') {
                [PSCustomObject]@{File=$_.Filename; Line=$line; Text=$_.Line.Trim()}
            }
        }
    if ($noTags) {
        Warn "azurerm resources possibly missing 'tags = local.common_tags':"
        $noTags | ForEach-Object { Write-Host "  $($_.File):$($_.Line) - $($_.Text)" -ForegroundColor Yellow }
    }

    # 5d. Check .tfvars.example exists (good practice)
    if (-not (Test-Path "$InfraDir\terraform.tfvars.example")) {
        Warn "No terraform.tfvars.example found. Consider adding one for onboarding."
    } else {
        Ok "terraform.tfvars.example present"
    }

    # 5e. Ensure .tfvars is NOT committed (check .gitignore)
    $gitignore = Join-Path (Split-Path $InfraDir -Parent) ".gitignore"
    if (Test-Path $gitignore) {
        $gitignoreContent = Get-Content $gitignore -Raw
        if ($gitignoreContent -notmatch 'terraform\.tfvars(?!\.)') {
            Warn "terraform.tfvars may not be in .gitignore — risk of committing secrets!"
        } else {
            Ok ".gitignore covers terraform.tfvars"
        }
    }

    # 5f. Check tfstate is not committed
    $tfstateInGit = git -C (Split-Path $InfraDir -Parent) ls-files --error-unmatch "infra/terraform.tfstate" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Fail "terraform.tfstate is tracked by git! Add to .gitignore and remove with: git rm --cached infra/terraform.tfstate"
    }

} finally {
    Pop-Location
}

# --- Summary ---
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
if ($script:failed) {
    Fail "Terraform validation FAILED. Fix the issues above."
    exit 1
} else {
    Ok "All Terraform validation checks passed!"
    exit 0
}
