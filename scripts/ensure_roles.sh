#!/bin/bash

# Configuration
RESOURCE_GROUP="email-poc-rg"
IDENTITY_NAME="email-poc-id"
APP_NAME="email-poc-api" # For final status check

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🚀 Starting RBAC Role Assignment Verification...${NC}"

# 0. Check Azure Login
echo -e "\n${YELLOW}🔑 Checking Azure Login...${NC}"
az account show > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "❌ You are not logged in. Initiating login..."
    az login
    if [ $? -ne 0 ]; then
        echo "❌ Login failed. Exiting."
        exit 1
    fi
else
    CURRENT_SUB=$(az account show --query name -o tsv)
    echo -e "${GREEN}✅ Logged in to: $CURRENT_SUB${NC}"
fi

# 1. Get Managed Identity Principal ID
echo -e "\n${YELLOW}🔍 Retrieving Managed Identity: $IDENTITY_NAME${NC}"
PRINCIPAL_ID=$(az identity show --name $IDENTITY_NAME --resource-group $RESOURCE_GROUP --query principalId -o tsv 2>/dev/null)

if [ -z "$PRINCIPAL_ID" ]; then
    echo -e "${YELLOW}Identity not found, checking if we need to crate or if it is a system assigned scenario...${NC}"
    # In this project we expect User Assigned. If missing, we assume Terraform hasn't run or failed.
    echo "❌ Managed Identity '$IDENTITY_NAME' not found. Please run Terraform first or check variables."
    exit 1
else
    echo -e "${GREEN}✅ Found Identity. Principal ID: $PRINCIPAL_ID${NC}"
fi

# Function to assign role
assign_role() {
    local role=$1
    local scope=$2
    local resource_desc=$3

    echo -e "   Checking role '${role}' on ${resource_desc}..."
    az role assignment create \
        --assignee $PRINCIPAL_ID \
        --role "$role" \
        --scope "$scope" \
        --output none 2>/dev/null

    if [ $? -eq 0 ]; then
        echo -e "   ${GREEN}✅ Role assigned (or already existed).${NC}"
    else
        echo -e "   ❌ Failed to assign role."
    fi
}

# 2. Assign Roles

# --- AI Foundry / Cognitive Services ---
echo -e "\n${YELLOW}🧠 AI Foundry / Cognitive Services${NC}"
AI_ACCOUNT_ID=$(az cognitiveservices account list --resource-group $RESOURCE_GROUP --query "[0].id" -o tsv)
if [ ! -z "$AI_ACCOUNT_ID" ]; then
    assign_role "Cognitive Services User" "$AI_ACCOUNT_ID" "AI Service"
else
    echo "⚠️  No Cognitive Services account found."
fi

# --- Storage Account ---
echo -e "\n${YELLOW}📦 Storage Account${NC}"
STORAGE_ID=$(az storage account list --resource-group $RESOURCE_GROUP --query "[0].id" -o tsv)
if [ ! -z "$STORAGE_ID" ]; then
    assign_role "Storage Blob Data Contributor" "$STORAGE_ID" "Storage Account"
else
    echo "⚠️  No Storage Account found."
fi

# --- Service Bus ---
echo -e "\n${YELLOW}messages Service Bus${NC}"
SB_ID=$(az servicebus namespace list --resource-group $RESOURCE_GROUP --query "[0].id" -o tsv)
if [ ! -z "$SB_ID" ]; then
    assign_role "Azure Service Bus Data Sender" "$SB_ID" "Service Bus"
    assign_role "Azure Service Bus Data Receiver" "$SB_ID" "Service Bus"
else
    echo "⚠️  No Service Bus Namespace found."
fi

# --- Cosmos DB ---
echo -e "\n${YELLOW}🪐 Cosmos DB${NC}"
COSMOS_ID=$(az cosmosdb list --resource-group $RESOURCE_GROUP --query "[0].id" -o tsv)
if [ ! -z "$COSMOS_ID" ]; then
    # Note: Cosmos DB built-in roles sometimes require 'az cosmosdb sql role assignment create' instead of standard RBAC depending on config.
    # We obey the standard RBAC instruction from README.
    assign_role "Cosmos DB Built-in Data Contributor" "$COSMOS_ID" "Cosmos DB"
else
    echo "⚠️  No Cosmos DB found."
fi

# --- Container Registry ---
echo -e "\n${YELLOW}🚢 Container Registry${NC}"
ACR_ID=$(az acr list --resource-group $RESOURCE_GROUP --query "[0].id" -o tsv)
if [ ! -z "$ACR_ID" ]; then
    assign_role "AcrPull" "$ACR_ID" "ACR"
else
    echo "⚠️  No Container Registry found."
fi

# 3. Final Status
echo -e "\n${GREEN}✅ Verification & Assignment Complete!${NC}"
echo ""
echo "🔍 Check status with:"
echo "   az containerapp show --name $APP_NAME --resource-group $RESOURCE_GROUP --query properties.runningStatus"
