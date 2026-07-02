# Microsoft AI Foundry Setup Guide



This guide explains how to configure Microsoft AI Foundry models for the ClassyMail MVP, including deployment creation, environment variable configuration, and Container Apps integration.



## Table of Contents

- [Prerequisites](#prerequisites)

- [Model Deployments Required](#model-deployments-required)

- [Step-by-Step Setup](#step-by-step-setup)

- [Environment Variable Configuration](#environment-variable-configuration)

- [Container Apps Configuration](#container-apps-configuration)

- [Validation & Testing](#validation--testing)

- [Troubleshooting](#troubleshooting)



---



## Prerequisites



Before starting, ensure you have:



1. **Azure Subscription** with access to:

   - Microsoft AI Foundry (formerly Azure OpenAI Service)

   - Azure Container Apps

   - Managed Identity configured with proper RBAC



2. **Azure CLI** installed and authenticated:

   ```bash

   az login

   az account set --subscription "<your-subscription-id>"

   ```



3. **Resource Group** created (e.g., `email-mvp-rg`)



4. **Microsoft AI Foundry Resource** deployed:

   - SKU: Standard (S0)

   - Region: Sweden Central (recommended for data residency)



---



## Model Deployments Required



The ClassyMail MVP requires the following model deployments in Microsoft AI Foundry:



### 1. **Phi-4 (Primary Classification)**

- **Model**: `Phi-4` (Microsoft)

- **Deployment Name** (recommended): `phi-4`

- **Purpose**: Primary email classification model

- **Tokens Per Minute Rate (TPM)**: 50,000+ recommended

- **Environment Variable**: `PHI_DEPLOYMENT`



### 2. **GPT-4.1-mini Fallback / Anonymizer / Vision** (Optional but recommended)

- **Model**: `gpt-4.1-mini` (OpenAI, GA, retires 2027-10-14)

- **Deployment Name** (recommended): `gpt-4.1-mini`

- **Purpose**: Fallback classification, anonymization, and vision tasks

- **TPM**: 25,000+

- **Environment Variable**: `PHI_FALLBACK_DEPLOYMENT`



### 3. **Mistral Document AI (OCR & Document Understanding)**

- **Model**: `Mistral Document AI 2512` (serverless MaaS)

- **Deployment Name** (required): `mistral-document-ai-2512`

- **Purpose**: OCR extraction from PDFs and document structure analysis

- **Mode**: Serverless (Models as a Service)

- **Environment Variable**: `MISTRAL_DEPLOYMENT`

- ?? **CRITICAL**: Deployment name MUST be `mistral-document-ai-2512` exactly. Typos (e.g., `mistral-ocr-2505`) will cause **HTTP 500 errors** during OCR processing.



### 4. **text-embedding-3-small (Vector Embeddings)**

- **Model**: `text-embedding-3-small` (OpenAI)

- **Deployment Name** (recommended): `text-embedding-3-small`

- **Purpose**: Vector embeddings for RAG chatbot search

- **TPM**: 30,000+

- **Environment Variable**: `EMBEDDING_DEPLOYMENT`



### 5. **GPT Model (Chat & Advanced Classification)**

- **Model**: `gpt-5.1` (reasoning model, GA, retires 2027-05-15)

- **Deployment Name** (recommended): `gpt-5.1`

- **Purpose**: Advanced reasoning, RAG chat

- **TPM**: 30,000+

- **Environment Variables**: `CHAT_DEPLOYMENT`, `GPT_DEPLOYMENT` (optional)



### 6. **GPT-4.1-nano (Category Assessment)** — Optional

- **Model**: `gpt-4.1-nano` (GA, retires 2027-10-14)

- **Deployment Name** (recommended): `gpt-4.1-nano`

- **Purpose**: AI-powered category quality analysis and advice

- **TPM**: 10,000+

- **Environment Variable**: Used via `GPT_DEPLOYMENT` fallback



---



## Step-by-Step Setup



### Step 1: Access Microsoft AI Foundry



1. Navigate to [Microsoft AI Foundry](https://ai.azure.com) or use Azure Portal

2. Select your AI Foundry resource (e.g., `email-mvp-aifoundry`)

3. Go to **Deployments** tab in the left sidebar



### Step 2: Deploy Phi-4 (Primary)



1. Click **+ Create new deployment**

2. Select model:

   - **Model family**: Phi

   - **Model**: Phi-4

   - **Version**: Latest stable

3. Configure deployment:

   - **Deployment name**: `phi-4`

   - **Deployment type**: Standard

   - **Tokens per Minute Rate Limit (TPM)**: 50,000

   - **Content filter**: Default (Moderate)

4. Click **Create**

5. Wait for deployment to complete (~2-5 minutes)



### Step 3: Deploy GPT-4.1-mini Fallback / Anonymizer / Vision



Create an Azure OpenAI deployment with:

- **Model**: `gpt-4.1-mini`

- **Version**: `2025-04-14`

- **Deployment name**: `gpt-4.1-mini`

- **TPM**: 25,000



### Step 4: Deploy Mistral Document AI (MaaS)



1. Click **+ Create new deployment**

2. Select **Model Catalog** ? **Mistral**

3. Find **Mistral Document AI 2512**

4. Choose **Serverless API (Models as a Service)**

5. Configure:

   - **Deployment name**: `mistral-document-ai-2512`

   - **Endpoint type**: Serverless

   - **Content filter**: Default

6. Accept terms and create

7. Rating: MaaS deployments are pay-per-use, no TPM allocation needed



### Step 5: Deploy GPT Model (Optional)



1. Click **+ Create new deployment**

2. Select model:

   - **Model family**: GPT

   - **Model**: `gpt-5.1`

   - **Version**: `2025-11-13`

3. Configure:

   - **Deployment name**: `gpt-5.1`

   - **TPM**: 30,000

   - **Content filter**: Default

4. Create deployment



### Step 6: Get AI Foundry Endpoint



1. In Microsoft AI Foundry resource, go to **Overview**

2. Copy the **Endpoint URL** (format: `https://<name>.cognitiveservices.azure.com/`)

3. Example: `https://classymail-aifoundry.cognitiveservices.azure.com/`



---



## Environment Variable Configuration



### Required Environment Variables for Container Apps



After deploying models, configure these environment variables in Azure Container Apps:



| Variable | Value | Example |

|----------|-------|---------|

| `AI_ENDPOINT` | Microsoft AI Foundry endpoint URL | `https://swedencentral.api.cognitive.microsoft.com/` |

| `AI_API_VERSION` | API version | `2024-08-01-preview` |

| `PHI_DEPLOYMENT` | Primary Phi-4 deployment name | `phi-4` |

| `PHI_FALLBACK_DEPLOYMENT` | Fallback/anonymizer/vision deployment name | `gpt-4.1-mini` |

| `MISTRAL_DEPLOYMENT` | Mistral deployment name | `mistral-document-ai-2512` |

| `MISTRAL_MODE` | Deployment mode | `maas` (for serverless MaaS) |

| `CHAT_DEPLOYMENT` | (Optional) Chat reasoning model deployment | `gpt-5.1` |

| `GPT_DEPLOYMENT` | (Optional) GPT deployment for advanced classification | `gpt-4.1` |



### How to Get Values



#### 1. AI_ENDPOINT

```bash

az cognitiveservices account show \

  --name <your-ai-foundry-name> \

  --resource-group <your-rg> \

  --query "properties.endpoint" \

  --output tsv

```



#### 2. Deployment Names

```bash

# List all deployments

az cognitiveservices account deployment list \

  --name <your-ai-foundry-name> \

  --resource-group <your-rg> \

  --query "[].{Name:name, Model:properties.model.name, Version:properties.model.version}" \

  --output table

```



Example output:

```

Name                           Model              Version

-----------------------------  -----------------  ------------

phi-4                          Phi-4              2024-10-01

gpt-4.1-mini                   gpt-4.1-mini       2025-04-14

mistral-document-ai-2512       Mistral-Large      2505

gpt-5.1                        gpt-5.1            2025-11-13

```



---



## Container Apps Configuration



### Option 1: Using Terraform (Recommended)



Update your `infra/terraform.tfvars`:



```hcl

# Microsoft AI Foundry Configuration

ai_foundry_endpoint = "https://swedencentral.api.cognitive.microsoft.com/"

ai_api_version      = "2024-08-01-preview"



# Model Deployments

phi_deployment          = "phi-4"

phi_fallback_deployment = "gpt-4.1-mini"

mistral_deployment      = "mistral-document-ai-2512"

mistral_mode            = "maas"

chat_deployment         = "gpt-5.1"

```



Then apply:

```bash

cd infra

terraform plan -out=tfplan

terraform apply tfplan

```



### Option 2: Using Azure CLI



#### For API Container:

```bash

az containerapp update \

  --name <your-api-name> \

  --resource-group <your-rg> \

  --set-env-vars \

    AI_ENDPOINT="https://swedencentral.api.cognitive.microsoft.com/" \

    AI_API_VERSION="2024-08-01-preview" \

    PHI_DEPLOYMENT="phi-4" \

    PHI_FALLBACK_DEPLOYMENT="gpt-4.1-mini" \

    MISTRAL_DEPLOYMENT="mistral-document-ai-2512" \

    MISTRAL_MODE="maas" \

    CHAT_DEPLOYMENT="gpt-5.1" \
    CHAT_API_VERSION="preview"

```



#### For Worker Container:

```bash

az containerapp update \

  --name <your-worker-name> \

  --resource-group <your-rg> \

  --set-env-vars \

    AI_ENDPOINT="https://swedencentral.api.cognitive.microsoft.com/" \

    AI_API_VERSION="2024-08-01-preview" \

    PHI_DEPLOYMENT="phi-4" \

    PHI_FALLBACK_DEPLOYMENT="gpt-4.1-mini" \

    MISTRAL_DEPLOYMENT="mistral-document-ai-2512" \

    MISTRAL_MODE="maas"

```



### Option 3: Using Azure Portal



1. Go to Azure Portal ? Container Apps

2. Select your API/Worker container

3. Go to **Settings** ? **Containers** ? **Environment variables**

4. Add/update the environment variables listed above

5. Click **Save**

6. Container will automatically restart with new configuration



---



## Validation & Testing



### Step 1: Verify Environment Variables



Use the built-in validation endpoint:



```bash

curl -X GET "https://<your-api-url>/api/admin/validate-aca-env"

```



Or through the UI:

1. Open ClassyMail UI

2. Go to **Settings** ? **Developer** tab

3. Click **Validate ACA Configuration**

4. Verify all AI model variables are present (?)



### Step 2: Test Model Connectivity



#### Via UI:

1. Go to **Settings** ? **Developer** tab

2. Click **Test LLM Models**

3. Verify all models return `"status": "success"`:

   - Phi-4 ?

   - Mistral OCR ?

   - GPT ?

   - Language service ?



#### Via API:

```bash

# Test Phi-4

curl "https://<your-api-url>/api/admin/test-phi4"



# Test Mistral

curl "https://<your-api-url>/api/admin/test-mistral-ocr"



# Test GPT

curl "https://<your-api-url>/api/admin/test-gpt"



# Test specific model

curl "https://<your-api-url>/api/admin/test-gpt?model=gpt-5.1"

```



Expected response (success):

```json

{

  "status": "success",

  "model": "phi-4",

  "response": "Classification model is operational",

  "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}

}

```



### Step 3: End-to-End Test



1. Upload a sample PDF email through the UI

2. Monitor processing in Dashboard

3. Verify classification results appear

4. Check Apply Insights for telemetry:

   ```bash

   az monitor app-insights query \

     --app <your-app-insights> \

     --resource-group <your-rg> \

     --analytics-query "dependencies | where name contains 'phi-4' | top 10 by timestamp desc"

   ```



---



## Troubleshooting



### Issue 1: "Deployment Not Found" Error



**Symptom**: Test endpoint returns `HTTP 404: Deployment not found`



**Causes**:

1. Deployment name mismatch in environment variables

2. Deployment not yet active (still provisioning)



**Solution**:

```bash

# List actual deployment names

az cognitiveservices account deployment list \

  --name <ai-foundry-name> \

  --resource-group <rg> \

  --query "[].name" \

  --output table



# Update environment variable to match exact deployment name

az containerapp update \

  --name <container-app> \

  --resource-group <rg> \

  --set-env-vars PHI_DEPLOYMENT="<correct-deployment-name>"

```



### Issue 2: "Rate Limit Exceeded" Error



**Symptom**: `HTTP 429: Too Many Requests`



**Causes**:

1. TPM (Tokens Per Minute) quota exceeded

2. Multiple concurrent requests



**Solution**:

```bash

# Increase TPM quota for deployment

az cognitiveservices account deployment update \

  --name <deployment-name> \

  --resource-group <rg> \

  --account-name <ai-foundry-name> \

  --sku-capacity 100  # Increase TPM to 100,000

```



Or implement request throttling in application.



### Issue 3: "Forbidden" / "Unauthorized" Error



**Symptom**: `HTTP 403: Access denied`



**Causes**:

1. Managed identity missing `Cognitive Services User` role

2. Wrong AI Foundry endpoint configured



**Solution**:

```bash

# Get managed identity principal ID

IDENTITY_ID=$(az identity show \

  --name <your-managed-identity> \

  --resource-group <rg> \

  --query principalId \

  --output tsv)



# Assign Cognitive Services User role

az role assignment create \

  --assignee $IDENTITY_ID \

  --role "a97b65f3-24c7-4388-baec-2e87135dc908" \

  --scope /subscriptions/<subscription-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<ai-foundry-name>

```



Verify role assignment:

```bash

az role assignment list \

  --scope /subscriptions/<subscription-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<ai-foundry-name> \

  --query "[?principalId=='$IDENTITY_ID'].{Role:roleDefinitionName, Principal:principalType}" \

  --output table

```



### Issue 4: Cosmos DB Connection Error (French Error Message)



**Symptom**:

```

Database unavailable: (Forbidden) Database Account '<prefix>-cosmos-<region>' does not exist

ActivityId: 2549f7ad-627a-4c2c-8e6c-09e482509f40

```



**Causes**:

1. Cosmos DB was recently recreated via Terraform (vector search capability added)

2. Container Apps still pointing to old Cosmos DB instance

3. Managed identity RBAC not yet propagated



**Solution**:

```bash

# 1. Verify new Cosmos DB exists

az cosmosdb show \

  --name <cosmos-account-name> \

  --resource-group <rg> \

  --query "{Name:name, State:properties.provisioningState, Endpoint:documentEndpoint}"



# 2. Restart Container Apps to pick up new connection

az containerapp restart --name <api-name> --resource-group <rg>

az containerapp restart --name <worker-name> --resource-group <rg>



# 3. Verify RBAC is assigned

az cosmosdb sql role assignment list \

  --account-name <cosmos-account-name> \

  --resource-group <rg> \

  --query "[].{Role:roleDefinitionId, Principal:principalId}"



# 4. If RBAC missing, reassign (Terraform should handle this)

cd infra

terraform apply -auto-approve

```



**Wait Time**: RBAC propagation can take 5-10 minutes. If error persists after restart, wait and try again.



**Quick Fix**:

```bash

# One-liner to fix Cosmos DB connection issues

cd infra && terraform apply -auto-approve && \

az containerapp restart --name $(az containerapp list -g <rg> --query "[?contains(name, 'api')].name" -o tsv) -g <rg> && \

az containerapp restart --name $(az containerapp list -g <rg> --query "[?contains(name, 'worker')].name" -o tsv) -g <rg>

```



### Issue 5: Mistral MaaS Endpoint Not Working



**Symptom**: Test returns `"status": "error"` for Mistral



**Causes**:

1. Wrong `MISTRAL_MODE` (should be `maas` for serverless)

2. Endpoint format differs for MaaS vs. PTU deployments



**Solution**:

```bash

# Ensure MISTRAL_MODE is set to "maas"

az containerapp update \

  --name <container-app> \

  --resource-group <rg> \

  --set-env-vars MISTRAL_MODE="maas"



# Verify deployment exists and is serverless

az cognitiveservices account deployment show \

  --name mistral-document-ai-2512 \

  --account-name <ai-foundry-name> \

  --resource-group <rg> \

  --query "{Name:name, State:properties.provisioningState, Model:properties.model.name}"

```



### Issue 6: Wrong API Version



**Symptom**: `HTTP 400: Invalid API version`



**Causes**:

1. Outdated `AI_API_VERSION` environment variable

2. Model doesn't support specified API version



**Solution**:

```bash

# Use recommended API version

az containerapp update \

  --name <container-app> \

  --resource-group <rg> \

  --set-env-vars AI_API_VERSION="2024-08-01-preview"

```



Supported API versions:

- `2024-08-01-preview` (recommended for Phi-4 + Mistral)

- `2024-06-01` (legacy stable version; prefer `2024-08-01-preview` or newer for current GPT-4.1 deployments)

- `2023-12-01-preview` (legacy, not recommended)



---



## Validation Scripts



### PowerShell: Verify All Models



Save as `scripts/test-all-models.ps1`:



```powershell

$ApiUrl = "https://<your-api-url>"



Write-Host "Testing Phi-4..." -ForegroundColor Cyan

$phi4 = Invoke-RestMethod -Uri "$ApiUrl/api/admin/test-phi4" -Method Get

if ($phi4.status -eq "success") {

    Write-Host "? Phi-4: OK" -ForegroundColor Green

} else {

    Write-Host "? Phi-4: FAILED - $($phi4.error)" -ForegroundColor Red

}



Write-Host "Testing Mistral..." -ForegroundColor Cyan

$mistral = Invoke-RestMethod -Uri "$ApiUrl/api/admin/test-mistral-ocr" -Method Get

if ($mistral.status -eq "success") {

    Write-Host "? Mistral: OK" -ForegroundColor Green

} else {

    Write-Host "? Mistral: FAILED - $($mistral.error)" -ForegroundColor Red

}



Write-Host "Testing GPT..." -ForegroundColor Cyan

$gpt = Invoke-RestMethod -Uri "$ApiUrl/api/admin/test-gpt" -Method Get

if ($gpt.status -eq "success") {

    Write-Host "? GPT: OK" -ForegroundColor Green

} else {

    Write-Host "? GPT: FAILED - $($gpt.error)" -ForegroundColor Red

}



Write-Host "Testing Language Service..." -ForegroundColor Cyan

$lang = Invoke-RestMethod -Uri "$ApiUrl/api/admin/test-language-service" -Method Get

if ($lang.status -eq "success") {

    Write-Host "? Language Service: OK" -ForegroundColor Green

} elseif ($lang.status -eq "not_configured") {

    Write-Host "? Language Service: Not configured (optional)" -ForegroundColor Yellow

} else {

    Write-Host "? Language Service: FAILED - $($lang.error)" -ForegroundColor Red

}

```



Run with:

```powershell

.\scripts\test-all-models.ps1

```



---



## Summary Checklist



- [ ] Microsoft AI Foundry resource deployed

- [ ] Phi-4 deployment created (`phi-4`)

- [ ] GPT-4.1-mini fallback/anonymizer/vision deployment created (`gpt-4.1-mini`)

- [ ] Mistral Document AI MaaS deployment created (`mistral-document-ai-2512`)

- [ ] text-embedding-3-small deployment created

- [ ] GPT deployment created (optional, `gpt-5.1`)

- [ ] GPT-4.1-nano deployment created (optional, for category assessment)

- [ ] `AI_ENDPOINT` configured in Container Apps

- [ ] `PHI_DEPLOYMENT` configured in Container Apps

- [ ] `MISTRAL_DEPLOYMENT` configured in Container Apps

- [ ] `MISTRAL_MODE=maas` configured

- [ ] Managed identity has `Cognitive Services User` role

- [ ] All connectivity tests pass (? in UI or via API)

- [ ] End-to-end PDF classification works

- [ ] Apply Insights shows model telemetry



---



## CLI Verification



Use the comprehensive verification scripts to validate your entire setup:



```bash

# Bash/Linux/Mac

./scripts/verify-mvp-setup.sh



# PowerShell/Windows

.\scripts\verify-mvp-setup.ps1

```



These scripts check:

- Azure CLI authentication

- Resource group existence

- Managed identity configuration

- All Azure resources (Storage, Cosmos DB, Service Bus, AI Foundry, Language service)

- RBAC role assignments (7 roles total)

- Container Apps configuration

- Model deployments and connectivity

- API endpoint health checks



---



## Related Documentation



- [ACA Environment Variables](ACA_ENVIRONMENT_VARIABLES.md) - Complete environment variable reference

- [Infrastructure Overview](INFRASTRUCTURE.md) - Full infrastructure architecture

- [Models Documentation](MODELS.md) - Detailed model specifications

- [RBAC Audit](RBAC_AUDIT.md) - Role-based access control setup

- [PII Anonymization & User Corrections](PII_ANONYMIZATION_AND_USER_CORRECTIONS.md) - PII protection in fine-tuning data

- [Troubleshooting Map](TROUBLESHOOTING_MAP.md) - Common issues and solutions



---



## Support



For issues not covered in this guide:

1. Run the verification script: `./scripts/verify-mvp-setup.sh` or `.\scripts\verify-mvp-setup.ps1`

2. Check Apply Insights logs for detailed error messages

3. Verify all environment variables with `/api/admin/validate-aca-env`

4. Test each model individually with `/api/admin/test-<model>`

5. Consult [Microsoft AI Foundry documentation](https://learn.microsoft.com/azure/ai-studio/)
