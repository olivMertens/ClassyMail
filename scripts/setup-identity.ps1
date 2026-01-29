# Script de configuration rapide - Identité Managée et Container Apps
# Usage: .\scripts\setup-identity.ps1

param(
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup = "email-poc-rg",

    [Parameter(Mandatory=$false)]
    [string]$IdentityName = "email-poc-app-id",

    [Parameter(Mandatory=$false)]
    [string]$ApiAppName = "email-poc-api",

    [Parameter(Mandatory=$false)]
    [string]$WorkerAppName = "email-poc-worker",

    [Parameter(Mandatory=$false)]
    [string]$LogWorkspaceName = "email-poc-logs",

    [Parameter(Mandatory=$false)]
    [switch]$ApplyRoles
)

Write-Host "🚀 Configuration de l'identité managée et des Container Apps" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

# Vérifier la connexion Azure
Write-Host "✓ Vérification de la connexion Azure..." -ForegroundColor Yellow
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "❌ Vous n'êtes pas connecté à Azure. Exécutez 'az login' d'abord." -ForegroundColor Red
    exit 1
}
Write-Host "  → Abonnement actif: $($account.name)" -ForegroundColor Green
Write-Host ""

# Récupérer les informations de l'identité managée
Write-Host "📋 Récupération des informations de l'identité managée..." -ForegroundColor Yellow
$identity = az identity show `
    --resource-group $ResourceGroup `
    --name $IdentityName `
    2>$null | ConvertFrom-Json

if (-not $identity) {
    Write-Host "❌ Identité managée '$IdentityName' introuvable dans le groupe '$ResourceGroup'" -ForegroundColor Red
    exit 1
}

$clientId = $identity.clientId
$principalId = $identity.principalId
$identityResourceId = $identity.id

Write-Host "  → Client ID: $clientId" -ForegroundColor Green
Write-Host "  → Principal ID: $principalId" -ForegroundColor Green
Write-Host ""

# Récupérer le Workspace ID de Log Analytics
Write-Host "📊 Récupération du Log Analytics Workspace ID..." -ForegroundColor Yellow
$workspace = az monitor log-analytics workspace show `
    --resource-group $ResourceGroup `
    --workspace-name $LogWorkspaceName `
    2>$null | ConvertFrom-Json

if (-not $workspace) {
    Write-Host "⚠️  Workspace '$LogWorkspaceName' introuvable. Les logs ne seront pas disponibles." -ForegroundColor Yellow
    $workspaceId = ""
} else {
    $workspaceId = $workspace.customerId
    Write-Host "  → Workspace ID: $workspaceId" -ForegroundColor Green
}
Write-Host ""

# Mettre à jour les Container Apps
Write-Host "🐳 Configuration des Container Apps..." -ForegroundColor Yellow

# API Container App
Write-Host "  → Configuration de $ApiAppName..." -ForegroundColor Cyan
$apiUpdate = az containerapp update `
    --resource-group $ResourceGroup `
    --name $ApiAppName `
    --set-env-vars `
        "AZURE_CLIENT_ID=$clientId" `
        "LOG_ANALYTICS_WORKSPACE_ID=$workspaceId" `
    2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "    ✓ API mise à jour avec succès" -ForegroundColor Green
} else {
    Write-Host "    ❌ Erreur lors de la mise à jour de l'API" -ForegroundColor Red
}

# Worker Container App
Write-Host "  → Configuration de $WorkerAppName..." -ForegroundColor Cyan
$workerUpdate = az containerapp update `
    --resource-group $ResourceGroup `
    --name $WorkerAppName `
    --set-env-vars `
        "AZURE_CLIENT_ID=$clientId" `
        "LOG_ANALYTICS_WORKSPACE_ID=$workspaceId" `
    2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "    ✓ Worker mis à jour avec succès" -ForegroundColor Green
} else {
    Write-Host "    ❌ Erreur lors de la mise à jour du Worker" -ForegroundColor Red
}
Write-Host ""

