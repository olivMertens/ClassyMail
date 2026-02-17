#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Bootstrap ClassyMail deployment in a new Azure tenant from scratch.

.DESCRIPTION
    Automated end-to-end deployment script that provisions all Azure infrastructure,
    builds and pushes the container image, and verifies the deployment.

    This script is IDEMPOTENT — safe to re-run.

.PARAMETER TenantId
    Azure AD Tenant ID (GUID). If omitted, uses current Azure CLI context.

.PARAMETER SubscriptionId
    Azure Subscription ID (GUID). If omitted, uses current Azure CLI context.

.PARAMETER Prefix
    Resource naming prefix. All resources are named {prefix}-*.

.PARAMETER Location
    Azure region. Must support AI Foundry, Container Apps, Cosmos DB Serverless.

.PARAMETER AcrName
    Azure Container Registry name. If not provided, one is created.

.PARAMETER AcrResourceGroup
    Resource group for the ACR. Defaults to {prefix}-acr-rg.

.PARAMETER ImageTag
    Container image tag.

.PARAMETER SkipFrontendBuild
    Skip npm install/build (use if frontend was already built).

.PARAMETER SkipProviderRegistration
    Skip Azure resource provider registration.

.PARAMETER SkipImageBuild
    Skip container image build and push.

.PARAMETER WhatIf
    Show what would happen without making changes.

.EXAMPLE
    .\scripts\bootstrap.ps1 -TenantId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" -SubscriptionId "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy"

.EXAMPLE
    .\scripts\bootstrap.ps1 -Prefix "email-poc-test" -AcrName "myexistingacr" -AcrResourceGroup "my-acr-rg"
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TenantId,
    [string]$SubscriptionId,
    [string]$Prefix = "email-poc-test",
    [string]$Location = "swedencentral",
    [string]$AcrName,
    [string]$AcrResourceGroup,
    [string]$ImageTag = "v1",
    [switch]$SkipFrontendBuild,
    [switch]$SkipProviderRegistration,
    [switch]$SkipImageBuild
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

# ─────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────

function Write-Step {
    param([string]$Step, [string]$Message)
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "[$Step] $Message" -ForegroundColor Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
}

function Require-Cmd {
    param([string]$Name, [string]$InstallHint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Error "Required command not found: $Name. $InstallHint"
        exit 1
    }
}

function Test-AzureLogin {
    $account = az account show -o json 2>$null | ConvertFrom-Json
    return $null -ne $account
}

# ─────────────────────────────────────────────────────────────────────
# Step 0: Validate Prerequisites
# ─────────────────────────────────────────────────────────────────────

Write-Step "0/9" "Validating prerequisites"

Require-Cmd "az"        "Install: https://learn.microsoft.com/cli/azure/install-azure-cli"
Require-Cmd "terraform" "Install: https://developer.hashicorp.com/terraform/install"
Require-Cmd "node"      "Install: https://nodejs.org/"
Require-Cmd "uv"        "Install: https://docs.astral.sh/uv/getting-started/installation/"

# Docker is optional if using ACR remote build
$hasDocker = $null -ne (Get-Command "docker" -ErrorAction SilentlyContinue)
if (-not $hasDocker) {
    Write-Host "  Docker not found — will use ACR remote build (az acr build)" -ForegroundColor Yellow
}

Write-Host "  All prerequisites OK" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────
# Step 1: Azure Authentication
# ─────────────────────────────────────────────────────────────────────

Write-Step "1/9" "Azure authentication"

if (-not (Test-AzureLogin)) {
    if (-not [string]::IsNullOrWhiteSpace($TenantId)) {
        Write-Host "  Logging in to tenant $TenantId..." -ForegroundColor Yellow
        az login --tenant $TenantId | Out-Null
    } else {
        Write-Host "  Logging in (interactive)..." -ForegroundColor Yellow
        az login | Out-Null
    }
} else {
    $currentTenant = az account show --query tenantId -o tsv
    if (-not [string]::IsNullOrWhiteSpace($TenantId) -and $currentTenant -ne $TenantId) {
        Write-Host "  Switching to tenant $TenantId..." -ForegroundColor Yellow
        az login --tenant $TenantId | Out-Null
    } else {
        Write-Host "  Already logged in to tenant $currentTenant" -ForegroundColor Green
    }
}

