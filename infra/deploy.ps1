Param(
  [string]$TenantId,
  [string]$SubscriptionId,
  [switch]$AutoApprove
)

$ErrorActionPreference = 'Stop'

function Require-Cmd([string]$name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "Required command not found: $name"
  }
}

Require-Cmd az
Require-Cmd terraform

Write-Host "== Azure login ==" -ForegroundColor Cyan
if ([string]::IsNullOrWhiteSpace($TenantId)) {
  $TenantId = Read-Host "Tenant ID (GUID) (leave blank to use default)"
}

if (-not [string]::IsNullOrWhiteSpace($TenantId)) {
  az login --tenant $TenantId | Out-Null
} else {
  az login | Out-Null
}

Write-Host "== Azure subscription ==" -ForegroundColor Cyan
if ([string]::IsNullOrWhiteSpace($SubscriptionId)) {
  $SubscriptionId = Read-Host "Subscription ID (GUID) (leave blank to use current)"
}

if (-not [string]::IsNullOrWhiteSpace($SubscriptionId)) {
  az account set --subscription $SubscriptionId | Out-Null
}

$DetectedSub = (az account show --query id -o tsv).Trim()
if ([string]::IsNullOrWhiteSpace($DetectedSub)) {
  throw "Could not detect subscription from Azure CLI. Run 'az account show' to verify you're logged in."
}

Write-Host "Using subscription: $DetectedSub" -ForegroundColor Green

Write-Host "== Terraform ==" -ForegroundColor Cyan
terraform -chdir=infra init -upgrade
terraform -chdir=infra plan -var "subscription_id=$DetectedSub" -out tfplan

if ($AutoApprove) {
  terraform -chdir=infra apply -auto-approve tfplan
  exit 0
}

$answer = Read-Host "Apply this plan? (y/N)"
if ($answer -match '^(y|yes)$') {
  terraform -chdir=infra apply tfplan
} else {
  Write-Host "Skipped apply." -ForegroundColor Yellow
}
