[CmdletBinding()]
param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
  [string]$ResourceGroup,
  [string]$Prefix = 'classymail',
  [string]$OutFile = 'secrets.env',
  [switch]$Force
)

$ErrorActionPreference = 'Stop'

function Require-AzCli {
  $az = Get-Command az -ErrorAction SilentlyContinue
  if (-not $az) {
    throw 'az introuvable. Installez Azure CLI puis relancez ce script.'
  }

  $account = az account show -o json 2>$null | ConvertFrom-Json
  if (-not $account) {
    throw "Impossible de lire le contexte Azure. Lancez d'abord 'az login'."
  }
}

function Get-Rg([string]$rg, [string]$prefix) {
  if ($rg) { return $rg }
  $found = az group list --query "[?starts_with(name, '$prefix')].name | [0]" -o tsv 2>$null
  if (-not $found) {
    throw "Resource group introuvable. Passez -ResourceGroup <nom> (ou ajustez -Prefix)."
  }
  return $found.Trim()
}

function Get-FirstOrNull([string]$command) {
  try {
    $value = Invoke-Expression $command
    if ($null -eq $value) { return $null }
    $text = ("$value").Trim()
    if ($text -eq '') { return $null }
    return $text
  } catch {
    return $null
  }
}

$outPath = Join-Path $RepoRoot $OutFile

if ((Test-Path $outPath) -and -not $Force) {
  throw "Le fichier '$outPath' existe déjà. Relancez avec -Force pour l'écraser."
}

Require-AzCli
$rg = Get-Rg -rg $ResourceGroup -prefix $Prefix

# Découverte des ressources via az CLI (sans Terraform)
$identityName = Get-FirstOrNull "az identity list -g '$rg' --query '[0].name' -o tsv"
$appClientId = if ($identityName) {
  Get-FirstOrNull "az identity show -g '$rg' -n '$identityName' --query clientId -o tsv"
} else { $null }

$sbNamespace = Get-FirstOrNull "az servicebus namespace list -g '$rg' --query '[0].name' -o tsv"
$serviceBusFqdn = if ($sbNamespace) { "$sbNamespace.servicebus.windows.net" } else { $null }
$serviceBusQueue = if ($sbNamespace) {
  Get-FirstOrNull "az servicebus queue list -g '$rg' --namespace-name '$sbNamespace' --query '[0].name' -o tsv"
} else { $null }

$storageAccountName = Get-FirstOrNull "az storage account list -g '$rg' --query '[0].name' -o tsv"
$storageAccountUrl = if ($storageAccountName) {
  Get-FirstOrNull "az storage account show -g '$rg' -n '$storageAccountName' --query primaryEndpoints.blob -o tsv"
} else { $null }

# IMPORTANT: Dans beaucoup de tenants, le Storage est privé (pas d'accès data-plane depuis le poste).
# On n'essaie pas de lister les containers ici (ça peut être lent/bloqué) et on utilise la valeur IaC par défaut.
$storageContainer = 'pdf-inputs'

$cosmosAccount = Get-FirstOrNull "az cosmosdb list -g '$rg' --query '[0].name' -o tsv"
$cosmosEndpoint = if ($cosmosAccount) {
  Get-FirstOrNull "az cosmosdb show -g '$rg' -n '$cosmosAccount' --query documentEndpoint -o tsv"
} else { $null }
$cosmosDb = if ($cosmosAccount) {
  $d = Get-FirstOrNull "az cosmosdb sql database list -g '$rg' -a '$cosmosAccount' --query '[0].name' -o tsv"
  if ($d) { $d } else { 'emailsdb' }
} else { 'emailsdb' }
$cosmosContainer = if ($cosmosAccount) {
  $t = Get-FirstOrNull "az cosmosdb sql container list -g '$rg' -a '$cosmosAccount' -d '$cosmosDb' --query '[0].name' -o tsv"
  if ($t) { $t } else { 'emails' }
} else { 'emails' }

$aiEndpoint = Get-FirstOrNull "az cognitiveservices account list -g '$rg' --query ""[?kind=='AIServices'].properties.endpoint | [0]"" -o tsv"
if (-not $aiEndpoint) {
  $aiEndpoint = Get-FirstOrNull "az cognitiveservices account list -g '$rg' --query '[0].properties.endpoint' -o tsv"
}

