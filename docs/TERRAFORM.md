# TERRAFORM

Terraform lives in `infra/`.

This folder provisions the Azure infrastructure used by the app:
- Storage account + container `pdf-inputs`
- Event Grid subscription → Service Bus queue
- Service Bus namespace + queue
- Cosmos DB (serverless) + SQL database/container
- Azure AI Foundry / AI Services account + project
- Managed identity + RBAC assignments

## Deploy (Windows)

```powershell
./infra/deploy.ps1
```

The script can optionally target a tenant/subscription:

```powershell
./infra/deploy.ps1 -TenantId <TENANT_ID> -SubscriptionId <SUBSCRIPTION_ID>
```

## Deploy (manual)

```powershell
az login
# multi-tenant: az login --tenant <TENANT_ID>

az account set --subscription <SUBSCRIPTION_ID>

terraform -chdir=infra init -upgrade
terraform -chdir=infra plan -var "subscription_id=<SUBSCRIPTION_ID>" -out tfplan
terraform -chdir=infra apply tfplan
```

## Why we still pass subscription_id

Some AzureRM versions cannot reliably infer the subscription from Azure CLI context. The deploy script detects the active subscription (`az account show`) and passes it to Terraform automatically.

## Policy-friendly defaults

- Storage is OAuth-only (no Shared Key).
- Service Bus local auth disabled.
- Cosmos uses Entra auth (RBAC) by default; no Cosmos key needed.

### Cosmos DB (Native RBAC) note

This project uses Cosmos **SQL data-plane RBAC** (`azurerm_cosmosdb_sql_role_assignment`).

In some tenants, assigning the built-in role at container scope (`/dbs/<db>/colls/<container>`) is not sufficient for metadata reads (you may see `Forbidden` on `readMetadata`).
We therefore assign **Cosmos DB Built-in Data Contributor** at **database scope** (`/dbs/<db>`), which matches the runtime fix validated in Azure Container Apps.

## Repo hygiene (what to commit)

Safe to commit from `infra/`:
- `main.tf`
- `.terraform.lock.hcl`
- `deploy.ps1`
- `terraform.tfvars.example`

Do NOT commit:
- `.terraform/`
- `terraform.tfstate*`
- `tfplan`
- `terraform.tfvars` (real values)
