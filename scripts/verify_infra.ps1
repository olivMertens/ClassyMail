param(
  [string]$ResourceGroup = $(if ($env:RESOURCE_GROUP) {$env:RESOURCE_GROUP} else {"classymail-rg"}),
  [string]$Prefix = $(if ($env:PREFIX) {$env:PREFIX} else {"classymail"}),
  [string]$IdentityName = $env:IDENTITY_NAME,
  [string]$CosmosAccount = $env:COSMOS_ACCOUNT,
  [string]$CosmosDb = $(if ($env:COSMOS_DB) {$env:COSMOS_DB} else {"emailsdb"}),
  [string[]]$CosmosContainers = $(if ($env:COSMOS_CONTAINERS) { $env:COSMOS_CONTAINERS.Split(' ') } else { @("emails","chat_history","vector_cache") }),
  [string]$StorageAccount = $env:STORAGE_ACCOUNT,
  [string]$ServiceBusNamespace = $env:SERVICEBUS_NAMESPACE,
  [string]$ServiceBusQueue = $(if ($env:SERVICEBUS_QUEUE) {$env:SERVICEBUS_QUEUE} else {"pdf-processing-queue"}),
  [string]$AiAccount = $env:AI_ACCOUNT,
  [string]$ContainerAppApi = $env:CONTAINER_APP_API,
  [string]$ContainerAppWorker = $env:CONTAINER_APP_WORKER
)

if (-not $IdentityName) { $IdentityName = "$Prefix-id" }
if (-not $CosmosAccount) { $CosmosAccount = "$Prefix-cosmos" }
if (-not $StorageAccount) {
    # Remove hyphens/underscores for default storage name
    $cleanPrefix = $Prefix -replace "[-_]", ""
    $StorageAccount = "${cleanPrefix}st"
}
if (-not $ServiceBusNamespace) { $ServiceBusNamespace = "$Prefix-sbus" }
if (-not $AiAccount) { $AiAccount = "$Prefix-aifoundry" }
if (-not $ContainerAppApi) { $ContainerAppApi = "$Prefix-api" }
if (-not $ContainerAppWorker) { $ContainerAppWorker = "$Prefix-worker" }

# Load from secrets.env if available and params not set
$AuthEnvPath = Join-Path $PSScriptRoot "../secrets.env"
if (Test-Path $AuthEnvPath) {
    $envContent = Get-Content $AuthEnvPath
    if (-not $ResourceGroup) {
        $rgMatch = $envContent | Select-String "AZURE_RESOURCE_GROUP=(.+)"
        if ($rgMatch) { $ResourceGroup = $rgMatch.Matches.Groups[1].Value.Trim() }
    }
    # Try to derive usage from known FQDN patterns in secrets.env if needed
    if (-not $ServiceBusNamespace) {
        $sbMatch = $envContent | Select-String "AZURE_SERVICE_BUS_FQDN=(.+)\.servicebus"
        if ($sbMatch) { $ServiceBusNamespace = $sbMatch.Matches.Groups[1].Value.Trim() }
    }
    if (-not $StorageAccount) {
        $stMatch = $envContent | Select-String "AZURE_STORAGE_ACCOUNT_URL=https://(.+)\.blob\.core\.windows\.net"
        if ($stMatch) { $StorageAccount = $stMatch.Matches.Groups[1].Value.Trim() }
    }
    if (-not $CosmosAccount) {
        $cosmosMatch = $envContent | Select-String "AZURE_COSMOS_ENDPOINT=https://(.+)\.documents\.azure\.com"
        if ($cosmosMatch) { $CosmosAccount = $cosmosMatch.Matches.Groups[1].Value.Trim() }
    }
    if (-not $AiAccount) {
        $aiMatch = $envContent | Select-String "AZURE_AI_ENDPOINT=https://(.+)\.cognitiveservices\.azure\.com"
        if ($aiMatch) { $AiAccount = $aiMatch.Matches.Groups[1].Value.Trim() }
    }
}

