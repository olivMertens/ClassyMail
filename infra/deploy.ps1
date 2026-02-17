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
  # Check if we are already logged in to avoid interactive prompt
  $CurrentTenant = az account show --query tenantId -o tsv 2>$null
  if (-not [string]::IsNullOrWhiteSpace($CurrentTenant)) {
    Write-Host "Already logged in to tenant $CurrentTenant. Skipping interactive login." -ForegroundColor Green
    $TenantId = $CurrentTenant
  } else {
    $TenantId = Read-Host "Tenant ID (GUID) (leave blank to use default)"
  }
}

if (-not [string]::IsNullOrWhiteSpace($TenantId)) {
   # Only login if explicitly requested or ensuring context, but strictly avoid interactive if possible in scripts
   # We assume if we have a TenantId and we are running this automated, we might already be logged in.
   # Re-running az login --tenant might prompt.
   # Let's check if the current context matches the requested tenant.
   $CurrentTenant = az account show --query tenantId -o tsv 2>$null
   if ($CurrentTenant -eq $TenantId) {
      Write-Host "Already logged in to requested tenant." -ForegroundColor Green
   } else {
      # This might still prompt! But we have no choice if contexts switch.
      # For now, we assume the user/agent context is correct.
      Write-Host "Parameters request specific Tenant $TenantId. Attempting login (may prompt)..." -ForegroundColor Yellow
      az login --tenant $TenantId | Out-Null
   }
} else {
   # No tenant specified, check if logged in
   if (az account show 2>$null) {
       Write-Host "Already logged in. Skipping login." -ForegroundColor Green
   } else {
       az login | Out-Null
   }
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

# ── Fortinet / corporate firewall workaround ──────────────────────────
# The azapi provider v1.x defaults use_msi=true, which makes Terraform
# call the IMDS endpoint (169.254.169.254). Corporate firewalls such as
# FortiGuard IPS block this endpoint, causing a 403 that crashes the
# credential chain. Setting ARM_USE_MSI=false prevents the attempt.
# The same flags are also set in provider blocks in main.tf.
$env:ARM_USE_MSI   = "false"
$env:ARM_USE_OIDC  = "false"
# ──────────────────────────────────────────────────────────────────────

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
