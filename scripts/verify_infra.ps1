param(
  [string]$ResourceGroup = $env:RESOURCE_GROUP -or "email-poc-rg",
  [string]$Prefix = $env:PREFIX -or "email-poc",
  [string]$IdentityName = $env:IDENTITY_NAME,
  [string]$CosmosAccount = $env:COSMOS_ACCOUNT,
  [string]$CosmosDb = $env:COSMOS_DB -or "emailsdb",
  [string[]]$CosmosContainers = $(if ($env:COSMOS_CONTAINERS) { $env:COSMOS_CONTAINERS.Split(' ') } else { @("emails","chat_history","vector_cache") }),
  [string]$StorageAccount = $env:STORAGE_ACCOUNT,
  [string]$ServiceBusNamespace = $env:SERVICEBUS_NAMESPACE,
  [string]$ServiceBusQueue = $env:SERVICEBUS_QUEUE -or "pdf-processing-queue",
  [string]$AiAccount = $env:AI_ACCOUNT,
  [string]$ContainerAppApi = $env:CONTAINER_APP_API,
  [string]$ContainerAppWorker = $env:CONTAINER_APP_WORKER
)

if (-not $IdentityName) { $IdentityName = "$Prefix-id" }
if (-not $CosmosAccount) { $CosmosAccount = "$Prefix-cosmos" }
if (-not $StorageAccount) { $StorageAccount = "$Prefix`st" }
if (-not $ServiceBusNamespace) { $ServiceBusNamespace = "$Prefix-sbus" }
if (-not $AiAccount) { $AiAccount = "$Prefix-aifoundry" }
if (-not $ContainerAppApi) { $ContainerAppApi = "$Prefix-api" }
if (-not $ContainerAppWorker) { $ContainerAppWorker = "$Prefix-worker" }

function Info($msg){ Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Ok($msg){ Write-Host "[OK] $msg" -ForegroundColor Green }
function Warn($msg){ Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Err($msg){ Write-Host "[ERR] $msg" -ForegroundColor Red }

Info "Checking az login"
az account show *> $null; if ($LASTEXITCODE -ne 0) { az login *> $null }
$subId = az account show --query id -o tsv
Ok "Logged in to $subId"

Info "Fetching Managed Identity $IdentityName"
$principalId = az identity show -g $ResourceGroup -n $IdentityName --query principalId -o tsv 2>$null
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
if ($sbId){ Ensure-Role $sbId "Azure Service Bus Data Sender" "Service Bus"; Ensure-Role $sbId "Azure Service Bus Data Receiver" "Service Bus" }
if ($cosmosId){ Ensure-Role $cosmosId "Cosmos DB Built-in Data Contributor" "Cosmos" }
$acrId = az acr list -g $ResourceGroup --query "[0].id" -o tsv 2>$null; if ($acrId){ Ensure-Role $acrId "AcrPull" "ACR" }

Warn "Policy check: TODO - awaiting policy level details for RG policies."

if ($cosmosId){ Info "Connectivity: list containers"; az cosmosdb sql container list -g $ResourceGroup -a $CosmosAccount -d $CosmosDb *> $null; if ($LASTEXITCODE -eq 0){ Ok "Cosmos connectivity OK" } else { Warn "Cosmos connectivity failed" } }
if ($storageId){ Info "Connectivity: storage containers"; az storage container list --account-name $StorageAccount --auth-mode login *> $null; if ($LASTEXITCODE -eq 0){ Ok "Storage connectivity OK" } else { Warn "Storage connectivity failed" } }
if ($sbId){ Info "Connectivity: service bus"; az servicebus namespace list -g $ResourceGroup *> $null; if ($LASTEXITCODE -eq 0){ Ok "Service Bus connectivity OK" } else { Warn "Service Bus connectivity failed" } }
