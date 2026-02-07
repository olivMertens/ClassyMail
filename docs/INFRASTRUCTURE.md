# Infrastructure & Deployment Guide

> 🏗️ **Comprehensive Guide**: Terraform provisioning, resource configuration, Event Grid setup, RBAC, and network strategy.
>
> 📌 **Note**: This project originated as a POC but has evolved into a production-ready MVP with enterprise-grade features including vector search, PII detection, multi-model classification, and comprehensive monitoring.

## Table of Contents

1. [Overview](#overview)
2. [G2S Mandatory Tags](#g2s-mandatory-tags)
3. [Terraform Deployment](#terraform-deployment)
4. [Resource Configuration](#resource-configuration)
5. [Event Grid Configuration](#event-grid-configuration)
6. [RBAC & Managed Identity](#rbac--managed-identity)
7. [Network Strategy](#network-strategy)
8. [Verification & Troubleshooting](#verification--troubleshooting)

---

## Overview

Terraform provisions the complete Azure infrastructure:
- Storage Account + container `pdf-inputs`
- Event Grid → Service Bus queue
- Service Bus namespace + queue
- Cosmos DB (serverless) + database/container
- Azure AI Foundry / Azure AI Services + project
- **Optional: Azure AI Language** service for native PII detection (TextAnalytics kind, Standard SKU)
- User-Assigned Managed Identity + RBAC roles
- **Required AI Model Deployments** (see below)

---

## G2S Mandatory Tags

🏷️ **Toutes les ressources Azure déployées sont automatiquement tagées avec les standards G2S :**

| Tag | Valeur | Description |
|-----|--------|-------------|
| `cp-code-sa` | `devin` | Code service applicatif - Projet DEVIN (email classification MVP) |
| `cp-deploiement` | `terraform` | Méthode de déploiement (Infrastructure as Code) |
| `cp-environnement` | `d` | Environnement : **d** (développement), **t** (test), **p** (production) |
| `cp-proprietaire` | `g2s-dtpo-iaf` | Propriétaire de la ressource (Direction Technique - Plateforme & Outils) |
| `cp-responsable` | `g2s-dtpo-iaf` | Responsable technique de la ressource |
| `cp-supervision` | `oui` | Activer la supervision/monitoring (Application Insights, Azure Monitor) |

### Application des Tags

**1. Via Terraform** (`infra/main.tf`):
```terraform
locals {
  common_tags = {
    "cp-code-sa"      = "devin"
    "cp-deploiement"  = "terraform"
    "cp-environnement" = "d"
    "cp-proprietaire" = "g2s-dtpo-iaf"
    "cp-responsable"  = "g2s-dtpo-iaf"
    "cp-supervision"  = "oui"
  }
}

# Tags propagés à toutes les ressources via `tags = local.common_tags`
```

**2. Via Azure Policy** (`infra/policy.tf`):
- **Policy Definition**: `add-g2s-mandatory-tags`
- **Scope**: Resource Group ou Subscription (configurable via `var.tag_policy_scope`)
- **Action**: Ajout automatique des tags manquants sur les ressources existantes
- **Remediation**: Tâche de réparation pour appliquer les tags aux ressources pré-existantes

**Vérification des tags :**
```bash
# Lister les tags sur une ressource
az resource show --ids <RESOURCE_ID> --query tags -o json

# Lister toutes les ressources avec un tag spécifique
az resource list --tag "cp-code-sa=devin" --query "[].{name:name, type:type}" -o table
```

---

## Required AI Model Deployments

**CRITICAL:** The following model deployments MUST exist in your Azure AI Foundry / Azure OpenAI resource for the MVP to function:

| Model | Deployment Name | Environment Variable | Purpose | Required |
|-------|----------------|---------------------|---------|----------|
| **Mistral Document AI 2505** | `mistral-document-ai-2505` | `MISTRAL_DEPLOYMENT` | OCR + Vision extraction | ✅ MANDATORY |
| **Phi-4** | `Phi-4` | `PHI_DEPLOYMENT` | Primary classification (8K) | ✅ MANDATORY |
| **GPT-4o-mini** | `gpt-4o-mini` | `PHI_FALLBACK_DEPLOYMENT` | Fallback classification (120K) + PII detection (LLM mode) | ✅ MANDATORY |
| **text-embedding-3-small** | `text-embedding-3-small` | `EMBEDDING_DEPLOYMENT` | Vector embeddings (RAG) | ✅ MANDATORY |
| **GPT-5.2-chat** | `gpt-5.2-chat` | `CHAT_DEPLOYMENT` | Chatbot conversational AI | ⚠️ RECOMMENDED |
| **GPT-5-nano** | `gpt-5-nano` | *(hardcoded in category_assessment.py)* | Category assessment AI | ⚠️ RECOMMENDED |

---

## Optional Azure Services

### Azure AI Language (PII Detection)

**Purpose:** Native PII/PHI detection with 43+ predefined entity categories (SSN, passport, credit cards, etc.)

**Deployment:**
```terraform
# In terraform.tfvars
deploy_language_service = true  # Default: false
```

**Configuration:**
- **Kind:** `TextAnalytics` (Cognitive Services)
- **SKU:** `S` (Standard)
- **Authentication:** Managed Identity (RBAC) - `Cognitive Services Language Reader` role
- **Fallback:** API key via `AZURE_LANGUAGE_KEY` environment variable (optional)

**Usage:** Settings > Processing > Detection Method → "Azure AI Language Service" or "Both (Hybrid)"

**Cost:** ~€1.00 per 1,000 text records (1 email = 1 record) → ~€0.001/email

**When to Use:**
- ✅ Compliance requirements (GDPR, HIPAA, industry regulatory)
- ✅ Need for 43+ predefined PII categories
- ✅ Budget allows (~€0.001/email fixed cost)
- ❌ Cost-sensitive deployments (use LLM-based method instead)

---

## Required AI Model Deployments (continued)

**Deployment Instructions:**

1. **Navigate to Azure AI Foundry**: https://ai.azure.com/
2. **Select your AI Hub**: `<your-project>-aihub` (created by Terraform)
3. **Go to Deployments** → **+ Create Deployment**
4. **Deploy each model** with the EXACT deployment names shown above

**Why Exact Names Matter:**
- The application code references these deployment names directly
- Mismatch between deployment name and environment variable will cause 404 errors
- Default configuration assumes standard naming convention (e.g., `Phi-4`, `gpt-4o-mini`)

**Terraform Note:**
- Terraform creates the AI Foundry account and project
- Model deployments must be created manually via Azure Portal/CLI (not yet supported in azurerm provider)
- Future enhancement: Use `azapi_resource` to automate model deployments

**Verification:**
```bash
# List all deployments in your AI Foundry project
az cognitiveservices account deployment list \
  --name <ai-foundry-account-name> \
  --resource-group <resource-group> \
  --query "[].{Name:name, Model:properties.model.name, Version:properties.model.version}" \
  --output table
```

---

## Terraform Deployment

### Quick Start (Windows)

```powershell
.\infra\deploy.ps1
```

Target specific tenant/subscription:

```powershell
.\infra\deploy.ps1 -TenantId <TENANT_ID> -SubscriptionId <SUBSCRIPTION_ID>
```

### Manual Deployment

```powershell
# Login
az login
# Multi-tenant: az login --tenant <TENANT_ID>

# Set subscription
az account set --subscription <SUBSCRIPTION_ID>

# Initialize Terraform
terraform -chdir=infra init -upgrade

# Plan
terraform -chdir=infra plan -var "subscription_id=<SUBSCRIPTION_ID>" -out tfplan

# Apply
terraform -chdir=infra apply tfplan
```

### Why Pass `subscription_id`?

Some AzureRM provider versions don't auto-detect subscription from Azure CLI. The `deploy.ps1` script detects the active subscription (`az account show`) and passes it to Terraform.

### Repository Hygiene

**Commit:**
- `main.tf`
- `.terraform.lock.hcl`
- `deploy.ps1`
- `terraform.tfvars.example`

**Do NOT commit:**
- `.terraform/`
- `terraform.tfstate*`
- `tfplan`
- `terraform.tfvars` (real values)

---

## Resource Configuration

### Mandatory Environment Variables per Service

#### API Service (`-api`)

| Variable | Description | Example |
|----------|-------------|---------|
| `AZURE_CLIENT_ID` | Managed Identity Client ID | `3ae24af5-97c6-437f-a4d2-521fbd5524d4` |
| `AZURE_SERVICE_BUS_FQDN` | Service Bus Hostname | `email-poc-sbus.servicebus.windows.net` |
| `AZURE_SERVICE_BUS_QUEUE` | Queue Name | `pdf-processing-queue` |
| `AZURE_STORAGE_ACCOUNT_URL` | Blob Storage Endpoint | `https://emailpocst.blob.core.windows.net` |
| `AZURE_STORAGE_CONTAINER` | Blob Container | `pdf-inputs` |
| `AZURE_COSMOS_ENDPOINT` | Cosmos DB URI | `https://email-poc-cosmos.documents.azure.com:443/` |
| `AZURE_COSMOS_DB` | Database Name | `emailsdb` |
| `AZURE_COSMOS_CONTAINER` | Container Name | `emails` |
| `AZURE_AI_ENDPOINT` | Azure AI Foundry Endpoint | `https://email-poc-aifoundry.cognitiveservices.azure.com/` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights telemetry | `InstrumentationKey=...;IngestionEndpoint=...` |
| `LOG_ANALYTICS_WORKSPACE_ID` | Log Analytics Workspace ID | `9f225d73-351d-471e-9371-c15d265e9bd4` |
| `OTEL_SERVICE_NAME` | OpenTelemetry service name | `classymail-api` |
| `ENABLE_WORKER` | Enable background processing? | `false` (API only) |
| `ORGANIZATION_NAME` | UI branding/destination name | `G2S`, `Groupama`, or `ClassyMail` (default) |
| `UI_SHOW_INFO_MODAL` | Show info modal button | `true` (default) |
| `UI_SHOW_DEVELOPER_TAB` | Show developer tab | `true` (default) |
| `MAX_UPLOAD_SIZE` | Max upload size (MB) | `10` (default) |

**⚠️ Security Note:** Do NOT set `AZURE_AI_KEY` in production. Use Managed Identity authentication (`DefaultAzureCredential`) with the `Cognitive Services User` role.

#### Worker Service (`-worker`)

| Variable | Description | Example |
|----------|-------------|---------|
| **`ENABLE_WORKER`** | **MANDATORY** | `true` |
| `AZURE_CLIENT_ID` | Managed Identity Client ID | `3ae24af5-97c6-437f-a4d2-521fbd5524d4` |
| `AZURE_SERVICE_BUS_FQDN` | Service Bus Hostname | `email-poc-sbus.servicebus.windows.net` |
| `AZURE_SERVICE_BUS_QUEUE` | Queue Name | `pdf-processing-queue` |
| `AZURE_STORAGE_ACCOUNT_URL` | Blob Storage Endpoint | `https://emailpocst.blob.core.windows.net` |
| `AZURE_STORAGE_CONTAINER` | Blob Container | `pdf-inputs` |
| `AZURE_COSMOS_ENDPOINT` | Cosmos DB URI | `https://email-poc-cosmos.documents.azure.com:443/` |
| `AZURE_COSMOS_DB` | Database Name | `emailsdb` |
| `AZURE_COSMOS_CONTAINER` | Container Name | `emails` |
| `AZURE_AI_ENDPOINT` | Azure AI Foundry Endpoint | `https://email-poc-aifoundry.cognitiveservices.azure.com/` |
| `PHI_DEPLOYMENT` | Classification Model Deployment Name | `Phi-4` |
| `MISTRAL_DEPLOYMENT` | OCR Model Deployment | `mistral-document-ai-2505` |
| `MISTRAL_MODE` | Mistral API mode | `maas` |
| `EMBEDDING_DEPLOYMENT` | Embeddings Model Deployment | `text-embedding-3-small` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights telemetry | `InstrumentationKey=...;IngestionEndpoint=...` |
| `LOG_ANALYTICS_WORKSPACE_ID` | Log Analytics Workspace ID | `9f225d73-351d-471e-9371-c15d265e9bd4` |
| `OTEL_SERVICE_NAME` | OpenTelemetry service name | `classymail-worker` |

**⚠️ Security Note:** Do NOT set `AZURE_AI_KEY` in production. Use Managed Identity authentication (`DefaultAzureCredential`) with the `Cognitive Services User` role.

**💡 Worker Configuration:** The Worker container does NOT need UI configuration variables (`UI_SHOW_INFO_MODAL`, `UI_SHOW_DEVELOPER_TAB`, `MAX_UPLOAD_SIZE`, `ORGANIZATION_NAME`) since it doesn't serve the web interface.

> **Note:** Keep `MISTRAL_DEPLOYMENT` consistent across Terraform, config defaults, and AI Foundry deployment (`mistral-document-ai-2505`).

### Chatbot Variables (Injected into Container Apps)

- **API** Container App receives:
  - `CHAT_ENDPOINT` = AI Foundry endpoint
  - `CHAT_DEPLOYMENT` = `gpt-5.2-chat`
  - `CHAT_API_VERSION` = `2024-08-01-preview`
- **Worker** does not need chatbot variables
- **Optional:** `COSMOS_QUERY_MAX_LIMIT` (default `20`)

### Images & Container Registry

- `variable "container_image"` **required**: Public image (e.g., `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest`) or private (e.g., `<monacr>.azurecr.io/ClassyMail-agent:tag`)
- ACR **not required** for public images
- ACR private: set `acr_name` (+ `acr_resource_group` if different) for Terraform to assign **AcrPull** role to managed identity

---

## Event Grid Configuration

### Architecture Overview

The connection between Blob Storage and Service Bus uses **Azure Event Grid**:

```mermaid
flowchart LR
    Blob[Blob Storage: pdf-inputs] -->|BlobCreated Event| EG[Event Grid System Topic]
    EG -->|Filtered Subscription - .pdf only| SB[Service Bus Queue: pdf-processing-queue]
    SB -->|KEDA Scaler - Message count| Worker[Worker Container App]
```

### Required Terraform Resources

#### 1. Event Grid System Topic

```hcl
resource "azurerm_eventgrid_system_topic" "storage_events" {
  name                   = "evgt-${var.project_name}-storage"
  resource_group_name    = azurerm_resource_group.rg.name
  location               = azurerm_resource_group.rg.location
  source_arm_resource_id = azurerm_storage_account.storage.id
  topic_type             = "Microsoft.Storage.StorageAccounts"
}
```

#### 2. Event Grid Subscription (Routes .pdf to Service Bus)

```hcl
resource "azurerm_eventgrid_event_subscription" "blob_to_servicebus" {
  name  = "evgs-blob-to-sb"
  scope = azurerm_eventgrid_system_topic.storage_events.id

  service_bus_queue_endpoint_id = azurerm_servicebus_queue.pdf_queue.id

  included_event_types = ["Microsoft.Storage.BlobCreated"]

  subject_filter {
    subject_ends_with = ".pdf"
  }

  subject_filter {
    subject_ends_with = ".PDF"
  }
}
```

#### 3. Service Bus Local Authentication (Critical)

```hcl
resource "azurerm_servicebus_namespace" "sb" {
  name                = "sb-${var.project_name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "Standard"

  local_auth_enabled = true  # ← REQUIRED for Event Grid delivery
}
```

**Why?** Event Grid uses SAS (Shared Access Signature) authentication. If `local_auth_enabled = false`, messages are silently dropped.

---

## RBAC & Managed Identity

### Deployed Configuration (email-poc-rg)

**Managed Identity Details:**
- **Name**: `email-poc-id`
- **Client ID**: `3ae24af5-97c6-437f-a4d2-521fbd5524d4`
- **Principal ID**: `fdf02fa5-2cd5-42f9-9b78-5cb7905d94d0`
- **Resource Group**: `email-poc-rg`
- **Location**: `swedencentral`

### Role Assignment Matrix (Verified)

The Container Apps use a **User-Assigned Managed Identity** with the following role assignments verified in Azure:

| Azure Resource | Role Name | Role Definition ID | Scope | Status |
|----------------|-----------|-------------------|-------|--------|
| **Blob Storage** | Storage Blob Data Contributor | `ba92f5b4-2d11-453d-a403-e96b0029c9fe` | Storage Account (`emailpocst`) | ✅ Verified |
| **Blob Storage** | Storage Blob Data Reader | `2a2b9908-6ea1-4ae2-8e65-a410df84e7d1` | Storage Account (`emailpocst`) | ✅ Verified |
| **Service Bus** | Azure Service Bus Data Sender | `69a216fc-b8fb-44d8-bc22-1f3c2cd27a39` | Service Bus Namespace (`email-poc-sbus`) | ✅ Verified |
| **Service Bus** | Azure Service Bus Data Receiver | `4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0` | Service Bus Namespace (`email-poc-sbus`) | ✅ Verified |
| **Cosmos DB** | Cosmos DB Built-in Data Contributor | `00000000-0000-0000-0000-000000000002` | Database Scope (`/dbs/emailsdb`) | ✅ Verified |
| **AI Foundry** | Cognitive Services User | `a97b65f3-24c7-4388-baec-2e87135dc908` | AI Services Account (`email-poc-aifoundry`) | ✅ Verified |
| **Container Registry** | AcrPull | `7f951dda-4ed3-4680-a7ca-43fe172d538d` | ACR (`emailpocacrxr0bjv`) | ✅ Verified |

### Terraform Configuration

```hcl
# Storage Contributor
resource "azurerm_role_assignment" "storage_contributor" {
  scope                = azurerm_storage_account.storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.aca_identity.principal_id
}

# Service Bus Sender
resource "azurerm_role_assignment" "servicebus_sender" {
  scope                = azurerm_servicebus_namespace.sb.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_user_assigned_identity.aca_identity.principal_id
}

# Service Bus Receiver
resource "azurerm_role_assignment" "servicebus_receiver" {
  scope                = azurerm_servicebus_namespace.sb.id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = azurerm_user_assigned_identity.aca_identity.principal_id
}

# Cosmos DB Contributor (SQL RBAC)
resource "azurerm_cosmosdb_sql_role_assignment" "cosmos_contributor" {
  resource_group_name = azurerm_resource_group.rg.name
  account_name        = azurerm_cosmosdb_account.cosmos.name
  role_definition_id  = "${azurerm_cosmosdb_account.cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.aca_identity.principal_id
  scope               = azurerm_cosmosdb_account.cosmos.id
}

# AI Foundry User
resource "azurerm_role_assignment" "ai_user" {
  scope                = azurerm_cognitive_account.ai.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.aca_identity.principal_id
}
```

### Cosmos DB RBAC (Data-Plane) - Account Scope Assignment

This project uses **Cosmos SQL data-plane RBAC** (`azurerm_cosmosdb_sql_role_assignment`).

**Important:** The Cosmos DB role assignment is configured at the **Account scope** (`/`), not at the database scope.
This is required because the Azure Cosmos DB Python SDK performs a `readMetadata` operation on the account before accessing the database, which requires account-level permissions.

**Deployed Configuration:**
```plaintext
Role: Custom App Role (readMetadata + data actions)
Scope: /subscriptions/.../resourceGroups/email-poc-rg/providers/Microsoft.DocumentDB/databaseAccounts/email-poc-cosmos
```

**Verification Command:**
```bash
az cosmosdb sql role assignment list \
  --account-name email-poc-cosmos \
  --resource-group email-poc-rg \
  --query "[?principalId=='<managed-identity-principal-id>'].roleDefinitionId"

## Network Strategy

### Current (Production MVP)

- All services accessible via public endpoints
- Cosmos DB: Firewall allows `0.0.0.0` (Azure services)
- Container Apps: External ingress enabled

This is the production-ready MVP configuration, designed for seamless scalability and enterprise deployment. For additional security hardening, consider the Private VNet strategy below.

### Production (Private VNet)

**Objective:** Isolate system from Internet (VNet Injection)

**Required Changes:**

1. **Virtual Network (VNet)**: Create VNet with subnet delegated to `Microsoft.App/environments`

2. **ACA VNet Injection**: Deploy Container App Environment in **Internal** mode

3. **Private Endpoints (PE)**:
   - Disable public access on Cosmos DB, Storage, Service Bus, AI Foundry
   - Create Private Endpoint for each PaaS service
   - Configure **Private DNS** zones (`privatelink.documents.azure.com`, `privatelink.blob.core.windows.net`, etc.)

4. **Firewall Exceptions**: Remove Cosmos DB `0.0.0.0` exception

**Outcome:** Traffic stays within Azure backbone via Private Endpoints.

---

## Verification & Troubleshooting

### Check Event Grid Subscription

```bash
az eventgrid event-subscription list \
  --source-resource-id $(az storage account show -n <storage-account-name> -g <resource-group> --query id -o tsv)
```

### Test Blob Upload → Queue Message

```bash
# Upload test file
az storage blob upload \
  --account-name <storage-account-name> \
  --container-name pdf-inputs \
  --name test.pdf \
  --file ./test.pdf \
  --auth-mode login

# Wait ~30 seconds, check queue
az servicebus queue show \
  --resource-group <resource-group> \
  --namespace-name <servicebus-namespace> \
  --name pdf-processing-queue \
  --query "countDetails.activeMessageCount"
```

If count > 0, Event Grid → Service Bus is working.

### Verify Managed Identity Roles

```bash
az role assignment list \
  --assignee <managed-identity-client-id> \
  --all \
  --query "[].{Role:roleDefinitionName, Scope:scope}" \
  --output table
```

### Troubleshooting: Messages not arriving in Service Bus

**Causes:**
1. `local_auth_enabled = false` on Service Bus
2. Event Grid subscription filter mismatch
3. Event Grid System Topic misconfigured

**Fix:**
```bash
az servicebus namespace update \
  --resource-group <rg> \
  --name <namespace> \
  --enable-local-auth true
```

### Troubleshooting: Worker not picking up messages

**Causes:**
1. `ENABLE_WORKER` not set to `true`
2. KEDA scaler not configured
3. Managed Identity missing "Azure Service Bus Data Receiver" role

**Fix:**
```bash
az containerapp show \
  --name email-poc-worker \
  --resource-group <rg> \
  --query "properties.template.containers[0].env[?name=='ENABLE_WORKER'].value"
```

### Troubleshooting: Cosmos DB "Unauthorized"

**Cause:** Managed Identity missing "Cosmos DB Built-in Data Contributor" role

**Fix:**
```bash
az cosmosdb sql role assignment create \
  --account-name <cosmos-account> \
  --resource-group <rg> \
  --role-definition-id 00000000-0000-0000-0000-000000000002 \
  --principal-id <managed-identity-principal-id> \
  --scope "/dbs/emailsdb"
```

### Troubleshooting: Cosmos DB "Request originated from IP ... through public internet"

**Error:**
```
(Forbidden) Request originated from IP 4.225.209.140 through public internet.
This is blocked by your Cosmos DB account firewall settings.
```

**Root Cause:**

This error occurs when **both** of the following conditions are met:
1. **Terraform Drift**: `publicNetworkAccess` is set to `Disabled` in Azure, but Terraform configuration expects `Enabled`
2. **Container App Outbound IP**: The Container App's outbound IP (`4.225.209.140`) is not in the firewall allowlist

**Critical Finding:**
Even with `ip_range_filter = ["0.0.0.0"]` (Allow Azure Services), if `publicNetworkAccess = Disabled`, **ALL connections are blocked**.

**Verification:**
```bash
# Check current public network access status
az cosmosdb show --name email-poc-cosmos --resource-group email-poc-rg \
  --query "{publicAccess:publicNetworkAccess, ipRules:ipRules}" -o json

# Should show:
# "publicAccess": "Enabled"
# "ipRules": [{"ipAddressOrRange": "0.0.0.0"}, ...]

# Check Container App outbound IP
az containerapp show --name email-poc-api --resource-group email-poc-rg \
  --query properties.outboundIpAddresses -o json
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
# Verify Terraform configuration (should already be correct)
grep -A2 "public_network_access_enabled" infra/main.tf
# Expected: public_network_access_enabled = true

# Apply Terraform to fix drift
cd infra
terraform plan -out=tfplan
terraform apply tfplan
```

**Why This Happens:**
Someone may have manually disabled public network access via Azure Portal or CLI, causing Terraform state drift. Always use `terraform apply` after manual changes to restore the infrastructure to the desired state.

---

## See Also

- [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) - Local setup & testing
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [RBAC_AUDIT.md](RBAC_AUDIT.md) - RBAC troubleshooting
- [CLI_SETUP.md](CLI_SETUP.md) - CLI commands reference
