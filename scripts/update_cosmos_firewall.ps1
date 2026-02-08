#!/usr/bin/env pwsh
<#
.SYNOPSIS
Updates Cosmos DB firewall to allow Container App outbound IPs + local dev IP.

.DESCRIPTION
Automatically retrieves the Container App outbound IP addresses and updates
Cosmos DB's ip_range_filter to include:
- 0.0.0.0 (Allow Azure Services)
- Container App outbound IPs (API + Worker)
- Current local developer IP (optional, for local scripts)

.PARAMETER ResourceGroup
Azure Resource Group name.

.PARAMETER CosmosAccountName
Cosmos DB account name.

.PARAMETER ApiAppName
API Container App name (default: email-poc-api).

.PARAMETER WorkerAppName
Worker Container App name (default: email-poc-worker).

.PARAMETER IncludeLocalIP
Include your current public IP in the firewall (for local scripts).

.EXAMPLE
.\scripts\update_cosmos_firewall.ps1 -ResourceGroup "email-poc-rg"

.EXAMPLE
.\scripts\update_cosmos_firewall.ps1 -ResourceGroup "email-poc-rg" -IncludeLocalIP
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroup,

    [string]$CosmosAccountName = "email-poc-cosmos",
    [string]$ApiAppName = "email-poc-api",
    [string]$WorkerAppName = "email-poc-worker",
    [switch]$IncludeLocalIP
)

$ErrorActionPreference = "Stop"

Write-Host "🔍 Retrieving Container App outbound IPs..." -ForegroundColor Cyan

# Get API outbound IPs
$apiIps = @()
try {
    $apiIpsJson = az containerapp show --name $ApiAppName --resource-group $ResourceGroup --query "properties.outboundIpAddresses" -o json 2>$null
    if ($apiIpsJson) {
        $apiIps = $apiIpsJson | ConvertFrom-Json
        Write-Host "  ✅ API App IPs: $($apiIps -join ', ')" -ForegroundColor Green
    }
} catch {
    Write-Host "  ⚠️  API App not found, skipping..." -ForegroundColor Yellow
}

# Get Worker outbound IPs
$workerIps = @()
try {
    $workerIpsJson = az containerapp show --name $WorkerAppName --resource-group $ResourceGroup --query "properties.outboundIpAddresses" -o json 2>$null
    if ($workerIpsJson) {
        $workerIps = $workerIpsJson | ConvertFrom-Json
        Write-Host "  ✅ Worker App IPs: $($workerIps -join ', ')" -ForegroundColor Green
    }
} catch {
    Write-Host "  ⚠️  Worker App not found, skipping..." -ForegroundColor Yellow
}

# Build IP list
$ipList = @("0.0.0.0")  # Always include Azure Services
$ipList += $apiIps
$ipList += $workerIps

# Add local IP if requested
if ($IncludeLocalIP) {
    Write-Host "🌐 Retrieving your public IP..." -ForegroundColor Cyan
    try {
        $localIp = (Invoke-RestMethod -Uri "https://ifconfig.me/ip" -TimeoutSec 5).Trim()
        Write-Host "  ✅ Your IP: $localIp" -ForegroundColor Green
        $ipList += $localIp
    } catch {
        Write-Host "  ⚠️  Failed to retrieve local IP, skipping..." -ForegroundColor Yellow
    }
}

# Deduplicate
$ipList = $ipList | Select-Object -Unique

# Build comma-separated string
$ipFilter = $ipList -join ","

Write-Host ""
Write-Host "📝 Final IP filter list:" -ForegroundColor Cyan
$ipList | ForEach-Object { Write-Host "  - $_" -ForegroundColor Gray }

Write-Host ""
Write-Host "🔧 Updating Cosmos DB firewall..." -ForegroundColor Cyan
Write-Host "  Account: $CosmosAccountName" -ForegroundColor Gray
Write-Host "  Resource Group: $ResourceGroup" -ForegroundColor Gray

try {
    az cosmosdb update `
        --name $CosmosAccountName `
        --resource-group $ResourceGroup `
        --public-network-access Enabled `
        --ip-range-filter $ipFilter `
        --output none

    Write-Host ""
    Write-Host "✅ Cosmos DB firewall updated successfully!" -ForegroundColor Green
    Write-Host "   You can now connect from:" -ForegroundColor Green
    Write-Host "   - Azure Services (0.0.0.0)" -ForegroundColor Gray
    Write-Host "   - Container Apps ($($apiIps.Count + $workerIps.Count) IPs)" -ForegroundColor Gray
    if ($IncludeLocalIP) {
        Write-Host "   - Your local machine" -ForegroundColor Gray
    }
} catch {
    Write-Host ""
    Write-Host "❌ Failed to update Cosmos DB firewall" -ForegroundColor Red
    Write-Host "Error: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "💡 If you see 'operation in progress', wait 1-2 minutes and retry." -ForegroundColor Yellow
    exit 1
}
