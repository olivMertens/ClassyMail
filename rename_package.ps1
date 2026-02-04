# PowerShell script to rename classificationg2s to classymail
# Run this script AFTER closing VS Code and stopping all Python processes

Write-Host "=== ClassificationG2S -> ClassyMail Rename Script ===" -ForegroundColor Cyan
Write-Host ""

$oldName = "classificationg2s"
$newName = "classymail"
$oldPath = Join-Path $PSScriptRoot $oldName
$newPath = Join-Path $PSScriptRoot $newName

# Check if old directory exists
if (!(Test-Path $oldPath)) {
    Write-Host "Error: Directory '$oldName' not found!" -ForegroundColor Red
    Write-Host "It may have already been renamed." -ForegroundColor Yellow
    exit 1
}

# Check if new directory already exists
if (Test-Path $newPath) {
    Write-Host "Error: Directory '$newName' already exists!" -ForegroundColor Red
    exit 1
}

Write-Host "This script will rename: $oldName -> $newName" -ForegroundColor Yellow
Write-Host ""
Write-Host "IMPORTANT: Make sure VS Code is closed and no Python processes are running!" -ForegroundColor Yellow
Write-Host ""
$confirmation = Read-Host "Continue? (Y/N)"

if ($confirmation -ne "Y" -and $confirmation -ne "y") {
    Write-Host "Cancelled." -ForegroundColor Yellow
    exit 0
}

Write-Host""
Write-Host "Step 1: Attempting to rename directory..." -ForegroundColor Cyan

try {
    Rename-Item -Path $oldPath -NewName $newName -ErrorAction Stop
    Write-Host "✓ Directory renamed successfully!" -ForegroundColor Green
} catch {
    Write-Host "✗ Failed to rename directory!" -ForegroundColor Red
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Possible causes:" -ForegroundColor Yellow
    Write-Host "  - VS Code is still open" -ForegroundColor Yellow
    Write-Host "  - Python process is still running" -ForegroundColor Yellow
    Write-Host "  - A terminal/PowerShell has the directory open" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Try these steps:" -ForegroundColor Cyan
    Write-Host "  1. Close VS Code completely" -ForegroundColor White
    Write-Host "  2. Close all PowerShell/CMD windows" -ForegroundColor White
    Write-Host "  3. Check Task Manager for python.exe processes" -ForegroundColor White
    Write-Host "  4. Restart your terminal and run this script again" -ForegroundColor White
    exit 1
}

Write-Host ""
Write-Host "Step 2: Updating uv.lock..." -ForegroundColor Cyan

try {
    $uvLockPath = Join-Path $PSScriptRoot "uv.lock"
    if (Test-Path $uvLockPath) {
        $content = Get-Content $uvLockPath -Raw
        $content = $content -replace 'name = "classificationg2s"', 'name = "classymail"'
        Set-Content $uvLockPath $content
        Write-Host "✓ uv.lock updated!" -ForegroundColor Green
    } else {
        Write-Host "⚠ uv.lock not found (skipping)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "⚠ Failed to update uv.lock: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Rename Complete! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Run: uv lock --refresh" -ForegroundColor White
Write-Host "  2. Run: uv sync" -ForegroundColor White
Write-Host "  3. Run: uv run pytest" -ForegroundColor White
Write-Host "  4. Open VS Code and verify everything works" -ForegroundColor White
Write-Host ""
