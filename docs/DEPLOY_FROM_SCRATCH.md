# Deploy ClassyMail from scratch (new tenant)

> **Goal**: A person clones this repo and deploys the full stack in a
> **fresh Azure tenant** they own — no prior infrastructure, no CI/CD.
>
> Estimated time: **45–60 minutes** (including model provisioning wait times).

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone and Configure](#2-clone-and-configure)
3. [Provision Infrastructure](#3-provision-infrastructure)
4. [Build and Push Container Image](#4-build-and-push-container-image)
5. [Deploy AI Models](#5-deploy-ai-models)
6. [Local Development Setup](#6-local-development-setup)
   - 6.5 [Upload PDFs to Blob Storage](#65-upload-pdfs-to-blob-storage)
7. [Verify and Smoke Test](#7-verify-and-smoke-test)
8. [Troubleshooting](#8-troubleshooting)
9. [Cleanup / Teardown](#9-cleanup--teardown)

---

## 1. Prerequisites

### 1.1 Azure Account

| Requirement | Details |
|-------------|---------|
| **Azure Subscription** | Active subscription with billing enabled |
| **Permissions** | **Owner** or **Contributor + User Access Administrator** at subscription level |
| **Quota** | Container Apps (2 apps, 0.5 CPU/1Gi each), Cosmos DB Serverless, Service Bus Standard |
| **Region** | `swedencentral` recommended (best EU model availability). Alternatives: `westeurope`, `eastus`, `eastus2` |

### 1.2 Tools (install on your machine)

```powershell
# Verify all are installed
az --version          # Azure CLI >= 2.60
terraform --version   # Terraform >= 1.5
docker --version      # Docker Desktop or Podman
node --version        # Node.js >= 18
python --version      # Python 3.12
uv --version          # uv (Python package manager)
```

**Install links:**

- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- [Terraform](https://developer.hashicorp.com/terraform/install)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Node.js](https://nodejs.org/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### 1.3 Register Azure Resource Providers

Resource providers must be registered **once per subscription** (idempotent):

```powershell
az login --tenant <YOUR_TENANT_ID>
az account set --subscription <YOUR_SUBSCRIPTION_ID>

# Register all required providers (takes 1-5 min each; runs in background)
$providers = @(
  "Microsoft.Storage",
  "Microsoft.ServiceBus",
  "Microsoft.DocumentDB",
  "Microsoft.CognitiveServices",
  "Microsoft.App",
  "Microsoft.EventGrid",
  "Microsoft.Insights",
  "Microsoft.OperationalInsights",
  "Microsoft.ManagedIdentity",
  "Microsoft.ContainerRegistry"
)
foreach ($p in $providers) {
  az provider register --namespace $p --wait
  Write-Host "Registered: $p"
}
```

### 1.4 Verify Mistral Document AI Availability

> **Mistral Document AI** is deployed directly through **Azure AI Foundry** as a
> Serverless API — no Azure Marketplace subscription is required.

1. Go to [Azure AI Foundry](https://ai.azure.com/)
2. Select your project (created by Terraform in Step 3)
3. Navigate to **Model catalog** and search for **"Mistral Document AI"**
4. Verify the model is available in your region (recommended: `swedencentral`)

If the model is not available in your region, check
[Azure AI model availability](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models)
and consider switching your `location` in `terraform.tfvars`.

---

## 2. Clone and Configure

### 2.1 Clone the Repository

```powershell
git clone https://github.com/<owner>/ClassificationG2S.git
cd ClassificationG2S
```

### 2.2 Create a Container Registry (if you don't have one)

```powershell
# Choose a globally unique name (letters+numbers only, 5-50 chars)
$ACR_NAME = "emailpoctestacr"
$ACR_RG   = "rg-acr-shared"
$LOCATION = "swedencentral"

az group create --name $ACR_RG --location $LOCATION
az acr create --name $ACR_NAME --resource-group $ACR_RG --sku Basic --admin-enabled false
```

### 2.3 Create terraform.tfvars

```powershell
Copy-Item infra/terraform.tfvars.example infra/terraform.tfvars
```

Edit `infra/terraform.tfvars` with your values:

```hcl
# REQUIRED
subscription_id = "<YOUR_SUBSCRIPTION_ID>"

# First deploy: use a placeholder image (real image built in Step 4)
container_image = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"

# ACR for the managed identity to pull images
acr_name           = "emailpoctestacr"
acr_resource_group = "rg-acr-shared"

# Customize prefix to avoid naming collisions
prefix   = "email-poc-test"
location = "swedencentral"

# Keep defaults for a clean new-tenant deployment
cosmos_use_rbac                = true
enable_model_deployments       = false    # Deploy models manually (Step 5)
deploy_language_service        = false    # Optional, enable later
tag_policy_enabled             = true
security_cost_policy_enabled   = true

# Your public IP for Cosmos DB data-plane access during local dev
# Find it: (Invoke-WebRequest ifconfig.me).Content.Trim()
allowed_ip_ranges = ["<YOUR_PUBLIC_IP>"]
```

> **Tip**: Find your public IP with:
> ```powershell
> (Invoke-WebRequest -Uri "https://ifconfig.me" -UseBasicParsing).Content.Trim()
> ```

---

## 3. Provision Infrastructure

### 3.1 Automated (recommended)

```powershell
.\infra\deploy.ps1 -TenantId "<TENANT_ID>" -SubscriptionId "<SUBSCRIPTION_ID>"
```

The script will:
1. Verify Azure CLI auth
2. **Set `ARM_USE_MSI=false`** (Fortinet/corporate firewall workaround — prevents IMDS calls)
3. Run `terraform init -upgrade`
4. Run `terraform plan` and show the plan
5. Ask for confirmation before `terraform apply`

> **Linux/macOS**: `bash infra/deploy.sh --tenant-id <TENANT_ID> --subscription-id <SUBSCRIPTION_ID>`

### 3.2 Manual (for transparency)

```powershell
az login --tenant <TENANT_ID>
az account set --subscription <SUBSCRIPTION_ID>

# Fortinet / corporate firewall workaround (mandatory on corp networks)
$env:ARM_USE_MSI  = "false"
$env:ARM_USE_OIDC = "false"

terraform -chdir=infra init -upgrade
terraform -chdir=infra plan -var "subscription_id=<SUBSCRIPTION_ID>" -out tfplan
terraform -chdir=infra apply tfplan
```

> **Linux/macOS**: use `export ARM_USE_MSI="false"` and `export ARM_USE_OIDC="false"` instead.

### 3.3 Expected Resources Created

After `terraform apply`, you should see ~25 resources:

| Resource | Name |
|----------|------|
| Resource Group | `email-poc-test-rg` |
| Storage Account | `emailpoctestst` |
| Blob Container | `pdf-inputs` |
| Service Bus Namespace | `email-poc-test-sbus` |
| Service Bus Queue | `pdf-processing-queue` |
| Event Grid Topic | `email-poc-test-blob-events` |
| Azure AI Foundry | `email-poc-test-aifoundry` |
| Cosmos DB Account | `email-poc-test-cosmos` |
| Cosmos DB Database | `emailsdb` |
| Cosmos Containers | `emails`, `chat_history`, `vector_cache` |
| Managed Identity | `email-poc-test-id` |
| Log Analytics | `email-poc-test-logs` |
| App Insights | `email-poc-test-appi` |
| Container App Env | `email-poc-test-env` |
| Container App: API | `email-poc-test-api` |
| Container App: Worker | `email-poc-test-worker` |

> **Note**: The Container Apps will be running the placeholder image at this point.
> That's expected — we'll update them in Step 4.

> **RBAC**: Terraform assigns exactly 7 roles to the managed identity (Storage Blob Data Contributor,
> Service Bus Data Sender + Receiver, Custom Cosmos App Role, Cognitive Services User, AcrPull,
> and optionally Cognitive Services Language Reader). **No extra manual roles are needed.**
> The verification scripts will warn if any unexpected roles are found.
> See [RBAC_AUDIT.md §8](../docs/RBAC_AUDIT.md#8-manual--extra-roles-historical--cleaned-up) for historical context.

### 3.4 Note Terraform Outputs

```powershell
terraform -chdir=infra output
```

Save these values — you'll need `AI_ENDPOINT` for configuring model deployments.

---

## 4. Build and Push Container Image

### 4.1 Install Frontend Dependencies and Build

```powershell
cd frontend
npm install
npm run build
cd ..
```

### 4.2 Fetch Vue Runtime

```powershell
.\scripts\fetch_vue_runtime.ps1
```

### 4.3 Build and Push to ACR

**Option A — Remote build (recommended, no Docker needed locally):**

```powershell
.\scripts\build_acr.ps1 -AcrName "emailpoctestacr" -Tag "v1"
```

**Option B — Local Docker build and push:**

```powershell
$IMAGE = "emailpoctestacr.azurecr.io/classymail-agent:v1"
az acr login --name emailpoctestacr
docker build -t $IMAGE .
docker push $IMAGE
```

### 4.4 Update Terraform with Real Image

Edit `infra/terraform.tfvars`:

```hcl
container_image = "emailpoctestacr.azurecr.io/classymail-agent:v1"
```

Re-apply:

```powershell
terraform -chdir=infra plan -var "subscription_id=<SUBSCRIPTION_ID>" -out tfplan
terraform -chdir=infra apply tfplan
```

This updates both Container Apps (API + Worker) to use your real image.

---

## 5. Deploy AI Models

> **Models must be deployed manually** in Azure AI Foundry.
> Availability varies by region and tenant.

### 5.1 Open Azure AI Foundry

1. Go to [Azure AI Foundry](https://ai.azure.com/)
2. Select your project: `email-poc-test-project`
3. Navigate to **Deployments** > **+ Deploy model**

### 5.2 Minimum Viable Models

Deploy these **three models** (strictly required):

| Model | Deployment Name | Type | Data Zone | Regions (Hub/Project) | Purpose |
|-------|----------------|------|:---------:|----------------------|---------|
| **Phi-4** | `phi-4` | Serverless API | ✅ | eastus, eastus2, northcentralus, southcentralus, swedencentral, westus, westus3 | Email classification |
| **Mistral Document AI 2505** | `mistral-document-ai-2505` | Global Standard | ✅ (US + EU) | All regions (Global Standard) ¹ | OCR / PDF extraction |
| **text-embedding-3-small** | `text-embedding-3-small` | Standard (Global) | ✅ | All Global Standard regions ¹ | RAG embeddings |

> ¹ [Full Global Standard region table](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-models/concepts/models-sold-directly-by-azure?view=foundry-classic&tabs=global-standard-aoai,global-standard&pivots=azure-openai#global-standard-model-availability)

### 5.3 Recommended Optional Models

These models appear in the UI model selector and are used by various features.
Deploy them as **Global Standard** (Azure OpenAI) or **Serverless API** (partner) deployments in Azure AI Foundry with the exact deployment names below.

| Model | Deployment Name | Type | Data Zone | Regions (Hub/Project) | Purpose |
|-------|----------------|------|:---------:|----------------------|---------|
| GPT-4o-mini | `gpt-4o-mini` | Global Standard | ✅ | 20+ regions (all major) ¹ | Fallback classifier, vision, anonymization |
| GPT-4.1-nano | `gpt-4.1-nano` | Global Standard | ✅ | 20+ regions (all major) ¹ | Category assessment (fast, default) |
| GPT-5-nano | `gpt-5-nano` | Global Standard | ✅ | 20+ regions (all major) ¹ | Category assessment (alternative) |
| GPT-5-mini | `gpt-5-mini` | Global Standard | ✅ | 20+ regions (all major) ¹ | Higher-quality classification |
| GPT-5.2-chat | `gpt-5.2-chat` | Global Standard | ✅ | eastus2, swedencentral + more ¹ | RAG chat model (preview) |
| Kimi-K2.5 | `Kimi-K2.5` | Serverless (Moonshot AI) | ❌ | See Foundry model catalog ² | Multilingual classification |
| GPT-4o | `gpt-4o` | Global Standard | ✅ | 20+ regions (all major) ¹ | Premium classification (high cost) |

> ¹ [Full Global Standard region table](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-models/concepts/models-sold-directly-by-azure?view=foundry-classic&tabs=global-standard-aoai,global-standard&pivots=azure-openai#global-standard-model-availability)
> ² [Serverless API region availability](https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/deploy-models-serverless-availability?view=foundry-classic)
>
> **Note**: The UI dynamically fetches available deployments from `/api/admin/deployments`.
> Models not deployed will still appear as selectable options (from a hardcoded fallback list)
> but will fail at inference time. Deploy at minimum **GPT-4o-mini** and **GPT-4.1-nano**.

### 5.4 Verify Deployments

```powershell
# After generating secrets.env (Step 6), verify:
uv run python scripts/list_deployments.py
```

---

## 6. Local Development Setup

### 6.1 Generate secrets.env

This script discovers all Azure resources and writes a local config file:

```powershell
.\scripts\write_secrets_env.ps1 `
  -ResourceGroup "email-poc-test-rg" `
  -Prefix "email-poc-test" `
  -Force
```

### 6.2 Assign RBAC Roles for Local Development

Your Azure CLI user needs data-plane access to Storage, Service Bus, and Cosmos DB:

```powershell
.\scripts\assign_local_dev_roles.ps1 `
  -StorageAccountName "emailpoctestst" `
  -ServiceBusNamespace "email-poc-test-sbus" `
  -CosmosAccountName "email-poc-test-cosmos" `
  -ResourceGroup "email-poc-test-rg"
```

> Wait **2-5 minutes** for RBAC propagation before testing.

### 6.3 Install Python Dependencies

```powershell
uv sync --dev
```

### 6.4 Run Locally

```powershell
uv run uvicorn classymail.app:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## 6.5 Upload PDFs to Blob Storage

After infrastructure is deployed and RBAC is assigned, you can populate the
`pdf-inputs` container with PDF files. **Every `.pdf` uploaded triggers the
full classification pipeline automatically** (Event Grid → Service Bus →
Worker → OCR → Classification → Cosmos DB).

> **Important constraints:**
>
> - Only **`.pdf` files** are processed. ZIP, DOCX, images, etc. are **ignored** by Event Grid.
> - **Shared-key / SAS token access is disabled** on the storage account. All methods must use **Entra ID (Azure AD) authentication**.
> - You need the **Storage Blob Data Contributor** role on the storage account (assigned in [Step 6.2](#62-assign-rbac-roles-for-local-development)).
> - Each PDF triggers one pipeline run. Uploading 10 000 files = 10 000 pipeline runs. The Service Bus queue buffers messages and the Worker auto-scales via KEDA.

### Path structure

The API stores uploads under a dated prefix:

```
pdf-inputs/
  uploads/
    2026/
      02/
        17/
          a1b2c3d4-my-document.pdf
          e5f6a7b8-another-file.pdf
```

When uploading directly (bypassing the API), you can use any structure — the
only requirement is that each blob path **ends with `.pdf`** and is **unique**
(uploading to the same path overwrites the file and re-triggers the pipeline).

**Recommended convention for bulk uploads:**

```
pdf-inputs/uploads/{filename}.pdf
```

Or mirror the API date-based structure:

```
pdf-inputs/uploads/2026/02/17/{filename}.pdf
```

---

### Method 1: Web UI (small batches)

**Best for**: Quick tests with a few files.

1. Open the application URL (local: `http://localhost:8000`, or the Container App URL)
2. Navigate to **Upload**
3. Drag-and-drop or select PDF files
4. Click **Upload**

**Limits**: 10 files per upload, 10 MB per file.

---

### Method 2: Azure Portal — Storage Browser (moderate batches)

**Best for**: GUI upload of tens to hundreds of files without installing anything.

1. Go to [Azure Portal](https://portal.azure.com/)
2. Navigate to your **Storage Account** (e.g. `emailpoctestst`)
3. In the left menu, click **Storage browser** → **Blob containers** → **pdf-inputs**
4. Click **Upload** (top toolbar)
5. Click **Browse for files** and select your PDFs (multi-select supported)
6. Set **Upload to folder** to `uploads` (or `uploads/2026/02/17`)
7. Click **Upload**

> **Note**: The portal supports selecting hundreds of files at once. For 10K+
> files, use AzCopy ([Method 4](#method-4-azcopy-10k-files--fastest)) instead — the portal may time out.

---

### Method 3: Azure CLI — `az storage blob upload-batch` (scripted bulk)

**Best for**: Scripted, repeatable uploads of thousands of files from a local folder.

**PowerShell:**

```powershell
# Upload all PDFs from a local folder into the "uploads" path
az storage blob upload-batch `
  --account-name emailpoctestst `
  --destination pdf-inputs `
  --destination-path uploads `
  --source "C:\MyPDFs" `
  --pattern "*.pdf" `
  --auth-mode login `
  --overwrite false

# Upload from a subdirectory tree (preserves folder hierarchy)
az storage blob upload-batch `
  --account-name emailpoctestst `
  --destination pdf-inputs `
  --destination-path uploads `
  --source "C:\MyPDFs\batch-2026-02" `
  --pattern "**/*.pdf" `
  --auth-mode login `
  --overwrite false
```

**Bash (Linux / macOS):**

```bash
az storage blob upload-batch \
  --account-name emailpoctestst \
  --destination pdf-inputs \
  --destination-path uploads \
  --source ./my-pdfs \
  --pattern "*.pdf" \
  --auth-mode login \
  --overwrite false
```

> `--auth-mode login` is **required** (shared keys are disabled).
> `--overwrite false` prevents accidental re-processing of already-uploaded files.

---

### Method 4: AzCopy (10K+ files — fastest)

**Best for**: Very large datasets. AzCopy uses parallel transfers and is
significantly faster than the Azure CLI for thousands of files.

**Install**: [AzCopy download](https://learn.microsoft.com/en-us/azure/storage/common/storage-use-azcopy-v10#download-azcopy)

**PowerShell:**

```powershell
# 1. Authenticate with Entra ID (required — SAS/shared keys are disabled)
azcopy login --tenant-id <YOUR_TENANT_ID>

# 2a. Copy all PDFs from a local folder
azcopy copy "C:\MyPDFs\*.pdf" `
  "https://emailpoctestst.blob.core.windows.net/pdf-inputs/uploads/" `
  --recursive

# 2b. Copy a directory tree (only PDFs, preserves subfolders)
azcopy copy "C:\MyPDFs\*" `
  "https://emailpoctestst.blob.core.windows.net/pdf-inputs/uploads/" `
  --recursive `
  --include-pattern "*.pdf"

# 2c. Server-side copy from another Azure storage account (no local download)
azcopy copy `
  "https://sourceaccount.blob.core.windows.net/source-container/*" `
  "https://emailpoctestst.blob.core.windows.net/pdf-inputs/uploads/" `
  --recursive `
  --include-pattern "*.pdf"
```

**Bash (Linux / macOS):**

```bash
azcopy login --tenant-id <YOUR_TENANT_ID>

azcopy copy "./my-pdfs/*.pdf" \
  "https://emailpoctestst.blob.core.windows.net/pdf-inputs/uploads/" \
  --recursive
```

> **Server-side copy**: If your PDFs are already in another Azure storage
> account, use AzCopy account-to-account copy — data moves within Azure
> without downloading locally. You need **Storage Blob Data Reader** on the
> source and **Storage Blob Data Contributor** on the destination.

---

### Method 5: VS Code — Azure Storage Extension (IDE)

**Best for**: Developers who prefer working inside their editor.

1. Install the [Azure Storage extension](https://marketplace.visualstudio.com/items?itemName=ms-azuretools.vscode-azurestorage) for VS Code
2. Sign in to Azure in the sidebar (**Azure** icon → **Sign in**)
3. Expand **Storage Accounts** → your account (e.g. `emailpoctestst`)
4. Expand **Blob Containers** → **pdf-inputs**
5. Right-click **pdf-inputs** → **Create Virtual Directory** → name it `uploads`
6. Right-click **uploads** → **Upload Files...**
7. Select your PDF files or an entire folder
8. Files are uploaded with your Entra ID credentials automatically

---

### Method 6: Azure Storage Explorer (desktop GUI)

**Best for**: Moderate batches with drag-and-drop from a desktop application.

**Install**: [Azure Storage Explorer](https://azure.microsoft.com/en-us/products/storage/storage-explorer/)

1. Open Storage Explorer and sign in with your Azure account
2. Navigate to **Storage Accounts** → your account → **Blob Containers** → **pdf-inputs**
3. Click **New Folder** to create `uploads` (or the date-based path)
4. Navigate into the folder
5. Click **Upload** → **Upload Files** or **Upload Folder**
6. Select your PDFs and confirm

> Storage Explorer uses your Entra ID session automatically — no SAS tokens needed.

---

### Upload methods comparison

| Method | Best for | Volume | Auth | Requires install? |
|--------|----------|--------|------|--------------------|
| Web UI | Quick test | ≤ 10 files, 10 MB each | App session | No |
| Azure Portal | Moderate GUI upload | Hundreds | Entra ID | No |
| `az storage blob upload-batch` | Scripted bulk | Thousands | `--auth-mode login` | Azure CLI |
| **AzCopy** | **Large datasets** | **10K – millions** | `azcopy login` | AzCopy binary |
| VS Code extension | IDE workflow | Hundreds | Entra ID | VS Code extension |
| Storage Explorer | Desktop drag-and-drop | Hundreds | Entra ID | Desktop app |

---

### What happens after upload

Every `.pdf` uploaded to `pdf-inputs` triggers this automated flow:

1. **Event Grid** fires a `BlobCreated` event (filtered to `.pdf` / `.PDF`)
2. **Service Bus** receives the event in the `pdf-processing-queue`
3. **Worker** picks up the message and creates a `PROCESSING` record in Cosmos DB
4. **Pipeline** runs: PDF download → Mistral OCR → Phi-4 classification → embedding
5. **Cosmos DB** receives the final `PROCESSED` (or `REVIEW_REQUIRED`) record
6. **Result** appears in the UI

### Monitor progress

```powershell
# Check Service Bus queue depth (messages waiting to be processed)
az servicebus queue show `
  --namespace-name email-poc-test-sbus `
  --resource-group email-poc-test-rg `
  --name pdf-processing-queue `
  --query "countDetails.activeMessageCount"

# Count blobs in the container
az storage blob list `
  --account-name emailpoctestst `
  --container-name pdf-inputs `
  --auth-mode login `
  --query "length(@)"

# Check processed records via the API
curl https://<your-api-url>/api/emails?limit=1 | jq '.total'
```

> **Tip**: After a large bulk upload, monitor the queue depth. When it reaches
> **0** and all Cosmos records show `PROCESSED` or `REVIEW_REQUIRED`, the
> batch is complete.

---

## 7. Verify and Smoke Test

### 7.1 Run Verification Script

```powershell
.\scripts\verify-mvp-setup.ps1 -ResourceGroup "email-poc-test-rg"
```

This checks all 12 components: auth, resource group, managed identity, storage,
Cosmos DB, Service Bus, AI Foundry, Language service, Container Apps, RBAC,
API endpoints, and provides a summary.

### 7.2 End-to-End Test

1. Open the API Container App URL (from `terraform output` or the verify script)
2. Upload a PDF via the UI
3. Verify:
   - PDF appears in Blob Storage (`pdf-inputs` container)
   - Service Bus queue receives a message
   - Worker processes the PDF (check Container App logs)
   - Classification result appears in Cosmos DB (`emails` container)
   - Result is visible in the UI

### 7.3 Run Unit Tests

```powershell
uv run pytest
```

---

## 8. Troubleshooting

### Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `terraform apply` fails on policies | Tenant restricts custom policy creation | Set `tag_policy_enabled = false` and `security_cost_policy_enabled = false` in `terraform.tfvars` |
| Cosmos DB 403 Forbidden | RBAC not propagated yet | Wait 5-10 min, then restart Container Apps: `az containerapp restart --name email-poc-test-api -g email-poc-test-rg` |
| Mistral deployment fails | Model not available in region | Check model catalog in Azure AI Foundry; try `swedencentral` or `eastus`. See [Section 1.4](#14-verify-mistral-document-ai-availability) |
| Container App stuck "Provisioning" | Placeholder image or ACR pull failure | Verify `acr_name` and `acr_resource_group` in tfvars, ensure AcrPull role is assigned |
| Event Grid messages not arriving | Service Bus local auth disabled by tenant policy | Check `az servicebus namespace show --name <ns> -g <rg> --query disableLocalAuth` — must be `false` for Event Grid |
| Model not available in region | Regional model availability | Try `swedencentral`, `eastus`, or check [Azure AI model availability](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models) |
| `write_secrets_env.ps1` fails | Resources not found with prefix | Pass `-ResourceGroup` and `-Prefix` explicitly |
| Docker build fails with `python:3.12-slim` | Docker Hub blocked in corporate network | Use an internal mirror or build via ACR (`.\scripts\build_acr.ps1`) |
| `azapi_resource` 403 / IMDS error on `vector_cache` | See detailed fix below | **Pull latest code** then follow checklist below |

#### Fix: `ChainedTokenCredential` / IMDS 403 on azapi resources

The `azapi` provider v1.13 defaults `use_msi = true` (unlike `azurerm` which defaults to `false`).
On corporate networks where firewalls (FortiGuard, Zscaler) block the IMDS endpoint (`169.254.169.254`), this causes a 403 HTML response that crashes the credential chain.

**Checklist for the deployer:**

```powershell
# 1. Pull the latest code (the fix is already committed)
git pull origin main

# 2. Use the deploy script (sets ARM_USE_MSI=false automatically)
.\infra\deploy.ps1 -SubscriptionId "<SUBSCRIPTION_ID>"
# Linux/macOS: bash infra/deploy.sh --subscription-id <SUBSCRIPTION_ID>

# -- OR if deploying manually --

# 2b. Set environment variables BEFORE terraform commands:
$env:ARM_USE_MSI  = "false"   # PowerShell
$env:ARM_USE_OIDC = "false"
# export ARM_USE_MSI="false"  # bash
# export ARM_USE_OIDC="false"

# 3. Delete cached providers and re-initialize
Remove-Item -Recurse -Force infra\.terraform -ErrorAction SilentlyContinue
Remove-Item -Force infra\.terraform.lock.hcl -ErrorAction SilentlyContinue
terraform -chdir=infra init -upgrade

# 4. Verify Azure CLI login is active:
az account show

# 5. Re-run plan/apply
terraform -chdir=infra plan -out=tfplan
terraform -chdir=infra apply tfplan
```

**Required RBAC**: Owner (or Contributor) on the **resource group** is sufficient.
Subscription-level Owner is NOT required.
`skip_provider_registration = true` is set in both providers so no subscription-level
resource-provider registration is attempted.

### Useful Commands

```powershell
# Check Container App logs
az containerapp logs show --name email-poc-test-api -g email-poc-test-rg --follow

# Check Worker logs
az containerapp logs show --name email-poc-test-worker -g email-poc-test-rg --follow

# Restart Container Apps after config changes
az containerapp restart --name email-poc-test-api -g email-poc-test-rg
az containerapp restart --name email-poc-test-worker -g email-poc-test-rg

# Update Cosmos DB firewall with your IP + Container App IPs
.\scripts\update_cosmos_firewall.ps1 -ResourceGroup "email-poc-test-rg" -IncludeLocalIP

# Check all Terraform state
terraform -chdir=infra show
```

---

## 9. Cleanup / Teardown

### Destroy All Infrastructure

```powershell
terraform -chdir=infra destroy -var "subscription_id=<SUBSCRIPTION_ID>"
```

### Delete ACR (if created in Step 2.2)

```powershell
az group delete --name rg-acr-shared --yes --no-wait
```

### Remove Local Files

```powershell
Remove-Item -Path secrets.env -ErrorAction SilentlyContinue
Remove-Item -Path infra/terraform.tfvars -ErrorAction SilentlyContinue
Remove-Item -Path infra/tfplan -ErrorAction SilentlyContinue
Remove-Item -Path infra/terraform.tfstate -ErrorAction SilentlyContinue
Remove-Item -Path infra/terraform.tfstate.backup -ErrorAction SilentlyContinue
Remove-Item -Recurse -Path infra/.terraform -ErrorAction SilentlyContinue
```

---

## Architecture Reference

```
flowchart TD
    A["API + UI - Container App"] --> B["Service Bus Queue"]
    A --> C["Blob Storage: pdf-inputs"]
    C --> D["Event Grid"] --> B
    B --> E["Worker - Container App"]
    E --> F["Mistral OCR"]
    E --> G["Phi-4 Classification"]
    E --> H["Cosmos DB: emails"]
    A --> H
    A --> I["text-embedding-3-small"]
```

For the full architecture, see `#docs/ARCHITECTURE.md`.

---

## Quick Reference Card

| What | Command |
|------|---------|
| Deploy infra | `.\infra\deploy.ps1 -TenantId <T> -SubscriptionId <S>` |
| Build + push image | `.\scripts\build_acr.ps1 -AcrName <acr> -Tag v1` |
| Generate secrets.env | `.\scripts\write_secrets_env.ps1 -ResourceGroup <rg> -Prefix <pfx> -Force` |
| Assign local RBAC | `.\scripts\assign_local_dev_roles.ps1 -ResourceGroup <rg> ...` |
| Verify setup | `.\scripts\verify-mvp-setup.ps1 -ResourceGroup <rg>` |
| Run locally | `uv run uvicorn classymail.app:app --reload --port 8000` |
| Run tests | `uv run pytest` |
| Destroy all | `terraform -chdir=infra destroy -var "subscription_id=<S>"` |
