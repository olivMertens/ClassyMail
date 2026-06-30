<#
.SYNOPSIS
  ClassyMail — Terraform deploy helper (Windows / PowerShell).

.DESCRIPTION
  Provisions the full ClassyMail Azure stack via Terraform and applies it to the
  remote subscription: Storage + Event Grid ingestion, Service Bus queue,
  AI Foundry (account + project), Cosmos DB (serverless, vector), Container Apps
  environment with the API + worker apps (KEDA Service Bus scaler), the user-
  assigned managed identity, all RBAC role assignments, the corporate tag/policy
  assignments and — when -GithubRepo is set — the GitHub OIDC CI/CD identity.

  Parameters are layered on top of any infra/terraform.tfvars using Terraform
  -var flags (CLI values win, tfvars is never overwritten). The script is
  idempotent — safe to re-run.

  Companion full-from-scratch flow (also builds & pushes the image, writes
  secrets.env and assigns local-dev RBAC): scripts/bootstrap.ps1

.PARAMETER TenantId
  Azure AD tenant (GUID). Defaults to the current Azure CLI context.
.PARAMETER SubscriptionId
  Azure subscription (GUID). Defaults to the current Azure CLI context.
.PARAMETER Prefix
  Resource-name prefix. Falls back to the Terraform default ('classymail').
.PARAMETER Location
  Azure region. Falls back to the Terraform default ('swedencentral').
.PARAMETER ContainerImage
  Image (registry/repo:tag) for the API + worker Container Apps. Required by
  Terraform; if omitted and terraform.tfvars has no value, a hello-world
  placeholder is used so the infra can be created — re-run with the real image.
.PARAMETER AcrName
  ACR name to grant AcrPull to the app identity (and AcrPush to CI/CD).
.PARAMETER AcrResourceGroup
  ACR resource group (required when -AcrName is set).
.PARAMETER GithubRepo
  'owner/repo' to create a GitHub OIDC CI/CD identity + federated credential.
.PARAMETER GithubEnvironment
  GitHub environment name for the OIDC subject claim (optional).
.PARAMETER AllowedIpRanges
  Public IPs/CIDRs allowed on the Cosmos DB firewall (e.g. your dev IP).
.PARAMETER DetectLocalIp
  Auto-detect this machine's public IP and add it to the Cosmos firewall.
.PARAMETER OrganizationName
  Organization name shown in the UI.
.PARAMETER CosmosUseRbac
  Cosmos data-plane via Entra RBAC, disabling local keys. Terraform default: true.
.PARAMETER CustomTagsEnabled
  Apply corporate tags to every resource. Terraform default: true.
.PARAMETER TagPolicyEnabled
  Enable the mandatory-tag auto-fill policy. Terraform default: true.
.PARAMETER SecurityCostPolicyEnabled
  Enable the SecurityControl/CostControl tag policy. Terraform default: true.
.PARAMETER TagPolicyScope
  'resource_group' or 'subscription'. Terraform default: resource_group.
.PARAMETER EnableModelDeployments
  Deploy Phi-4 + Mistral OCR via Terraform. Terraform default: false.
.PARAMETER DeployOptionalModels
  Deploy optional models (requires -EnableModelDeployments). Terraform default: false.
.PARAMETER DeployLanguageService
  Deploy Azure AI Language for native PII detection. Terraform default: false.
.PARAMETER DeployDocumentIntelligence
  Deploy Document Intelligence OCR fallback. Terraform default: false.
.PARAMETER ResourceGroup
  Existing resource group to discover & verify roles against. Defaults to
  '<prefix>-rg'. Used by -VerifyOnly and by the post-apply role verification.
.PARAMETER VerifyOnly
  Discovery / double-check mode: skip Terraform entirely. Confirm the resource
  group exists, discover the app managed identity + resources, and idempotently
  add only the MISSING RBAC role assignments (verify/warn for Cosmos data-plane).
.PARAMETER SkipRoleVerification
  Skip the automatic post-apply discovery + role verification step.
.PARAMETER SkipProviderRegistration
  Skip Azure resource-provider registration.
.PARAMETER PlanOnly
  Run init + plan only; do not apply (dry run).
.PARAMETER AutoApprove
  Apply without the interactive confirmation prompt.

