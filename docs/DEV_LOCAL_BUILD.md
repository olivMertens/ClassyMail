# Guide Développeur — Build local & push ACR (sans CI)

## ✅ Pré-requis
- Terraform appliqué (`infra/deploy.ps1 -AutoApprove` ou `terraform -chdir=infra apply tfplan`).
- Outils installés : `az` CLI, `docker`, `uv`, PowerShell/Bash.
- Connexion Azure :
  ```bash
  az login
  az account set --subscription <SUBSCRIPTION_ID>
  ```

## 🔧 Variables d’environnement (exemple)
```powershell
$env:ACR_NAME = "<acrname>"           # ex: myregistry
$env:RESOURCE_GROUP = "<rg>"
$env:IMAGE_NAME = "classimail-agent"
$env:WORKER_APP_NAME = "classimail-agent-worker"
$env:TAG = "local"
$env:IDENTITY_NAME = "<managed-identity-name>"  # si registry avec Managed Identity
```

## 🛠 Build & Push (scripts)
  ```powershell
  scripts/build_acr.ps1 -AcrName $env:ACR_NAME -ImageName $env:IMAGE_NAME -Tag $env:TAG
  ```
  ```bash
  ./scripts/build_acr.sh -a $ACR_NAME -i $IMAGE_NAME -t $TAG
  ```

## Build & push a container image (without CI)

### UI dependency (Vue runtime)

The UI loads Vue from `static/js/vue.global.prod.js`.

- The repository tracks a small **stub** file for development, which is not sufficient for production.
- For a working UI, you must provide the real Vue runtime **before building the Docker image**.

If you have internet access:

- Windows (PowerShell): `./scripts/fetch_vue_runtime.ps1`
- Linux/macOS: `bash ./scripts/fetch_vue_runtime.sh`

If you need a fully offline build, copy a previously downloaded `vue.global.prod.js` into `static/js/vue.global.prod.js` before building.
## 🛠 Build & Push (manuel)
```bash
REGISTRY=$(az acr show --name $ACR_NAME --query loginServer -o tsv)
az acr login --name $ACR_NAME

docker build -t $REGISTRY/$IMAGE_NAME:$TAG .
docker push $REGISTRY/$IMAGE_NAME:$TAG
```

## 🚀 Déployer sur Azure Container Apps (sans CI)
```bash
REGISTRY=$(az acr show --name $ACR_NAME --query loginServer -o tsv)

# API
az containerapp update -n $IMAGE_NAME -g $RESOURCE_GROUP \
  --image $REGISTRY/$IMAGE_NAME:$TAG

# Worker (ENABLE_WORKER=true)
az containerapp update -n $WORKER_APP_NAME -g $RESOURCE_GROUP \
  --image $REGISTRY/$IMAGE_NAME:$TAG \
  --set-env-vars ENABLE_WORKER=true
```

### 🔐 Registry attaché via Managed Identity (si besoin)
```bash
IDENTITY_ID=$(az identity show -g $RESOURCE_GROUP -n $IDENTITY_NAME --query id -o tsv)
az containerapp registry set \
  --name $IMAGE_NAME \
  --resource-group $RESOURCE_GROUP \
  --server $REGISTRY \
  --identity $IDENTITY_ID
```

## 🧪 Tests locaux rapides
```bash
uv sync --frozen --extra dev
uv run uvicorn classificationg2s.app:app --port 8000
```

## ✅ Lint & Tests

Configuration du hook de pré-commit (à faire une fois) :
```bash
uv run pre-commit install
```

Cela lancera les validations (ruff check + format) sur chaque `git commit`.

Lancer manuellement :
```bash
uv run pre-commit run --all-files
uv run ruff check .
uv run pytest
```

## 🔄 Après terraform : remplir `secrets.env`
Utiliser `terraform output` (infra/) pour renseigner `secrets.env` ou `secrets.env.example`.

Ajouter (ou laisser les valeurs par défaut) pour l’assistant IA :
```dotenv
CHAT_ENDPOINT=... # optionnel, défaut PHI_ENDPOINT
CHAT_DEPLOYMENT=gpt-5.2-chat
CHAT_API_VERSION=2024-08-01-preview
COSMOS_QUERY_MAX_LIMIT=20
```

## 📌 Références
- `scripts/build_acr.ps1`, `scripts/build_acr.sh`
- `docs/LOCAL_RUN.md`
- `docs/CICD_GITHUB.md`
- `infra/deploy.ps1`
