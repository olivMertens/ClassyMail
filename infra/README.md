# Infra folder

Terraform and deployment documentation lives in [docs/DEPLOY_FROM_SCRATCH.md](../docs/DEPLOY_FROM_SCRATCH.md).

**Quick Reference:**
- **Deployment Guide**: Run `./infra/deploy.ps1` (Windows) or `bash infra/deploy.sh` (Linux/macOS) from repo root
- **Verify / repair roles**: `./infra/deploy.ps1 -VerifyOnly -ResourceGroup <prefix>-rg` (or `--verify-only`)
- **Fresh Tenant**: See [docs/DEPLOY_FROM_SCRATCH.md](../docs/DEPLOY_FROM_SCRATCH.md) for complete onboarding
- **Models**: See [docs/MODELS.md](../docs/MODELS.md#deployment-aliases)
- **Model Deployments**: Terraform can provision models when the relevant flags are enabled; check availability and quotas first.
- **Custom Tags**: Configurable via `custom_tags_enabled`; see [configuration](../docs/INTEGRATION.md#categories-and-customization).
- **State drift / Container App names**: The two ACAs are named `${app_name}-api` / `${app_name}-worker` (default `classymail`), **decoupled from `prefix`** so Terraform and CI/CD agree. To realign Terraform state with the live apps, see [docs/TROUBLESHOOTING_MAP.md](../docs/TROUBLESHOOTING_MAP.md).

**Repository deployment defaults (verify service availability and feature flags):**
1. `mistral-document-ai-2512` - OCR + Vision extraction
2. `Phi-4` - Primary classification (8K context)
3. `gpt-5.4-mini` - Fallback classification, anonymization, and vision
4. `text-embedding-3-small` - Vector embeddings for RAG chatbot
5. `gpt-6-sol` - Chatbot reasoning model, synthetic data, agentic tier3 + red team (recommended)
6. `gpt-6-luna` - Category assessment AI + agentic orchestrator/tier1 (recommended)

**Legacy selections:** `deploy_legacy_models = true` retains legacy model provisioning. Existing chat/fallback aliases can be kept through `chat_deployment` and `fallback_deployment`; check their current availability separately. Code compatibility does not establish model lifecycle dates.

See [deployment configuration](../docs/DEPLOY_FROM_SCRATCH.md#configuration) for deployment instructions.

---

## Deploying with `deploy.ps1`

`deploy.ps1` is an idempotent Terraform wrapper that applies the full stack to
your subscription — Storage + Event Grid ingestion, Service Bus, AI Foundry,
Cosmos DB, the two Container Apps (API + worker, KEDA Service Bus scaler), the
managed identity, **all RBAC role assignments**, the corporate **tag policies**,
and (optionally) the **GitHub OIDC CI/CD identity**.

It logs in, registers the required resource providers, then layers any
parameters you pass on top of `terraform.tfvars` via Terraform `-var` flags
(CLI values win; `terraform.tfvars` is never overwritten).

Quick deploy from the repo root (interactive — prompts before apply):

```powershell
./infra/deploy.ps1
```

Full non-interactive deploy with a real image, ACR pull, local IP allow-list:

```powershell
./infra/deploy.ps1 `
  -ContainerImage myacr.azurecr.io/classymail:latest `
  -AcrName myacr -AcrResourceGroup my-acr-rg `
  -DetectLocalIp -AutoApprove
```

Wire GitHub Actions OIDC at the same time (prints the secrets to set):

```powershell
./infra/deploy.ps1 -ContainerImage myacr.azurecr.io/classymail:v1 `
  -AcrName myacr -AcrResourceGroup my-acr-rg -GithubRepo owner/repo
```

Dry run (init + plan only, no changes):

```powershell
./infra/deploy.ps1 -PlanOnly
```

**Key parameters** (run `Get-Help ./infra/deploy.ps1 -Detailed` for all):

| Parameter | Purpose |
|-----------|---------|
| `-ContainerImage` | Image for API + worker (required by Terraform; a placeholder is used if omitted). |
| `-Prefix` / `-Location` | Resource naming prefix / Azure region. |
| `-ResourceGroup` | Existing RG to discover/verify roles against (default `<prefix>-rg`). |
| `-AcrName` / `-AcrResourceGroup` | Grant `AcrPull` to the app identity (and `AcrPush` to CI/CD). |
| `-GithubRepo` / `-GithubEnvironment` | Create the GitHub OIDC CI/CD identity + federated credential. |
| `-AllowedIpRanges` / `-DetectLocalIp` | Cosmos DB firewall allow-list (explicit IPs or auto-detected). |
| `-CosmosUseRbac` / `-CustomTagsEnabled` / `-TagPolicyEnabled` / `-SecurityCostPolicyEnabled` | Override the (true-by-default) RBAC / tag-policy toggles. |
| `-EnableModelDeployments` / `-DeployLanguageService` / `-DeployDocumentIntelligence` | Opt-in optional AI services/models. |
| `-VerifyOnly` / `-SkipRoleVerification` | Discovery/role-verification controls (see below). |
| `-SkipProviderRegistration` / `-PlanOnly` / `-AutoApprove` | Flow control. |

### Linux / macOS — `deploy.sh`

`deploy.sh` is the bash counterpart with identical behaviour and flags (kebab-case
instead of PascalCase). Run `bash infra/deploy.sh --help` for the full list.

```bash
# Interactive deploy
bash infra/deploy.sh

# Non-interactive deploy with a real image + ACR pull + local IP allow-list
bash infra/deploy.sh \
  --container-image myacr.azurecr.io/classymail:latest \
  --acr-name myacr --acr-resource-group my-acr-rg \
  --detect-local-ip --auto-approve

# Dry run
bash infra/deploy.sh --plan-only
```

### Discovery & role verification

Both scripts discover the app managed identity (`<prefix>-id`) and **verify the
RBAC role assignments against an existing resource group**, adding **only the
missing** ones (idempotent — nothing is removed or re-created if already
present). This runs automatically after a successful `apply`, and can also be
run standalone to double-check an existing deployment without touching
Terraform:

```powershell
# Windows — verify/repair roles on an existing RG, no Terraform plan/apply
./infra/deploy.ps1 -VerifyOnly -ResourceGroup classymail-rg
```

```bash
# Linux/macOS
bash infra/deploy.sh --verify-only --resource-group classymail-rg
```

Roles checked (source of truth: [docs/DEPLOY_FROM_SCRATCH.md](../docs/DEPLOY_FROM_SCRATCH.md)):

| Role | Scope | Condition |
|------|-------|-----------|
| Storage Blob Data Contributor | Storage account | always |
| Azure Service Bus Data Receiver | Service Bus namespace | always |
| Azure Service Bus Data Sender | Service Bus namespace | always |
| Cognitive Services User | AI Foundry account | always |
| AcrPull | Container Registry | if an ACR is present / `-AcrName` set |
| Cognitive Services Language Reader | Language service | if the Language service exists |
| Cosmos SQL custom role (data-plane) | Cosmos DB account | **verified & warned only** — Terraform owns this custom role |

Notes:

- The Cosmos DB data-plane role is a Terraform-managed **custom** SQL role
  (`azurerm_cosmosdb_sql_role_definition`), not a built-in role. The scripts
  verify it and warn if missing rather than creating it — re-run
  `terraform apply` (or the full deploy) to restore it.
- Adding missing control-plane roles requires **Owner** or **User Access
  Administrator** on the scope. Failures are reported in the summary line.
- Use `-SkipRoleVerification` / `--skip-role-verification` to skip the
  automatic post-apply check.

For a full from-scratch run that also **builds and pushes the image**, writes
`secrets.env`, and assigns local-dev RBAC, use
[`scripts/bootstrap.ps1`](../scripts/bootstrap.ps1) instead
(see [docs/DEPLOY_FROM_SCRATCH.md](../docs/DEPLOY_FROM_SCRATCH.md)).
