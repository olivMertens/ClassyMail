#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Assigns RBAC roles to current Azure CLI user for local development.

.DESCRIPTION
    This script assigns the necessary Azure RBAC roles to your current Azure CLI
    user identity so you can run the application locally with full Azure access.

.PARAMETER StorageAccountName
    Name of the Azure Storage account

.PARAMETER ServiceBusNamespace
    Name of the Azure Service Bus namespace

.PARAMETER CosmosAccountName
    Name of the Azure Cosmos DB account

.EXAMPLE
    .\assign_local_dev_roles.ps1 -Prefix "classymail"
    .\assign_local_dev_roles.ps1 -Prefix "myapp" -ResourceGroup "myapp-rg"
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$Prefix = "classymail",

    [Parameter(Mandatory=$false)]
    [string]$StorageAccountName,

    [Parameter(Mandatory=$false)]
    [string]$ServiceBusNamespace,

    [Parameter(Mandatory=$false)]
    [string]$CosmosAccountName,

    [Parameter(Mandatory=$false)]
    [string]$AiAccountName,

    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup
)

# Derive defaults from prefix if not explicitly set
if (-not $ResourceGroup) { $ResourceGroup = "$Prefix-rg" }
if (-not $StorageAccountName) {
    $cleanPrefix = $Prefix -replace "[-_]", ""
    $StorageAccountName = "${cleanPrefix}st"
}
if (-not $ServiceBusNamespace) { $ServiceBusNamespace = "$Prefix-sbus" }
if (-not $CosmosAccountName) { $CosmosAccountName = "$Prefix-cosmos" }
if (-not $AiAccountName) { $AiAccountName = "$Prefix-aifoundry" }

Write-Host "🔐 Assigning RBAC roles for local development..." -ForegroundColor Cyan
Write-Host ""

# Get current user's object ID
Write-Host "Getting current Azure CLI user..." -ForegroundColor Yellow
$currentUser = az ad signed-in-user show --query id -o tsv
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to get current user. Make sure you're logged in with 'az login'"
    exit 1
}
Write-Host "✅ Current user object ID: $currentUser" -ForegroundColor Green
Write-Host ""

# Storage roles
Write-Host "📦 Assigning Storage roles..." -ForegroundColor Yellow
$storageId = az storage account show --name $StorageAccountName --resource-group $ResourceGroup --query id -o tsv

if ($LASTEXITCODE -eq 0) {
    # Storage Blob Data Contributor (read, write, delete blobs)
    Write-Host "  - Storage Blob Data Contributor"
    az role assignment create --assignee $currentUser --role "Storage Blob Data Contributor" --scope $storageId 2>$null

    Write-Host "✅ Storage roles assigned" -ForegroundColor Green
} else {
    Write-Warning "  ⚠️  Storage account not found or not accessible"
}
Write-Host ""

# Service Bus roles
Write-Host "📨 Assigning Service Bus roles..." -ForegroundColor Yellow
$serviceBusId = az servicebus namespace show --name $ServiceBusNamespace --resource-group $ResourceGroup --query id -o tsv

if ($LASTEXITCODE -eq 0) {
    # Azure Service Bus Data Owner (send and receive messages)
    Write-Host "  - Azure Service Bus Data Owner"
    az role assignment create --assignee $currentUser --role "Azure Service Bus Data Owner" --scope $serviceBusId 2>$null

    Write-Host "✅ Service Bus roles assigned" -ForegroundColor Green
} else {
    Write-Warning "  ⚠️  Service Bus namespace not found or not accessible"
}
Write-Host ""

# Cosmos DB roles
Write-Host "🗄️  Assigning Cosmos DB roles..." -ForegroundColor Yellow
$cosmosId = az cosmosdb show --name $CosmosAccountName --resource-group $ResourceGroup --query id -o tsv

if ($LASTEXITCODE -eq 0) {
    # Cosmos DB Built-in Data Contributor (RBAC for data plane)
    # Note: For local dev we use the built-in role (superset of the Terraform-managed Custom App Role).
    # The Custom App Role is narrower (readMetadata + specific CRUD) and is managed by Terraform for the Managed Identity.
    Write-Host "  - Cosmos DB Built-in Data Contributor (data plane, local dev)"

    # For Cosmos DB RBAC, we need to use a different command
    $roleDefinitionId = "00000000-0000-0000-0000-000000000002"  # Built-in Data Contributor
    az cosmosdb sql role assignment create `
        --account-name $CosmosAccountName `
        --resource-group $ResourceGroup `
        --role-definition-id $roleDefinitionId `
        --principal-id $currentUser `
        --scope "/" 2>$null

    Write-Host "✅ Cosmos DB roles assigned" -ForegroundColor Green
} else {
    Write-Warning "  ⚠️  Cosmos DB account not found or not accessible"
}
Write-Host ""

# AI Foundry roles
Write-Host "🤖 Assigning AI Foundry roles..." -ForegroundColor Yellow
$aiId = az cognitiveservices account show --name $AiAccountName --resource-group $ResourceGroup --query id -o tsv 2>$null

if ($LASTEXITCODE -eq 0) {
    Write-Host "  - Cognitive Services User"
    az role assignment create --assignee $currentUser --role "Cognitive Services User" --scope $aiId 2>$null

    Write-Host "✅ AI Foundry roles assigned" -ForegroundColor Green
} else {
    Write-Warning "  ⚠️  AI Foundry account not found or not accessible"
}
Write-Host ""

Write-Host "🎉 RBAC role assignment complete!" -ForegroundColor Green
Write-Host ""
Write-Host "⏰ Note: Role assignments may take a few minutes to propagate." -ForegroundColor Yellow
Write-Host "   If you get authorization errors, wait 2-3 minutes and try again." -ForegroundColor Yellow
Write-Host ""
Write-Host "✨ You can now run: uv run python scripts/test_e2e_local.py" -ForegroundColor Cyan
