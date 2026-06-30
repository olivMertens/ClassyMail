# RBAC Audit & Managed Identity Configuration



> ?? **Purpose**: Document and verify managed identity role assignments for ClassyMail deployment on Azure Container Apps.

>

> ?? **Naming convention**: `<prefix>` refers to your Terraform `prefix` variable (default: `classymail`). All Azure resource names are derived from it.



## Overview



ClassyMail uses **Azure Managed Identity** (specifically, User-Assigned Managed Identity) to authenticate securely with Azure services. This guide covers:



1. **What roles are assigned** - Access control matrix

2. **How to audit current assignments** - Azure CLI commands

3. **Troubleshooting** - Common authentication errors and fixes

4. **Local development setup** - Using `az login` for identity



**Key Principle**: No credentials (API keys, connection strings) are stored in code or environment variables. Authentication is delegated to Azure's identity plane using `DefaultAzureCredential`.



---



## 1. Role Assignment Matrix



The Terraform configuration (`infra/main.tf`) assigns the following roles to the ClassyMail managed identity (`<prefix>-id`):



| # | Terraform Resource | Role Name | Scope | Purpose | Conditional |

|---|---|-----------|-------|---------|-------------|

| 1 | `aca_storage_contrib` | **Storage Blob Data Contributor** | Storage Account | Upload/download PDFs, results, logs | Always |

| 2 | `aca_sb_owner` | **Azure Service Bus Data Owner** | Service Bus Namespace | Send + receive messages AND read queue runtime properties (queue-stats monitoring via `ServiceBusAdministrationClient.get_queue_runtime_properties`) | Always |

| 3 | `app_role` | **Custom Cosmos DB Role** | Cosmos DB Account | `readMetadata` + CRUD + Query (see §9) | Assignment gated by `cosmos_use_rbac` |

| 4 | `rbac_ai` | **Cognitive Services User** | AI Foundry Account | Inference (Chat, Embeddings, OCR) | Always |

| 5 | `acr_pull` | **AcrPull** | Container Registry | Pull Docker images | Only if `acr_name` is set |

| 6 | `aca_language_reader` | **Cognitive Services Language Reader** | Language Service | PII detection / NER | Only if `deploy_language_service` is true |



**Ratings**:

- The Custom Cosmos DB Role is defined via `azurerm_cosmosdb_sql_role_definition` — it is **not** the built-in "Cosmos DB Built-in Data Contributor" role. See section 9 for details.

- The Python SDK requires Cosmos DB permissions at the **Account Scope** to perform metadata operations. Database-level scoping will cause SDK failures.



---



## 2. Audit Commands



### 2.1 List all role assignments for a managed identity



```bash

# Set variables

IDENTITY_NAME="<prefix>-id"

RESOURCE_GROUP="<prefix>-rg"



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

Storage Blob Data Contributor                 /subscriptions/.../resourceGroups/<prefix>-rg/providers/Microsoft.Storage/storageAccounts/<prefix>sto...

Azure Service Bus Data Owner                  /subscriptions/.../resourceGroups/<prefix>-rg/providers/Microsoft.ServiceBus/namespaces/<prefix>-sbus

Cognitive Services User                       /subscriptions/.../resourceGroups/<prefix>-rg/providers/Microsoft.CognitiveServices/accounts/<prefix>-aifoundry

... (Cosmos DB custom role shown separately via az cosmosdb sql role assignment list)

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

  --name <prefix>-api \

  --resource-group <prefix>-rg



# Expected output includes:

# "userAssignedIdentities": {

#   "/subscriptions/.../resourceGroups/<prefix>-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/<prefix>-id": {...}

# }

```



---



## 3. Troubleshooting Authentication Errors



### Error: `Unauthorized (401)` when calling Microsoft AI Foundry



**Possible Causes**:

1. Missing `Cognitive Services User` role on the AI Foundry account

2. Endpoint region mismatch (model deployed in different region than identity)

3. Managed identity not assigned to Container App



**Solutions**:



