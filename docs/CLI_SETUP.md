# CLI Quick Reference

> 🚀 **Quick Commands**: Essential CLI commands for setup and configuration. For detailed RBAC troubleshooting, see [RBAC_AUDIT.md](RBAC_AUDIT.md).

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

# 4. Test locally
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

# Via Azure CLI
$RESOURCE_GROUP = "email-poc-rg"
$IDENTITY_NAME = "email-poc-app-id"

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
  --name email-poc-api `
  --user-assigned $IDENTITY_ID
```

---

## Container Apps

### Update Container Image

```powershell
az containerapp update `
  --name email-poc-api `
  --resource-group $RESOURCE_GROUP `
  --image $REGISTRY/$IMAGE_NAME:$TAG
```

### Update Environment Variables

```powershell
az containerapp update `
  --resource-group $RESOURCE_GROUP `
  --name email-poc-api `
  --set-env-vars "AZURE_CLIENT_ID=$CLIENT_ID"
```

### View Logs

```powershell
# Stream logs
az containerapp logs show `
  --resource-group $RESOURCE_GROUP `
  --name email-poc-api `
  --follow

# Recent logs
az containerapp logs show `
  --resource-group $RESOURCE_GROUP `
  --name email-poc-api `
  --tail 50
```

---

## Verification

### Health Checks

```powershell
# Local
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz

# Production
curl https://email-poc-api.azurecontainerapps.io/healthz
```

### Test Connectivity

```powershell
# Test API endpoint
$API_URL = terraform output -raw api_url
curl "$API_URL/api/stats"
```

---

## See Also

- **[RBAC_AUDIT.md](RBAC_AUDIT.md)** - Complete RBAC configuration & troubleshooting
- **[INFRASTRUCTURE.md](INFRASTRUCTURE.md)** - Terraform deployment guide
- **[LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)** - Local setup instructions