.EXAMPLE
  ./infra/deploy.ps1 -ContainerImage myacr.azurecr.io/classymail:latest `
    -AcrName myacr -AcrResourceGroup my-acr-rg -DetectLocalIp -AutoApprove

.EXAMPLE
  # Discover an existing RG and add only the missing role assignments
  ./infra/deploy.ps1 -VerifyOnly -ResourceGroup classymail-rg

.EXAMPLE
  # Dry run against the current subscription
  ./infra/deploy.ps1 -PlanOnly

.EXAMPLE
  # Provision and wire GitHub Actions OIDC CI/CD
  ./infra/deploy.ps1 -ContainerImage myacr.azurecr.io/classymail:v1 `
    -AcrName myacr -AcrResourceGroup my-acr-rg -GithubRepo olivMertens/ClassyMail
#>
[CmdletBinding()]
Param(
  [string]$TenantId,
  [string]$SubscriptionId,
  [string]$Prefix,
  [string]$Location,
  [string]$ResourceGroup,
  [string]$ContainerImage,
  [string]$AcrName,
  [string]$AcrResourceGroup,
  [string]$GithubRepo,
  [string]$GithubEnvironment,
  [string[]]$AllowedIpRanges,
  [switch]$DetectLocalIp,
  [string]$OrganizationName,
  [bool]$CosmosUseRbac,
  [bool]$CustomTagsEnabled,
  [bool]$TagPolicyEnabled,
  [bool]$SecurityCostPolicyEnabled,
  [ValidateSet('resource_group', 'subscription')][string]$TagPolicyScope,
  [bool]$EnableModelDeployments,
  [bool]$DeployOptionalModels,
  [bool]$DeployLanguageService,
  [bool]$DeployDocumentIntelligence,
  [switch]$SkipProviderRegistration,
  [switch]$VerifyOnly,
  [switch]$SkipRoleVerification,
  [switch]$PlanOnly,
  [switch]$AutoApprove
)

$ErrorActionPreference = 'Stop'

# Resolve the infra directory from the script location so the script can be run
# from anywhere (e.g. ./infra/deploy.ps1 from repo root, or directly).
$InfraDir = $PSScriptRoot

function Require-Cmd([string]$name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "Required command not found: $name"
  }
}

Require-Cmd az
Require-Cmd terraform