```bash

# Check if identity has required AI roles

IDENTITY_ID=$(az identity show --name <prefix>-id --resource-group <prefix>-rg --query principalId --output tsv)



az role assignment list \

  --assignee $IDENTITY_ID \

  --role "Cognitive Services User" \

  --query "[].scope" \

  --output tsv



# If empty, assign the role manually

AI_ACCOUNT_ID=$(az cognitiveservices account show \

  --name <prefix>-aifoundry \

  --resource-group <prefix>-rg \

  --query id \

  --output tsv)



az role assignment create \

  --role "Cognitive Services User" \

  --assignee $IDENTITY_ID \

  --scope $AI_ACCOUNT_ID

```



### Error: `PermissionDenied` when uploading to Blob Storage



**Cause**: Missing `Storage Blob Data Contributor` role



**Solution**:

```bash

# Assign role to Storage Account

STORAGE_ID=$(az storage account show \

  --name <prefix>sto<region> \

  --resource-group <prefix>-rg \

  --query id \

  --output tsv)



az role assignment create \

  --role "Storage Blob Data Contributor" \

  --assignee $IDENTITY_ID \

  --scope $STORAGE_ID

```



### Error: `ServiceUnavailable` when reading Service Bus



**Cause**: Missing `Azure Service Bus Data Owner` (or legacy `Data Receiver`) or endpoint misconfiguration

**Solution**:

```bash

# Check role assignment

az role assignment list \

  --assignee $IDENTITY_ID \

  --role "Azure Service Bus Data Owner" \

  --output table



# Check Service Bus connectivity (if needed, test via portal)

az servicebus queue show \

  --name pdf-processing-queue \

  --namespace-name <prefix>-sbus \

  --resource-group <prefix>-rg

```



### Error: Event Grid not triggering Service Bus



**Cause**: Service Bus Local Authentication disabled (`disableLocalAuth: true`).

**Impact**: Event Grid cannot deliver messages to the queue. The Terraform configuration explicitly enables local auth to support this integration.



**Solution**:

```bash

# Enable Local Authentication

az servicebus namespace update \

  --resource-group <prefix>-rg \

  --name <prefix>-sbus \

  --disable-local-auth false

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

     --name <prefix>-sp \

     --role "Contributor" \

     --scopes $(az group show --name <prefix>-rg --query id --output tsv))



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

  --name <prefix>-aifoundry \

  --resource-group <prefix>-rg \

  --query location \

  --output tsv

# Expected: eastus, westeurope, etc.



# View Storage Account location

az storage account show \

  --name <prefix>sto<region> \

  --resource-group <prefix>-rg \

  --query primaryLocation \

  --output tsv

```



### Model availability by region



| Model | EU Central | Global (US) | Asia |

|-------|-----------|-------------|------|

| Phi-4 (Foundry)| ? | ? | ? |

| gpt-4o-mini | ? | ? | ? |

| Mistral OCR (2505) | ? | ? | ? |



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



> **Automated verify & repair:** `infra/deploy.ps1` / `infra/deploy.sh` discover
> the app managed identity and **add only the missing** role assignments. Run them
> standalone against an existing resource group to double-check a deployment:
>
> ```powershell
> ./infra/deploy.ps1 -VerifyOnly -ResourceGroup <prefix>-rg
> ```
> ```bash
> bash infra/deploy.sh --verify-only --resource-group <prefix>-rg
> ```
>
> This runs automatically after every successful deploy (skip with
> `-SkipRoleVerification` / `--skip-role-verification`). The manual script below
> remains available for a read-only check.

Use this script to validate all role assignments at deployment time:



```bash

#!/bin/bash

# health_check_rbac.sh



IDENTITY_NAME="<prefix>-id"

RG="<prefix>-rg"



IDENTITY_ID=$(az identity show --name $IDENTITY_NAME --resource-group $RG --query principalId --output tsv)



echo "?? RBAC Health Check"

echo "====================="

echo "Identity: $IDENTITY_NAME (ID: $IDENTITY_ID)"

echo ""



# Check each required role

ROLES=(

  "Storage Blob Data Contributor"

  "Azure Service Bus Data Owner"

  "Cognitive Services User"

)



for role in "${ROLES[@]}"; do

  count=$(az role assignment list --assignee $IDENTITY_ID --role "$role" --query "length(@)" --output tsv 2>/dev/null)

  if [ "$count" -gt 0 ]; then

    echo "? $role: ASSIGNED"

  else

    echo "? $role: MISSING"

  fi

done



echo ""

echo "??  Rating: Cosmos DB uses a custom SQL role (not listed above). Check with:"

echo "  az cosmosdb sql role assignment list --account-name <prefix>-cosmos --resource-group <prefix>-rg"

echo ""

echo "??  Run 'terraform apply' in infra/ to assign missing roles."

```



