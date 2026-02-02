# RBAC Audit & Managed Identity Configuration

> 🔐 **Purpose**: Document and verify managed identity role assignments for ClassificationG2S deployment on Azure Container Apps.

## Overview

ClassificationG2S uses **Azure Managed Identity** (specifically, User-Assigned Managed Identity) to authenticate securely with Azure services. This guide covers:

1. **What roles are assigned** - Access control matrix
2. **How to audit current assignments** - Azure CLI commands
3. **Troubleshooting** - Common authentication errors and fixes
4. **Local development setup** - Using `az login` for identity

**Key Principle**: No credentials (API keys, connection strings) are stored in code or environment variables. Authentication is delegated to Azure's identity plane using `DefaultAzureCredential`.

---

## 1. Role Assignment Matrix

The Terraform configuration (`infra/main.tf`) assigns the following roles to the ClassificationG2S managed identity:

| # | Role Name | Scope | Purpose | Resource |
|---|-----------|-------|---------|----------|
| 1 | **Storage Blob Data Reader** | Blob Storage (pdf-inputs) | Download PDFs for OCR/classification | `Storage Account` |
| 2 | **Storage Blob Data Contributor** | Blob Storage (pdf-inputs, pdf-outputs) | Upload results, error logs | `Storage Account` |
| 3 | **Service Bus Data Receiver** | Service Bus Queue | Consume messages from pdf-processing-queue | `Service Bus` |
| 4 | **Service Bus Data Sender** | Service Bus Queue | Send messages (retry, async comparison) | `Service Bus` |
| 5 | **Cosmos DB Account Reader Role** | Cosmos DB | Query email records / metadata | `Cosmos DB Account` |
| 6 | **Cosmos DB Built-in Data Contributor** | Cosmos DB (emailsdb/emails) | Create, update, delete email records | `Cosmos DB Database/Container` |
| 7 | **Cognitive Services OpenAI Contributor** | Azure AI Foundry (model deployments) | Call classification & OCR endpoints | `Foundry Account` |
| 8 | **Cognitive Services OpenAI User** | Azure AI Foundry | Read model metadata | `Foundry Account` |
| 9 | **Reader** | Resource Group | List resources (health checks, discovery) | `Resource Group` |
| 10 | **Event Grid Data Sender** (optional) | Event Grid | Send events (if worker publishes) | `Event Grid Topic` |

**Note**: Roles #1-10 are essential. Role #10 is optional unless worker publishes events.

---

## 2. Audit Commands

### 2.1 List all role assignments for a managed identity

```bash
# Set variables
IDENTITY_NAME="email-poc-identity"
RESOURCE_GROUP="rg-email-poc"

# Get the managed identity object ID
IDENTITY_ID=$(az identity show \
  --name $IDENTITY_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId \
  --output tsv)

echo "Managed Identity ID: $IDENTITY_ID"

# List all role assignments
az role assignment list \
  --assignee $IDENTITY_ID \
  --output table

# Filter to see only the assignments (with descriptions)
az role assignment list \
  --assignee $IDENTITY_ID \
  --query "[].{Role:roleDefinitionName, Scope:scope}" \
  --output table
```

**Expected Output** (sample):
```
Role                                          Scope
--------------------------------------------------------------
Storage Blob Data Reader                      /subscriptions/.../resourceGroups/rg-email-poc/providers/Microsoft.Storage/storageAccounts/stgemailpoc
Storage Blob Data Contributor                 /subscriptions/.../resourceGroups/rg-email-poc/providers/Microsoft.Storage/storageAccounts/stgemailpoc
Service Bus Data Receiver                      /subscriptions/.../resourceGroups/rg-email-poc/providers/Microsoft.ServiceBus/namespaces/sbemailpoc
Service Bus Data Sender                        /subscriptions/.../resourceGroups/rg-email-poc/providers/Microsoft.ServiceBus/namespaces/sbemailpoc
Cosmos DB Built-in Data Contributor            /subscriptions/.../resourceGroups/rg-email-poc/providers/Microsoft.DocumentDB/databaseAccounts/cosmosemailpoc
... (more roles)
```