function Info($msg){ Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Ok($msg){ Write-Host "[OK] $msg" -ForegroundColor Green }
function Warn($msg){ Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Err($msg){ Write-Host "[ERR] $msg" -ForegroundColor Red }

Info "Configuration:"
Write-Host "  Resource Group: '$ResourceGroup'"
Write-Host "  Identity Name : '$IdentityName'"
Write-Host "  Prefix        : '$Prefix'"

Info "Checking az login"
az account show *> $null; if ($LASTEXITCODE -ne 0) { az login *> $null }
$subId = az account show --query id -o tsv
Ok "Logged in to $subId"

Info "Fetching Managed Identity $IdentityName in RG $ResourceGroup"
# Removed 2>$null to show error if any
$principalId = az identity show -g $ResourceGroup -n $IdentityName --query principalId -o tsv
if (-not $principalId) { Err "Identity not found"; exit 1 }
Ok "PrincipalId: $principalId"

function Ensure-Role($scope, $role, $desc){
  Info "Ensure role '$role' on $desc"
  $assigned = az role assignment list --assignee $principalId --scope $scope --query "[?roleDefinitionName=='$role']" -o tsv
  if ($assigned) { Ok "Role already assigned" }
  else { az role assignment create --assignee $principalId --role $role --scope $scope *> $null; if ($LASTEXITCODE -eq 0){ Ok "Role assigned" } else { Err "Failed to assign $role" } }
}

Info "Check RG"
az group show -n $ResourceGroup *> $null; if ($LASTEXITCODE -ne 0){ Err "RG missing"; exit 1 } else { Ok "RG exists" }

Info "Check Storage"
$storageId = az storage account show -g $ResourceGroup -n $StorageAccount --query id -o tsv 2>$null; if ($storageId){ Ok "Storage exists" } else { Warn "Storage missing" }

Info "Check Service Bus"
$sbId = az servicebus namespace show -g $ResourceGroup -n $ServiceBusNamespace --query id -o tsv 2>$null; if ($sbId){ Ok "SB exists"; az servicebus queue show -g $ResourceGroup --namespace-name $ServiceBusNamespace -n $ServiceBusQueue *> $null; if ($LASTEXITCODE -eq 0){ Ok "Queue exists" } else { Warn "Queue missing" } } else { Warn "Service Bus missing" }

Info "Check Cosmos"
$cosmosId = az cosmosdb show -g $ResourceGroup -n $CosmosAccount --query id -o tsv 2>$null; if ($cosmosId){
  Ok "Cosmos exists"
  az cosmosdb sql database show -g $ResourceGroup -a $CosmosAccount -n $CosmosDb *> $null; if ($LASTEXITCODE -eq 0){ Ok "DB exists" } else { Warn "DB missing" }
  foreach ($c in $CosmosContainers){ az cosmosdb sql container show -g $ResourceGroup -a $CosmosAccount -d $CosmosDb -n $c *> $null; if ($LASTEXITCODE -eq 0){ Ok "Container $c exists" } else { Warn "Container $c missing" } }
} else { Warn "Cosmos missing" }

Info "Check Cognitive Services"
$aiId = az cognitiveservices account show -g $ResourceGroup -n $AiAccount --query id -o tsv 2>$null; if ($aiId){ Ok "AI account exists" } else { Warn "AI account missing" }

Info "Check Container Apps"
az containerapp show -g $ResourceGroup -n $ContainerAppApi *> $null; if ($LASTEXITCODE -eq 0){ Ok "API CA exists" } else { Warn "API CA missing" }
az containerapp show -g $ResourceGroup -n $ContainerAppWorker *> $null; if ($LASTEXITCODE -eq 0){ Ok "Worker CA exists" } else { Warn "Worker CA missing" }

if ($aiId){ Ensure-Role $aiId "Cognitive Services User" "Cognitive Services" }
if ($storageId){ Ensure-Role $storageId "Storage Blob Data Contributor" "Storage" }
if ($sbId){ Ensure-Role $sbId "Azure Service Bus Data Owner" "Service Bus" }
if ($cosmosId){
  Info "Checking Cosmos DB SQL Role Assignments..."
  $cosmosAssignments = az cosmosdb sql role assignment list --account-name $CosmosAccount --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
  $myAssignments = $cosmosAssignments | Where-Object { $_.principalId -eq $principalId }
  if ($myAssignments) {
    Ok "Cosmos DB SQL Role assigned ($($myAssignments.Count) assignment(s))"
    foreach ($a in $myAssignments) {
      # Check scope is account-level (not database-scoped)
      if ($a.scope -match '/dbs/') {
        Warn "  Cosmos role scoped to DATABASE ($($a.scope)) — should be Account scope for SDK readMetadata"
      } else {
        Ok "  Scope: Account-level (correct)"
      }
      # Check if custom role or built-in
      if ($a.roleDefinitionId -match '00000000-0000-0000-0000-000000000002') {
        Info "  Using built-in Data Contributor role"
      } else {
        Ok "  Using Custom App Role ($($a.roleDefinitionId | Split-Path -Leaf))"
      }
    }
  } else { Warn "Cosmos DB SQL Role MISSING. Run Terraform to fix." }
}
$acrId = az acr list -g $ResourceGroup --query "[0].id" -o tsv 2>$null; if ($acrId){ Ensure-Role $acrId "AcrPull" "ACR" }

# Language Reader — only needed when a Language service exists in the RG
Info "Checking for Language Service (optional)..."
$langId = az cognitiveservices account list -g $ResourceGroup --query "[?kind=='TextAnalytics'] | [0].id" -o tsv 2>$null
if ($langId) {
  Ensure-Role $langId "Cognitive Services Language Reader" "Language Service"
} else {
  Info "No Language Service found in RG — skipping Language Reader check"
}

# AZURE_CLIENT_ID env var on Container Apps
Info "Checking AZURE_CLIENT_ID env var on Container Apps..."
foreach ($caName in @($ContainerAppApi, $ContainerAppWorker)) {
  $envVars = az containerapp show -g $ResourceGroup -n $caName --query "properties.template.containers[0].env[].name" -o tsv 2>$null
  if ($envVars) {
    if ($envVars -contains "AZURE_CLIENT_ID") {
      Ok "AZURE_CLIENT_ID set on $caName"
    } else {
      Warn "AZURE_CLIENT_ID MISSING on $caName — DefaultAzureCredential may pick wrong identity"
    }
  } else {
    Info "Could not read env vars for $caName (may not be deployed yet)"
  }
}

# --- Unexpected / Extra Roles Detection ---
Info "Checking for unexpected extra roles on managed identity..."
$expectedRoles = @(
  "Storage Blob Data Contributor",
  "Azure Service Bus Data Owner",
  "Cognitive Services User",
  "AcrPull",
  "Cognitive Services Language Reader"  # optional but expected when Language service deployed
)
$allRoles = az role assignment list --assignee $principalId --all 2>$null | ConvertFrom-Json
if ($allRoles) {
  $unexpectedRoles = $allRoles | Where-Object { $_.roleDefinitionName -notin $expectedRoles }
  if ($unexpectedRoles -and $unexpectedRoles.Count -gt 0) {
    Warn "Found $($unexpectedRoles.Count) extra role(s) NOT managed by Terraform:"
    foreach ($ur in $unexpectedRoles) {
      Warn "  - $($ur.roleDefinitionName) on $($ur.scope | Split-Path -Leaf)"
    }
    Info "These may be manual leftovers. See docs/RBAC_AUDIT.md section 8."
  } else {
    Ok "No unexpected extra roles found — clean deployment"
  }
}

Warn "Policy check: TODO - awaiting policy level details for RG policies."

if ($cosmosId){ Info "Connectivity: list containers"; az cosmosdb sql container list -g $ResourceGroup -a $CosmosAccount -d $CosmosDb *> $null; if ($LASTEXITCODE -eq 0){ Ok "Cosmos connectivity OK" } else { Warn "Cosmos connectivity failed" } }
if ($storageId){ Info "Connectivity: storage containers"; az storage container list --account-name $StorageAccount --auth-mode login *> $null; if ($LASTEXITCODE -eq 0){ Ok "Storage connectivity OK" } else { Warn "Storage connectivity failed" } }
if ($sbId){ Info "Connectivity: service bus"; az servicebus namespace list -g $ResourceGroup *> $null; if ($LASTEXITCODE -eq 0){ Ok "Service Bus connectivity OK" } else { Warn "Service Bus connectivity failed" } }