# ──────────────────────────────────────────────────────────────────────
# Discovery + idempotent role verification.
#
# Given an existing resource group, confirm it exists, discover the app
# user-assigned managed identity ('<prefix>-id') and the key resources, then
# verify each expected RBAC role assignment and add ONLY the missing ones.
# Cosmos DB data-plane access uses a Terraform-managed custom SQL role, so it
# is verified and reported (warn) rather than created here.
#
# Canonical role list (source: docs/RBAC_AUDIT.md + infra/main.tf):
#   Storage Blob Data Contributor        -> storage account      (always)
#   Azure Service Bus Data Receiver      -> Service Bus namespace (always)
#   Azure Service Bus Data Sender        -> Service Bus namespace (always)
#   Cognitive Services User              -> AI Foundry account    (always)
#   AcrPull                              -> Container Registry    (if present)
#   Cognitive Services Language Reader   -> Language service      (if present)
#   Cosmos SQL custom role (data-plane)  -> Cosmos DB account     (verify/warn)
# ──────────────────────────────────────────────────────────────────────
function Invoke-RoleDiscovery {
  param(
    [Parameter(Mandatory)][string]$ResourceGroup,
    [string]$Prefix,
    [string]$AcrName,
    [string]$AcrResourceGroup,
    [switch]$Strict
  )

  Write-Host ""
  Write-Host "== Discovery & role verification ==" -ForegroundColor Cyan
  Write-Host "  Resource group : $ResourceGroup" -ForegroundColor Gray

  az group show -n $ResourceGroup -o none 2>$null
  if ($LASTEXITCODE -ne 0) {
    if ($Strict) { throw "Resource group '$ResourceGroup' not found." }
    Write-Warning "Resource group '$ResourceGroup' not found - skipping role verification."
    return
  }
  Write-Host "  [ok]  resource group exists" -ForegroundColor Green

  # Derived resource names — must match the naming in infra/main.tf.
  $cleanPrefix  = ($Prefix -replace '[-_]', '')
  $identityName = "$Prefix-id"
  $storageName  = "${cleanPrefix}st"
  $sbNamespace  = "$Prefix-sbus"
  $cosmosName   = "$Prefix-cosmos"
  $aiName       = "$Prefix-aifoundry"

  $principalId = (az identity show -g $ResourceGroup -n $identityName --query principalId -o tsv 2>$null)
  if ([string]::IsNullOrWhiteSpace($principalId)) {
    if ($Strict) { throw "Managed identity '$identityName' not found in '$ResourceGroup'." }
    Write-Warning "Managed identity '$identityName' not found - skipping role verification."
    return
  }
  $principalId = $principalId.Trim()
  Write-Host "  [ok]  identity '$identityName' principalId: $principalId" -ForegroundColor Green

  # Resource scopes (empty => resource absent => role skipped).
  $storageId = (az storage account show -g $ResourceGroup -n $storageName --query id -o tsv 2>$null)
  $sbId      = (az servicebus namespace show -g $ResourceGroup -n $sbNamespace --query id -o tsv 2>$null)
  $aiId      = (az cognitiveservices account show -g $ResourceGroup -n $aiName --query id -o tsv 2>$null)
  $cosmosId  = (az cosmosdb show -g $ResourceGroup -n $cosmosName --query id -o tsv 2>$null)
  $langId    = (az cognitiveservices account list -g $ResourceGroup --query "[?kind=='TextAnalytics'] | [0].id" -o tsv 2>$null)

  $acrId = $null
  if ($AcrName) {
    if ($AcrResourceGroup) {
      $acrId = (az acr show -n $AcrName -g $AcrResourceGroup --query id -o tsv 2>$null)
    } else {
      $acrId = (az acr show -n $AcrName --query id -o tsv 2>$null)
    }
  } else {
    $acrId = (az acr list -g $ResourceGroup --query "[0].id" -o tsv 2>$null)
  }

  # Mutable counters shared with the nested helper (hashtable = reference type).
  $stats = @{ added = 0; present = 0; skipped = 0; failed = 0 }

  function Ensure-Role([string]$scope, [string]$role, [string]$desc) {
    if ([string]::IsNullOrWhiteSpace($scope)) {
      Write-Host "  [skip] $desc absent - '$role' not applicable" -ForegroundColor DarkGray
      $stats.skipped++
      return
    }
    $scope = $scope.Trim()
    $existing = az role assignment list --assignee $principalId --scope $scope `
      --query "[?roleDefinitionName=='$role'] | [0].id" -o tsv 2>$null
    if (-not [string]::IsNullOrWhiteSpace($existing)) {
      Write-Host "  [ok]  '$role' already on $desc" -ForegroundColor Green
      $stats.present++
      return
    }
    Write-Host "  [add] '$role' -> $desc" -ForegroundColor Yellow
    az role assignment create --assignee-object-id $principalId `
      --assignee-principal-type ServicePrincipal --role $role --scope $scope -o none 2>$null
    if ($LASTEXITCODE -eq 0) {
      $stats.added++
    } else {
      Write-Warning "  failed to add '$role' on $desc"
      $stats.failed++
    }
  }

  Ensure-Role $storageId 'Storage Blob Data Contributor'      "Storage ($storageName)"
  Ensure-Role $sbId      'Azure Service Bus Data Receiver'    "Service Bus ($sbNamespace)"
  Ensure-Role $sbId      'Azure Service Bus Data Sender'      "Service Bus ($sbNamespace)"
  Ensure-Role $aiId      'Cognitive Services User'            "AI Foundry ($aiName)"
  Ensure-Role $acrId     'AcrPull'                            'Container Registry'
  if ($langId) { Ensure-Role $langId 'Cognitive Services Language Reader' 'Language service' }

  # Cosmos DB data-plane: Terraform owns the custom SQL role — verify & warn only.
  if ($cosmosId) {
    $cosmosJson = az cosmosdb sql role assignment list --account-name $cosmosName `
      --resource-group $ResourceGroup -o json 2>$null
    $hasCosmos = $false
    if (-not [string]::IsNullOrWhiteSpace($cosmosJson)) {
      try {
        $hasCosmos = [bool](($cosmosJson | ConvertFrom-Json) |
          Where-Object { $_.principalId -eq $principalId })
      } catch { $hasCosmos = $false }
    }
    if ($hasCosmos) {
      Write-Host "  [ok]  Cosmos SQL data-plane role present ($cosmosName)" -ForegroundColor Green
    } else {
      Write-Warning "  Cosmos SQL data-plane role MISSING for identity on $cosmosName - run 'terraform apply' (Terraform-managed custom role)."
    }
  } else {
    Write-Host "  [skip] Cosmos account absent - data-plane role not applicable" -ForegroundColor DarkGray
  }

  Write-Host ("  Summary: {0} added, {1} present, {2} skipped, {3} failed" -f `
      $stats.added, $stats.present, $stats.skipped, $stats.failed) -ForegroundColor Cyan
  if ($stats.failed -gt 0) {
    Write-Warning "Some role assignments could not be created - check your permissions (need Owner/User Access Administrator)."
  }
}