if (-not [string]::IsNullOrWhiteSpace($SubscriptionId)) {
    az account set --subscription $SubscriptionId | Out-Null
}

$detectedSub = (az account show --query id -o tsv).Trim()
$detectedTenant = (az account show --query tenantId -o tsv).Trim()
$detectedSubName = (az account show --query name -o tsv).Trim()

Write-Host "  Tenant:       $detectedTenant" -ForegroundColor Green
Write-Host "  Subscription: $detectedSub ($detectedSubName)" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────
# Step 2: Register Resource Providers
# ─────────────────────────────────────────────────────────────────────

if (-not $SkipProviderRegistration) {
    Write-Step "2/9" "Registering Azure resource providers"

    $providers = @(
        "Microsoft.Storage",
        "Microsoft.ServiceBus",
        "Microsoft.DocumentDB",
        "Microsoft.CognitiveServices",
        "Microsoft.App",
        "Microsoft.EventGrid",
        "Microsoft.Insights",
        "Microsoft.OperationalInsights",
        "Microsoft.ManagedIdentity",
        "Microsoft.ContainerRegistry"
    )

    foreach ($p in $providers) {
        $state = az provider show --namespace $p --query registrationState -o tsv 2>$null
        if ($state -eq "Registered") {
            Write-Host "  Already registered: $p" -ForegroundColor DarkGray
        } else {
            if ($PSCmdlet.ShouldProcess($p, "Register resource provider")) {
                Write-Host "  Registering: $p ..." -ForegroundColor Yellow
                az provider register --namespace $p | Out-Null
            }
        }
    }

    Write-Host "  All providers registered (propagation may take 1-5 min)" -ForegroundColor Green
} else {
    Write-Step "2/9" "Skipping resource provider registration (SkipProviderRegistration)"
}

# ─────────────────────────────────────────────────────────────────────
# Step 3: Create ACR (if needed)
# ─────────────────────────────────────────────────────────────────────

Write-Step "3/9" "Container Registry setup"

# Default ACR name: strip dashes from prefix + "acr"
if ([string]::IsNullOrWhiteSpace($AcrName)) {
    $AcrName = ($Prefix -replace "-", "") + "acr"
}
if ([string]::IsNullOrWhiteSpace($AcrResourceGroup)) {
    $AcrResourceGroup = "$Prefix-acr-rg"
}

$acrExists = az acr show --name $AcrName --resource-group $AcrResourceGroup --query name -o tsv 2>$null
if ($acrExists) {
    Write-Host "  ACR '$AcrName' already exists in '$AcrResourceGroup'" -ForegroundColor Green
} else {
    # Check if ACR exists in another RG
    $acrAnyRg = az acr show --name $AcrName --query name -o tsv 2>$null
    if ($acrAnyRg) {
        $actualRg = az acr show --name $AcrName --query resourceGroup -o tsv
        Write-Host "  ACR '$AcrName' found in resource group '$actualRg'" -ForegroundColor Green
        $AcrResourceGroup = $actualRg
    } else {
        if ($PSCmdlet.ShouldProcess("$AcrName in $AcrResourceGroup", "Create ACR")) {
            Write-Host "  Creating ACR '$AcrName' in '$AcrResourceGroup' ($Location)..." -ForegroundColor Yellow
            az group create --name $AcrResourceGroup --location $Location --output none 2>$null
            az acr create --name $AcrName --resource-group $AcrResourceGroup --sku Basic --admin-enabled false --output none
            Write-Host "  ACR created" -ForegroundColor Green
        }
    }
}

$containerImage = "$AcrName.azurecr.io/classymail-agent:$ImageTag"
Write-Host "  Image target: $containerImage" -ForegroundColor Cyan

# ─────────────────────────────────────────────────────────────────────
# Step 4: Create terraform.tfvars (first pass — placeholder image)
# ─────────────────────────────────────────────────────────────────────

Write-Step "4/9" "Terraform configuration"

$tfvarsPath = Join-Path $RepoRoot "infra/terraform.tfvars"

# Detect public IP for Cosmos firewall
$myIp = try { (Invoke-WebRequest -Uri "https://ifconfig.me" -UseBasicParsing -TimeoutSec 5).Content.Trim() } catch { $null }

$tfvarsContent = @"
# Auto-generated by bootstrap.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
subscription_id = "$detectedSub"

