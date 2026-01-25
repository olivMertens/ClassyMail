# Exécution locale

## Prérequis

- Python 3.11 ou 3.12 (certains wheels Azure SDK ne sont pas encore publiés pour 3.13)
- Outil d'env : `uv` (recommandé), Poetry ou pip

## Installation

### Option A : uv (recommandé)

```bash
uv lock
uv sync
```

Pour forcer Python 3.12 si plusieurs versions sont installées :

```bash
uv lock --python 3.12
uv sync --python 3.12
```

### Option B : pip

```bash
pip install -r requirements.txt
```

## Variables d’environnement

Créer un fichier local `secrets.env` (NON committé). Variables minimales :

```dotenv
AI_ENDPOINT=https://<your-ai-endpoint>.cognitiveservices.azure.com/
AZURE_SERVICE_BUS_FQDN=<namespace>.servicebus.windows.net
AZURE_SERVICE_BUS_QUEUE=pdf-processing-queue
AZURE_STORAGE_ACCOUNT_URL=https://<storage>.blob.core.windows.net/
AZURE_STORAGE_CONTAINER=pdf-inputs
AZURE_COSMOS_ENDPOINT=https://<cosmos>.documents.azure.com:443/
AZURE_COSMOS_DB=emailsdb
AZURE_COSMOS_CONTAINER=emails

# Optional if using key-based Cosmos (not recommended)
# AZURE_COSMOS_KEY=

# Models (can be the same as AI_ENDPOINT)
MISTRAL_ENDPOINT=$AI_ENDPOINT
PHI_ENDPOINT=$AI_ENDPOINT
PHI_DEPLOYMENT=phi-4

# Optional fallback
PHI_FALLBACK_DEPLOYMENT=gpt-4o-mini
```

Charger dans la session avant de lancer :

### PowerShell

```powershell
Get-Content .\secrets.env | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
  $k, $v = $_ -split '=', 2
  [Environment]::SetEnvironmentVariable($k, $v)
}
```

## Lancer l’appli

### API + worker dans un seul process (dev)

```bash
uv run uvicorn main:app --reload
```

Ouvrir : `http://127.0.0.1:8000/`

## Build & push image

Voir [docs/DEV_LOCAL_BUILD.md](DEV_LOCAL_BUILD.md) pour les commandes détaillées (scripts et manuel) et le déploiement ACA sans CI.

## Notes

- The app uses `DefaultAzureCredential` / Entra ID. For local dev, `az login` is typically the easiest path.
- If you don’t have Azure resources yet, run Terraform first (see `docs/TERRAFORM.md`).
