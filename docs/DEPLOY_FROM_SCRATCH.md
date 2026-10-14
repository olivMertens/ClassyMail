# Azure Deployment And Operations

## Before Provisioning

Confirm the intended tenant, subscription, region, resource permissions, model
availability and quotas. A configuration example is not evidence that those services
exist. Use Terraform for infrastructure; the canonical definitions are
[#infra/main.tf](../infra/main.tf) and [#infra/policy.tf](../infra/policy.tf).

The stack includes API and worker Container Apps, Service Bus with a KEDA queue scaler,
Blob Storage/Event Grid ingestion, Cosmos DB, managed identity and monitoring.
Foundry models, AI Search, Language and Document Intelligence depend on deployment flags.
Review the full variable definitions rather than assuming every optional resource is enabled.

## Terraform

Use [terraform.tfvars.example](../infra/terraform.tfvars.example) as the starting point
for an untracked `infra/terraform.tfvars`. Set `container_image` to a real image accessible
to the app identity. Both apps use the same image; their entry points differ.

```powershell
terraform -chdir=infra init
terraform -chdir=infra validate
terraform -chdir=infra plan
terraform -chdir=infra apply
```

Review the plan before applying. The Container App names use `app_name` (default
`classymail`), not `prefix`; other resource names use `prefix`. The current GitHub
workflow targets `classymail-api` and `classymail-worker`. Changing `app_name` requires
aligning the workflow, or it can create a second pair of apps.

Deployment wrappers are [deploy.ps1](../infra/deploy.ps1) and
[deploy.sh](../infra/deploy.sh); bootstrap helpers are
[bootstrap.ps1](../scripts/bootstrap.ps1) and [bootstrap.sh](../scripts/bootstrap.sh).
Inspect their parameters and side effects before using them. Some verification modes
also grant missing roles: they are not necessarily read-only audits.

## Container Images

For ACR cloud builds, stage only the Dockerfile inputs in `.tmp/`, excluding secrets,
Git metadata, local environments, node_modules, docs, tests, infrastructure and datasets.
Do not send the full repository to ACR Tasks or assume `.dockerignore` bounds the upload.
See the explicit build-context recipe in
[repository instructions](../.github/copilot-instructions.md).

Build for `linux/amd64`, tag with both `latest` and the short commit SHA, and pass
`COMMIT_SHA` and a UTC `BUILD_TIMESTAMP` as build arguments. Roll out the same immutable
image to both apps and set `APP_VERSION` to that SHA. Verify `/healthz`, `/readyz` and
`/api/admin/version` afterward. A successful build is not a successful rollout.

## Configuration

Environment variables are defined in [#classymail/core/config.py](../classymail/core/config.py)
and injected into apps by [#infra/main.tf](../infra/main.tf).
[write_secrets_env.ps1](../scripts/write_secrets_env.ps1) and
[write_secrets_env.sh](../scripts/write_secrets_env.sh) derive local configuration from
Terraform outputs. Keep generated secrets private.

| Area | Important variables |
| --- | --- |
| Queue | `AZURE_SERVICE_BUS_FQDN`, `AZURE_SERVICE_BUS_QUEUE` |
| Storage | `AZURE_STORAGE_ACCOUNT_URL`, `AZURE_STORAGE_CONTAINER` |
| Cosmos | `AZURE_COSMOS_ENDPOINT`, `AZURE_COSMOS_DB`, `AZURE_COSMOS_CONTAINER` |
| Models | `PHI_ENDPOINT`, `PHI_DEPLOYMENT`, `PHI_FALLBACK_DEPLOYMENT`, `MISTRAL_ENDPOINT`, `MISTRAL_DEPLOYMENT` |
| Retrieval | `AZURE_SEARCH_ENDPOINT`, `EMBEDDING_DEPLOYMENT` |
| OCR fallback | `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` |
| Optional OCR | `OCR_PROVIDER`, `CONTENT_UNDERSTANDING_ENDPOINT` |
| Identity and telemetry | `AZURE_CLIENT_ID`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `LOG_ANALYTICS_WORKSPACE_ID` |

Use actual deployment aliases, including case, rather than assuming catalog model
names are valid deployment names. Chat, reasoning and compaction variables are covered
in [models](MODELS.md). `UPLOAD_MAX_BYTES` controls per-file upload size in bytes;
`MAX_UPLOAD_SIZE` is not the environment variable consumed by the app.

## Identity And RBAC

Prefer managed identity in Azure and developer credentials locally. Optional key-based
paths exist in the code; their existence is not a recommendation to deploy keys.

The Terraform role assignments are the source of truth, including:

| Dependency | App access |
| --- | --- |
| Blob Storage | Storage Blob Data Contributor |
| Service Bus | Azure Service Bus Data Owner |
| Cosmos DB | Native SQL data-plane role, separate from Azure management-plane IAM |
| Foundry models / Document Intelligence | Cognitive Services User on the appropriate resource |
| AI Search | Search Index Data Contributor; check index-management permissions separately |
| Optional Language service | Cognitive Services Language Reader |
| ACR | AcrPull |

Review the actual principal and scope when diagnosing permissions. Network access,
data-plane RBAC and management-plane IAM are separate controls. Role changes can take
time to propagate. Do not delete apparent duplicate roles without checking the identity
and scope that use them.

Public endpoints and broad firewall allowances in a demo are not a private-production
architecture. Review ingress authentication, network restrictions, data residency,
retention and sensitive telemetry before exposing customer data.

## GitHub Actions CI/CD

[#.github/workflows/deploy.yml](../.github/workflows/deploy.yml) owns the exact pipeline.
It validates Python, frontend and Terraform; builds one image; deploys the two apps;
and performs post-deploy checks. Ordinary docs-only pushes skip image rollout, but
`workflow_dispatch` can explicitly force a build.

OIDC uses `azure/login@v2` and these repository secrets: `AZURE_CLIENT_ID`,
`AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`. The workflow also supports an
`AZURE_CREDENTIALS` legacy service-principal branch; prefer federation.

Set `github_repo` in Terraform to provision the CI identity and federation. Outputs
include `CICD_CLIENT_ID` and `CICD_TENANT_ID`. Repository variables used by the workflow
include `ACR_NAME`, `AZURE_RESOURCE_GROUP`, `AZURE_IDENTITY_NAME` and
`AZURE_CONTAINERAPP_ENV`. Federation subjects must match the branch/environment in use.

Terraform owns app configuration and ignores image-field drift for CI rollouts.
The workflow also sets rollout metadata and fills missing legacy model variables through
`LEGACY_MODEL_PINS`; it does not overwrite existing model selections. Check actual app
variables after changing model defaults: new code defaults alone do not migrate an
existing deployment.

## State And Troubleshooting

Preserve the correct Terraform state and lock access when sharing it. Remote state is
a deployment choice, not something this document assumes already exists. Never run
`terraform state rm` as a routine repair. For import, duplicate-app detection and
unexpected replacement, use [state drift](TROUBLESHOOTING_MAP.md#terraform-state-drift).
