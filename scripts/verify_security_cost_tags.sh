#!/bin/bash
#
# Security and Cost Control Tags Verification Script
# ===================================================
# This script verifies and applies SecurityControl/CostControl tags to Azure resources.
#
# Usage:
#   ./scripts/verify_security_cost_tags.sh [resource-group] [--apply] [--remediate]
#
# Examples:
#   # Check compliance only
#   ./scripts/verify_security_cost_tags.sh classymail-rg
#
#   # Apply policy definition and assignment
#   ./scripts/verify_security_cost_tags.sh classymail-rg --apply
#
#   # Remediate non-compliant resources
#   ./scripts/verify_security_cost_tags.sh classymail-rg --remediate
#
#   # Full workflow: apply policy and remediate
#   ./scripts/verify_security_cost_tags.sh classymail-rg --apply --remediate
#
# Prerequisites:
#   - Azure CLI installed and authenticated (az login)
#   - Contributor or Owner role on subscription
#   - jq installed for JSON parsing
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Parse arguments
RG=""
APPLY_POLICY=false
REMEDIATE=false

for arg in "$@"; do
    case $arg in
        --apply)
            APPLY_POLICY=true
            shift
            ;;
        --remediate)
            REMEDIATE=true
            shift
            ;;
        *)
            if [ -z "$RG" ]; then
                RG="$arg"
            fi
            ;;
    esac
done

# Check for jq
if ! command -v jq &> /dev/null; then
    echo -e "${YELLOW}Warning: jq not installed. Install with: sudo apt-get install jq${NC}"
    echo "Continuing with limited JSON parsing..."