### 2.2 Check a specific role assignment

```bash
# Check if identity has "Storage Blob Data Reader" role
az role assignment list \
  --assignee $IDENTITY_ID \
  --role "Storage Blob Data Reader" \
  --query "[].scope" \
  --output tsv
```

### 2.3 Docker/Container App context

When the app runs in **Container Apps**, it uses the managed identity assigned to the Container App:

```bash
# List identities assigned to a Container App
az containerapp identity show \
  --name email-poc-api \
  --resource-group rg-email-poc

# Expected output includes:
# "userAssignedIdentities": {
#   "/subscriptions/.../resourceGroups/rg-email-poc/providers/Microsoft.ManagedIdentity/userAssignedIdentities/email-poc-identity": {...}
# }
```

---

## 3. Troubleshooting Authentication Errors

### Error: `Unauthorized (401)` when calling Azure AI Foundry

**Possible Causes**:
1. Missing `Cognitive Services OpenAI Contributor` or `Cognitive Services OpenAI User` role
2. Endpoint region mismatch (model deployed in different region than identity)
3. Managed identity not assigned to Container App

**Solutions**:

```bash
# Check if identity has required AI roles
IDENTITY_ID=$(az identity show --name email-poc-identity --resource-group rg-email-poc --query principalId --output tsv)

az role assignment list \
  --assignee $IDENTITY_ID \
  --role "Cognitive Services OpenAI Contributor" \
  --query "[].scope" \
  --output tsv

# If empty, assign the role manually
AI_ACCOUNT_ID=$(az cognitiveservices account show \
  --name ai-email-poc \
  --resource-group rg-email-poc \
  --query id \
  --output tsv)

az role assignment create \
  --role "Cognitive Services OpenAI Contributor" \
  --assignee $IDENTITY_ID \
  --scope $AI_ACCOUNT_ID
```

### Error: `PermissionDenied` when uploading to Blob Storage

**Cause**: Missing `Storage Blob Data Contributor` role

**Solution**:
```bash
# Assign role to Storage Account
STORAGE_ID=$(az storage account show \
  --name stgemailpoc \
  --resource-group rg-email-poc \
  --query id \
  --output tsv)

az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee $IDENTITY_ID \
  --scope $STORAGE_ID
```

### Error: `ServiceUnavailable` when reading Service Bus

**Cause**: Missing `Service Bus Data Receiver` or endpoint misconfiguration

**Solution**:
```bash
# Check role assignment
az role assignment list \
  --assignee $IDENTITY_ID \
  --role "Service Bus Data Receiver" \
  --output table

# Check Service Bus connectivity (if needed, test via portal)
az servicebus queue show \
  --name pdf-processing-queue \
  --namespace-name sbemailpoc \
  --resource-group rg-email-poc
```

### Error: `CredentialUnavailableError` in local development

**Cause**: `DefaultAzureCredential` can't find credentials locally

**Solutions**:

1. **Use Azure CLI login** (recommended):
   ```bash
   az login
   # This sets up local credentials for DefaultAzureCredential to use
   ```

2. **Check authenticated user has roles**:
   ```bash
   # Get current authenticated user ID
   CURRENT_USER=$(az account show --query user.name --output tsv)

   # List their role assignments
   az role assignment list \
     --assignee $CURRENT_USER \
     --output table
   ```

3. **If you need service principal authentication** (for CI/CD):
   ```bash
   # Create service principal
   SERVICE_PRINCIPAL=$(az ad sp create-for-rbac \
     --name email-poc-sp \
     --role "Contributor" \
     --scopes $(az group show --name rg-email-poc --query id --output tsv))

   # Export credentials (for use in GitHub Actions, etc)
   echo $SERVICE_PRINCIPAL | jq '{clientId, clientSecret, subscriptionId, tenantId}'
   ```

---

## 4. Data Zone Validation

When `AZURE_PREFERRED_DATA_ZONE` is set (e.g., `eu-central`), the system logs warnings if endpoints are not in the specified region.

