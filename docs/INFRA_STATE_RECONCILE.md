# Terraform State Reconciliation — Container Apps

One-time runbook to align Terraform state with the **live** Container Apps after the
duplicate-app cleanup. Run this **once**, on the machine that holds the Terraform
state (the one you normally run `./infra/deploy.ps1` from).

## Background — what happened

- The infrastructure was deployed with `prefix = "email-poc"`, so Terraform named the
  two Container Apps `email-poc-api` and `email-poc-worker`.
- CI/CD (`.github/workflows/deploy.yml`) hard-codes the app names `classymail-api` /
  `classymail-worker` and deploys with `az containerapp update`. Because the names
  differed, CI created a **second, parallel** set of apps (`classymail-*`) next to the
  Terraform-managed ones (`email-poc-*`), inside the same resource group `email-poc-rg`.
- The stale `email-poc-api` / `email-poc-worker` apps were deleted out-of-band. Only
  `classymail-api` / `classymail-worker` (the CI-deployed, live apps) remain.
- **Result:** Terraform state still references the now-deleted `email-poc-*` apps, while
  the live `classymail-*` apps are unmanaged. A plain `terraform apply` would try to
  **re-create** `email-poc-*` and resurrect the duplicates.

## The durable fix (already in the repo)

`infra/main.tf` now **decouples the Container App names from `var.prefix`** via a
dedicated `app_name` variable (default `classymail`):

```hcl
variable "app_name" { default = "classymail" }            # <app_name>-api / <app_name>-worker

resource "azurerm_container_app" "api"    { name = "${var.app_name}-api"    ... }
resource "azurerm_container_app" "worker" { name = "${var.app_name}-worker" ... }
```

So Terraform now *describes* exactly the live apps (`classymail-api` / `classymail-worker`)
regardless of `prefix`, and matches the names CI deploys to. Every other resource still
uses `prefix` (e.g. `email-poc-cosmos`) and is unaffected.

> The image tag is **not** managed by Terraform — both apps already have
> `lifecycle { ignore_changes = [template[0].container[0].image] }`, so `terraform apply`
> will not revert the image that CI deployed. Terraform owns the app *definition*; CI owns
> the *image rollout*.

## One-time reconciliation

> Prereqs: `az login` to the right tenant, the correct subscription selected, and your
> existing `infra/terraform.tfvars` (with `prefix = "email-poc"`, `container_image`, etc.).

```powershell
az account set --subscription ec8bd34d-34d2-4b35-a587-2904775884b1   # External-olmertens-demosub

cd infra
terraform init

# 1) Drop the two deleted apps from state (they no longer exist in Azure).
terraform state rm azurerm_container_app.api azurerm_container_app.worker

# 2) Import the live, CI-deployed apps into the SAME addresses.
terraform import azurerm_container_app.api `
  "/subscriptions/ec8bd34d-34d2-4b35-a587-2904775884b1/resourceGroups/email-poc-rg/providers/Microsoft.App/containerapps/classymail-api"

terraform import azurerm_container_app.worker `
  "/subscriptions/ec8bd34d-34d2-4b35-a587-2904775884b1/resourceGroups/email-poc-rg/providers/Microsoft.App/containerapps/classymail-worker"

# 3) Verify — expect NO destroy/recreate of the container apps.
terraform plan
```

### Reading the plan

- ✅ **Expected:** no changes to `azurerm_container_app.api` / `.worker`, or only trivial
  in-place updates (tags, env vars). The `image` field is ignored by design.
- ❌ **Stop if you see** `must be replaced` / `destroy` on either container app, or a name
  change back to `email-poc-*`. That means `app_name` wasn't applied — re-check `infra/main.tf`
  and that you didn't override `app_name` in `terraform.tfvars`.

After a clean plan, normal `./infra/deploy.ps1` runs are safe again. Day-to-day image
deployments continue to flow through CI/CD (`deploy.yml`) untouched.

## Recommended hardening — remote state backend

Today the state is **local** (`infra/terraform.tfstate` on one machine). That is fragile and
not shareable with teammates or CI. The best-practice setup is an **azurerm** backend in a
dedicated Storage Account:

```powershell
# Create a state container (once)
az group create -n tfstate-rg -l swedencentral
az storage account create -n classymailtfstate -g tfstate-rg -l swedencentral --sku Standard_LRS
az storage container create --account-name classymailtfstate -n tfstate
```

Then add a backend block to `infra/main.tf` inside the existing `terraform { ... }` and
migrate the local state into it:

```hcl
terraform {
  backend "azurerm" {
    resource_group_name  = "tfstate-rg"
    storage_account_name = "classymailtfstate"
    container_name       = "tfstate"
    key                  = "classymail.tfstate"
  }
}
```

```powershell
cd infra
terraform init -migrate-state   # copies your existing local state into the storage account
```

Do this **after** the reconciliation above so the migrated state already contains the correct
`classymail-*` apps.
