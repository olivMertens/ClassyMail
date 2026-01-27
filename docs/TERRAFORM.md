# TERRAFORM

Terraform est dans `infra/`.

Ce dossier provisionne l’infra Azure de l’app :
- Storage account + container `pdf-inputs`
- Event Grid → Service Bus queue
- Service Bus namespace + queue
- Cosmos DB (serverless) + base/collection SQL
- Azure AI Foundry / Azure AI Services + projet
- Identité managée + rôles (RBAC)

## Déploiement (Windows)

```powershell
./infra/deploy.ps1
```

The script can optionally target a tenant/subscription:

```powershell
./infra/deploy.ps1 -TenantId <TENANT_ID> -SubscriptionId <SUBSCRIPTION_ID>
```

## Déploiement (manuel)

```powershell
az login
# multi-tenant: az login --tenant <TENANT_ID>

az account set --subscription <SUBSCRIPTION_ID>

terraform -chdir=infra init -upgrade
terraform -chdir=infra plan -var "subscription_id=<SUBSCRIPTION_ID>" -out tfplan
terraform -chdir=infra apply tfplan
```

## Pourquoi passer `subscription_id`

Certaines versions AzureRM n’infèrent pas toujours la subscription depuis Azure CLI. Le script `deploy.ps1` détecte la subscription active (`az account show`) et la passe à Terraform.

## Defaults compatibles policies

- Storage en OAuth-only (pas de Shared Key).
- Service Bus auth locale désactivée.
- Cosmos en Entra ID (RBAC) par défaut ; pas de clé Cosmos nécessaire.

### Cosmos DB (RBAC data-plane)

Le projet utilise **Cosmos SQL data-plane RBAC** (`azurerm_cosmosdb_sql_role_assignment`).

Sur certains tenants, l’assignation d’un rôle built-in au scope collection (`/dbs/<db>/colls/<container>`) n’est pas suffisante pour lire les métadonnées (`Forbidden` sur `readMetadata`).
On assigne donc **Cosmos DB Built-in Data Contributor** au scope base (`/dbs/<db>`), conforme au fix validé côté Container Apps.

## Rôles Assignés (Identity)

Terraform crée une **User Assigned Managed Identity** (`<prefix>-id`) et lui assigne les rôles suivants sur les ressources créées :

| Ressource | Rôle | Description |
|-----------|------|-------------|
| **Storage Account** | `Storage Blob Data Contributor` | Lecture/Ecriture des PDFs dans le container `pdf-inputs`. |
| **Service Bus** | `Azure Service Bus Data Receiver` | Lecture des messages depuis la queue (Worker). |
| **Service Bus** | `Azure Service Bus Data Sender` | Envoi (si besoin) ou gestion deadcheck (API/Worker). |
| **ACR** | `AcrPull` | Pull des images Docker privées (si `acr_name` fourni). |
| **AI Foundry / Services** | `Cognitive Services User` | Appel des APIs d'inférence (Phi-4, Mistral). |
| **Cosmos DB** | `Cosmos DB Built-in Data Contributor` | Lecture/Ecriture des résultats de classification (Scope Database). |

## Variables Chatbot (injection Container App)

- **API** reçoit automatiquement :
  - `CHAT_ENDPOINT` = endpoint AI Foundry
  - `CHAT_DEPLOYMENT` = `gpt-5.2-chat`
  - `CHAT_API_VERSION` = `2024-08-01-preview`
- **Worker** n’en a pas besoin.

## Hygiene repo (ce qu’on commit)

À committer :
- `main.tf`
- `.terraform.lock.hcl`
- `deploy.ps1`
- `terraform.tfvars.example`

Ne pas committer :
- `.terraform/`
- `terraform.tfstate*`
- `tfplan`
- `terraform.tfvars` (real values)

## Images & registries

- `variable "container_image"` **obligatoire** : image publique (*ex*: `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest`) ou privée (*ex*: `<monacr>.azurecr.io/classimail-agent:tag`).
- ACR **non obligatoire** avec image publique.
- ACR privé : renseigner `acr_name` (+ `acr_resource_group` si différent) pour que Terraform assigne **AcrPull** à l’identité managée.
