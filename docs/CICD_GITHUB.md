# CICD_GITHUB

Ce document décrit une approche CI/CD GitHub Actions pour :

- valider/tester l'app Python
- déployer l'image Docker puis la Container App Azure
- exécuter Terraform plan/apply proprement

## Auth recommandée : OIDC (pas de secrets longue durée)

Utilisez des identifiants fédérés (Workload Identity Federation) afin que GitHub obtienne un jeton court (id-token) sans stocker de mot de passe/secret.

Vue d'ensemble :

1) Créer une app registration Entra + service principal.
2) Configurer une federated identity credential pour votre repo/environnement GitHub.
3) Assigner les rôles Azure nécessaires (scope au niveau du RG si possible).

Références :

- Pricing (Azure AI Foundry) : https://azure.microsoft.com/fr-fr/pricing/details/ai-foundry-models/microsoft/
- OIDC GitHub Actions → Azure : https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect
- Trust WIF (Entra) : https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation-create-trust

## Workflow de déploiement (Container Apps)

Le workflow [deploy.yml](../.github/workflows/deploy.yml) :

- build/test (uv + `python -m compileall`)
- build & push image Docker
- déploiement sur Azure Container Apps
- affectation d'une **User Assigned Managed Identity** à la Container App (pour RBAC data-plane, sans clés)
- injection des variables d'environnement nécessaires

### Secrets GitHub requis (OIDC)

À définir dans GitHub → Settings → Secrets and variables → Actions → Secrets :

- `AZURE_CLIENT_ID` (client id du service principal OIDC)
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

Fallback (si vous n'utilisez pas OIDC) :

- `AZURE_CREDENTIALS` (JSON de service principal, format azure/login)

### Variables GitHub requises (non sensibles)

À définir dans GitHub → Settings → Secrets and variables → Actions → Variables :

- `AZURE_RESOURCE_GROUP` (ex: `email-poc-rg`)
- `AZURE_IDENTITY_NAME` (ex: `email-poc-id`)
- `AZURE_APP_CLIENT_ID` (clientId de l'identité managée **de l'app** ; Terraform output: `APP_ID_CLIENT_ID`)

Optionnel (recommandé) :

- `AZURE_CONTAINERAPP_ENV` (ex: `email-poc-env`). Si absent, le workflow utilise `email-poc-env` par défaut.

Terraform outputs → variables à renseigner :

- `AZURE_SERVICE_BUS_FQDN` (output: `AZURE_SERVICE_BUS_FQDN`)
- `AZURE_SERVICE_BUS_QUEUE` (output: `AZURE_SERVICE_BUS_QUEUE`)
- `AZURE_STORAGE_ACCOUNT_URL` (output: `AZURE_STORAGE_ACCOUNT_URL`)
- `AZURE_STORAGE_CONTAINER` (output: `AZURE_STORAGE_CONTAINER`)
- `AZURE_COSMOS_ENDPOINT` (output: `AZURE_COSMOS_ENDPOINT`)
- `AZURE_COSMOS_DB` (output: `AZURE_COSMOS_DB`)
- `AZURE_COSMOS_CONTAINER` (output: `AZURE_COSMOS_CONTAINER`)
- `AZURE_AI_ENDPOINT` (output: `AI_ENDPOINT`)
- `MISTRAL_DEPLOYMENT` (ex: `mistral-ocr-2505`)
- `MISTRAL_MODE` (ex: `maas`)
- `PHI_DEPLOYMENT` (ex: `phi-4`)

ACR :

- Option A (recommandé) : définir `ACR_NAME` (nom du registry ACR) et donner au SP OIDC le rôle **AcrPush**.
- Option B : définir `ACR_LOGIN_SERVER`, `ACR_USERNAME`, `ACR_PASSWORD` en secrets (ancienne méthode).

## Terraform dans GitHub Actions

### Terraform plan sur PR (squelette)

```yaml
name: terraform-plan
on:
  pull_request:
    paths:
      - 'infra/**'

permissions:
  id-token: write
  contents: read

jobs:
  plan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      - uses: hashicorp/setup-terraform@v3
      - run: terraform -chdir=infra init -upgrade
      - run: terraform -chdir=infra validate
      - run: terraform -chdir=infra plan -var "subscription_id=${{ secrets.AZURE_SUBSCRIPTION_ID }}" -out tfplan
```

### Bonnes pratiques

- Ne lancez pas Terraform avec state local en CI pour un environnement “réel”.
  - Préférez un backend distant (Azure Storage) + lock.
- Scope RBAC minimal ; éviter Owner.
- Séparer dev/test/prod (subscriptions/environments GitHub).

Référence IaC dans GitHub Actions : https://learn.microsoft.com/en-us/devops/deliver/iac-github-actions
