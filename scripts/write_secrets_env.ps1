[CmdletBinding()]
param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
  [string]$ResourceGroup,
  [string]$Prefix = 'email-poc',
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

$lines = @(
  '# Fichier local (NE PAS COMMITTER) — ignoré par .gitignore',
  '# Généré via scripts/write_secrets_env.ps1',
  '',
  'PORT=8000',
  "API_BASE_URL=$apiBaseUrl",
  '',
  "# Managed Identity (User Assigned) — clientId de l'identité utilisée par l'app",
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
  '',
  '# Azure AI Foundry / Cognitive Services endpoint (même endpoint pour Mistral + Phi si vous utilisez Foundry)',
  "AZURE_AI_ENDPOINT=$aiEndpoint",
  "AZURE_AI_API_VERSION=$aiApiVersion",
  "AZURE_AI_SCOPE=$aiScope",
  "MISTRAL_ENDPOINT=$aiEndpoint",
  'MISTRAL_DEPLOYMENT=mistral-ocr-2505',
  'MISTRAL_MODE=maas',
  "PHI_ENDPOINT=$aiEndpoint",
  'PHI_DEPLOYMENT=phi-4',
  '',
  '# Azure OpenAI (utilisé uniquement pour scripts/generate_dummy_pdfs.py si --use-aoai)',
  "AZURE_OPENAI_ENDPOINT=$aiEndpoint",
  'AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini',
  'AZURE_OPENAI_API_VERSION=2024-10-01-preview',
  'AZURE_OPENAI_SCOPE=https://cognitiveservices.azure.com/.default',
  '# AZURE_OPENAI_API_KEY=__optional__  # si absent, auth Entra ID via DefaultAzureCredential',
  ''
)

# Écrire sans afficher le contenu (évite de leak des infos dans les logs CI)
Set-Content -Path $outPath -Value ($lines -join "`n") -Encoding UTF8

Write-Output "OK: secrets.env écrit dans '$outPath'"
