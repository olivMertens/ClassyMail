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

## Upload PDF & déclencher le traitement

### Où sont stockés les PDFs dans le Blob ?

Quand vous uploadez via l’UI (onglet **Upload POC**) ou via l’API `POST /api/upload`, les PDFs sont écrits dans :

- Container: `AZURE_STORAGE_CONTAINER` (défaut: `pdf-inputs`)
- Blob path: `uploads/YYYY/MM/DD/<uuid>-<filename>.pdf`

L’API renvoie aussi `blob_url` pour chaque fichier.

### Comment le worker est déclenché ?

Deux modes sont supportés (selon votre infra) :

1) **Event Grid → Service Bus (direct)**
   - Un `BlobCreated` sur le container déclenche un message dans la queue Service Bus.
   - Le worker accepte soit notre format interne `{ "blob_url": "..." }`, soit directement le payload Event Grid (data.url).

2) **Event Grid → Webhook → Service Bus** (utile si vous voulez transformer/filtrer)
   - Vous pointez Event Grid sur `POST /webhook/ingest`.
   - Le webhook envoie ensuite `{ "blob_url": "..." }` dans la queue.

### Forcer un enqueue (après upload)

Si vous voulez déclencher manuellement le traitement d’un PDF déjà présent dans le blob :

- Via le webhook (simple) :

  ```bash
  curl -X POST http://127.0.0.1:8000/webhook/ingest \
    -H "Content-Type: application/json" \
    -d '[{"eventType":"Microsoft.Storage.BlobCreated","data":{"url":"<BLOB_URL>"}}]'
  ```

### Upload dans le Blob via Azure CLI (sans UI)

Vous pouvez déposer un PDF directement dans le container (auth Entra) :

```bash
# Exemple: uploader un fichier local dans le container pdf-inputs
az storage blob upload \
  --auth-mode login \
  --account-name <storageAccountName> \
  --container-name pdf-inputs \
  --name uploads/$(date +%Y/%m/%d)/manual-$(uuidgen).pdf \
  --file ./mon-fichier.pdf \
  --content-type application/pdf
```

Ensuite, déclenchez l’enqueue (cf. webhook ci-dessus) ou laissez Event Grid faire (si configuré).

### Générer des PDFs (script) puis uploader en batch

Si vous générez des PDFs localement (ex: dataset de test), vous pouvez les déposer en masse dans le Blob.

1) Générer des PDFs

```bash
# Génère 75 PDFs dans un dossier local (par défaut: dataset_emails_hardcore)
python scripts/generate_dummy_pdfs.py --count 75 --out dataset_emails_hardcore
```

2) Uploader en batch dans le container `pdf-inputs`

Prérequis : `az login` + droits data-plane sur le Storage Account (RBAC).

```bash
# Bash (Linux/macOS/Git Bash)
az storage blob upload-batch \
  --auth-mode login \
  --account-name <storageAccountName> \
  --destination pdf-inputs \
  --destination-path "uploads/$(date +%Y/%m/%d)/" \
  --source ./dataset_emails_hardcore \
  --pattern "*.pdf" \
  --content-type application/pdf
```

```powershell
# PowerShell
$datePath = Get-Date -Format "yyyy/MM/dd"
az storage blob upload-batch `
  --auth-mode login `
  --account-name <storageAccountName> `
  --destination pdf-inputs `
  --destination-path "uploads/$datePath/" `
  --source .\dataset_emails_hardcore `
  --pattern "*.pdf" `
  --content-type application/pdf
```

Variante : uploader le dossier déjà présent dans le repo

Le repo contient déjà des PDFs d’exemple dans `dataset/pdf/`. Vous pouvez les uploader directement :

```bash
az storage blob upload-batch \
  --auth-mode login \
  --account-name <storageAccountName> \
  --destination pdf-inputs \
  --destination-path "uploads/$(date +%Y/%m/%d)/" \
  --source ./dataset/pdf \
  --pattern "*.pdf" \
  --content-type application/pdf
```

Notes :

- Chaque upload crée un événement `Microsoft.Storage.BlobCreated`.
- Dans l’infra Terraform du repo, Event Grid envoie ces événements directement vers Service Bus (avec un filtre sur les URLs finissant par `.pdf`).
- Donc: *N PDFs uploadés* ⇒ *N messages* dans la queue ⇒ le worker va les traiter au fil de l’eau (KEDA/scale).

## Build & push image

Voir [docs/DEV_LOCAL_BUILD.md](DEV_LOCAL_BUILD.md) pour les commandes détaillées (scripts et manuel) et le déploiement ACA sans CI.

## Notes

- The app uses `DefaultAzureCredential` / Entra ID. For local dev, `az login` is typically the easiest path.
- If you don’t have Azure resources yet, run Terraform first (see `docs/TERRAFORM.md`).

## Troubleshooting

### "Upload Failed: 500 Internal Server Error"

Si vous rencontrez une erreur 500 lors de l'upload (via UI ou API), vérifiez les logs (ACA Logs ou output local).
Une cause fréquente est le **pare-feu du compte de stockage (Storage Account)** qui bloque les connexions.

- **Symptôme** : `AzureError: Public access is not permitted on this storage account.` ou `AuthorizationPermissionMismatch`.
- **Cause** : Si `public_network_access_enabled = false` dans Terraform, l'application (ACA ou locale) ne peut pas joindre le Blob Storage sauf via Private Endpoint (non configuré par défaut dans ce POC).
- **Solution** : Dans `infra/main.tf`, assurez-vous de définir :
  ```hcl
  resource "azurerm_storage_account" "st" {
      # ...
      public_network_access_enabled = true
      # ...
  }
  ```
- **Note** : Même avec l'accès public réseau, l'accès aux données reste protégé par RBAC (`Storage Blob Data Contributor`).

### "System Error" (Cosmos DB)

Si vous voyez une erreur concernant `enable_cross_partition_query` :
- **Cause** : Version récente du SDK Python Cosmos DB qui ne supporte plus cet argument déprécié.
- **Solution** : Mettre à jour le code backend (déjà corrigé dans la branche `main` récente).

```
