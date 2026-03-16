#!/bin/bash
#
# ClassyMail MVP Setup Verification Script
# ========================================
# This script validates the complete Azure infrastructure setup for the ClassyMail MVP.
#
# Usage:
#   ./scripts/verify-mvp-setup.sh [resource-group-name] [--auto-fix-network]
#
# Example:
#   ./scripts/verify-mvp-setup.sh email-mvp-rg
#   ./scripts/verify-mvp-setup.sh email-mvp-rg --auto-fix-network
#
# Prerequisites:
#   - Azure CLI installed and authenticated (az login)
#   - jq installed (for JSON parsing)
#

set -euo pipefail

# Parse arguments
AUTO_FIX_NETWORK=false
RG=""

for arg in "$@"; do
    case $arg in
        --auto-fix-network)
            AUTO_FIX_NETWORK=true
            shift
            ;;
        *)
            if [ -z "$RG" ]; then
                RG="$arg"
            fi
            ;;
    esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Symbols
CHECK_MARK="✓"
CROSS_MARK="✗"
CIRCLE="○"

# Counters
PASSED=0
FAILED=0
WARNINGS=0

# Resource Group (can be passed as argument or will be prompted)
if [ -z "$RG" ]; then
    RG="${1:-}"
fi

# Function to print colored output
print_status() {
    local status=$1
    local message=$2
    case $status in
        "success")
            echo -e "${GREEN}${CHECK_MARK} ${message}${NC}"
            ((PASSED++))
            ;;
        "error")
            echo -e "${RED}${CROSS_MARK} ${message}${NC}"
            ((FAILED++))
            ;;
        "warning")
            echo -e "${YELLOW}${CIRCLE} ${message}${NC}"
            ((WARNINGS++))
            ;;
        "info")
            echo -e "${CYAN}${message}${NC}"
            ;;
    esac
}

print_header() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}========================================${NC}"
}

print_subheader() {
    echo ""
    echo -e "${CYAN}--- $1 ---${NC}"
}

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    print_status "warning" "jq not installed. JSON parsing may be limited. Install with: sudo apt-get install jq"
fi

print_header "ClassyMail MVP Setup Verification"
echo "Date: $(date)"
echo ""

# Step 1: Verify Azure CLI authentication
print_subheader "Step 1/12: Azure CLI Authentication"
if az account show &> /dev/null; then
    SUBSCRIPTION=$(az account show --query name -o tsv)
    SUBSCRIPTION_ID=$(az account show --query id -o tsv)
    print_status "success" "Azure CLI authenticated"
    echo "  Subscription: $SUBSCRIPTION"
    echo "  Subscription ID: $SUBSCRIPTION_ID"
else
    print_status "error" "Azure CLI not authenticated. Run: az login"
    exit 1
fi

# Get resource group name if not provided
if [ -z "$RG" ]; then
    echo ""
    echo "Available resource groups:"
    az group list --query "[].name" -o tsv | nl
    echo ""
    read -p "Enter resource group name: " RG
fi

# Step 2: Verify Resource Group
print_subheader "Step 2/12: Resource Group"
if az group show --name "$RG" &> /dev/null; then
    LOCATION=$(az group show --name "$RG" --query location -o tsv)
    print_status "success" "Resource group '$RG' exists"
    echo "  Location: $LOCATION"
else
    print_status "error" "Resource group '$RG' not found"
    exit 1
fi

# Step 3: Verify Managed Identity
print_subheader "Step 3/12: Managed Identity"
IDENTITY_NAME=$(az identity list --resource-group "$RG" --query "[0].name" -o tsv 2>/dev/null || echo "")
if [ -n "$IDENTITY_NAME" ]; then
    IDENTITY_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$RG" --query principalId -o tsv)
    IDENTITY_CLIENT_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$RG" --query clientId -o tsv)
    print_status "success" "Managed identity '$IDENTITY_NAME' found"
    echo "  Principal ID: $IDENTITY_ID"
    echo "  Client ID: $IDENTITY_CLIENT_ID"
else
    print_status "error" "No managed identity found in resource group"
fi

