# CLI Reference

> 🚀 **Complete CLI guide**: Setup, authentication, managed identity, Container Apps management, RAG operations, and verification commands.
>
> For RBAC troubleshooting, see [RBAC_AUDIT.md](RBAC_AUDIT.md). For infrastructure details, see [INFRASTRUCTURE.md](INFRASTRUCTURE.md).

## Quick Start

```powershell
# 1. Login to Azure
az login

# 2. Deploy infrastructure
cd infra
terraform init
terraform apply

# 3. Get managed identity info
$CLIENT_ID = terraform output -raw app_identity_client_id
$WORKSPACE_ID = terraform output -raw log_analytics_workspace_id

# 4. Local testly
$env:AZURE_CLIENT_ID = $CLIENT_ID
$env:LOG_ANALYTICS_WORKSPACE_ID = $WORKSPACE_ID
uv run pytest

# 5. Verify application
$API_URL = terraform output -raw api_url
curl "$API_URL/healthz"
```

---

## Authentication

```powershell
# Interactive login
az login

# Service Principal login
az login --service-principal --username $APP_ID --password $PASSWORD --tenant $TENANT_ID

# Verify active subscription
az account show

# Change subscription
az account set --subscription "Subscription-Name-or-ID"
```

---

## Managed Identity

### Get Identity Information

```powershell
# Via Terraform outputs
cd infra
terraform output app_identity_client_id
terraform output app_identity_principal_id

# Via Azure CLI (replace <prefix> with your deployment prefix)
$RESOURCE_GROUP = "<prefix>-rg"
$IDENTITY_NAME = "<prefix>-id"

# Client ID
az identity show `
  --resource-group $RESOURCE_GROUP `
  --name $IDENTITY_NAME `
  --query clientId `
  --output tsv

# Principal ID (for RBAC)
az identity show `
  --resource-group $RESOURCE_GROUP `
  --name $IDENTITY_NAME `
  --query principalId `
  --output tsv
```

### Assign Identity to Container App

```powershell
$IDENTITY_ID = az identity show `
  --resource-group $RESOURCE_GROUP `
  --name $IDENTITY_NAME `
  --query id `
  --output tsv

az containerapp identity assign `
  --resource-group $RESOURCE_GROUP `
  --name <prefix>-api `
  --user-assigned $IDENTITY_ID
```

---

## Container Apps

### Update Container Image

```powershell
az containerapp update `
  --name <prefix>-api `
  --resource-group $RESOURCE_GROUP `
  --image $REGISTRY/$IMAGE_NAME:$TAG
```

### Update Environment Variables

```powershell
az containerapp update `
  --resource-group $RESOURCE_GROUP `
  --name <prefix>-api `
  --set-env-vars "AZURE_CLIENT_ID=$CLIENT_ID"
```

### View Logs

```powershell
# Stream logs
az containerapp logs show `
  --resource-group $RESOURCE_GROUP `
  --name <prefix>-api `
  --follow

# Recent logs
az containerapp logs show `
  --resource-group $RESOURCE_GROUP `
  --name <prefix>-api `
  --tail 50
```

---

## Health Checks & Verification

```powershell
# Local
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz

# Production (replace with your app URL)
curl https://<prefix>-api.azurecontainerapps.io/healthz

# Test API endpoint
$API_URL = terraform output -raw api_url
curl "$API_URL/api/stats"
```

---

## Verify Infrastructure & RBAC

### Bash (Linux/WSL/Cloud Shell)

```bash
# Set env overrides if needed (replace <prefix>)
export RESOURCE_GROUP=<prefix>-rg
export PREFIX=<prefix>
# Run verification (checks resources, assigns roles if missing)
scripts/verify_infra.sh
```

### PowerShell (Windows/Azure Cloud Shell)

```pwsh
$env:RESOURCE_GROUP="<prefix>-rg"
$env:PREFIX="<prefix>"
./scripts/verify_infra.ps1
```

**What it does:**
- Verifies presence of Resource Group, Storage, Service Bus, Cosmos, AI account, Container Apps
- Ensures Managed Identity has roles: Cognitive Services User, Storage Blob Data Contributor, Service Bus Data Sender/Receiver, Custom App Role Cosmos (readMetadata + CRUD) at Account scope (and AcrPull if ACR exists)
- Connectivity checks to Cosmos/Storage/Service Bus

---

## RAG Operations

### Backfill Embeddings & Chunks

```bash
uv run python -m classymail.cli --backfill-rag --max-items 50
```

Regenerates email embeddings and stores chunk embeddings for RAG.

### Run in Azure Cloud Shell

1. Open https://shell.azure.com
2. Clone repo or mount storage
3. Run `az login` (Cloud Shell is usually pre-authenticated)
4. Execute the scripts as above (bash or pwsh)

### Run in GitHub Actions

- Use `azure/login@v1` then run `scripts/verify_infra.sh`
- Ensure `AZURE_CREDENTIALS` secret is configured

---

## See Also

- **[RBAC_AUDIT.md](RBAC_AUDIT.md)** — Complete RBAC configuration & troubleshooting
- **[INFRASTRUCTURE.md](INFRASTRUCTURE.md)** — Terraform deployment guide
- **[LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)** — Local setup instructions
- **[DEPLOY_FROM_SCRATCH.md](DEPLOY_FROM_SCRATCH.md)** — Fresh tenant deployment guide
