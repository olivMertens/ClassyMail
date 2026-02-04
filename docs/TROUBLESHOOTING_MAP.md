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
| **Service Bus** | `Azure Service Bus Data Owner` (or Sender/Receiver) | Read tasks, manage locks, send DLQ. |
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
    *   **Look for `ModuleNotFoundError`**: The startup command is wrong (e.g., using old `classificationg2s` instead of `classymail`).
    *   **Look for `AttributeError: 'NoneType' object has no attribute 'strip'`**: Missing Environment Variables (likely `AZURE_SERVICE_BUS_FQDN`).
    *   **Look for `AzureIdentityCredentialAdapter` errors**: The RBAC role is missing on the resource.

### Scenario B: GitHub Action fails - "Resource does not exist"

The identity used by GitHub Actions (`email-poc-id`) lacks permissions to **read/list** resources, even if it can **push** to them.

*   **Error:** `The environment '.../email-poc-env' does not exist.`
    *   **Fix:** Grant **Contributor** role on the Resource Group to the Managed Identity.
*   **Error:** `The resource with name '...acr...' could not be found.`
    *   **Fix:** Grant **Reader** role on the ACR to the Managed Identity (in addition to `AcrPush`).

### Scenario C: "Worker is crashing loop" (ProvisioningState: Failed)

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

### Scenario D: Authentication/Login Failures (AADSTS700213)

GitHub Action fails to login via OIDC.

1.  **Verify Subject:** Ensure the `Subject` key in the Federated Credential matches exact case: `repo:olivMertens/ClassyMail:ref:refs/heads/main`.
2.  **Verify Secrets:** Ensure GitHub Secret `AZURE_CLIENT_ID` matches the `clientId` of `email-poc-id`.
    ```bash
    az identity show -n email-poc-id -g email-poc-rg --query clientId
    ```
