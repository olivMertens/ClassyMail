# Architecture & Troubleshooting Map

This document maps the critical connections between Azure Container Apps (ACA), Service Bus, Storage, and Identity, and provides a troubleshooting guide for common failures (worker loops, queue blockages, deployment errors).

## 1. System Data Flow & Connections

The system relies on asynchronous message passing using the **Claim Check Pattern**:

1.  **API App** (`email-poc-api`)
    *   Uploads PDF to **Blob Storage** (`pdf-inputs`).
    *   Creates a document in **Cosmos DB** (`emails`) with status `pending`.
    *   Sends a message to **Service Bus Queue** (`pdf-processing-queue`).
2.  **Worker App** (`email-poc-worker`)
    *   Polls **Service Bus Queue**.
    *   Downloads PDF from **Blob Storage** using the path from the message.
    *   Sends content to **AI Foundry** (Mistral/Phi-4) for classification.
    *   Updates **Cosmos DB** with results or errors.

### Critical Infrastructure Glue (Managed Identity)

Both Container Apps use the **same User Assigned Managed Identity** (`email-poc-id`) to authenticate. There are no access keys in code (Access Keys are disabled).

| Resource | Required Role for Identity | Purpose |
| :--- | :--- | :--- |
| **Service Bus** | `Azure Service Bus Data Sender` + `Data Receiver` | Send messages (API, DLQ retry) + consume tasks (Worker). |
| **Storage Account** | `Storage Blob Data Contributor` | Read PDF content. |
| **Cosmos DB** | `Cosmos DB Built-in Data Contributor` | Read/Write metadata & results. |
| **AI Foundry** | `Cognitive Services User` | Invoke LLM models. |
| **Container Registry** | `AcrPull` | Download Docker image for ACA. |
| **Resource Group** | `Contributor` (CI/CD only) | Allow GitHub Actions to deploy ACA. |

---

## 2. Environment Variable Mapping

Both API and Worker share these critical configuration values. **If one is missing, the application will crash.**

| Env Var Name | Value Source (Terraform/Azure) | Function |
| :--- | :--- | :--- |
| `AZURE_CLIENT_ID` | Identity Client ID | Tells `DefaultAzureCredential` which identity to use (OIDC/MSI). |
| `AZURE_SERVICE_BUS_FQDN` | `${prefix}-sbus.servicebus.windows.net` | Connection to queue. |
| `AZURE_SERVICE_BUS_QUEUE` | `pdf-processing-queue` | The specific channel name. |
| `AZURE_STORAGE_ACCOUNT_URL` | `https://${prefix}st.blob.core.windows.net/` | Base URL for finding PDFs. |
| `AZURE_STORAGE_CONTAINER` | `pdf-inputs` | Folder name for PDFs. |
| `AZURE_COSMOS_DB` | `emailsdb` | Database name. |
| `AZURE_COSMOS_CONTAINER` | `emails` | Container name on Cosmos. |
| `AZURE_AI_ENDPOINT` | `${prefix}-aifoundry...` | MaaS/AI Gateway URL. |

---

## 3. Troubleshooting Guide

### Scenario A: "Messages are stuck in the Queue" (Active > 0)

The worker is likely crashing or configured incorrectly.

1.  **Check Message Counts:**
    ```bash
    az servicebus queue show --name pdf-processing-queue --namespace-name email-poc-sbus --resource-group email-poc-rg --query countDetails
    ```
2.  **Check Worker Logs:**
    ```bash
    az containerapp logs show --name email-poc-worker --resource-group email-poc-rg --tail 50
    ```
    *   **Look for `ModuleNotFoundError`**: The startup command is wrong (e.g., using old package name instead of `classymail`).
    *   **Look for `AttributeError: 'NoneType' object has no attribute 'strip'`**: Missing Environment Variables (likely `AZURE_SERVICE_BUS_FQDN`).
    *   **Look for `AzureIdentityCredentialAdapter` errors**: The RBAC role is missing on the resource.

### Scenario B: GitHub Action fails - "Resource does not exist"

The identity used by GitHub Actions (`email-poc-id`) lacks permissions to **read/list** resources, even if it can **push** to them.

*   **Error:** `The environment '.../email-poc-env' does not exist.`
    *   **Fix:** Grant **Contributor** role on the Resource Group to the Managed Identity.
*   **Error:** `The resource with name '...acr...' could not be found.`
    *   **Fix:** Grant **Reader** role on the ACR to the Managed Identity (in addition to `AcrPush`).

### Scenario C: Cosmos DB "readMetadata" Forbidden (RBAC Scope Bug)

**Error:**
```
Request blocked by Auth email-poc-cosmos : Request is blocked because principal [...]
does not have required RBAC permissions to perform action
[Microsoft.DocumentDB/databaseAccounts/readMetadata] on resource [dbs/emailsdb].
```

**Root cause:** The Cosmos SQL role assignment (`Cosmos DB Built-in Data Contributor`) is scoped to the **database** level (`dbs/emailsdb`) instead of the **account** level. The Python SDK calls `readMetadata` at the account level before any data-plane operation, and a database-scoped assignment doesn't cover it.

**Verify current assignments:**
```bash
# List all Cosmos SQL role assignments
az cosmosdb sql role assignment list \
  --account-name email-poc-cosmos \
  --resource-group email-poc-rg \
  -o table

# Check scope — must be the account ID, NOT .../dbs/emailsdb
az cosmosdb sql role assignment list \
  --account-name email-poc-cosmos \
  --resource-group email-poc-rg \
  --query "[].{name:name, principal:principalId, scope:scope}" \
  -o table
```