# Optionnel: Appliquer les rôles RBAC
if ($ApplyRoles) {
    Write-Host "🔐 Application des rôles RBAC..." -ForegroundColor Yellow

    # Storage Blob Data Contributor
    Write-Host "  → Storage Blob Data Contributor..." -ForegroundColor Cyan
    $storageAccount = az storage account list `
        --resource-group $ResourceGroup `
        --query "[0].id" `
        --output tsv

    if ($storageAccount) {
        az role assignment create `
            --assignee $principalId `
            --role "Storage Blob Data Contributor" `
            --scope $storageAccount `
            2>$null | Out-Null
        Write-Host "    ✓ Rôle assigné" -ForegroundColor Green
    }

    # Storage Blob Data Reader
    Write-Host "  → Storage Blob Data Reader..." -ForegroundColor Cyan
    if ($storageAccount) {
        az role assignment create `
            --assignee $principalId `
            --role "Storage Blob Data Reader" `
            --scope $storageAccount `
            2>$null | Out-Null
        Write-Host "    ✓ Rôle assigné" -ForegroundColor Green
    }

    # Service Bus Data Receiver
    Write-Host "  → Service Bus Data Receiver..." -ForegroundColor Cyan
    $serviceBus = az servicebus namespace list `
        --resource-group $ResourceGroup `
        --query "[0].id" `
        --output tsv

    if ($serviceBus) {
        az role assignment create `
            --assignee $principalId `
            --role "Azure Service Bus Data Receiver" `
            --scope $serviceBus `
            2>$null | Out-Null
        Write-Host "    ✓ Rôle assigné" -ForegroundColor Green
    }

    # Service Bus Data Sender
    Write-Host "  → Service Bus Data Sender..." -ForegroundColor Cyan
    if ($serviceBus) {
        az role assignment create `
            --assignee $principalId `
            --role "Azure Service Bus Data Sender" `
            --scope $serviceBus `
            2>$null | Out-Null
        Write-Host "    ✓ Rôle assigné" -ForegroundColor Green
    }

    # Log Analytics Reader
    Write-Host "  → Log Analytics Reader..." -ForegroundColor Cyan
    if ($workspace) {
        az role assignment create `
            --assignee $principalId `
            --role "Log Analytics Reader" `
            --scope $workspace.id `
            2>$null | Out-Null
        Write-Host "    ✓ Rôle assigné" -ForegroundColor Green
    }

    # Cognitive Services User
    Write-Host "  → Cognitive Services User..." -ForegroundColor Cyan
    $aiAccount = az cognitiveservices account list `
        --resource-group $ResourceGroup `
        --query "[0].id" `
        --output tsv

    if ($aiAccount) {
        az role assignment create `
            --assignee $principalId `
            --role "Cognitive Services User" `
            --scope $aiAccount `
            2>$null | Out-Null
        Write-Host "    ✓ Rôle assigné" -ForegroundColor Green
    }
    Write-Host ""
}

# Générer le fichier secrets.env local
Write-Host "📝 Génération du fichier secrets.env pour le développement local..." -ForegroundColor Yellow
$secretsEnvPath = Join-Path $PSScriptRoot "..\secrets.env"

$secretsContent = @"
# Généré automatiquement par setup-identity.ps1
# Date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

# --- Identité Managée ---
AZURE_CLIENT_ID=$clientId

# --- Log Analytics ---
LOG_ANALYTICS_WORKSPACE_ID=$workspaceId

# --- Azure Resources (à compléter avec Terraform outputs) ---
# Exécutez: cd infra && terraform output
AZURE_SERVICE_BUS_FQDN=
AZURE_SERVICE_BUS_QUEUE=pdf-processing-queue
AZURE_STORAGE_ACCOUNT_URL=
AZURE_STORAGE_CONTAINER=pdf-inputs
AZURE_COSMOS_ENDPOINT=
AZURE_COSMOS_DB=emailsdb
AZURE_COSMOS_CONTAINER=emails
AZURE_AI_ENDPOINT=
PHI_ENDPOINT=
PHI_DEPLOYMENT=Phi-4
MISTRAL_ENDPOINT=
MISTRAL_DEPLOYMENT=mistral-ocr-2505
CHAT_DEPLOYMENT=gpt-5.2-chat
EMBEDDING_DEPLOYMENT=text-embedding-3-small
"@

Set-Content -Path $secretsEnvPath -Value $secretsContent -Force
Write-Host "  ✓ Fichier secrets.env créé/mis à jour" -ForegroundColor Green
Write-Host "  → Emplacement: $secretsEnvPath" -ForegroundColor Cyan
Write-Host ""

# Résumé
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "✅ Configuration terminée avec succès!" -ForegroundColor Green
Write-Host ""
Write-Host "📌 Prochaines étapes:" -ForegroundColor Yellow
Write-Host "  1. Compléter secrets.env avec les outputs Terraform:" -ForegroundColor White
Write-Host "     cd infra && terraform output" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. Tester la connexion localement:" -ForegroundColor White
Write-Host "     uv run pytest tests/test_smoke.py" -ForegroundColor Gray
Write-Host ""
Write-Host "  3. Vérifier les logs dans l'UI:" -ForegroundColor White
Write-Host "     → Settings > Telemetry Logs" -ForegroundColor Gray
Write-Host ""

# Afficher l'URL de l'API
$apiUrl = az containerapp show `
    --resource-group $ResourceGroup `
    --name $ApiAppName `
    --query "properties.configuration.ingress.fqdn" `
    --output tsv 2>$null

if ($apiUrl) {
    Write-Host "🌐 URL de l'API: https://$apiUrl" -ForegroundColor Cyan
}