# Placeholder image — updated after ACR push (Step 7)
container_image = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"

# Container Registry
acr_name           = "$AcrName"
acr_resource_group = "$AcrResourceGroup"

# Naming
prefix   = "$Prefix"
location = "$Location"

# Security & Auth
cosmos_use_rbac = true

# Models: deploy manually via Azure AI Foundry portal
enable_model_deployments = false
deploy_language_service  = false

# Policies (set to false if your tenant restricts custom policy creation)
tag_policy_enabled             = true
security_cost_policy_enabled   = true

# Network: allow your IP for Cosmos DB local dev access
$(if ($myIp) { "allowed_ip_ranges = [`"$myIp`"]" } else { "# allowed_ip_ranges = [`"YOUR.PUBLIC.IP`"]  # Could not auto-detect" })
"@

if (Test-Path $tfvarsPath) {
    Write-Host "  terraform.tfvars already exists — backing up to terraform.tfvars.bak" -ForegroundColor Yellow
    Copy-Item $tfvarsPath "$tfvarsPath.bak" -Force
}

if ($PSCmdlet.ShouldProcess($tfvarsPath, "Write terraform.tfvars")) {
    Set-Content -Path $tfvarsPath -Value $tfvarsContent -Encoding UTF8
    Write-Host "  terraform.tfvars written" -ForegroundColor Green
}

# ─────────────────────────────────────────────────────────────────────
# Step 5: Terraform — first apply (placeholder image)
# ─────────────────────────────────────────────────────────────────────

Write-Step "5/9" "Terraform init + plan + apply (pass 1 — placeholder image)"

if ($PSCmdlet.ShouldProcess("infra", "Terraform apply")) {
    Push-Location (Join-Path $RepoRoot "infra")
    try {
        terraform init -upgrade
        if ($LASTEXITCODE -ne 0) { throw "terraform init failed" }

        terraform plan -var "subscription_id=$detectedSub" -out tfplan
        if ($LASTEXITCODE -ne 0) { throw "terraform plan failed" }

        terraform apply tfplan
        if ($LASTEXITCODE -ne 0) { throw "terraform apply failed" }

        Write-Host "  Infrastructure provisioned" -ForegroundColor Green

        # Capture outputs
        $tfOutputs = terraform output -json | ConvertFrom-Json
        Write-Host "  AI endpoint: $($tfOutputs.AI_ENDPOINT.value)" -ForegroundColor Cyan
    } finally {
        Pop-Location
    }
}

# ─────────────────────────────────────────────────────────────────────
# Step 6: Build Frontend + Container Image
# ─────────────────────────────────────────────────────────────────────

if (-not $SkipImageBuild) {
    Write-Step "6/9" "Building frontend and container image"

    # 6a: Frontend
    if (-not $SkipFrontendBuild) {
        Write-Host "  Building frontend..." -ForegroundColor Yellow
        Push-Location (Join-Path $RepoRoot "frontend")
        try {
            npm install --silent 2>&1 | Out-Null
            npm run build
            if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
            Write-Host "  Frontend built" -ForegroundColor Green
        } finally {
            Pop-Location
        }
    }

    # 6b: Vue runtime
    Write-Host "  Fetching Vue runtime..." -ForegroundColor Yellow
    & (Join-Path $RepoRoot "scripts/fetch_vue_runtime.ps1")

    # 6c: Build & push image
    Write-Host "  Building and pushing container image..." -ForegroundColor Yellow
    Push-Location $RepoRoot
    try {
        if ($hasDocker) {
            # Local build + push
            az acr login --name $AcrName | Out-Null
            docker build -t $containerImage .
            if ($LASTEXITCODE -ne 0) { throw "Docker build failed" }
            docker push $containerImage
            if ($LASTEXITCODE -ne 0) { throw "Docker push failed" }
        } else {
            # Remote build via ACR
            az acr build --registry $AcrName --image "classymail-agent:$ImageTag" .
            if ($LASTEXITCODE -ne 0) { throw "ACR build failed" }
        }
        Write-Host "  Image pushed: $containerImage" -ForegroundColor Green
    } finally {
        Pop-Location
    }
} else {
    Write-Step "6/9" "Skipping image build (SkipImageBuild)"
}

# ─────────────────────────────────────────────────────────────────────
# Step 7: Terraform — second apply (real image)
# ─────────────────────────────────────────────────────────────────────

if (-not $SkipImageBuild) {
    Write-Step "7/9" "Terraform apply (pass 2 — real container image)"

    # Update terraform.tfvars with real image
    $tfvarsText = Get-Content $tfvarsPath -Raw
    $tfvarsText = $tfvarsText -replace 'container_image\s*=\s*"[^"]*"', "container_image = `"$containerImage`""
    Set-Content -Path $tfvarsPath -Value $tfvarsText -Encoding UTF8

    if ($PSCmdlet.ShouldProcess("infra", "Terraform apply (real image)")) {
        Push-Location (Join-Path $RepoRoot "infra")
        try {
            terraform plan -var "subscription_id=$detectedSub" -out tfplan
            if ($LASTEXITCODE -ne 0) { throw "terraform plan (pass 2) failed" }

            terraform apply tfplan
            if ($LASTEXITCODE -ne 0) { throw "terraform apply (pass 2) failed" }

            Write-Host "  Container Apps updated with real image" -ForegroundColor Green
        } finally {
            Pop-Location
        }
    }
} else {
    Write-Step "7/9" "Skipping second Terraform apply (no image change)"
}

# ─────────────────────────────────────────────────────────────────────
# Step 8: Generate secrets.env + assign local RBAC
# ─────────────────────────────────────────────────────────────────────

Write-Step "8/9" "Local development setup"

$rgName = "$Prefix-rg"

# Generate secrets.env
Write-Host "  Generating secrets.env..." -ForegroundColor Yellow
& (Join-Path $RepoRoot "scripts/write_secrets_env.ps1") `
    -ResourceGroup $rgName `
    -Prefix $Prefix `
    -Force

# Derive resource names from prefix
$storageAccountName = ($Prefix -replace "-", "") + "st"
$serviceBusNamespace = "$Prefix-sbus"
$cosmosAccountName = "$Prefix-cosmos"

# Assign local dev RBAC
Write-Host "  Assigning local RBAC roles..." -ForegroundColor Yellow
& (Join-Path $RepoRoot "scripts/assign_local_dev_roles.ps1") `
    -StorageAccountName $storageAccountName `
    -ServiceBusNamespace $serviceBusNamespace `
    -CosmosAccountName $cosmosAccountName `
    -ResourceGroup $rgName

Write-Host "  Local development configured" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────
# Step 9: Verify
# ─────────────────────────────────────────────────────────────────────

Write-Step "9/9" "Verification"

Write-Host "  Running verify-mvp-setup.ps1..." -ForegroundColor Yellow
& (Join-Path $RepoRoot "scripts/verify-mvp-setup.ps1") -ResourceGroup $rgName

# ─────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host "  BOOTSTRAP COMPLETE" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host ""
Write-Host "  Prefix:          $Prefix" -ForegroundColor White
Write-Host "  Resource Group:  $rgName" -ForegroundColor White
Write-Host "  Location:        $Location" -ForegroundColor White
Write-Host "  ACR:             $AcrName" -ForegroundColor White
Write-Host "  Image:           $containerImage" -ForegroundColor White
Write-Host ""
Write-Host "  MANUAL STEP REQUIRED:" -ForegroundColor Yellow
Write-Host "  Deploy AI models in Azure AI Foundry:" -ForegroundColor Yellow
Write-Host "    1. Go to https://ai.azure.com/" -ForegroundColor White
Write-Host "    2. Select project: $Prefix-project" -ForegroundColor White
Write-Host "    3. Deploy these models:" -ForegroundColor White
Write-Host "       - phi-4             (Standard)   <- classification" -ForegroundColor White
Write-Host "       - mistral-document-ai-2505 (MaaS) <- OCR" -ForegroundColor White
Write-Host "       - text-embedding-3-small (Standard) <- embeddings" -ForegroundColor White
Write-Host ""
Write-Host "  After deploying models, verify:" -ForegroundColor Cyan
Write-Host "    uv run python scripts/list_deployments.py" -ForegroundColor White
Write-Host ""
Write-Host "  Run locally:" -ForegroundColor Cyan
Write-Host "    uv run uvicorn classymail.app:app --reload --port 8000" -ForegroundColor White
Write-Host ""
Write-Host "  Full guide: docs/DEPLOY_FROM_SCRATCH.md" -ForegroundColor DarkGray
Write-Host ""
