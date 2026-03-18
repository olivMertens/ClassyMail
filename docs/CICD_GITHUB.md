# CI/CD with GitHub Actions

This document describes the GitHub Actions CI/CD pipeline for ClassyMail.

## Overview

The pipeline handles:
- Python validation (ruff linter, pytest, pre-commit)
- Frontend linting and build (ESLint, Vite)
- Terraform validation
- Docker image build and push to ACR
- Container App deployment (API + Worker)
- Post-deployment verification (Cosmos firewall, health checks)

## Authentication: OIDC (no long-lived secrets)

Use federated credentials (Workload Identity Federation) so GitHub obtains a short-lived token (id-token) without storing passwords or secrets.

### Provisioned by Terraform (recommended)

The CI/CD identity is **fully managed by Terraform**:

``hcl
# In terraform.tfvars
github_repo = "yourorg/ClassyMail"
# github_environment = "production"  # optional
``

`terraform apply` automatically creates:

1. **User Assigned Managed Identity** (`<prefix>-cicd-id`) -- dedicated CI/CD identity
2. **Federated Identity Credential** (`github-main`) -- OIDC link for `refs/heads/main`
3. **Federated Identity Credential** (`github-env-<env>`) -- (optional) OIDC link for a GitHub environment
4. **RBAC roles**:
   - `Contributor` on the Resource Group (manage Container Apps, Cosmos firewall, etc.)
   - `AcrPush` on the ACR (push + pull images)

### Terraform Outputs

After `terraform apply`, retrieve the values for GitHub secrets:

``bash
AZURE_CLIENT_ID=$(terraform -chdir=infra output -raw CICD_CLIENT_ID)
AZURE_TENANT_ID=$(terraform -chdir=infra output -raw CICD_TENANT_ID)
AZURE_SUBSCRIPTION_ID="<YOUR_SUBSCRIPTION_ID>"
``

### GitHub Secrets Configuration

In your GitHub repository settings, add these secrets:

| Secret | Description |
|--------|-------------|
| `AZURE_CLIENT_ID` | Managed Identity Client ID (from Terraform output) |
| `AZURE_TENANT_ID` | Azure AD Tenant ID (from Terraform output) |
| `AZURE_SUBSCRIPTION_ID` | Azure Subscription ID |

And these repository variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `ACR_NAME` | Container Registry name | `classymailacr` |
| `AZURE_RESOURCE_GROUP` | Resource Group name | `classymail-rg` |
| `AZURE_IDENTITY_NAME` | Managed Identity name | `classymail-id` |
| `AZURE_CONTAINERAPP_ENV` | Container Apps Environment (optional) | `classymail-env` |

## Pipeline Stages

### 1. Changes Detection

Analyzes which files changed to determine what needs building:
- API code changes -> rebuild + redeploy API
- Worker code changes -> rebuild + redeploy Worker
- Docs-only changes -> skip build entirely

### 2. Validation Matrix

Runs 5 checks in parallel:
- **ruff** -- Python linting
- **pytest** -- Unit tests
- **terraform** -- `terraform init + validate`
- **pre-commit** -- All hooks
- **frontend-lint** -- ESLint + Vite build

### 3. Build

- Installs Python dependencies and builds frontend
- Logs into ACR via OIDC
- Builds Docker image and pushes to ACR

### 4. Deploy

- Deploys API and Worker Container Apps in parallel
- Assigns Managed Identity
- Configures ACR pull credentials
- Updates container image (environment variables managed by Terraform)

### 5. Post-Deployment Verification

- Updates Cosmos DB firewall with new Container App IPs
- Waits for Container Apps to reach Running state
- Checks `/healthz` and `/readyz` endpoints
- Runs API validation endpoint

## Environment Variables

Container App environment variables are managed by **Terraform** (not by the deploy workflow).

Key variables that must match your Terraform configuration:

| Variable | Description |
|----------|-------------|
| `MISTRAL_DEPLOYMENT` | Must be exactly `mistral-document-ai-2512` |
| `PHI_DEPLOYMENT` | Must be exactly `Phi-4` |
| `AZURE_AI_ENDPOINT` | AI Foundry endpoint URL |

See [ACA_ENVIRONMENT_VARIABLES.md](ACA_ENVIRONMENT_VARIABLES.md) for the complete list.

## Troubleshooting

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| 403 on Cosmos DB | Container App IPs changed | Run `update_cosmos_firewall` script |
| ACR pull fails | Missing AcrPull role | Check Managed Identity RBAC |
| OIDC auth fails | Wrong Client ID or Tenant ID | Verify Terraform outputs match GitHub secrets |
| Build fails | Frontend build error | Check Node.js version (18+) |