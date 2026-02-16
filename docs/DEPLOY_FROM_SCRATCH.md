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

### 1.4 Accept Mistral MaaS Marketplace Terms

> **This step cannot be scripted — it must be done in the Azure Portal.**

1. Go to [Azure Marketplace](https://portal.azure.com/#view/Microsoft_Azure_Marketplace/MarketplaceOffersBlade)
2. Search for **"Mistral"**
3. Find **Mistral Document AI** and click **"Get It Now"** / **"Subscribe"**
4. Accept the terms and conditions

If you skip this step, Mistral OCR model deployment will fail with a Marketplace terms error.

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
2. Run `terraform init -upgrade`
3. Run `terraform plan` and show the plan
4. Ask for confirmation before `terraform apply`

### 3.2 Manual (for transparency)

```powershell
az login --tenant <TENANT_ID>
az account set --subscription <SUBSCRIPTION_ID>

terraform -chdir=infra init -upgrade
terraform -chdir=infra plan -var "subscription_id=<SUBSCRIPTION_ID>" -out tfplan
terraform -chdir=infra apply tfplan
```

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
$IMAGE = "emailpoctestacr.azurecr.io/ClassyMail-agent:v1"
az acr login --name emailpoctestacr
docker build -t $IMAGE .
docker push $IMAGE
```

### 4.4 Update Terraform with Real Image

Edit `infra/terraform.tfvars`:

```hcl
container_image = "emailpoctestacr.azurecr.io/ClassyMail-agent:v1"
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

| Model | Deployment Name | Type | Purpose |
|-------|----------------|------|---------|
| **Phi-4** | `phi-4` | Standard (Global) | Email classification |
| **Mistral Document AI 2505** | `mistral-document-ai-2505` | Serverless (MaaS) | OCR / PDF extraction |
| **text-embedding-3-small** | `text-embedding-3-small` | Standard (Global) | RAG embeddings |

### 5.3 Recommended Optional Models

| Model | Deployment Name | Type | Purpose |
|-------|----------------|------|---------|
| GPT-4o-mini | `gpt-4o-mini` | Standard | Fallback classifier (long context) |
| GPT-4.1-nano / GPT-5-nano | `gpt-4o-mini` | Standard | Vision / anonymization |
| GPT-5.2-chat | `gpt-5.2-chat` | Standard | RAG chat model |

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
| Mistral deployment fails | Marketplace terms not accepted | See [Section 1.4](#14-accept-mistral-maas-marketplace-terms) |
| Container App stuck "Provisioning" | Placeholder image or ACR pull failure | Verify `acr_name` and `acr_resource_group` in tfvars, ensure AcrPull role is assigned |
| Event Grid messages not arriving | Service Bus local auth disabled by tenant policy | Check `az servicebus namespace show --name <ns> -g <rg> --query disableLocalAuth` — must be `false` for Event Grid |
| Model not available in region | Regional model availability | Try `swedencentral`, `eastus`, or check [Azure AI model availability](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models) |
| `write_secrets_env.ps1` fails | Resources not found with prefix | Pass `-ResourceGroup` and `-Prefix` explicitly |
| Docker build fails with `python:3.12-slim` | Docker Hub blocked in corporate network | Use an internal mirror or build via ACR (`.\scripts\build_acr.ps1`) |

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
