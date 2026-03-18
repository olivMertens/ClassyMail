#
# ClassyMail MVP Setup Verification Script (PowerShell)
# ========================================
# This script validates the complete Azure infrastructure setup for the ClassyMail MVP.
#
# Usage:
#   .\scripts\verify-mvp-setup.ps1 [-ResourceGroup <name>]
#
# Example:
#   .\scripts\verify-mvp-setup.ps1 -ResourceGroup "email-mvp-rg"
#
# Prerequisites:
#   - Azure CLI installed and authenticated (az login)
#

param(
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup,

    [Parameter(Mandatory=$false)]
    [switch]$AutoFixNetwork = $false
)

# Counters
$script:Passed = 0
$script:Failed = 0
$script:Warnings = 0

# Function to print colored output
function Write-Status {
    param(
        [Parameter(Mandatory=$true)]
        [ValidateSet("success", "error", "warning", "info")]
        [string]$Status,

        [Parameter(Mandatory=$true)]
        [string]$Message
    )

    switch ($Status) {
        "success" {
            Write-Host "✓ $Message" -ForegroundColor Green
            $script:Passed++
        }
        "error" {
            Write-Host "✗ $Message" -ForegroundColor Red
            $script:Failed++
        }
        "warning" {
            Write-Host "○ $Message" -ForegroundColor Yellow
            $script:Warnings++
        }
        "info" {
            Write-Host $Message -ForegroundColor Cyan
        }
    }
}

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
}

function Write-SubHeader {
    param([string]$Text)
    Write-Host ""
    Write-Host "--- $Text ---" -ForegroundColor Cyan
}

# Start verification
Write-Header "ClassyMail MVP Setup Verification"
Write-Host "Date: $(Get-Date)"
Write-Host ""

# Step 1: Verify Azure CLI authentication
Write-SubHeader "Step 1/12: Azure CLI Authentication"
try {
    $account = az account show 2>$null | ConvertFrom-Json
    if ($account) {
        Write-Status -Status success -Message "Azure CLI authenticated"
        Write-Host "  Subscription: $($account.name)"
        Write-Host "  Subscription ID: $($account.id)"
    } else {
        Write-Status -Status error -Message "Azure CLI not authenticated. Run: az login"
        exit 1
    }
} catch {
    Write-Status -Status error -Message "Azure CLI not authenticated. Run: az login"
    exit 1
}

# Get resource group name
if (-not $ResourceGroup) {
    # Try to load from secrets.env first
    if (Test-Path "secrets.env") {
        $envContent = Get-Content "secrets.env"
        foreach ($line in $envContent) {
            if ($line -match "^AZURE_RESOURCE_GROUP=(.*)") {
                $ResourceGroup = $matches[1]
                Write-Host "Auto-detected Resource Group from secrets.env: $ResourceGroup" -ForegroundColor Cyan
                break
            }
        }
    }
}

if (-not $ResourceGroup) {
    Write-Host ""
    Write-Host "Available resource groups:"
    $groups = az group list --query "[].name" -o tsv 2>$null
    $i = 1
    foreach ($g in $groups) {
        Write-Host "  $i. $g"
        $i++
    }
    Write-Host ""
    $ResourceGroup = Read-Host "Enter resource group name"
}

# Step 2: Verify Resource Group
Write-SubHeader "Step 2/12: Resource Group"
try {
    $rg = az group show --name $ResourceGroup 2>$null | ConvertFrom-Json
    if ($rg) {
        Write-Status -Status success -Message "Resource group '$ResourceGroup' exists"
        Write-Host "  Location: $($rg.location)"
    } else {
        Write-Status -Status error -Message "Resource group '$ResourceGroup' not found"
        exit 1
    }
} catch {
    Write-Status -Status error -Message "Resource group '$ResourceGroup' not found"
    exit 1
}

# Step 3: Verify Managed Identity
Write-SubHeader "Step 3/12: Managed Identity"
$identities = az identity list --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
if ($identities -and $identities.Count -gt 0) {
    $identity = $identities[0]
    Write-Status -Status success -Message "Managed identity '$($identity.name)' found"
    Write-Host "  Principal ID: $($identity.principalId)"
    Write-Host "  Client ID: $($identity.clientId)"
    $identityId = $identity.principalId
} else {
    Write-Status -Status error -Message "No managed identity found in resource group"
    $identityId = $null
}

