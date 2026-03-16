# CICD_GITHUB

Ce document dï¿½crit une approche CI/CD GitHub Actions pour :

- valider/tester l'app Python
- dï¿½ployer l'image Docker puis la Container App Azure
- exï¿½cuter Terraform plan/apply proprement

## Auth recommandï¿½e : OIDC (pas de secrets longue durï¿½e)

Utilisez des identifiants fï¿½dï¿½rï¿½s (Workload Identity Federation) afin que GitHub obtienne un jeton court (id-token) sans stocker de mot de passe/secret.

### Provisionnï¿½ par Terraform (recommandï¿½)

Depuis la version actuelle de l'IaC, l'identitï¿½ CI/CD est **entiï¿½rement gï¿½rï¿½e par Terraform** :

```hcl
# Dans terraform.tfvars
github_repo = "olivMertens/ClassyMail"
# github_environment = "production"  # optionnel
```

`terraform apply` crï¿½e automatiquement :

1. **User Assigned Managed Identity** (`<prefix>-cicd-id`) ï¿½ identitï¿½ dï¿½diï¿½e au CI/CD.
2. **Federated Identity Credential** (`github-main`) ï¿½ lien OIDC pour `refs/heads/main`.
3. **Federated Identity Credential** (`github-env-<env>`) ï¿½ (optionnel) lien OIDC pour un environment GitHub.
4. **RBAC** :
   - `Contributor` sur le Resource Group (gï¿½rer Container Apps, Cosmos firewall, etc.)
   - `AcrPush` sur l'ACR (push + pull d'images)

Aprï¿½s `terraform apply`, configurez les secrets GitHub avec les outputs :

```bash
terraform output CICD_CLIENT_ID       # ? secret AZURE_CLIENT_ID
terraform output CICD_TENANT_ID       # ? secret AZURE_TENANT_ID
# AZURE_SUBSCRIPTION_ID = votre ID de subscription
```

> **Note** : Cette approche utilise une Managed Identity (pas une App Registration).
> Aucun provider `azuread` n'est nï¿½cessaire.

### Alternative manuelle (App Registration)

Si vous ne pouvez pas utiliser Terraform (par ex. tenant restreint), crï¿½ez manuellement :

1) Crï¿½er une app registration Entra + service principal.
2) Configurer une federated identity credential pour votre repo/environnement GitHub.
3) Assigner les rï¿½les Azure nï¿½cessaires (scope au niveau du RG si possible).

## RBAC (qui a besoin de quoi)

Il y a **2 identitï¿½s** distinctes dans ce projet :

1) **Service principal GitHub OIDC** (CI/CD) : utilisï¿½ par `azure/login@v2` dans GitHub Actions.
2) **User Assigned Managed Identity** de l'app (runtime) : utilisï¿½e par la Container App pour accï¿½der aux services Azure **sans clï¿½s**.

### 1) RBAC du CI/CD Managed Identity (`<prefix>-cicd-id`)

Objectif : build/push l'image et dï¿½ployer/mettre ï¿½ jour la Container App.

Provisionnï¿½ automatiquement par Terraform (`github_repo` non vide) :

- **Contributor** sur le RG (ex: `<prefix>-rg`) ï¿½ gï¿½re Container Apps, lit les identitï¿½s, met ï¿½ jour le firewall Cosmos
- **AcrPush** sur l'ACR ï¿½ push + pull d'images Docker

Option "least privilege" (alternative manuelle, plus strict) :

