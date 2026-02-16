# CICD_GITHUB

Ce document décrit une approche CI/CD GitHub Actions pour :

- valider/tester l'app Python
- déployer l'image Docker puis la Container App Azure
- exécuter Terraform plan/apply proprement

## Auth recommandée : OIDC (pas de secrets longue durée)

Utilisez des identifiants fédérés (Workload Identity Federation) afin que GitHub obtienne un jeton court (id-token) sans stocker de mot de passe/secret.

### Provisionné par Terraform (recommandé)

Depuis la version actuelle de l'IaC, l'identité CI/CD est **entièrement gérée par Terraform** :

```hcl
# Dans terraform.tfvars
github_repo = "olivMertens/ClassyMail"
# github_environment = "production"  # optionnel
```

`terraform apply` crée automatiquement :

1. **User Assigned Managed Identity** (`<prefix>-cicd-id`) — identité dédiée au CI/CD.
2. **Federated Identity Credential** (`github-main`) — lien OIDC pour `refs/heads/main`.
3. **Federated Identity Credential** (`github-env-<env>`) — (optionnel) lien OIDC pour un environment GitHub.
4. **RBAC** :
   - `Contributor` sur le Resource Group (gérer Container Apps, Cosmos firewall, etc.)
   - `AcrPush` sur l'ACR (push + pull d'images)

Après `terraform apply`, configurez les secrets GitHub avec les outputs :

```bash
terraform output CICD_CLIENT_ID       # → secret AZURE_CLIENT_ID
terraform output CICD_TENANT_ID       # → secret AZURE_TENANT_ID
# AZURE_SUBSCRIPTION_ID = votre ID de subscription
```

> **Note** : Cette approche utilise une Managed Identity (pas une App Registration).
> Aucun provider `azuread` n'est nécessaire.

### Alternative manuelle (App Registration)

Si vous ne pouvez pas utiliser Terraform (par ex. tenant restreint), créez manuellement :

1) Créer une app registration Entra + service principal.
2) Configurer une federated identity credential pour votre repo/environnement GitHub.
3) Assigner les rôles Azure nécessaires (scope au niveau du RG si possible).

## RBAC (qui a besoin de quoi)

Il y a **2 identités** distinctes dans ce projet :

1) **Service principal GitHub OIDC** (CI/CD) : utilisé par `azure/login@v2` dans GitHub Actions.
2) **User Assigned Managed Identity** de l'app (runtime) : utilisée par la Container App pour accéder aux services Azure **sans clés**.

### 1) RBAC du CI/CD Managed Identity (`<prefix>-cicd-id`)

Objectif : build/push l'image et déployer/mettre à jour la Container App.

Provisionné automatiquement par Terraform (`github_repo` non vide) :

- **Contributor** sur le RG (ex: `<prefix>-rg`) — gère Container Apps, lit les identités, met à jour le firewall Cosmos
- **AcrPush** sur l'ACR — push + pull d'images Docker

Option "least privilege" (alternative manuelle, plus strict) :