# ──────────────────────────────────────────────────────────────────────
# Azure login
# ──────────────────────────────────────────────────────────────────────
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
  # Only login if the current context doesn't already match the requested tenant.
  $CurrentTenant = az account show --query tenantId -o tsv 2>$null
  if ($CurrentTenant -eq $TenantId) {
    Write-Host "Already logged in to requested tenant." -ForegroundColor Green
  } else {
    Write-Host "Parameters request specific Tenant $TenantId. Attempting login (may prompt)..." -ForegroundColor Yellow
    az login --tenant $TenantId | Out-Null
  }
} else {
  if (az account show 2>$null) {
    Write-Host "Already logged in. Skipping login." -ForegroundColor Green
  } else {
    az login | Out-Null
  }
}

# ──────────────────────────────────────────────────────────────────────
# Azure subscription
# ──────────────────────────────────────────────────────────────────────
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

# Effective prefix / resource group used by discovery & post-apply verification.
# Falls back to the Terraform default prefix ('classymail') when not supplied.
$EffectivePrefix = if ($Prefix) { $Prefix } else { 'classymail' }
if ([string]::IsNullOrWhiteSpace($ResourceGroup)) { $ResourceGroup = "$EffectivePrefix-rg" }

# ──────────────────────────────────────────────────────────────────────
# Verify-only / discovery mode: skip Terraform; just confirm the RG exists,
# discover the identity + resources, and add only the missing role assignments.
# ──────────────────────────────────────────────────────────────────────
if ($VerifyOnly) {
  Invoke-RoleDiscovery -ResourceGroup $ResourceGroup -Prefix $EffectivePrefix `
    -AcrName $AcrName -AcrResourceGroup $AcrResourceGroup -Strict
  Write-Host ""
  Write-Host "Verification complete." -ForegroundColor Green
  exit 0
}

# ──────────────────────────────────────────────────────────────────────
# Register required resource providers
# A fresh tenant/subscription must have these registered before Terraform can
# create managed identities, RBAC role assignments, policy assignments, etc.
# Registration is idempotent and only triggered when not already Registered.
# ──────────────────────────────────────────────────────────────────────
if (-not $SkipProviderRegistration) {
  Write-Host "== Resource providers ==" -ForegroundColor Cyan
  $providers = @(
    'Microsoft.Storage',
    'Microsoft.ServiceBus',
    'Microsoft.DocumentDB',
    'Microsoft.CognitiveServices',
    'Microsoft.App',
    'Microsoft.EventGrid',
    'Microsoft.Insights',
    'Microsoft.OperationalInsights',
    'Microsoft.ManagedIdentity',
    'Microsoft.ContainerRegistry'
  )
  foreach ($p in $providers) {
    $state = az provider show --namespace $p --query registrationState -o tsv 2>$null
    if ($state -eq 'Registered') {
      Write-Host "  already registered: $p" -ForegroundColor DarkGray
    } else {
      Write-Host "  registering: $p ..." -ForegroundColor Yellow
      az provider register --namespace $p | Out-Null
    }
  }
  Write-Host "  Providers registered (propagation may take 1-5 min)." -ForegroundColor Green
}

# ── Fortinet / corporate firewall workaround ──────────────────────────
# The azapi provider v1.x defaults use_msi=true, which makes Terraform
# call the IMDS endpoint (169.254.169.254). Corporate firewalls such as
# FortiGuard IPS block this endpoint, causing a 403 that crashes the
# credential chain. Setting ARM_USE_MSI=false prevents the attempt.
# The same flags are also set in provider blocks in main.tf.
$env:ARM_USE_MSI = "false"
$env:ARM_USE_OIDC = "false"
# ──────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────
# Build the Terraform -var arguments from supplied parameters.
# Only explicitly-provided values are passed; everything else falls back to
# terraform.tfvars (if present) or the variable defaults in the .tf files.
# ──────────────────────────────────────────────────────────────────────
$varArgs = @('-var', "subscription_id=$DetectedSub")

function Add-TfVar([string]$name, [string]$value) {
  $script:varArgs += @('-var', "$name=$value")
}

if ($Prefix) { Add-TfVar 'prefix' $Prefix }
if ($Location) { Add-TfVar 'location' $Location }
if ($AcrName) { Add-TfVar 'acr_name' $AcrName }
if ($AcrResourceGroup) { Add-TfVar 'acr_resource_group' $AcrResourceGroup }
if ($GithubRepo) { Add-TfVar 'github_repo' $GithubRepo }
if ($GithubEnvironment) { Add-TfVar 'github_environment' $GithubEnvironment }
if ($OrganizationName) { Add-TfVar 'organization_name' $OrganizationName }
if ($TagPolicyScope) { Add-TfVar 'tag_policy_scope' $TagPolicyScope }

# Boolean toggles — pass only when the caller set them explicitly, so Terraform
# defaults (true for tags/policies/RBAC, false for optional models/services) win otherwise.
$boolMap = @(
  @{ Param = 'CosmosUseRbac'; Var = 'cosmos_use_rbac' },
  @{ Param = 'CustomTagsEnabled'; Var = 'custom_tags_enabled' },
  @{ Param = 'TagPolicyEnabled'; Var = 'tag_policy_enabled' },
  @{ Param = 'SecurityCostPolicyEnabled'; Var = 'security_cost_policy_enabled' },
  @{ Param = 'EnableModelDeployments'; Var = 'enable_model_deployments' },
  @{ Param = 'DeployOptionalModels'; Var = 'deploy_optional_models' },
  @{ Param = 'DeployLanguageService'; Var = 'deploy_language_service' },
  @{ Param = 'DeployDocumentIntelligence'; Var = 'deploy_document_intelligence' }
)
foreach ($b in $boolMap) {
  if ($PSBoundParameters.ContainsKey($b.Param)) {
    $val = (Get-Variable $b.Param).Value.ToString().ToLowerInvariant()
    Add-TfVar $b.Var $val
  }
}

# Cosmos DB firewall allow-list (optionally including the local public IP)
$ips = @()
if ($AllowedIpRanges) { $ips += $AllowedIpRanges }
if ($DetectLocalIp) {
  try {
    $myIp = (Invoke-WebRequest -Uri 'https://ifconfig.me/ip' -UseBasicParsing -TimeoutSec 5).Content.Trim()
    if ($myIp) {
      Write-Host "  detected local public IP: $myIp" -ForegroundColor Green
      $ips += $myIp
    }
  } catch {
    Write-Warning "Could not auto-detect public IP (continuing without it)."
  }
}
if ($ips.Count -gt 0) {
  $ipHcl = '[' + (($ips | ForEach-Object { '"' + $_ + '"' }) -join ',') + ']'
  Add-TfVar 'allowed_ip_ranges' $ipHcl
}

# container_image is REQUIRED by Terraform (validation rejects ""). Resolve it
# from the parameter, else from terraform.tfvars, else fall back to a placeholder.
$tfvarsPath = Join-Path $InfraDir 'terraform.tfvars'
$tfvarsHasImage = $false
if (Test-Path $tfvarsPath) {
  if ((Get-Content $tfvarsPath -Raw) -match '(?m)^\s*container_image\s*=\s*"[^"]+"') {
    $tfvarsHasImage = $true
  }
}
if ($ContainerImage) {
  Add-TfVar 'container_image' $ContainerImage
} elseif (-not $tfvarsHasImage) {
  $placeholder = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
  Write-Warning "No -ContainerImage supplied and terraform.tfvars has no container_image."
  Write-Warning "Using placeholder '$placeholder'. Build & push your image, then re-run with -ContainerImage to deploy the real app."
  Add-TfVar 'container_image' $placeholder
}

# ──────────────────────────────────────────────────────────────────────
# Terraform init / plan / apply
# ──────────────────────────────────────────────────────────────────────
Write-Host "== Terraform ==" -ForegroundColor Cyan
terraform "-chdir=$InfraDir" init -upgrade
if ($LASTEXITCODE -ne 0) { throw "terraform init failed" }

$planArgs = @("-chdir=$InfraDir", 'plan') + $varArgs + @('-out', 'tfplan')
terraform @planArgs
if ($LASTEXITCODE -ne 0) { throw "terraform plan failed" }

if ($PlanOnly) {
  Write-Host "Plan only — skipping apply." -ForegroundColor Yellow
  exit 0
}

if (-not $AutoApprove) {
  $answer = Read-Host "Apply this plan? (y/N)"
  if ($answer -notmatch '^(y|yes)$') {
    Write-Host "Skipped apply." -ForegroundColor Yellow
    exit 0
  }
}

terraform "-chdir=$InfraDir" apply tfplan
if ($LASTEXITCODE -ne 0) { throw "terraform apply failed" }

# ──────────────────────────────────────────────────────────────────────
# Post-apply discovery + role verification (idempotent — adds only missing).
# ──────────────────────────────────────────────────────────────────────
if (-not $SkipRoleVerification) {
  Invoke-RoleDiscovery -ResourceGroup $ResourceGroup -Prefix $EffectivePrefix `
    -AcrName $AcrName -AcrResourceGroup $AcrResourceGroup
}

