# Guide CLI - Configuration & Connexion

## 1. Authentification Azure

### Se connecter avec Azure CLI

```powershell
# Connexion interactive
az login

# Ou connexion avec un Service Principal
az login --service-principal --username $APP_ID --password $PASSWORD --tenant $TENANT_ID

# Vérifier l'abonnement actif
az account show

# Changer d'abonnement si nécessaire
az account set --subscription "Nom-Abonnement-ou-ID"
```

### Se connecter avec Terraform

```powershell
cd infra

# Initialiser Terraform
terraform init

# Planifier les changements
terraform plan

# Appliquer les changements
terraform apply
```

## 2. Récupérer les informations de l'identité managée

### Option A : Via Terraform Output

```powershell
cd infra

# Afficher toutes les outputs
terraform output

# Afficher une output spécifique
terraform output app_identity_client_id
terraform output app_identity_principal_id
terraform output log_analytics_workspace_id
```

### Option B : Via Azure CLI

```powershell
# Définir les variables
$RESOURCE_GROUP = "email-poc-rg"
$IDENTITY_NAME = "email-poc-app-id"

# Obtenir le Client ID (Application ID)
az identity show `
  --resource-group $RESOURCE_GROUP `
  --name $IDENTITY_NAME `
  --query clientId `
  --output tsv

# Obtenir le Principal ID (Object ID pour RBAC)
az identity show `
  --resource-group $RESOURCE_GROUP `
  --name $IDENTITY_NAME `
  --query principalId `
  --output tsv

# Obtenir l'ID complet de la ressource
az identity show `
  --resource-group $RESOURCE_GROUP `
  --name $IDENTITY_NAME `
  --query id `
  --output tsv
```

## 3. Configurer l'identité managée pour un Container App

### Assigner l'identité managée

```powershell
# Variables
$RESOURCE_GROUP = "email-poc-rg"
$ACA_NAME = "email-poc-api"  # ou "email-poc-worker"
$IDENTITY_ID = "/subscriptions/YOUR_SUB_ID/resourcegroups/email-poc-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/email-poc-app-id"

# Assigner l'identité managée au Container App
az containerapp identity assign `
  --resource-group $RESOURCE_GROUP `
  --name $ACA_NAME `
  --user-assigned $IDENTITY_ID

# Vérifier l'assignation
az containerapp identity show `
  --resource-group $RESOURCE_GROUP `
  --name $ACA_NAME
```

### Définir l'identité par défaut (AZURE_CLIENT_ID)

```powershell
# Obtenir le Client ID de l'identité
$CLIENT_ID = az identity show `
  --resource-group $RESOURCE_GROUP `
  --name $IDENTITY_NAME `
  --query clientId `
  --output tsv

# Mettre à jour la variable d'environnement dans le Container App
az containerapp update `
  --resource-group $RESOURCE_GROUP `
  --name $ACA_NAME `
  --set-env-vars "AZURE_CLIENT_ID=$CLIENT_ID"
```

## 4. Configurer les rôles RBAC

### Attribution des rôles requis

```powershell
# Variables
$RESOURCE_GROUP = "email-poc-rg"
$IDENTITY_NAME = "email-poc-app-id"
$PRINCIPAL_ID = az identity show --resource-group $RESOURCE_GROUP --name $IDENTITY_NAME --query principalId --output tsv

# Storage Blob Data Contributor
$STORAGE_ACCOUNT_ID = az storage account show --name emailpocst --resource-group $RESOURCE_GROUP --query id --output tsv
az role assignment create `
  --assignee $PRINCIPAL_ID `
  --role "Storage Blob Data Contributor" `
  --scope $STORAGE_ACCOUNT_ID

# Storage Blob Data Reader
az role assignment create `
  --assignee $PRINCIPAL_ID `
  --role "Storage Blob Data Reader" `
  --scope $STORAGE_ACCOUNT_ID

# Service Bus Data Receiver
$SB_ID = az servicebus namespace show --name email-poc-sbus --resource-group $RESOURCE_GROUP --query id --output tsv
az role assignment create `
  --assignee $PRINCIPAL_ID `
  --role "Azure Service Bus Data Receiver" `
  --scope $SB_ID

# Service Bus Data Sender
az role assignment create `
  --assignee $PRINCIPAL_ID `
  --role "Azure Service Bus Data Sender" `
  --scope $SB_ID

# Log Analytics Reader
$LOG_WORKSPACE_ID = az monitor log-analytics workspace show --resource-group $RESOURCE_GROUP --workspace-name email-poc-logs --query id --output tsv
az role assignment create `
  --assignee $PRINCIPAL_ID `
  --role "Log Analytics Reader" `
  --scope $LOG_WORKSPACE_ID

# Cognitive Services User (AI Foundry)
$AI_ACCOUNT_ID = az cognitiveservices account show --name email-poc-aifoundry --resource-group $RESOURCE_GROUP --query id --output tsv
az role assignment create `
  --assignee $PRINCIPAL_ID `
  --role "Cognitive Services User" `
  --scope $AI_ACCOUNT_ID
```

### Vérifier les assignations de rôles