- **Container Apps Contributor** sur le RG
- **Managed Identity Operator** sur la User Assigned Managed Identity (pour permettre l'assignation ï¿½ la Container App)
- **AcrPush** + **Reader** sur l'ACR

### 2) RBAC de l'identitï¿½ managï¿½e de l'app (runtime)

Objectif : lire/ï¿½crire dans Cosmos, Storage, Service Bus, et appeler Azure AI Foundry.

- Storage Account (scope = storage account): **Storage Blob Data Contributor**
- Service Bus Namespace (scope = namespace): **Azure Service Bus Data Receiver** + **Azure Service Bus Data Sender**
- Azure AI Foundry account (scope = AI account): **Cognitive Services User**
- Cosmos DB (data-plane SQL RBAC): **Custom App Role** (`readMetadata` + CRUD) au scope **Account** (voir `infra/main.tf`)
- ACR (si pull via identitï¿½ managï¿½e): **AcrPull** sur l'ACR

## Federated Identity Credential (GitHub OIDC)

> **Terraform gï¿½re cette configuration automatiquement.** Cette section est documentï¿½e comme rï¿½fï¿½rence.

Rï¿½sumï¿½ des champs clï¿½s de la federated credential :

- **Issuer**: `https://token.actions.githubusercontent.com`
- **Audience**: `api://AzureADTokenExchange`
- **Subject**: dï¿½pend de votre setup GitHub.
  - Recommandï¿½ (Environment): `repo:<OWNER>/<REPO>:environment:<ENV_NAME>`
  - Alternative (branch): `repo:<OWNER>/<REPO>:ref:refs/heads/<BRANCH>`

Terraform crï¿½e les federated credentials sur une **Managed Identity** (`<prefix>-cicd-id`), pas une App Registration.
Rï¿½fï¿½rence officielle : https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect

Rï¿½fï¿½rences :

- Pricing (Azure AI Foundry) : https://azure.microsoft.com/fr-fr/pricing/details/ai-foundry-models/microsoft/
- OIDC GitHub Actions ? Azure : https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect
- Trust WIF (Entra) : https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation-create-trust

## Workflow de dï¿½ploiement (Container Apps)

Le workflow [deploy.yml](../.github/workflows/deploy.yml) est structurï¿½ en plusieurs jobs :

### 1. Jobs de dï¿½ploiement (API + Worker)

- build/test (uv + `python -m compileall`)
- build & push image Docker
- dï¿½ploiement sur Azure Container Apps
- affectation d'une **User Assigned Managed Identity** ï¿½ la Container App (pour RBAC data-plane, sans clï¿½s)
- injection des variables d'environnement nï¿½cessaires

### 2. Post-Deployment Verification & Auto-Fix (nouveau)

? **Job critique** qui s'exï¿½cute **APRï¿½S** le dï¿½ploiement des Container Apps pour garantir que l'infrastructure est fonctionnelle.

**Caractï¿½ristiques :**
- ? S'exï¿½cute automatiquement aprï¿½s `deploy-api` et `deploy-worker`
- ? Utilise `continue-on-error: true` (ne bloque jamais le pipeline)
- ? Auto-corrige les problï¿½mes critiques dï¿½tectï¿½s
- ? Gï¿½nï¿½re des warnings pour les problï¿½mes non auto-rï¿½parables

**ï¿½tapes d'auto-correction :**

1. **Cosmos DB Firewall (CRITIQUE)** ??
   - Dï¿½tecte les IPs sortantes actuelles des Container Apps
   - Met ï¿½ jour automatiquement le firewall Cosmos DB
   - Ajoute `0.0.0.0` (Azure Services) si manquant
   - **Bloque le pipeline si ï¿½chec** (problï¿½me critique)

2. **Tags Policy (Gouvernance)** ???
   - Applique la politique `SecurityControl` / `CostControl`
   - Lance la remï¿½diation asynchrone des ressources non conformes
   - **N'ï¿½choue pas** si problï¿½me (non critique)

3. **Container Apps Readiness** ?
   - Vï¿½rifie que les Container Apps sont dans l'ï¿½tat `Running`
   - 12 tentatives avec 10s d'intervalle (total: 2 minutes)
   - **Avertit** si non prï¿½t, mais ne bloque pas

4. **API Health Checks** ??
   - Teste `/health` endpoint (12 tentatives, 10s intervalle)
   - Teste `/readyz` endpoint (connectivitï¿½ Cosmos/Storage/AI)
   - **Bloque le pipeline** si `/health` ï¿½choue aprï¿½s 2 minutes

5. **RBAC Roles Audit (Report Only)** ??
   - Vï¿½rifie la prï¿½sence des rï¿½les critiques sur la Managed Identity
   - Gï¿½nï¿½re un **GitHub Warning** si rï¿½les manquants
   - **N'ï¿½choue jamais** (rapport seulement)
   - Rï¿½les vï¿½rifiï¿½s :
     - `Storage Blob Data Contributor`
     - `Cognitive Services User`
     - `Azure Service Bus Data Owner` (ou Sender + Receiver)

**Exemple de sortie (RBAC manquant) :**
```
?? WARNING: Missing RBAC roles detected

Missing roles:
  - Cognitive Services User

FIX: These roles should have been assigned by Terraform.
     Run: cd infra && terraform apply

IMPACT: Container Apps may fail to access Azure resources
```

**Pourquoi cette approche ?**
- ? **Dï¿½ploiement d'abord** : Container Apps toujours dï¿½ployï¿½es, mï¿½me si vï¿½rifications futures ï¿½chouent
- ?? **Auto-correction** : Problï¿½mes rï¿½seau (firewall) corrigï¿½s automatiquement
- ?? **Visibilitï¿½** : RBAC manquants remontï¿½s comme warnings GitHub
- ?? **Pas de blocage** : Pipeline rï¿½ussit mï¿½me avec warnings (action manuelle post-dï¿½ploiement)

### ï¿½tapes de validation (avant dï¿½ploiement)

- `uv run ruff check .`
- `uv run pytest`
- `terraform init -backend=false` + `terraform validate`


### Secrets GitHub requis (OIDC)

ï¿½ dï¿½finir dans GitHub ? Settings ? Secrets and variables ? Actions ? Secrets :

- `AZURE_CLIENT_ID` ï¿½ Terraform output: `CICD_CLIENT_ID` (client id de l'identitï¿½ managï¿½e CI/CD)
- `AZURE_TENANT_ID` ï¿½ Terraform output: `CICD_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID` ï¿½ votre subscription Azure

```bash
# Aprï¿½s terraform apply :
AZURE_CLIENT_ID=$(terraform -chdir=infra output -raw CICD_CLIENT_ID)
AZURE_TENANT_ID=$(terraform -chdir=infra output -raw CICD_TENANT_ID)
AZURE_SUBSCRIPTION_ID="<YOUR_SUBSCRIPTION_ID>"
```

Fallback (si vous n'utilisez pas OIDC) :

- `AZURE_CREDENTIALS` (JSON de service principal, format azure/login)

### Variables GitHub requises (non sensibles)

ï¿½ dï¿½finir dans GitHub ? Settings ? Secrets and variables ? Actions ? Variables :

- `AZURE_RESOURCE_GROUP` (ex: `<prefix>-rg`)
- `AZURE_IDENTITY_NAME` (ex: `<prefix>-id`)
- `AZURE_APP_CLIENT_ID` (clientId de l'identitï¿½ managï¿½e **de l'app** ; Terraform output: `APP_ID_CLIENT_ID`)

Optionnel (recommandï¿½) :

- `AZURE_CONTAINERAPP_ENV` (ex: `<prefix>-env`). Si absent, le workflow utilise `<prefix>-env` par dï¿½faut.

Terraform outputs ? variables ï¿½ renseigner :

- `AZURE_SERVICE_BUS_FQDN` (output: `AZURE_SERVICE_BUS_FQDN`)
- `AZURE_SERVICE_BUS_QUEUE` (output: `AZURE_SERVICE_BUS_QUEUE`)
- `AZURE_STORAGE_ACCOUNT_URL` (output: `AZURE_STORAGE_ACCOUNT_URL`)
- `AZURE_STORAGE_CONTAINER` (output: `AZURE_STORAGE_CONTAINER`)
- `AZURE_COSMOS_ENDPOINT` (output: `AZURE_COSMOS_ENDPOINT`)
- `AZURE_COSMOS_DB` (output: `AZURE_COSMOS_DB`)
- `AZURE_COSMOS_CONTAINER` (output: `AZURE_COSMOS_CONTAINER`)
- `AZURE_AI_ENDPOINT` (output: `AI_ENDPOINT`)
- `MISTRAL_DEPLOYMENT` (ex: `mistral-document-ai-2512`) ï¿½ ?? **CRITICAL**: Must be exactly `mistral-document-ai-2512` or OCR will fail with HTTP 500 errors
- `MISTRAL_MODE` (ex: `maas`)
- `PHI_DEPLOYMENT` (ex: `phi-4`)

ACR :

- Option A (recommandï¿½) : dï¿½finir `ACR_NAME` (nom du registry ACR) et donner au SP OIDC les rï¿½les **AcrPush** et **Reader**.
- Option B : dï¿½finir `ACR_LOGIN_SERVER`, `ACR_USERNAME`, `ACR_PASSWORD` en secrets (ancienne mï¿½thode).

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

- Ne lancez pas Terraform avec state local en CI pour un environnement ï¿½rï¿½elï¿½.
  - Prï¿½fï¿½rez un backend distant (Azure Storage) + lock.
- Scope RBAC minimal ; ï¿½viter Owner.
- Sï¿½parer dev/test/prod (subscriptions/environments GitHub).

Rï¿½fï¿½rence IaC dans GitHub Actions : https://learn.microsoft.com/en-us/devops/deliver/iac-github-actions

## Build local & ACR

Voir [docs/DEV_LOCAL_BUILD.md](DEV_LOCAL_BUILD.md) pour les scripts et commandes manuelles (build/push ACR, deploy ACA sans CI).