# URL publique de l'API (si ingress externe)
$apiFqdn = Get-FirstOrNull "az containerapp list -g '$rg' --query `"[?contains(name, 'api')].properties.configuration.ingress.fqdn | [0]`" -o tsv"
if (-not $apiFqdn) {
  $apiFqdn = Get-FirstOrNull "az containerapp list -g '$rg' --query `"[?properties.configuration.ingress.fqdn!=null].properties.configuration.ingress.fqdn | [0]`" -o tsv"
}
$apiBaseUrl = if ($apiFqdn) { "https://$apiFqdn" } else { $null }

# Valeurs par défaut cohérentes avec main.py (peuvent être ajustées localement)
$aiApiVersion = '2024-08-01-preview'
$aiScope = 'https://cognitiveservices.azure.com/.default'

# Découverte Application Insights (pour telemetry)
# Note: Utilisation de 'az resource' car 'az monitor' peut échouer si le module python est corrompu
$appInsightsName = Get-FirstOrNull "az resource list -g '$rg' --resource-type 'Microsoft.Insights/components' --query '[0].name' -o tsv"
$appInsightsConnStr = if ($appInsightsName) {
  Get-FirstOrNull "az resource show -g '$rg' -n '$appInsightsName' --resource-type 'Microsoft.Insights/components' --query properties.ConnectionString -o tsv"
} else { $null }

# Découverte Log Analytics Workspace
$logWorkspaceName = Get-FirstOrNull "az monitor log-analytics workspace list -g '$rg' --query '[0].name' -o tsv"
$logWorkspaceId = if ($logWorkspaceName) {
  Get-FirstOrNull "az monitor log-analytics workspace show -g '$rg' -n '$logWorkspaceName' --query customerId -o tsv"
} else { $null }