```powershell
# Lister tous les rôles assignés à l'identité
az role assignment list `
  --assignee $PRINCIPAL_ID `
  --output table

# Avec détails
az role assignment list `
  --assignee $PRINCIPAL_ID `
  --all `
  --include-inherited `
  --query "[].{Role:roleDefinitionName, Scope:scope}" `
  --output table
```

## 5. Configurer les variables d'environnement Container Apps

### Via Azure CLI

```powershell
# Obtenir le Log Analytics Workspace ID
$LOG_WORKSPACE_ID = az monitor log-analytics workspace show `
  --resource-group $RESOURCE_GROUP `
  --workspace-name email-poc-logs `
  --query customerId `
  --output tsv

# Mettre à jour les variables d'environnement
az containerapp update `
  --resource-group $RESOURCE_GROUP `
  --name email-poc-api `
  --set-env-vars `
    "LOG_ANALYTICS_WORKSPACE_ID=$LOG_WORKSPACE_ID" `
    "AZURE_CLIENT_ID=$CLIENT_ID"

# Vérifier les variables d'environnement
az containerapp show `
  --resource-group $RESOURCE_GROUP `
  --name email-poc-api `
  --query "properties.template.containers[0].env" `
  --output table
```

### Via Terraform (recommandé)

Les variables sont déjà configurées dans `infra/main.tf`:

```hcl
env {
  name  = "AZURE_CLIENT_ID"
  value = azurerm_user_assigned_identity.app_id.client_id
}
env {
  name  = "LOG_ANALYTICS_WORKSPACE_ID"
  value = azurerm_log_analytics_workspace.log.workspace_id
}
```

Pour appliquer :
```powershell
cd infra
terraform apply
```

## 6. Tester la connexion

### Test local avec identité managée simulée

```powershell
# Définir les variables d'environnement localement
$env:AZURE_CLIENT_ID = "YOUR_CLIENT_ID"
$env:LOG_ANALYTICS_WORKSPACE_ID = "YOUR_WORKSPACE_ID"

# Activer l'environnement virtuel
& .venv\Scripts\Activate.ps1

# Tester la connexion
uv run python -c "from classificationg2s.services.azure_clients import Clients; import asyncio; asyncio.run(Clients().init())"
```

### Test des endpoints API

```powershell
# Healthcheck
curl https://email-poc-api.azurecontainerapps.io/healthz

# Readiness check
curl https://email-poc-api.azurecontainerapps.io/readyz

# Test des logs (nécessite authentification)
curl https://email-poc-api.azurecontainerapps.io/api/admin/telemetry/logs?days=1&limit=10
```

## 7. Debugging

### Logs Container Apps

```powershell
# Logs en temps réel (streaming)
az containerapp logs show `
  --resource-group $RESOURCE_GROUP `
  --name email-poc-api `
  --follow

# Logs récents
az containerapp logs show `
  --resource-group $RESOURCE_GROUP `
  --name email-poc-api `
  --tail 50
```

### Requêtes Log Analytics

```powershell
# Via Azure CLI
az monitor log-analytics query `
  --workspace $LOG_WORKSPACE_ID `
  --analytics-query "ContainerAppConsoleLogs_CL | where ContainerAppName_s == 'email-poc-api' | order by TimeGenerated desc | take 50" `
  --output table
```

## 8. Outputs Terraform utiles

### Créer un fichier d'outputs complet

Ajouter à `infra/main.tf` (à la fin) :

```hcl
output "app_identity_client_id" {
  description = "Client ID de l'identité managée (AZURE_CLIENT_ID)"
  value       = azurerm_user_assigned_identity.app_id.client_id
}

output "app_identity_principal_id" {
  description = "Principal ID de l'identité managée (pour RBAC)"
  value       = azurerm_user_assigned_identity.app_id.principal_id
}

output "log_analytics_workspace_id" {
  description = "Workspace ID pour Log Analytics (LOG_ANALYTICS_WORKSPACE_ID)"
  value       = azurerm_log_analytics_workspace.log.workspace_id
}

output "api_url" {
  description = "URL de l'API Container App"
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "connection_test_commands" {
  description = "Commandes pour tester la connexion"
  value = <<-EOT
    # Test health
    curl https://${azurerm_container_app.api.ingress[0].fqdn}/healthz

    # Set env vars locally
    $env:AZURE_CLIENT_ID = "${azurerm_user_assigned_identity.app_id.client_id}"
    $env:LOG_ANALYTICS_WORKSPACE_ID = "${azurerm_log_analytics_workspace.log.workspace_id}"
  EOT
}
```

Ensuite :
```powershell
terraform apply
terraform output
```

## Résumé - Quick Start

```powershell
# 1. Se connecter
az login

# 2. Déployer avec Terraform
cd infra
terraform init
terraform apply

# 3. Récupérer les informations
$CLIENT_ID = terraform output -raw app_identity_client_id
$WORKSPACE_ID = terraform output -raw log_analytics_workspace_id

# 4. Tester localement
$env:AZURE_CLIENT_ID = $CLIENT_ID
$env:LOG_ANALYTICS_WORKSPACE_ID = $WORKSPACE_ID
uv run pytest

# 5. Vérifier l'application
$API_URL = terraform output -raw api_url
curl "$API_URL/healthz"
```