- **Container Apps Contributor** sur le RG
- **Managed Identity Operator** sur la User Assigned Managed Identity (pour permettre l'assignation à la Container App)
- **AcrPush** + **Reader** sur l'ACR

### 2) RBAC de l'identité managée de l'app (runtime)

Objectif : lire/écrire dans Cosmos, Storage, Service Bus, et appeler Azure AI Foundry.

- Storage Account (scope = storage account): **Storage Blob Data Contributor**
- Service Bus Namespace (scope = namespace): **Azure Service Bus Data Receiver** + **Azure Service Bus Data Sender**
- Azure AI Foundry account (scope = AI account): **Cognitive Services User**
- Cosmos DB (data-plane SQL RBAC): **Custom App Role** (`readMetadata` + CRUD) au scope **Account** (voir `infra/main.tf`)
- ACR (si pull via identité managée): **AcrPull** sur l'ACR

## Federated Identity Credential (GitHub OIDC)

> **Terraform gère cette configuration automatiquement.** Cette section est documentée comme référence.

Résumé des champs clés de la federated credential :

- **Issuer**: `https://token.actions.githubusercontent.com`
- **Audience**: `api://AzureADTokenExchange`
- **Subject**: dépend de votre setup GitHub.
  - Recommandé (Environment): `repo:<OWNER>/<REPO>:environment:<ENV_NAME>`
  - Alternative (branch): `repo:<OWNER>/<REPO>:ref:refs/heads/<BRANCH>`

Terraform crée les federated credentials sur une **Managed Identity** (`<prefix>-cicd-id`), pas une App Registration.
Référence officielle : https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect

Références :

- Pricing (Azure AI Foundry) : https://azure.microsoft.com/fr-fr/pricing/details/ai-foundry-models/microsoft/
- OIDC GitHub Actions → Azure : https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect
- Trust WIF (Entra) : https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation-create-trust

## Workflow de déploiement (Container Apps)

Le workflow [deploy.yml](../.github/workflows/deploy.yml) est structuré en plusieurs jobs :

### 1. Jobs de déploiement (API + Worker)

- build/test (uv + `python -m compileall`)
- build & push image Docker
- déploiement sur Azure Container Apps
- affectation d'une **User Assigned Managed Identity** à la Container App (pour RBAC data-plane, sans clés)
- injection des variables d'environnement nécessaires

### 2. Post-Deployment Verification & Auto-Fix (nouveau)

⚡ **Job critique** qui s'exécute **APRÈS** le déploiement des Container Apps pour garantir que l'infrastructure est fonctionnelle.

**Caractéristiques :**
- ✅ S'exécute automatiquement après `deploy-api` et `deploy-worker`
- ✅ Utilise `continue-on-error: true` (ne bloque jamais le pipeline)
- ✅ Auto-corrige les problèmes critiques détectés
- ✅ Génère des warnings pour les problèmes non auto-réparables

**Étapes d'auto-correction :**

1. **Cosmos DB Firewall (CRITIQUE)** 🔧
   - Détecte les IPs sortantes actuelles des Container Apps
   - Met à jour automatiquement le firewall Cosmos DB
   - Ajoute `0.0.0.0` (Azure Services) si manquant
   - **Bloque le pipeline si échec** (problème critique)

2. **Tags Policy (Gouvernance)** 🏷️
   - Applique la politique `SecurityControl` / `CostControl`
   - Lance la remédiation asynchrone des ressources non conformes
   - **N'échoue pas** si problème (non critique)

3. **Container Apps Readiness** ⏳
   - Vérifie que les Container Apps sont dans l'état `Running`
   - 12 tentatives avec 10s d'intervalle (total: 2 minutes)
   - **Avertit** si non prêt, mais ne bloque pas

4. **API Health Checks** 🩺
   - Teste `/health` endpoint (12 tentatives, 10s intervalle)
   - Teste `/readyz` endpoint (connectivité Cosmos/Storage/AI)
   - **Bloque le pipeline** si `/health` échoue après 2 minutes

5. **RBAC Roles Audit (Report Only)** 🔐
   - Vérifie la présence des rôles critiques sur la Managed Identity
   - Génère un **GitHub Warning** si rôles manquants
   - **N'échoue jamais** (rapport seulement)
   - Rôles vérifiés :
     - `Storage Blob Data Contributor`
     - `Cognitive Services User`
     - `Azure Service Bus Data Owner` (ou Sender + Receiver)

**Exemple de sortie (RBAC manquant) :**
```
⚠️ WARNING: Missing RBAC roles detected

Missing roles:
  - Cognitive Services User

FIX: These roles should have been assigned by Terraform.
     Run: cd infra && terraform apply

IMPACT: Container Apps may fail to access Azure resources
```

**Pourquoi cette approche ?**
- ⚡ **Déploiement d'abord** : Container Apps toujours déployées, même si vérifications futures échouent
- 🔧 **Auto-correction** : Problèmes réseau (firewall) corrigés automatiquement
- 📊 **Visibilité** : RBAC manquants remontés comme warnings GitHub
- 🚀 **Pas de blocage** : Pipeline réussit même avec warnings (action manuelle post-déploiement)

### Étapes de validation (avant déploiement)

- `uv run ruff check .`
- `uv run pytest`
- `terraform init -backend=false` + `terraform validate`


### Secrets GitHub requis (OIDC)

À définir dans GitHub → Settings → Secrets and variables → Actions → Secrets :

- `AZURE_CLIENT_ID` — Terraform output: `CICD_CLIENT_ID` (client id de l'identité managée CI/CD)
- `AZURE_TENANT_ID` — Terraform output: `CICD_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID` — votre subscription Azure

```bash
# Après terraform apply :
AZURE_CLIENT_ID=$(terraform -chdir=infra output -raw CICD_CLIENT_ID)
AZURE_TENANT_ID=$(terraform -chdir=infra output -raw CICD_TENANT_ID)
AZURE_SUBSCRIPTION_ID="ec8bd34d-34d2-4b35-a587-2904775884b1"
```

Fallback (si vous n'utilisez pas OIDC) :

- `AZURE_CREDENTIALS` (JSON de service principal, format azure/login)

### Variables GitHub requises (non sensibles)

À définir dans GitHub → Settings → Secrets and variables → Actions → Variables :

- `AZURE_RESOURCE_GROUP` (ex: `<prefix>-rg`)
- `AZURE_IDENTITY_NAME` (ex: `<prefix>-id`)
- `AZURE_APP_CLIENT_ID` (clientId de l'identité managée **de l'app** ; Terraform output: `APP_ID_CLIENT_ID`)

Optionnel (recommandé) :

- `AZURE_CONTAINERAPP_ENV` (ex: `<prefix>-env`). Si absent, le workflow utilise `<prefix>-env` par défaut.

Terraform outputs → variables à renseigner :

- `AZURE_SERVICE_BUS_FQDN` (output: `AZURE_SERVICE_BUS_FQDN`)
- `AZURE_SERVICE_BUS_QUEUE` (output: `AZURE_SERVICE_BUS_QUEUE`)
- `AZURE_STORAGE_ACCOUNT_URL` (output: `AZURE_STORAGE_ACCOUNT_URL`)
- `AZURE_STORAGE_CONTAINER` (output: `AZURE_STORAGE_CONTAINER`)
- `AZURE_COSMOS_ENDPOINT` (output: `AZURE_COSMOS_ENDPOINT`)
- `AZURE_COSMOS_DB` (output: `AZURE_COSMOS_DB`)
- `AZURE_COSMOS_CONTAINER` (output: `AZURE_COSMOS_CONTAINER`)
- `AZURE_AI_ENDPOINT` (output: `AI_ENDPOINT`)
- `MISTRAL_DEPLOYMENT` (ex: `mistral-document-ai-2505`) — ⚠️ **CRITICAL**: Must be exactly `mistral-document-ai-2505` or OCR will fail with HTTP 500 errors
- `MISTRAL_MODE` (ex: `maas`)
- `PHI_DEPLOYMENT` (ex: `phi-4`)

ACR :

- Option A (recommandé) : définir `ACR_NAME` (nom du registry ACR) et donner au SP OIDC les rôles **AcrPush** et **Reader**.
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

## Build local & ACR

Voir [docs/DEV_LOCAL_BUILD.md](DEV_LOCAL_BUILD.md) pour les scripts et commandes manuelles (build/push ACR, deploy ACA sans CI).