**Fix (CLI — immediate):**
```bash
# Get the managed identity principal
PRINCIPAL=$(az identity show -n email-poc-id -g email-poc-rg --query principalId -o tsv)

# Create account-scoped role assignment
ACCOUNT_ID=$(az cosmosdb show -n email-poc-cosmos -g email-poc-rg --query id -o tsv)
az cosmosdb sql role assignment create \
  --account-name email-poc-cosmos \
  --resource-group email-poc-rg \
  --role-definition-id "00000000-0000-0000-0000-000000000002" \
  --principal-id "$PRINCIPAL" \
  --scope "$ACCOUNT_ID"
```

**Fix (Terraform — permanent):** In `infra/main.tf`, the `azurerm_cosmosdb_sql_role_assignment` scope must be:
```hcl
scope = azurerm_cosmosdb_account.db.id  # account-level, NOT .../dbs/emailsdb
```

**Verify fix:**
```bash
# Test a simple read — should return documents or empty list, not 403
az rest --method POST \
  --uri "https://email-poc-cosmos.documents.azure.com/dbs/emailsdb/colls/emails/docs" \
  --headers "x-ms-version=2018-12-31" "x-ms-documentdb-query=true" \
  --body '{"query": "SELECT TOP 1 * FROM c"}'
# Or simply restart the Container App and check logs
az containerapp revision restart -n email-poc-api -g email-poc-rg
```

### Scenario D: "Worker is crashing loop" (ProvisioningState: Failed)

If manual updates corrupted the configuration (e.g., wiped env vars):

1.  **Export current YAML state:**
    ```bash
    az containerapp show -n email-poc-worker -g email-poc-rg --yaml > debug.yaml
    ```
2.  **Verify `containers[0].env`**: Ensure the list is populated (should have ~20 vars).
3.  **Verify `containers[0].args`**: Ensure it points to the correct module:
    ```yaml
    args: ["-m", "classymail.worker_main"]
    ```
4.  **Restore Config:** Use the `worker-restore.yaml` file (if available) or copy env vars from the API app (`email-poc-api`).

### Scenario E: Authentication/Login Failures (AADSTS700213)

GitHub Action fails to login via OIDC.

1.  **Verify Subject:** Ensure the `Subject` key in the Federated Credential matches exact case: `repo:olivMertens/ClassyMail:ref:refs/heads/main`.
2.  **Verify Secrets:** Ensure GitHub Secret `AZURE_CLIENT_ID` matches the `clientId` of `email-poc-id`.
    ```bash
    az identity show -n email-poc-id -g email-poc-rg --query clientId
    ```

### Scenario F: Cosmos DB 403 "Request originated from IP ... through public internet"

**Error:**
```
(Forbidden) Request originated from IP xxx.xxx.xxx.xxx through public internet.
This is blocked by your Cosmos DB account firewall settings.
```

**Root Cause:**
This error has **TWO** distinct causes:

#### Cause 1: Public Network Access Disabled (Terraform Drift)

**Critical Issue:** `publicNetworkAccess` is set to `Disabled` in Azure, even though Terraform expects `Enabled`.

**Impact:** Even with `ip_range_filter = ["0.0.0.0"]` (Allow Azure Services), **ALL public connections are blocked** when `publicNetworkAccess = Disabled`.

**Verification:**
```bash
# Check if public network access is disabled
az cosmosdb show --name email-poc-cosmos --resource-group email-poc-rg \
  --query publicNetworkAccess -o tsv

# Should return: Enabled
# If it returns: Disabled → This is the root cause
```

**Fix (Immediate - CLI):**
```bash
# Enable public network access
az cosmosdb update \
  --name email-poc-cosmos \
  --resource-group email-poc-rg \
  --public-network-access Enabled
```

**Fix (Permanent - Terraform):**
```bash
# Verify Terraform is correct (should already have this)
grep "public_network_access_enabled" infra/main.tf
# Expected: public_network_access_enabled = true

# Apply Terraform to restore desired state
cd infra
terraform plan -out=tfplan
terraform apply tfplan
```

#### Cause 2: Missing IP in Firewall Allowlist

**Scenario:** Public network access is enabled, but your specific IP is not in the allowlist.

This often happens when running local scripts (`test_e2e_flow.py`) from a developer machine.
Note: Azure Container Apps work because `0.0.0.0` (Azure Cloud access) is in the allowlist.

**Fix (Immediate - CLI):**
```bash
# Add your current IP to the firewall
az cosmosdb update \
  --name email-poc-cosmos \
  --resource-group email-poc-rg \
  --ip-range-filter "0.0.0.0,$(curl -s ifconfig.me)"
```

**Fix (Terraform - Permanent):**
Add your IP to `infra/terraform.tfvars`:
```hcl
allowed_ip_ranges = ["xxx.xxx.xxx.xxx"]
```
Then run `terraform apply`.

**Diagnostic Decision Tree:**
```
Error: "Request originated from IP X.X.X.X through public internet"
  ↓
1. Check: az cosmosdb show --query publicNetworkAccess
  ↓
  If "Disabled" → Run: az cosmosdb update --public-network-access Enabled
  If "Enabled" → Continue to step 2
  ↓
2. Check: az cosmosdb show --query ipRules
  ↓
  If "0.0.0.0" is missing → Add it via terraform or CLI
  If "0.0.0.0" is present but your IP is not → Add your IP
```
