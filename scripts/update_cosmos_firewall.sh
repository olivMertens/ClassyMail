#!/bin/bash
set -euo pipefail

# update_cosmos_firewall.sh
# Updates Cosmos DB firewall to allow Container App outbound IPs + local dev IP

RESOURCE_GROUP="${RESOURCE_GROUP:-}"
COSMOS_ACCOUNT="${COSMOS_ACCOUNT:-email-poc-cosmos}"
API_APP="${API_APP:-email-poc-api}"
WORKER_APP="${WORKER_APP:-email-poc-worker}"
INCLUDE_LOCAL_IP="${INCLUDE_LOCAL_IP:-false}"

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Updates Cosmos DB firewall to allow Container App outbound IPs.

OPTIONS:
    -g, --resource-group <name>   Resource Group name (required)
    -c, --cosmos-account <name>   Cosmos DB account name (default: email-poc-cosmos)
    -a, --api-app <name>          API Container App name (default: email-poc-api)
    -w, --worker-app <name>       Worker Container App name (default: email-poc-worker)
    -l, --include-local-ip        Include your current public IP
    -h, --help                    Show this help message

EXAMPLES:
    # Basic usage
    $0 -g email-poc-rg

    # Include local IP for development
    $0 -g email-poc-rg --include-local-ip

    # Use environment variables
    export RESOURCE_GROUP=email-poc-rg
    export INCLUDE_LOCAL_IP=true
    $0
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -g|--resource-group)
            RESOURCE_GROUP="$2"
            shift 2
            ;;
        -c|--cosmos-account)
            COSMOS_ACCOUNT="$2"
            shift 2
            ;;
        -a|--api-app)
            API_APP="$2"
            shift 2
            ;;
        -w|--worker-app)
            WORKER_APP="$2"
            shift 2
            ;;
        -l|--include-local-ip)
            INCLUDE_LOCAL_IP=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate required parameters
if [ -z "$RESOURCE_GROUP" ]; then
    echo "❌ Error: Resource Group is required"
    echo "Use: $0 -g <resource-group> or set RESOURCE_GROUP environment variable"
    exit 1
fi

echo "🔍 Retrieving Container App outbound IPs..."

# Get API outbound IPs
API_IPS=()
if az containerapp show --name "$API_APP" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    mapfile -t API_IPS < <(az containerapp show --name "$API_APP" --resource-group "$RESOURCE_GROUP" --query "properties.outboundIpAddresses[]" -o tsv 2>/dev/null || echo "")
    if [ ${#API_IPS[@]} -gt 0 ]; then
        echo "  ✅ API App IPs: ${API_IPS[*]}"
    fi
else
    echo "  ⚠️  API App not found, skipping..."
fi

# Get Worker outbound IPs
WORKER_IPS=()
if az containerapp show --name "$WORKER_APP" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    mapfile -t WORKER_IPS < <(az containerapp show --name "$WORKER_APP" --resource-group "$RESOURCE_GROUP" --query "properties.outboundIpAddresses[]" -o tsv 2>/dev/null || echo "")
    if [ ${#WORKER_IPS[@]} -gt 0 ]; then
        echo "  ✅ Worker App IPs: ${WORKER_IPS[*]}"
    fi
else
    echo "  ⚠️  Worker App not found, skipping..."
fi

# Build IP list
IP_LIST=("0.0.0.0")  # Always include Azure Services
IP_LIST+=("${API_IPS[@]}")
IP_LIST+=("${WORKER_IPS[@]}")

# Add local IP if requested
if [ "$INCLUDE_LOCAL_IP" = true ]; then
    echo "🌐 Retrieving your public IP..."
    LOCAL_IP=$(curl -s --max-time 5 ifconfig.me || echo "")
    if [ -n "$LOCAL_IP" ]; then
        echo "  ✅ Your IP: $LOCAL_IP"
        IP_LIST+=("$LOCAL_IP")
    else
        echo "  ⚠️  Failed to retrieve local IP, skipping..."
    fi
fi

# Deduplicate and join
IP_FILTER=$(printf '%s\n' "${IP_LIST[@]}" | sort -u | paste -sd ',')

echo ""
echo "📝 Final IP filter list:"
printf '%s\n' "${IP_LIST[@]}" | sort -u | sed 's/^/  - /'

echo ""
echo "🔧 Updating Cosmos DB firewall..."
echo "  Account: $COSMOS_ACCOUNT"
echo "  Resource Group: $RESOURCE_GROUP"

if az cosmosdb update \
    --name "$COSMOS_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --public-network-access Enabled \
    --ip-range-filter "$IP_FILTER" \
    --output none 2>/dev/null; then

    echo ""
    echo "✅ Cosmos DB firewall updated successfully!"
    echo "   You can now connect from:"
    echo "   - Azure Services (0.0.0.0)"
    echo "   - Container Apps ($((${#API_IPS[@]} + ${#WORKER_IPS[@]})) IPs)"
    [ "$INCLUDE_LOCAL_IP" = true ] && echo "   - Your local machine"
else
    echo ""
    echo "❌ Failed to update Cosmos DB firewall"
    echo ""
    echo "💡 If you see 'operation in progress', wait 1-2 minutes and retry."
    exit 1
fi