# Découverte Azure AI Language (optional)
$languageEndpoint = Get-FirstOrNull "az cognitiveservices account list -g '$rg' --query `"[?kind=='TextAnalytics'].properties.endpoint | [0]`" -o tsv"

$lines = @(
  '# =============================================================================',
  '# Fichier local (NE PAS COMMITTER) — ignoré par .gitignore',
  '# Généré via scripts/write_secrets_env.ps1',
  "# Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
  '# =============================================================================',
  '',
  '# --- CORE AZURE RESOURCES ---',
  '',
  '# Managed Identity (User Assigned) — clientId',
  "AZURE_CLIENT_ID=$appClientId",
  '',
  '# Service Bus',
  "AZURE_SERVICE_BUS_FQDN=$serviceBusFqdn",
  "AZURE_SERVICE_BUS_QUEUE=$serviceBusQueue",
  '',
  '# Blob Storage',
  "AZURE_STORAGE_ACCOUNT_URL=$storageAccountUrl",
  "AZURE_STORAGE_CONTAINER=$storageContainer",
  '',
  '# Cosmos DB',
  "AZURE_COSMOS_ENDPOINT=$cosmosEndpoint",
  "AZURE_COSMOS_DB=$cosmosDb",
  "AZURE_COSMOS_CONTAINER=$cosmosContainer",
  'AZURE_COSMOS_CHAT_CONTAINER=chat_history',
  'AZURE_COSMOS_CACHE_CONTAINER=vector_cache',
  '',
  '# --- AI MODEL ENDPOINTS ---',
  '',
  '# Main AI Foundry Endpoint',
  "AZURE_AI_ENDPOINT=$aiEndpoint",
  "AI_API_VERSION=$aiApiVersion",
  "AI_SCOPE=$aiScope",
  '',
  '# Mistral OCR Model',
  "MISTRAL_ENDPOINT=$aiEndpoint",
  'MISTRAL_DEPLOYMENT=mistral-document-ai-2512',
  'MISTRAL_MODE=maas',
  'MISTRAL_API_VERSION=2024-05-01-preview',
  '',
  '# Phi-4 Classification Model',
  "PHI_ENDPOINT=$aiEndpoint",
  'PHI_DEPLOYMENT=phi-4',
  '',
  '# Fallback Model (long context)',
  "PHI_FALLBACK_ENDPOINT=$aiEndpoint",
  'PHI_FALLBACK_DEPLOYMENT=gpt-4.1-mini',
  '',
  '# --- RAG & EMBEDDINGS (Optional) ---',
  '',
  '# Embedding Model',
  "EMBEDDING_ENDPOINT=$aiEndpoint",
  'EMBEDDING_DEPLOYMENT=text-embedding-3-small',
  "EMBEDDING_API_VERSION=$aiApiVersion",
  '',
  '# Chat Model (RAG)',
  "CHAT_ENDPOINT=$aiEndpoint",
  'CHAT_DEPLOYMENT=gpt-5.1',
  'CHAT_API_VERSION=preview',
  '',
  '# Vision Model',
  "VISION_ENDPOINT=$aiEndpoint",
  'VISION_DEPLOYMENT=gpt-4.1-mini',
  "VISION_API_VERSION=$aiApiVersion",
  '',
  '# --- PII DETECTION & ANONYMIZATION (Optional) ---',
  '',
  '# Azure AI Language (Native PII Detection)',
  "AZURE_LANGUAGE_ENDPOINT=$languageEndpoint",
  '',
  '# Anonymization Model',
  "ANONYMIZER_ENDPOINT=$aiEndpoint",
  'ANONYMIZER_DEPLOYMENT=gpt-4.1-mini',
  "ANONYMIZER_API_VERSION=$aiApiVersion",
  'ANONYMIZER_PROMPT_VERSION=v1',
  'ANONYMIZER_MAX_TOKENS=6000',
  '',
  '# --- TELEMETRY & OBSERVABILITY ---',
  '',
  '# Application Insights',
  "APPLICATIONINSIGHTS_CONNECTION_STRING=$appInsightsConnStr",
  '',
  '# Log Analytics',
  "LOG_ANALYTICS_WORKSPACE_ID=$logWorkspaceId",
  '',
  '# OpenTelemetry',
  'OTEL_SERVICE_NAME=classymail-api',
  'OTEL_RESOURCE_ATTRIBUTES=service.namespace=classymail',
  'AZURE_MONITOR_ENABLE_GENAI_TRACES=true',
  '',
  '# --- CONFIGURATION (Defaults) ---',
  '',
  'AZURE_REGION=swedencentral',
  'AZURE_PREFERRED_DATA_ZONE=eu-central',
  'COSMOS_QUERY_MAX_LIMIT=100',
  'PHI_PRIMARY_MAX_INPUT_TOKENS=8000',
  'PHI_FALLBACK_MAX_INPUT_TOKENS=120000',
  'PHI_RESERVED_OUTPUT_TOKENS=1000',
  '',
  '# Cost Tracking',
  'PHI4_COST_PER_1K_INPUT=0.000107',
  'PHI4_COST_PER_1K_OUTPUT=0.00043',
  'MISTRAL_OCR_COST_PER_1K_PAGES=1.0',
  'FALLBACK_COST_PER_1K_INPUT=0.00015',
  'FALLBACK_COST_PER_1K_OUTPUT=0.0006',
  '',
  '# OCR Configuration',
  'MISTRAL_OCR_MAX_ATTEMPTS=2',
  'REVIEW_CONFIDENCE_THRESHOLD=0.85',
  '',
  '# --- WORKER CONFIGURATION ---',
  '',
  'WORKER_CONCURRENCY=30',
  'WORKER_LOCK_RENEWAL_DURATION=3600',
  'MISTRAL_RPM=30',
  'MISTRAL_TPM=60000',
  'PHI_RPM=60',
  'PHI_TPM=80000',
  'CHAT_RPM=60',
  'CHAT_TPM=80000',
  '',
  '# --- UI CONFIGURATION ---',
  '',
  'UI_SHOW_INFO_MODAL=true',
  'UI_SHOW_DEVELOPER_TAB=true',
  'ORGANIZATION_NAME=ClassyMail',
  'MAX_UPLOAD_SIZE=10',
  'UPLOAD_MAX_BYTES=10485760',
  '',
  '# --- ENVIRONMENT ---',
  '',
  'AZURE_ENV=development',
  'PORT=8000',
  "API_BASE_URL=$apiBaseUrl",
  '',
  '# --- TESTING (Local Development) ---',
  '',
  '# Azure OpenAI (for scripts/generate_dummy_pdfs.py --use-aoai)',
  "AZURE_OPENAI_ENDPOINT=$aiEndpoint",
  'AZURE_OPENAI_DEPLOYMENT=gpt-4.1-mini',
  'AZURE_OPENAI_API_VERSION=2024-10-01-preview',
  'AZURE_OPENAI_SCOPE=https://cognitiveservices.azure.com/.default',
  'AZURE_OPENAI_TIMEOUT=30',
  '# AZURE_OPENAI_API_KEY=  # Optional: for key-based auth',
  ''
)

# Écrire sans afficher le contenu (évite de leak des infos dans les logs CI)
Set-Content -Path $outPath -Value ($lines -join "`n") -Encoding UTF8

Write-Output "OK: secrets.env écrit dans '$outPath'"