### Check endpoint region

```bash
# View Foundry account location
az cognitiveservices account show \
  --name ai-email-poc \
  --resource-group rg-email-poc \
  --query location \
  --output tsv
# Expected: eastus, westeurope, etc.

# View Storage Account location
az storage account show \
  --name stgemailpoc \
  --resource-group rg-email-poc \
  --query primaryLocation \
  --output tsv
```

### Model availability by region

| Model | EU Central | Global (US) | Asia |
|-------|-----------|-------------|------|
| Phi-4 (Foundry)| ✅ | ✅ | ✅ |
| gpt-4o-mini | ✅ | ✅ | ✅ |
| Mistral OCR (2505) | ✅ | ✅ | ❌ |

See: [Microsoft Learn - Foundry Model Availability](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-models/)

---

## 5. Terraform Role Assignment Reference

The `infra/main.tf` uses the following pattern to assign roles:

```hcl
# Example: Storage Blob Data Reader role
resource "azurerm_role_assignment" "storage_reader" {
  scope              = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id       = azurerm_user_assigned_identity.main.principal_id
}
```

**Key Points**:
- `principal_id` = the object ID of the managed identity (used for authorization)
- `scope` = resource (Storage Account, Service Bus, Cosmos DB, etc)
- `role_definition_name` = friendly name (Azure automatically maps to role ID)

---

## 6. Health Check Commands

Use this script to validate all role assignments at deployment time:

```bash
#!/bin/bash
# health_check_rbac.sh

IDENTITY_NAME="email-poc-identity"
RG="rg-email-poc"

IDENTITY_ID=$(az identity show --name $IDENTITY_NAME --resource-group $RG --query principalId --output tsv)

echo "🔐 RBAC Health Check"
echo "====================="
echo "Identity: $IDENTITY_NAME (ID: $IDENTITY_ID)"
echo ""

# Check each required role
ROLES=(
  "Storage Blob Data Reader"
  "Storage Blob Data Contributor"
  "Service Bus Data Receiver"
  "Service Bus Data Sender"
  "Cosmos DB Built-in Data Contributor"
  "Cognitive Services OpenAI Contributor"
)

for role in "${ROLES[@]}"; do
  count=$(az role assignment list --assignee $IDENTITY_ID --role "$role" --query "length(@)" --output tsv 2>/dev/null)
  if [ "$count" -gt 0 ]; then
    echo "✅ $role: ASSIGNED"
  else
    echo "❌ $role: MISSING"
  fi
done

echo ""
echo "ℹ️  Run 'terraform apply' in infra/ to assign missing roles."
```

---

## 7. Common Questions

### Q: Why use Managed Identity instead of API keys?

**A**: Managed Identity provides:
- ✅ No secrets in code/config
- ✅ Automatic credential rotation
- ✅ Audit trail via Azure Activity Log
- ✅ Works seamlessly in Container Apps
- ✅ Local dev with `az login` (same credentials)

### Q: Can I use a System-Assigned Identity?

**A**: Yes, but User-Assigned is preferred because:
- Works across multiple Container Apps (API + Worker)
- Easier to debug (named resource, not auto-generated)
- Can be tested locally independent of Container App

### Q: How do I test role assignments locally?

**A**: Use `az login` then verify:
```bash
# Your user's roles
az role assignment list \
  --assignee $(az account show --query user.name --output tsv) \
  --output table

# Or assign roles to your user for local testing
SUBSCRIBER_ID=$(az account show --query id --output tsv)
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $(az account show --query user.name --output tsv) \
  --scope /subscriptions/$SUBSCRIBER_ID/resourceGroups/rg-email-poc
```

---

## 8. References

- [Azure Managed Identities](https://learn.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/)
- [DefaultAzureCredential](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential)
- [Azure Container Apps Managed Identity](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity)
- [Azure RBAC Built-in Roles](https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles)
- [Azure AI Foundry Roles](https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/index)

---

**Last Updated**: 2024-12-01
**Maintained by**: ClassificationG2S Team