# ──────────────────────────────────────────────────────────────────────
# Surface the key outputs (endpoints, identity, CI/CD secrets)
# ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "== Deployment outputs ==" -ForegroundColor Cyan
$tf = terraform "-chdir=$InfraDir" output -json 2>$null | ConvertFrom-Json

function Show-Out([string]$label, [string]$key) {
  $entry = $tf.$key
  if ($null -ne $entry -and -not [string]::IsNullOrWhiteSpace([string]$entry.value)) {
    Write-Host ("  {0,-26} {1}" -f $label, $entry.value)
  }
}

Show-Out 'AI Foundry endpoint' 'AI_ENDPOINT'
Show-Out 'Cosmos endpoint' 'AZURE_COSMOS_ENDPOINT'
Show-Out 'Service Bus FQDN' 'AZURE_SERVICE_BUS_FQDN'
Show-Out 'Service Bus queue' 'AZURE_SERVICE_BUS_QUEUE'
Show-Out 'Storage blob URL' 'AZURE_STORAGE_ACCOUNT_URL'
Show-Out 'Storage container' 'AZURE_STORAGE_CONTAINER'
Show-Out 'App identity clientId' 'APP_ID_CLIENT_ID'
Show-Out 'Language endpoint' 'LANGUAGE_ENDPOINT'
Show-Out 'Doc Intelligence endpoint' 'DOCUMENT_INTELLIGENCE_ENDPOINT'