fi

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}Security & Cost Control Tags Verification${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo "Date: $(date)"
echo ""

# Verify Azure CLI authentication
echo -e "${CYAN}Checking Azure CLI authentication...${NC}"
if ! az account show &> /dev/null; then
    echo -e "${RED}✗ Azure CLI not authenticated${NC}"
    echo "  Run: az login"
    exit 1
fi

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
SUBSCRIPTION_NAME=$(az account show --query name -o tsv)
echo -e "${GREEN}✓ Authenticated${NC}"
echo "  Subscription: $SUBSCRIPTION_NAME"
echo "  Subscription ID: $SUBSCRIPTION_ID"
echo ""

# Get resource group
if [ -z "$RG" ]; then
    echo "Available resource groups:"
    az group list --query "[].name" -o tsv | nl
    echo ""
    read -p "Enter resource group name: " RG
fi

# Verify resource group exists
if ! az group show --name "$RG" &> /dev/null; then
    echo -e "${RED}✗ Resource group '$RG' not found${NC}"
    exit 1
fi

LOCATION=$(az group show --name "$RG" --query location -o tsv)
echo -e "${GREEN}✓ Resource group found: $RG${NC}"
echo "  Location: $LOCATION"
echo ""

# Policy definition
POLICY_NAME="add-security-cost-control-tags"
POLICY_DISPLAY_NAME="Add Security Control and Cost Control Ignore Tags"
POLICY_ASSIGNMENT_NAME="assign-security-cost-tags"

# Create policy definition if --apply flag is set
if [ "$APPLY_POLICY" == "true" ]; then
    echo -e "${CYAN}--- Step 1/3: Creating/Updating Policy Definition ---${NC}"
    echo ""

    # Check if policy already exists
    EXISTING_POLICY=$(az policy definition list --query "[?name=='$POLICY_NAME'].name" -o tsv 2>/dev/null | head -n 1 || echo "")

    if [ -n "$EXISTING_POLICY" ]; then
        echo -e "${YELLOW}○ Policy definition '$POLICY_NAME' already exists${NC}"
        echo "  Updating existing policy..."
    else
        echo "  Creating new policy definition..."
    fi

    # Create policy definition JSON
    cat > /tmp/policy_definition.json <<'EOF'
{
  "mode": "All",
  "policyRule": {
    "if": {
      "allOf": [
        {
          "field": "type",
          "notIn": [
            "Microsoft.Resources/subscriptions",
            "Microsoft.Resources/resourceGroups",
            "Microsoft.Resources/deployments",
            "Microsoft.Management/managementGroups"
          ]
        },
        {
          "anyOf": [
            {
              "field": "tags['SecurityControl']",
              "exists": "false"
            },
            {
              "field": "tags['CostControl']",
              "exists": "false"
            }
          ]
        }
      ]
    },
    "then": {
      "effect": "modify",
      "details": {
        "roleDefinitionIds": [
          "/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c"
        ],
        "operations": [
          {
            "operation": "addOrReplace",
            "field": "tags['SecurityControl']",
            "value": "ignore"
          },
          {
            "operation": "addOrReplace",
            "field": "tags['CostControl']",
            "value": "ignore"
          }
        ]
      }
    }
  },
  "parameters": {},
  "displayName": "Add Security Control and Cost Control Ignore Tags",
  "description": "This policy automatically adds 'SecurityControl' and 'CostControl' tags with value 'ignore' to all resources except subscriptions, resource groups, deployments, and management groups.",
  "metadata": {
    "category": "Tags",
    "version": "1.0.0"
  }
}
EOF

    # Create or update the policy definition
    az policy definition create \
        --name "$POLICY_NAME" \
        --display-name "$POLICY_DISPLAY_NAME" \
        --description "Automatically adds SecurityControl and CostControl tags with value 'ignore' to resources" \
        --rules /tmp/policy_definition.json \
        --mode All \
        --subscription "$SUBSCRIPTION_ID" \
        > /dev/null 2>&1 || \
    az policy definition update \
        --name "$POLICY_NAME" \
        --rules /tmp/policy_definition.json \
        --subscription "$SUBSCRIPTION_ID" \
        > /dev/null 2>&1

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Policy definition created/updated successfully${NC}"
    else
        echo -e "${RED}✗ Failed to create/update policy definition${NC}"
        exit 1
    fi

    # Clean up
    rm -f /tmp/policy_definition.json
    echo ""

    # Assign policy to resource group
    echo -e "${CYAN}--- Step 2/3: Assigning Policy to Resource Group ---${NC}"
    echo ""

    # Check if assignment exists
    EXISTING_ASSIGNMENT=$(az policy assignment list --resource-group "$RG" --query "[?name=='$POLICY_ASSIGNMENT_NAME'].name" -o tsv 2>/dev/null | head -n 1 || echo "")

    if [ -n "$EXISTING_ASSIGNMENT" ]; then
        echo -e "${YELLOW}○ Policy assignment already exists${NC}"
        echo "  Updating existing assignment..."
    else
        echo "  Creating new policy assignment..."
    fi

    # Create managed identity for the assignment (needed for modify effect)
    ASSIGNMENT_RESULT=$(az policy assignment create \
        --name "$POLICY_ASSIGNMENT_NAME" \
        --display-name "Security & Cost Control Tags Assignment" \
        --policy "$POLICY_NAME" \
        --resource-group "$RG" \
        --location "$LOCATION" \
        --assign-identity \
        --identity-scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG" \
        --role "Contributor" \
        2>&1)

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Policy assigned successfully${NC}"

        # Extract assignment ID and identity
        ASSIGNMENT_ID=$(echo "$ASSIGNMENT_RESULT" | jq -r '.id // empty' 2>/dev/null || echo "")
        IDENTITY_PRINCIPAL=$(echo "$ASSIGNMENT_RESULT" | jq -r '.identity.principalId // empty' 2>/dev/null || echo "")

        if [ -n "$ASSIGNMENT_ID" ]; then
            echo "  Assignment ID: $ASSIGNMENT_ID"
        fi

        if [ -n "$IDENTITY_PRINCIPAL" ]; then
            echo "  Identity Principal ID: $IDENTITY_PRINCIPAL"
            echo ""
            echo -e "${YELLOW}⏳ Waiting 30 seconds for identity propagation...${NC}"
            sleep 30
        fi
    else
        echo -e "${RED}✗ Failed to assign policy${NC}"
        echo "$ASSIGNMENT_RESULT"
        exit 1
    fi

    echo ""
fi

# Check compliance for all resources
echo -e "${CYAN}--- Checking Resource Compliance ---${NC}"
echo ""

# Get all resources in resource group
echo "Scanning resources in '$RG'..."
RESOURCES=$(az resource list --resource-group "$RG" --query "[?type!='Microsoft.Resources/deployments']" -o json)

if [ "$RESOURCES" == "[]" ] || [ -z "$RESOURCES" ]; then
    echo -e "${YELLOW}○ No resources found in resource group${NC}"
    exit 0
fi

RESOURCE_COUNT=$(echo "$RESOURCES" | jq 'length' 2>/dev/null || echo "0")
echo "Found $RESOURCE_COUNT resources"
echo ""

COMPLIANT=0
NON_COMPLIANT=0
EXCLUDED=0

# Excluded types (as per policy)
EXCLUDED_TYPES=(
    "Microsoft.Resources/subscriptions"
    "Microsoft.Resources/resourceGroups"
    "Microsoft.Resources/deployments"
    "Microsoft.Management/managementGroups"
)

# Function to check if resource type is excluded
is_excluded() {
    local type=$1
    for excluded in "${EXCLUDED_TYPES[@]}"; do
        if [ "$type" == "$excluded" ]; then
            return 0
        fi
    done
    return 1
}

# Check each resource
echo "Resource Compliance Report:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if command -v jq &> /dev/null; then
    echo "$RESOURCES" | jq -c '.[]' | while read -r resource; do
        NAME=$(echo "$resource" | jq -r '.name')
        TYPE=$(echo "$resource" | jq -r '.type')
        RESOURCE_ID=$(echo "$resource" | jq -r '.id')

        # Check if excluded type
        if is_excluded "$TYPE"; then
            echo -e "○ ${CYAN}$NAME${NC} ($TYPE)"
            echo "  Status: EXCLUDED (policy doesn't apply)"
            echo ""
            ((EXCLUDED++)) || true
            continue
        fi

        # Check for tags
        SECURITY_TAG=$(echo "$resource" | jq -r '.tags.SecurityControl // empty')
        COST_TAG=$(echo "$resource" | jq -r '.tags.CostControl // empty')

        if [ -n "$SECURITY_TAG" ] && [ -n "$COST_TAG" ]; then
            echo -e "✓ ${GREEN}$NAME${NC} ($TYPE)"
            echo "  Status: COMPLIANT"
            echo "  Tags: SecurityControl=$SECURITY_TAG, CostControl=$COST_TAG"
            ((COMPLIANT++)) || true
        else
            echo -e "✗ ${RED}$NAME${NC} ($TYPE)"
            echo "  Status: NON-COMPLIANT"
            [ -z "$SECURITY_TAG" ] && echo "  Missing: SecurityControl tag"
            [ -z "$COST_TAG" ] && echo "  Missing: CostControl tag"
            [ -n "$SECURITY_TAG" ] && echo "  Has: SecurityControl=$SECURITY_TAG"
            [ -n "$COST_TAG" ] && echo "  Has: CostControl=$COST_TAG"
            ((NON_COMPLIANT++)) || true
        fi
        echo ""
    done
else
    # Fallback without jq
    echo -e "${YELLOW}Limited parsing without jq - showing basic resource list${NC}"
    az resource list --resource-group "$RG" --query "[?type!='Microsoft.Resources/deployments'].[name,type]" -o tsv | while read -r name type; do
        echo "  - $name ($type)"
    done
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Summary:"
echo -e "  ${GREEN}Compliant:     $COMPLIANT${NC}"
echo -e "  ${RED}Non-Compliant: $NON_COMPLIANT${NC}"
echo -e "  ${CYAN}Excluded:      $EXCLUDED${NC}"
echo -e "  Total:         $RESOURCE_COUNT"
echo ""

# Remediation
if [ "$REMEDIATE" == "true" ]; then
    echo -e "${CYAN}--- Step 3/3: Creating Remediation Task ---${NC}"
    echo ""

    if [ "$NON_COMPLIANT" -eq 0 ]; then
        echo -e "${GREEN}✓ All resources are compliant - no remediation needed${NC}"
        exit 0
    fi

    # Check if policy assignment exists
    ASSIGNMENT_ID=$(az policy assignment list --resource-group "$RG" --query "[?name=='$POLICY_ASSIGNMENT_NAME'].id" -o tsv 2>/dev/null | head -n 1)

    if [ -z "$ASSIGNMENT_ID" ]; then
        echo -e "${RED}✗ Policy assignment not found${NC}"
        echo "  Run with --apply flag first to create the policy assignment"
        exit 1
    fi

    echo "Creating remediation task for non-compliant resources..."
    REMEDIATION_NAME="remediate-tags-$(date +%Y%m%d-%H%M%S)"

    REMEDIATION_RESULT=$(az policy remediation create \
        --name "$REMEDIATION_NAME" \
        --policy-assignment "$ASSIGNMENT_ID" \
        --resource-group "$RG" \
        --resource-discovery-mode ReEvaluateCompliance \
        2>&1)

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Remediation task created successfully${NC}"
        echo "  Task name: $REMEDIATION_NAME"
        echo ""
        echo -e "${YELLOW}⏳ Remediation is running in the background...${NC}"
        echo "  Monitor progress with:"
        echo "    az policy remediation show --name $REMEDIATION_NAME --resource-group $RG"
        echo ""
        echo "  Check deployment status:"
        echo "    az policy remediation deployment list --name $REMEDIATION_NAME --resource-group $RG"
    else
        echo -e "${RED}✗ Failed to create remediation task${NC}"
        echo "$REMEDIATION_RESULT"
        exit 1
    fi
fi

echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}Next Steps${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

if [ "$APPLY_POLICY" == "false" ]; then
    echo "To apply the policy definition and assignment:"
    echo "  ./scripts/verify_security_cost_tags.sh \"$RG\" --apply"
    echo ""
fi

if [ "$REMEDIATE" == "false" ] && [ "$NON_COMPLIANT" -gt 0 ]; then
    echo "To remediate $NON_COMPLIANT non-compliant resource(s):"
    echo "  ./scripts/verify_security_cost_tags.sh \"$RG\" --remediate"
    echo ""
    echo "Or apply and remediate in one command:"
    echo "  ./scripts/verify_security_cost_tags.sh \"$RG\" --apply --remediate"
    echo ""
fi

if [ "$APPLY_POLICY" == "true" ]; then
    echo "Policy is now active for new/updated resources in '$RG'"
    echo ""
fi

if [ "$REMEDIATE" == "true" ]; then
    echo "Wait 5-10 minutes, then re-run verification:"
    echo "  ./scripts/verify_security_cost_tags.sh \"$RG\""
    echo ""
fi

echo "For more information, see: infra/policy.tf"
echo ""

exit 0