# Step 4: Verify Storage Account
print_subheader "Step 4/12: Storage Account"
STORAGE_ACCOUNT=$(az storage account list --resource-group "$RG" --query "[0].name" -o tsv 2>/dev/null || echo "")
if [ -n "$STORAGE_ACCOUNT" ]; then
    STORAGE_STATE=$(az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RG" --query provisioningState -o tsv)
    print_status "success" "Storage account '$STORAGE_ACCOUNT' found"
    echo "  Provisioning state: $STORAGE_STATE"

    # Check containers
    CONTAINERS=$(az storage container list --account-name "$STORAGE_ACCOUNT" --auth-mode login --query "[].name" -o tsv 2>/dev/null || echo "")
    if [ -n "$CONTAINERS" ]; then
        print_status "success" "Storage containers found: $(echo $CONTAINERS | tr '\n' ', ' | sed 's/,$//')"
    else
        print_status "warning" "No storage containers found or access denied"
    fi
else
    print_status "error" "No storage account found in resource group"
fi

# Step 5: Verify Cosmos DB
print_subheader "Step 5/12: Cosmos DB"
COSMOS_ACCOUNT=$(az cosmosdb list --resource-group "$RG" --query "[0].name" -o tsv 2>/dev/null || echo "")
if [ -n "$COSMOS_ACCOUNT" ]; then
    COSMOS_STATE=$(az cosmosdb show --name "$COSMOS_ACCOUNT" --resource-group "$RG" --query provisioningState -o tsv)
    COSMOS_ENDPOINT=$(az cosmosdb show --name "$COSMOS_ACCOUNT" --resource-group "$RG" --query documentEndpoint -o tsv)
    print_status "success" "Cosmos DB '$COSMOS_ACCOUNT' found"
    echo "  Provisioning state: $COSMOS_STATE"
    echo "  network access configuration
    PUBLIC_ACCESS=$(az cosmosdb show --name "$COSMOS_ACCOUNT" --resource-group "$RG" --query publicNetworkAccess -o tsv 2>/dev/null || echo "Unknown")
    IP_RULES=$(az cosmosdb show --name "$COSMOS_ACCOUNT" --resource-group "$RG" --query "ipRules[].ipAddressOrRange" -o tsv 2>/dev/null || echo "")

    echo "  Public network access: $PUBLIC_ACCESS"

    if [ "$PUBLIC_ACCESS" == "Disabled" ]; then
        print_status "error" "Cosmos DB public network access is DISABLED"
        echo -e "    ${YELLOW}⚠️  Container Apps cannot connect without VNet integration${NC}"
        echo -e "    ${CYAN}📝 Fix: Run ./scripts/update_cosmos_firewall.sh \"$RG\"${NC}"

        if [ "$AUTO_FIX_NETWORK" == "true" ]; then
            echo ""
            echo -e "  ${YELLOW}🔧 Auto-fix enabled - Running update_cosmos_firewall.sh...${NC}"
            if bash "$(dirname "$0")/update_cosmos_firewall.sh" "$RG" --include-local-ip; then
                print_status "success" "  Network firewall updated successfully"
            else
                print_status "error" "  Failed to update network firewall"
            fi
        fi
    else
        print_status "success" "Public network access: Enabled"

        # Check if firewall has IP rules
        if [ -n "$IP_RULES" ]; then
            IP_LIST=$(echo "$IP_RULES" | tr '\n' ', ' | sed 's/,$//')
            echo "  Firewall IP rules: $IP_LIST"

            # Check if 0.0.0.0 (Azure Services) is included
            if echo "$IP_RULES" | grep -q "0.0.0.0"; then
                print_status "success" "Azure Services (0.0.0.0) allowed in firewall"
            else
                print_status "warning" "Azure Services (0.0.0.0) NOT in firewall - may cause connection issues"
                echo -e "    ${CYAN}📝 Fix: Run ./scripts/update_cosmos_firewall.sh \"$RG\"${NC}"

                if [ "$AUTO_FIX_NETWORK" == "true" ]; then
                    echo ""
                    echo -e "  ${YELLOW}🔧 Auto-fix enabled - Running update_cosmos_firewall.sh...${NC}"
                    if bash "$(dirname "$0")/update_cosmos_firewall.sh" "$RG" --include-local-ip; then
                        print_status "success" "  Network firewall updated successfully"
                    else
                        print_status "error" "  Failed to update network firewall"
                    fi
                fi
            fi
        else
            print_status "warning" "No firewall IP rules configured - may cause connection issues"
            echo -e "    ${CYAN}📝 Fix: Run ./scripts/update_cosmos_firewall.sh \"$RG\"${NC}"

            if [ "$AUTO_FIX_NETWORK" == "true" ]; then
                echo ""
                echo -e "  ${YELLOW}🔧 Auto-fix enabled - Running update_cosmos_firewall.sh...${NC}"
                if bash "$(dirname "$0")/update_cosmos_firewall.sh" "$RG" --include-local-ip; then
                    print_status "success" "  Network firewall updated successfully"
                else
                    print_status "error" "  Failed to update network firewall"
                fi
            fi
        fi
    fi

    # Check Endpoint: $COSMOS_ENDPOINT"

    # Check RBAC assignments
    if [ -n "$IDENTITY_ID" ]; then
        COSMOS_ROLES=$(az cosmosdb sql role assignment list --account-name "$COSMOS_ACCOUNT" --resource-group "$RG" --query "length([?principalId=='$IDENTITY_ID'])" -o tsv 2>/dev/null || echo "0")
        if [ "$COSMOS_ROLES" -gt 0 ]; then
            print_status "success" "Cosmos DB RBAC assigned to managed identity ($COSMOS_ROLES role(s))"
        else
            print_status "error" "Cosmos DB RBAC NOT assigned to managed identity"
            echo "  Action: Run 'cd infra && terraform apply' to assign RBAC"
        fi
    fi

    # Check databases
    DATABASES=$(az cosmosdb sql database list --account-name "$COSMOS_ACCOUNT" --resource-group "$RG" --query "[].id" -o tsv 2>/dev/null | wc -l)
    if [ "$DATABASES" -gt 0 ]; then
        print_status "success" "Cosmos DB databases found: $DATABASES database(s)"
    else
        print_status "warning" "No Cosmos DB databases found"
    fi
else
    print_status "error" "No Cosmos DB account found in resource group"
fi

# Step 6: Verify Service Bus
print_subheader "Step 6/12: Service Bus"
SERVICEBUS_NS=$(az servicebus namespace list --resource-group "$RG" --query "[0].name" -o tsv 2>/dev/null || echo "")
if [ -n "$SERVICEBUS_NS" ]; then
    SERVICEBUS_STATE=$(az servicebus namespace show --name "$SERVICEBUS_NS" --resource-group "$RG" --query provisioningState -o tsv)
    print_status "success" "Service Bus namespace '$SERVICEBUS_NS' found"
    echo "  Provisioning state: $SERVICEBUS_STATE"

    # Check queues
    QUEUES=$(az servicebus queue list --namespace-name "$SERVICEBUS_NS" --resource-group "$RG" --query "[].name" -o tsv 2>/dev/null || echo "")
    if [ -n "$QUEUES" ]; then
        print_status "success" "Service Bus queues found: $(echo $QUEUES | tr '\n' ', ' | sed 's/,$//')"

        # Check message count for main queue (pdf-queue)
        for QUEUE in $QUEUES; do
            MSG_COUNT=$(az servicebus queue show --name "$QUEUE" --namespace-name "$SERVICEBUS_NS" --resource-group "$RG" --query "countDetails.activeMessageCount" -o tsv 2>/dev/null || echo "0")
            echo "    Queue '$QUEUE': $MSG_COUNT active messages"
        done
    else
        print_status "warning" "No Service Bus queues found"
    fi
else
    print_status "error" "No Service Bus namespace found in resource group"
fi

# Step 7: Verify Azure AI Foundry (Cognitive Services)
print_subheader "Step 7/12: Azure AI Foundry"
AI_ACCOUNT=$(az cognitiveservices account list --resource-group "$RG" --query "[?kind=='AIServices' || kind=='OpenAI'].name" -o tsv 2>/dev/null | head -n 1 || echo "")
if [ -n "$AI_ACCOUNT" ]; then
    AI_STATE=$(az cognitiveservices account show --name "$AI_ACCOUNT" --resource-group "$RG" --query "properties.provisioningState" -o tsv)
    AI_ENDPOINT=$(az cognitiveservices account show --name "$AI_ACCOUNT" --resource-group "$RG" --query "properties.endpoint" -o tsv)
    print_status "success" "Azure AI Foundry '$AI_ACCOUNT' found"
    echo "  Provisioning state: $AI_STATE"
    echo "  Endpoint: $AI_ENDPOINT"

    # Check deployments
    DEPLOYMENTS=$(az cognitiveservices account deployment list --name "$AI_ACCOUNT" --resource-group "$RG" --query "[].{Name:name, Model:properties.model.name, State:properties.provisioningState}" -o json 2>/dev/null || echo "[]")
    if [ "$DEPLOYMENTS" != "[]" ]; then
        print_status "success" "Model deployments found:"
        if command -v jq &> /dev/null; then
            echo "$DEPLOYMENTS" | jq -r '.[] | "    - \(.Name) (\(.Model)): \(.State)"'
        else
            echo "$DEPLOYMENTS" | grep -oP '"Name":"\K[^"]+' | sed 's/^/    - /'
        fi
    else
        print_status "warning" "No model deployments found. Run setup: docs/AZURE_AI_FOUNDRY_SETUP.md"
    fi
else
    print_status "error" "No Azure AI Foundry resource found in resource group"
    echo "  Action: Deploy Azure AI Foundry resource or check resource group"
fi

# Step 8: Verify Azure AI Language (optional)
print_subheader "Step 8/12: Azure AI Language Service (Optional)"
LANGUAGE_ACCOUNT=$(az cognitiveservices account list --resource-group "$RG" --query "[?kind=='TextAnalytics'].name" -o tsv 2>/dev/null | head -n 1 || echo "")
if [ -n "$LANGUAGE_ACCOUNT" ]; then
    LANGUAGE_STATE=$(az cognitiveservices account show --name "$LANGUAGE_ACCOUNT" --resource-group "$RG" --query "properties.provisioningState" -o tsv)
    LANGUAGE_ENDPOINT=$(az cognitiveservices account show --name "$LANGUAGE_ACCOUNT" --resource-group "$RG" --query "properties.endpoint" -o tsv)
    print_status "success" "Azure AI Language '$LANGUAGE_ACCOUNT' found"
    echo "  Provisioning state: $LANGUAGE_STATE"
    echo "  Endpoint: $LANGUAGE_ENDPOINT"
else
    print_status "warning" "Azure AI Language service not found (optional for PII detection)"
fi

# Step 9: Verify Container Apps
print_subheader "Step 9/12: Container Apps"
CONTAINER_APPS=$(az containerapp list --resource-group "$RG" --query "[].name" -o tsv 2>/dev/null || echo "")
if [ -n "$CONTAINER_APPS" ]; then
    print_status "success" "Container Apps found: $(echo $CONTAINER_APPS | tr '\n' ', ' | sed 's/,$//')"

    for APP in $CONTAINER_APPS; do
        APP_STATE=$(az containerapp show --name "$APP" --resource-group "$RG" --query "properties.runningStatus" -o tsv 2>/dev/null || echo "Unknown")
        REPLICAS=$(az containerapp show --name "$APP" --resource-group "$RG" --query "properties.template.scale.minReplicas" -o tsv 2>/dev/null || echo "0")
        MANAGED_ID=$(az containerapp show --name "$APP" --resource-group "$RG" --query "identity.type" -o tsv 2>/dev/null || echo "None")

        echo ""
        echo "  Container App: $APP"
        echo "    Running status: $APP_STATE"
        echo "    Min replicas: $REPLICAS"
        echo "    Managed identity: $MANAGED_ID"

        if [ "$APP_STATE" == "Running" ]; then
            print_status "success" "  $APP is running"
        else
            print_status "warning" "  $APP is not running (status: $APP_STATE)"
        fi
    done
else
    print_status "error" "No Container Apps found in resource group"
fi

# Step 10: Verify RBAC Role Assignments
print_subheader "Step 10/12: RBAC Role Assignments"
if [ -n "$IDENTITY_ID" ]; then
    echo "Checking role assignments for managed identity..."

    # Required roles (Cognitive + Storage are standard)
    REQUIRED_ROLES=(
        "Storage Blob Data Contributor"
        "Cognitive Services User"
    )

    # Get all role assignments for the managed identity
    ROLE_ASSIGNMENTS=$(az role assignment list --assignee "$IDENTITY_ID" --all --query "[].roleDefinitionName" -o tsv 2>/dev/null || echo "")

    if [ -n "$ROLE_ASSIGNMENTS" ]; then
        print_status "success" "Role assignments found for managed identity:"
        echo "$ROLE_ASSIGNMENTS" | sort -u | sed 's/^/    - /'

        # Check for required roles
        echo ""
        echo "  Checking required roles:"
        for ROLE in "${REQUIRED_ROLES[@]}"; do
            if echo "$ROLE_ASSIGNMENTS" | grep -q "$ROLE"; then
                echo -e "    ${GREEN}${CHECK_MARK}${NC} $ROLE"
            else
                echo -e "    ${RED}${CROSS_MARK}${NC} $ROLE (MISSING)"
                print_status "error" "  Role '$ROLE' not assigned to managed identity"
            fi
        done

        # Service Bus Check (Owner OR Sender+Receiver)
        if echo "$ROLE_ASSIGNMENTS" | grep -q "Azure Service Bus Data Owner"; then
            echo -e "    ${GREEN}${CHECK_MARK}${NC} Azure Service Bus Data Owner"
        elif echo "$ROLE_ASSIGNMENTS" | grep -q "Azure Service Bus Data Sender" && echo "$ROLE_ASSIGNMENTS" | grep -q "Azure Service Bus Data Receiver"; then
            echo -e "    ${GREEN}${CHECK_MARK}${NC} Azure Service Bus Data Sender & Receiver"
        else
            echo -e "    ${RED}${CROSS_MARK}${NC} Service Bus Roles (MISSING)"
            print_status "error" "  Service Bus RBAC roles missing (Need 'Owner' OR 'Sender' + 'Receiver')"
        fi

    else
        print_status "error" "No role assignments found for managed identity"
        echo "  Action: Run 'cd infra && terraform apply' to assign RBAC roles"
    fi
else
    print_status "warning" "Cannot check RBAC: Managed identity not found"
fi

# Step 11: Test API Endpoints (if Container Apps are running)
print_subheader "Step 11/12: API Endpoint Testing"
API_APP=$(echo "$CONTAINER_APPS" | grep -m 1 "api" || echo "")
if [ -n "$API_APP" ]; then
    API_FQDN=$(az containerapp show --name "$API_APP" --resource-group "$RG" --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || echo "")

    if [ -n "$API_FQDN" ]; then
        API_URL="https://$API_FQDN"
        echo "  API URL: $API_URL"
        echo ""

        # Test health endpoint
        echo "  Testing /health endpoint..."
        HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/health" 2>/dev/null || echo "000")
        if [ "$HEALTH_RESPONSE" == "200" ]; then
            print_status "success" "  Health endpoint: OK (HTTP $HEALTH_RESPONSE)"
        else
            print_status "error" "  Health endpoint: FAILED (HTTP $HEALTH_RESPONSE)"
        fi

        # Test readiness endpoint
        echo "  Testing /readyz endpoint..."
        READY_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/readyz" 2>/dev/null || echo "000")
        if [ "$READY_RESPONSE" == "200" ]; then
            print_status "success" "  Readiness endpoint: OK (HTTP $READY_RESPONSE)"
        else
            print_status "warning" "  Readiness endpoint: Not ready (HTTP $READY_RESPONSE)"
        fi

        # Test admin validate endpoint
        echo "  Testing /api/admin/validate-aca-env..."
        VALIDATE_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/api/admin/validate-aca-env" 2>/dev/null || echo "000")
        if [ "$VALIDATE_RESPONSE" == "200" ]; then
            print_status "success" "  Admin validation endpoint: OK (HTTP $VALIDATE_RESPONSE)"
        else
            print_status "warning" "  Admin validation endpoint: FAILED (HTTP $VALIDATE_RESPONSE)"
        fi
    else
        print_status "warning" "API FQDN not found - Container App may not have ingress configured"
    fi
else
    print_status "warning" "No API Container App found for endpoint testing"
fi

# Step 12: Summary
print_header "Verification Summary"
echo ""
echo -e "${GREEN}Passed:   $PASSED${NC}"
echo -e "${RED}Failed:   $FAILED${NC}"
echo -e "${YELLOW}Warnings: $WARNINGS${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    print_status "success" "All critical checks passed!"
    echo ""
    echo "Next steps:"
    echo "  1. Deploy models in Azure AI Foundry (if deployments missing)"
    echo "     See: docs/AZURE_AI_FOUNDRY_SETUP.md"
    echo "  2. Test end-to-end workflow by uploading a PDF via UI"
    echo "  3. Monitor Application Insights for telemetry"
    echo "  4. Review warnings above and address if needed"
    echo ""
    echo "Tip: Use --auto-fix-network to automatically fix Cosmos DB firewall issues"
    echo "     ./scripts/verify-mvp-setup.sh \"$RG\" --auto-fix-network"
else
    print_status "error" "Some checks failed. Please review errors above."
    echo ""
    echo "Common fixes:"
    echo "  - RBAC issues: cd infra && terraform apply"
    echo "  - Network issues: ./scripts/update_cosmos_firewall.sh \"$RG\""
    echo "  - Container Apps not running: az containerapp restart --name <app-name> -g $RG"
    echo "  - Cosmos DB errors: Wait 5-10 min for RBAC propagation, then restart apps"
    echo "  - Missing deployments: See docs/AZURE_AI_FOUNDRY_SETUP.md"
    echo ""
    echo "Tip: Use --auto-fix-network to automatically fix network issues"
    echo "     ./scripts/verify-mvp-setup.sh \"$RG\" --auto-fix-network"
fi

echo ""
echo "For detailed troubleshooting, see: docs/AZURE_AI_FOUNDRY_SETUP.md"
echo "For complete infrastructure docs, see: docs/INFRASTRUCTURE.md"
echo ""

exit $FAILED