# Best-effort: public API URL of the api Container App
$apiFqdn = az containerapp list -g $ResourceGroup --query "[?contains(name, 'api')].properties.configuration.ingress.fqdn | [0]" -o tsv 2>$null
if (-not [string]::IsNullOrWhiteSpace($apiFqdn)) {
  Write-Host ("  {0,-26} https://{1}" -f 'API URL', $apiFqdn.Trim()) -ForegroundColor Green
}

# CI/CD OIDC identity (only when github_repo was set)
if ($GithubRepo) {
  Write-Host ""
  Write-Host "  GitHub Actions OIDC — set these as repository secrets:" -ForegroundColor Yellow
  Show-Out 'AZURE_CLIENT_ID' 'CICD_CLIENT_ID'
  Show-Out 'AZURE_TENANT_ID' 'CICD_TENANT_ID'
  Write-Host ("  {0,-26} {1}" -f 'AZURE_SUBSCRIPTION_ID', $DetectedSub)
  Write-Host "  (details: docs/CICD_GITHUB.md)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Deployment complete." -ForegroundColor Green
if (-not $ContainerImage -and -not $tfvarsHasImage) {
  Write-Host "NOTE: A placeholder image was deployed. Re-run with -ContainerImage <registry/repo:tag> once your image is pushed." -ForegroundColor Yellow
}