---



## 7. Common Questions



### Q: Why use Managed Identity instead of API keys?



**A**: Managed Identity provides:

- ? No secrets in code/config

- ? Automatic credential rotation

- ? Audit trail via Azure Activity Log

- ? Works seamlessly in Container Apps

- ? Local dev with `az login` (same credentials)



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

  --scope /subscriptions/$SUBSCRIBER_ID/resourceGroups/<prefix>-rg

```



---



## 8. Manual / Extra Roles (Historical — Cleaned Up)



> **Status**: These 4 extra roles were found as manual leftovers on the original `classymail`

> environment. After a deep code-level audit confirmed none are used by the application,

> they were **removed on 2026-02-16**. A clean Terraform deployment will never create them.



| Extra Role | Scope | Verdict | Evidence |

|---|---|---|---|

| Storage Blob Data Reader | Storage Account | **REDUNDANT** — removed | Superset role (Data Contributor) already assigned by TF. All code uses a single `BlobServiceClient` for both reads and writes. |

| AcrPush | Container Registry | **UNUSED** — removed | Image pushing uses operator/CI-CD context (`az acr build`, `docker push`), never the managed identity. |

| Reader | Container Registry | **UNUSED** — removed | AcrPull (TF `acr_pull`) suffices for Container Apps image pulls. `az acr show` only runs in CI/CD or operator context. |

| Contributor | Resource Group | **UNUSED** — removed | No `azure-mgmt-*` SDK in `pyproject.toml`. All management-plane ops run via Terraform or CI/CD SP. |



**If you ever find unexpected extra roles**, they can be removed:



```bash

# List all roles for the managed identity

az role assignment list --assignee <principalId> --all -o table



# Remove a specific extra role

az role assignment delete --assignee <principalId> --role "<RoleName>" --scope <resourceId>

```



The verification scripts (`verify_infra.ps1`, `verify-mvp-setup.ps1`) **warn** about unexpected extra roles.



---



## 9. Security Best Practices & Design Decisions



### Why a Custom Role for Cosmos DB?



In typical Azure Cosmos DB deployments, the **"Cosmos DB Built-in Data Contributor"** role is commonly used. However, this role grants broader permissions than minimal necessary, and bundling permissions can sometimes violate the principle of least privilege.



**Design Decision:**

We use a **Custom Role** (`Custom App Role`) defined in Terraform for two key reasons:

1. **SDK Requirement**: The Azure Cosmos DB Python SDK executes a `readMetadata` operation on the **Account scope** upon initialization. Without this permission at the account level, the application crashes on startup.

2. **Security Granularity**: By creating a custom role, we explicitly grant `readMetadata` (Account Scope) while restricting data operations strictly to standard CRUD (Create, Read, Update, Delete) and Query operations. This avoids granting administrative privileges over the account or other databases that might exist in shared environments.



### Why Account Scope?



While Database-level scope (`/dbs/emailsdb`) is theoretically more secure, it breaks the Python SDK's initialization logic.

**The "Strict" Compromise**: We assign the role at the **Account Scope** to satisfy the SDK's metadata needs, but we limit the *actions* the role can perform via the Custom Role definition. This ensures the application works reliably without being an unrestricted admin.



## 10. References



- [Azure Managed Identities](https://learn.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/)

- [DefaultAzureCredential](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential)

- [Azure Container Apps Managed Identity](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity)

- [Azure RBAC Built-in Roles](https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles)

- [Microsoft AI Foundry Roles](https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/index)



---



**Last Updated**: 2026-02-16

**Maintained by**: ClassyMail Team