# Step 4: Verify Storage Account
Write-SubHeader "Step 4/12: Storage Account"
$storageAccounts = az storage account list --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
if ($storageAccounts -and $storageAccounts.Count -gt 0) {
    $storage = $storageAccounts[0]
    Write-Status -Status success -Message "Storage account '$($storage.name)' found"
    Write-Host "  Provisioning state: $($storage.provisioningState)"

    # Check containers
    try {
        $containers = az storage container list --account-name $storage.name --auth-mode login --query "[].name" -o tsv 2>$null
        if ($containers) {
            $containerList = $containers -join ", "
            Write-Status -Status success -Message "Storage containers found: $containerList"
        } else {
            Write-Status -Status warning -Message "No storage containers found or access denied"
        }
    } catch {
        Write-Status -Status warning -Message "Could not list storage containers"
    }
} else {
    Write-Status -Status error -Message "No storage account found in resource group"
}

# Step 5: Verify Cosmos DB
Write-SubHeader "Step 5/12: Cosmos DB"
$cosmosAccounts = az cosmosdb list --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
if ($cosmosAccounts -and $cosmosAccounts.Count -gt 0) {
    $cosmos = $cosmosAccounts[0]
    Write-Status -Status success -Message "Cosmos DB '$($cosmos.name)' found"
    Write-Host "  Provisioning state: $($cosmos.provisioningState)"
    Write-Host "  Endpoint: $($cosmos.documentEndpoint)"

    # Check network access configuration
    try {
        $cosmosDetail = az cosmosdb show --name $cosmos.name --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
        $publicAccess = $cosmosDetail.publicNetworkAccess
        $ipRules = $cosmosDetail.ipRules

        Write-Host "  Public network access: $publicAccess"

        if ($publicAccess -eq "Disabled") {
            Write-Status -Status error -Message "Cosmos DB public network access is DISABLED"
            Write-Host "    ⚠️  Container Apps cannot connect without VNet integration" -ForegroundColor Yellow
            Write-Host "    📝 Fix: Run .\scripts\update_cosmos_firewall.ps1 -ResourceGroup `"$ResourceGroup`"" -ForegroundColor Cyan

            if ($AutoFixNetwork) {
                Write-Host ""
                Write-Host "  🔧 Auto-fix enabled - Running update_cosmos_firewall.ps1..." -ForegroundColor Magenta
                & "$PSScriptRoot\update_cosmos_firewall.ps1" -ResourceGroup $ResourceGroup -IncludeLocalIP
                if ($LASTEXITCODE -eq 0) {
                    Write-Status -Status success -Message "  Network firewall updated successfully"
                } else {
                    Write-Status -Status error -Message "  Failed to update network firewall"
                }
            }
        } else {
            Write-Status -Status success -Message "Public network access: Enabled"

            # Check if Container App IPs are in firewall
            if ($ipRules -and $ipRules.Count -gt 0) {
                $ipList = ($ipRules | ForEach-Object { $_.ipAddressOrRange }) -join ", "
                Write-Host "  Firewall IP rules: $ipList"

                # Check if 0.0.0.0 (Azure Services) is included
                $hasAzureServices = $ipRules | Where-Object { $_.ipAddressOrRange -eq "0.0.0.0" }
                if ($hasAzureServices) {
                    Write-Status -Status success -Message "Azure Services (0.0.0.0) allowed in firewall"
                } else {
                    Write-Status -Status warning -Message "Azure Services (0.0.0.0) NOT in firewall - may cause connection issues"
                    Write-Host "    📝 Fix: Run .\scripts\update_cosmos_firewall.ps1 -ResourceGroup `"$ResourceGroup`"" -ForegroundColor Cyan

                    if ($AutoFixNetwork) {
                        Write-Host ""
                        Write-Host "  🔧 Auto-fix enabled - Running update_cosmos_firewall.ps1..." -ForegroundColor Magenta
                        & "$PSScriptRoot\update_cosmos_firewall.ps1" -ResourceGroup $ResourceGroup -IncludeLocalIP
                        if ($LASTEXITCODE -eq 0) {
                            Write-Status -Status success -Message "  Network firewall updated successfully"
                        } else {
                            Write-Status -Status error -Message "  Failed to update network firewall"
                        }
                    }
                }
            } else {
                Write-Status -Status warning -Message "No firewall IP rules configured - may cause connection issues"
                Write-Host "    📝 Fix: Run .\scripts\update_cosmos_firewall.ps1 -ResourceGroup `"$ResourceGroup`"" -ForegroundColor Cyan

                if ($AutoFixNetwork) {
                    Write-Host ""
                    Write-Host "  🔧 Auto-fix enabled - Running update_cosmos_firewall.ps1..." -ForegroundColor Magenta
                    & "$PSScriptRoot\update_cosmos_firewall.ps1" -ResourceGroup $ResourceGroup -IncludeLocalIP
                    if ($LASTEXITCODE -eq 0) {
                        Write-Status -Status success -Message "  Network firewall updated successfully"
                    } else {
                        Write-Status -Status error -Message "  Failed to update network firewall"
                    }
                }
            }
        }
    } catch {
        Write-Status -Status warning -Message "Could not check Cosmos DB network configuration"
    }

    # Check RBAC assignments
    if ($identityId) {
        try {
            $roleAssignments = az cosmosdb sql role assignment list --account-name $cosmos.name --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
            $identityRoles = $roleAssignments | Where-Object { $_.principalId -eq $identityId }
            if ($identityRoles -and $identityRoles.Count -gt 0) {
                Write-Status -Status success -Message "Cosmos DB RBAC assigned to managed identity ($($identityRoles.Count) role(s))"
                foreach ($role in $identityRoles) {
                    # Validate scope — must be Account-level, not database-scoped
                    if ($role.scope -match '/dbs/') {
                        Write-Status -Status error -Message "  Cosmos role scoped to DATABASE ($($role.scope)) — must be Account scope for SDK readMetadata"
                    } else {
                        Write-Status -Status success -Message "  Scope: Account-level (correct)"
                    }
                    # Validate role type — should be Custom, not built-in 00000000-...-02
                    if ($role.roleDefinitionId -match '00000000-0000-0000-0000-000000000002') {
                        Write-Status -Status warning -Message "  Using built-in Data Contributor — consider Custom App Role for readMetadata"
                    } else {
                        Write-Status -Status success -Message "  Using Custom App Role (correct)"
                    }
                }
            } else {
                Write-Status -Status error -Message "Cosmos DB RBAC NOT assigned to managed identity"
                Write-Host "  Action: Run 'cd infra && terraform apply' to assign RBAC"
            }
        } catch {
            Write-Status -Status warning -Message "Could not check Cosmos DB RBAC assignments"
        }
    }

    # Check databases
    try {
        $databases = az cosmosdb sql database list --account-name $cosmos.name --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
        if ($databases -and $databases.Count -gt 0) {
            Write-Status -Status success -Message "Cosmos DB databases found: $($databases.Count) database(s)"
        } else {
            Write-Status -Status warning -Message "No Cosmos DB databases found"
        }
    } catch {
        Write-Status -Status warning -Message "Could not list Cosmos DB databases"
    }
} else {
    Write-Status -Status error -Message "No Cosmos DB account found in resource group"
}

# Step 6: Verify Service Bus
Write-SubHeader "Step 6/12: Service Bus"
$serviceBusNs = az servicebus namespace list --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
if ($serviceBusNs -and $serviceBusNs.Count -gt 0) {
    $sb = $serviceBusNs[0]
    Write-Status -Status success -Message "Service Bus namespace '$($sb.name)' found"
    Write-Host "  Provisioning state: $($sb.provisioningState)"

    # Check queues
    try {
        $queues = az servicebus queue list --namespace-name $sb.name --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
        if ($queues -and $queues.Count -gt 0) {
            $queueNames = ($queues | ForEach-Object { $_.name }) -join ", "
            Write-Status -Status success -Message "Service Bus queues found: $queueNames"

            # Check message count for each queue
            foreach ($queue in $queues) {
                $queueInfo = az servicebus queue show --name $queue.name --namespace-name $sb.name --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
                $msgCount = $queueInfo.countDetails.activeMessageCount
                Write-Host "    Queue '$($queue.name)': $msgCount active messages"
            }
        } else {
            Write-Status -Status warning -Message "No Service Bus queues found"
        }
    } catch {
        Write-Status -Status warning -Message "Could not list Service Bus queues"
    }
} else {
    Write-Status -Status error -Message "No Service Bus namespace found in resource group"
}

# Step 7: Verify Microsoft AI Foundry (Cognitive Services)
Write-SubHeader "Step 7/12: Microsoft AI Foundry"
$cognitiveAccounts = az cognitiveservices account list --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
$aiAccount = $cognitiveAccounts | Where-Object { $_.kind -eq "AIServices" -or $_.kind -eq "OpenAI" } | Select-Object -First 1

if ($aiAccount) {
    Write-Status -Status success -Message "Microsoft AI Foundry '$($aiAccount.name)' found"
    Write-Host "  Provisioning state: $($aiAccount.properties.provisioningState)"
    Write-Host "  Endpoint: $($aiAccount.properties.endpoint)"

    # Check deployments
    try {
        $deployments = az cognitiveservices account deployment list --name $aiAccount.name --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
        if ($deployments -and $deployments.Count -gt 0) {
            Write-Status -Status success -Message "Model deployments found:"
            foreach ($dep in $deployments) {
                Write-Host "    - $($dep.name) ($($dep.properties.model.name)): $($dep.properties.provisioningState)"
            }
        } else {
            Write-Status -Status warning -Message "No model deployments found. Run setup: docs/AI_FOUNDRY_SETUP.md"
        }
    } catch {
        Write-Status -Status warning -Message "Could not list model deployments"
    }
} else {
    Write-Status -Status error -Message "No Microsoft AI Foundry resource found in resource group"
    Write-Host "  Action: Deploy Microsoft AI Foundry resource or check resource group"
}

# Step 8: Verify Azure AI Language (optional)
Write-SubHeader "Step 8/12: Azure AI Language Service (Optional)"
$languageAccount = $cognitiveAccounts | Where-Object { $_.kind -eq "TextAnalytics" } | Select-Object -First 1

if ($languageAccount) {
    Write-Status -Status success -Message "Azure AI Language '$($languageAccount.name)' found"
    Write-Host "  Provisioning state: $($languageAccount.properties.provisioningState)"
    Write-Host "  Endpoint: $($languageAccount.properties.endpoint)"

    # Check Language Reader role for managed identity
    if ($identityId) {
        $langRoles = az role assignment list --assignee $identityId --scope $languageAccount.id --query "[?roleDefinitionName=='Cognitive Services Language Reader']" 2>$null | ConvertFrom-Json
        if ($langRoles -and $langRoles.Count -gt 0) {
            Write-Status -Status success -Message "Cognitive Services Language Reader role assigned"
        } else {
            Write-Status -Status warning -Message "Cognitive Services Language Reader role MISSING on Language Service"
            Write-Host "    Fix: terraform apply with deploy_language_service = true"
        }
    }
} else {
    Write-Status -Status warning -Message "Azure AI Language service not found (optional for PII detection)"
}

# Step 9: Verify Container Apps
Write-SubHeader "Step 9/12: Container Apps"
$containerApps = az containerapp list --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
if ($containerApps -and $containerApps.Count -gt 0) {
    $appNames = ($containerApps | ForEach-Object { $_.name }) -join ", "
    Write-Status -Status success -Message "Container Apps found: $appNames"

    foreach ($app in $containerApps) {
        $appDetail = az containerapp show --name $app.name --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
        $runningStatus = $appDetail.properties.runningStatus
        $minReplicas = $appDetail.properties.template.scale.minReplicas
        $managedIdentity = $appDetail.identity.type

        Write-Host ""
        Write-Host "  Container App: $($app.name)"
        Write-Host "    Running status: $runningStatus"
        Write-Host "    Min replicas: $minReplicas"
        Write-Host "    Managed identity: $managedIdentity"

        if ($runningStatus -eq "Running") {
            Write-Status -Status success -Message "  $($app.name) is running"
        } else {
            Write-Status -Status warning -Message "  $($app.name) is not running (status: $runningStatus)"
        }

        # Check AZURE_CLIENT_ID env var
        $envVars = $appDetail.properties.template.containers[0].env | ForEach-Object { $_.name }
        if ($envVars -contains "AZURE_CLIENT_ID") {
            Write-Status -Status success -Message "  AZURE_CLIENT_ID set on $($app.name)"
        } else {
            Write-Status -Status error -Message "  AZURE_CLIENT_ID MISSING on $($app.name) — DefaultAzureCredential may pick wrong identity"
            Write-Host "      Fix: Set AZURE_CLIENT_ID env var to the managed identity client ID in Terraform"
        }
    }
} else {
    Write-Status -Status error -Message "No Container Apps found in resource group"
}

# Step 10: Verify RBAC Role Assignments
Write-SubHeader "Step 10/12: RBAC Role Assignments"
if ($identityId) {
    Write-Host "Checking role assignments for managed identity..."

    # Required roles check logic is handled below dynamically

    # Get all role assignments for the managed identity
    try {
        $roleAssignments = az role assignment list --assignee $identityId --all 2>$null | ConvertFrom-Json

        if ($roleAssignments -and $roleAssignments.Count -gt 0) {
            $assignedRoles = $roleAssignments | Select-Object -ExpandProperty roleDefinitionName -Unique | Sort-Object
            Write-Status -Status success -Message "Role assignments found for managed identity:"
            foreach ($role in $assignedRoles) {
                Write-Host "    - $role"
            }

            # Check for required roles
            Write-Host ""
            Write-Host "  Checking required roles:"

            # Storage Check
            if ($assignedRoles -contains "Storage Blob Data Contributor") {
                 Write-Host "    ✓ Storage Blob Data Contributor" -ForegroundColor Green
            } else {
                 Write-Host "    ✗ Storage Blob Data Contributor (MISSING)" -ForegroundColor Red
                 $script:Failed++
            }

            # Cognitive Services Check
            if ($assignedRoles -contains "Cognitive Services User") {
                 Write-Host "    ✓ Cognitive Services User" -ForegroundColor Green
            } else {
                 Write-Host "    ✗ Cognitive Services User (MISSING)" -ForegroundColor Red
                 $script:Failed++
            }

            # Service Bus Check (Accept Owner OR (Sender + Receiver))
            $hasOwner = $assignedRoles -contains "Azure Service Bus Data Owner"
            $hasSender = $assignedRoles -contains "Azure Service Bus Data Sender"
            $hasReceiver = $assignedRoles -contains "Azure Service Bus Data Receiver"

            if ($hasOwner) {
                Write-Host "    ✓ Azure Service Bus Data Owner (Found)" -ForegroundColor Green
            } elseif ($hasSender -and $hasReceiver) {
                Write-Host "    ✓ Azure Service Bus Data Sender & Receiver (Found)" -ForegroundColor Green
            } else {
                Write-Host "    ✗ Service Bus Roles (MISSING)" -ForegroundColor Red
                Write-Host "      Expected: 'Azure Service Bus Data Owner' OR ('Sender' + 'Receiver')"
                Write-Status -Status error -Message "  Service Bus RBAC roles missing"
            }

            # Check for unexpected extra roles (not managed by Terraform)
            Write-Host ""
            Write-Host "  Checking for unexpected extra roles:"
            $expectedRoleNames = @(
              "Storage Blob Data Contributor",
              "Azure Service Bus Data Receiver",
              "Azure Service Bus Data Sender",
              "Azure Service Bus Data Owner",
              "Cognitive Services User",
              "AcrPull",
              "Cognitive Services Language Reader"
            )
            $unexpectedRoles = $roleAssignments | Where-Object { $_.roleDefinitionName -notin $expectedRoleNames }
            if ($unexpectedRoles -and $unexpectedRoles.Count -gt 0) {
                Write-Status -Status warning -Message "Found $($unexpectedRoles.Count) extra role(s) NOT managed by Terraform:"
                foreach ($ur in $unexpectedRoles) {
                    $scopeLeaf = ($ur.scope -split '/')[-1]
                    Write-Host "    ! $($ur.roleDefinitionName) on $scopeLeaf" -ForegroundColor Yellow
                }
                Write-Host "    These are safe to remove. See docs/RBAC_AUDIT.md section 8." -ForegroundColor Cyan
            } else {
                Write-Status -Status success -Message "No unexpected extra roles - clean Terraform-only RBAC"
            }

        } else {
            Write-Status -Status error -Message "No role assignments found for managed identity"
            Write-Host "  Action: Run 'cd infra && terraform apply' to assign RBAC roles"
        }
    } catch {
        Write-Status -Status warning -Message "Could not check RBAC role assignments"
    }
} else {
    Write-Status -Status warning -Message "Cannot check RBAC: Managed identity not found"
}

# Step 11: Test API Endpoints (if Container Apps are running)
Write-SubHeader "Step 11/12: API Endpoint Testing"
$apiApp = $containerApps | Where-Object { $_.name -like "*api*" } | Select-Object -First 1

if ($apiApp) {
    try {
        $appDetail = az containerapp show --name $apiApp.name --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
        $apiFqdn = $appDetail.properties.configuration.ingress.fqdn

        if ($apiFqdn) {
            $apiUrl = "https://$apiFqdn"
            Write-Host "  API URL: $apiUrl"
            Write-Host ""

            # Test health endpoint
            Write-Host "  Testing /health endpoint..."
            try {
                $healthResponse = Invoke-WebRequest -Uri "$apiUrl/health" -Method Get -TimeoutSec 10 -ErrorAction SilentlyContinue
                if ($healthResponse.StatusCode -eq 200) {
                    Write-Status -Status success -Message "  Health endpoint: OK (HTTP $($healthResponse.StatusCode))"
                } else {
                    Write-Status -Status error -Message "  Health endpoint: FAILED (HTTP $($healthResponse.StatusCode))"
                }
            } catch {
                Write-Status -Status error -Message "  Health endpoint: FAILED (Could not connect)"
            }

            # Test readiness endpoint
            Write-Host "  Testing /readyz endpoint..."
            try {
                $readyResponse = Invoke-WebRequest -Uri "$apiUrl/readyz" -Method Get -TimeoutSec 10 -ErrorAction SilentlyContinue
                if ($readyResponse.StatusCode -eq 200) {
                    Write-Status -Status success -Message "  Readiness endpoint: OK (HTTP $($readyResponse.StatusCode))"
                } else {
                    Write-Status -Status warning -Message "  Readiness endpoint: Not ready (HTTP $($readyResponse.StatusCode))"
                }
            } catch {
                Write-Status -Status warning -Message "  Readiness endpoint: Not ready (Could not connect)"
            }

            # Test admin validate endpoint
            Write-Host "  Testing /api/admin/validate-aca-env..."
            try {
                $validateResponse = Invoke-WebRequest -Uri "$apiUrl/api/admin/validate-aca-env" -Method Get -TimeoutSec 10 -ErrorAction SilentlyContinue
                if ($validateResponse.StatusCode -eq 200) {
                    Write-Status -Status success -Message "  Admin validation endpoint: OK (HTTP $($validateResponse.StatusCode))"
                } else {
                    Write-Status -Status warning -Message "  Admin validation endpoint: FAILED (HTTP $($validateResponse.StatusCode))"
                }
            } catch {
                Write-Status -Status warning -Message "  Admin validation endpoint: FAILED (Could not connect)"
            }
        } else {
            Write-Status -Status warning -Message "API FQDN not found - Container App may not have ingress configured"
        }
    } catch {
        Write-Status -Status warning -Message "Could not get API Container App details"
    }
} else {
    Write-Status -Status warning -Message "No API Container App found for endpoint testing"
}

# Step 12: Summary
Write-Header "Verification Summary"
Write-Host ""
Write-Host "Passed:   $script:Passed" -ForegroundColor Green
Write-Host "Failed:   $script:Failed" -ForegroundColor Red
Write-Host "Warnings: $script:Warnings" -ForegroundColor Yellow
Write-Host ""

if ($script:Failed -eq 0) {
    Write-Status -Status success -Message "All critical checks passed!"
    Write-Host ""
    Write-Host "Next steps:"
    Write-Host "  1. Deploy models in Microsoft AI Foundry (if deployments missing)"
    Write-Host "     See: docs/AI_FOUNDRY_SETUP.md"
    Write-Host "  2. Test end-to-end workflow by uploading a PDF via UI"
    Write-Host "  3. Monitor Application Insights for telemetry"
    Write-Host "  4. Review warnings above and address if needed"
} else {
    Write-Status -Status error -Message "Some checks failed. Please review errors above."
    Write-Host ""
    Write-Host "  - Network issues: .\scripts\update_cosmos_firewall.ps1 -ResourceGroup `"$ResourceGroup`""
    Write-Host "  - Container Apps not running: az containerapp restart --name <app-name> -g $ResourceGroup"
    Write-Host "  - Cosmos DB errors: Wait 5-10 min for RBAC propagation, then restart apps"
    Write-Host "  - Missing deployments: See docs/AI_FOUNDRY_SETUP.md"
    Write-Host ""
    Write-Host "Tip: Use -AutoFixNetwork to automatically fix network issues"
    Write-Host "     .\scripts\verify-mvp-setup.ps1 -ResourceGroup `"$ResourceGroup`" -AutoFixNetwork"
}

Write-Host ""
Write-Host "For detailed troubleshooting, see: docs/AI_FOUNDRY_SETUP.md"
Write-Host "For complete infrastructure docs, see: docs/INFRASTRUCTURE.md"
Write-Host ""

exit $script:Failed
