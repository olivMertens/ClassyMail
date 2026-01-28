
# POC Classification Emails : Azure AI Foundry & Mistral + FastAPI Dashboard

**Author:** Olivier Mertens — olmertens@microsoft.com
**Update:** Février 2026 (POC Refonte UI & Infra)

> **⚠️ Important Update (Jan 2026):** Fixed Mistral Document AI to use Microsoft Foundry endpoint directly (no path suffix needed).
> This is NOT the standard OpenAI Chat Completions API. See [docs/MODELS.md](docs/MODELS.md) for details.

## Pourquoi ce POC ?

Ce repo est un **POC “agent + pipeline”** pour traiter des emails/PDFs **à fort volume**, avec un objectif de **latence stable** et de **coûts observables**.
Il sert à valider rapidement :

- Une architecture **événementielle découplée** (ingestion vs traitement) pour absorber des pics (ex: 10k fichiers).
- Un workflow de **review humaine** (dashboard interactif) + boucle de **reinforcement / fine-tuning**.
- Un mode de déploiement cloud **prod-ready** (Terraform + Azure Container Apps) et une exécution locale simple.
- **Nouveau (Fév 2026)** : Interface "Dark Mode" native, Danger Zone (Reset complet), Filtres avancés (Catégorie/Confiance), "Average Quality" stat, et **Assistant IA (chat) connecté à Cosmos DB**.

## Comment ça marche (vue d’ensemble)

1) **Upload** d’un PDF dans Blob Storage.
2) **Event Grid** déclenche un message dans **Service Bus** (queue) pour lisser la charge.
3) Un **worker** consomme la queue, télécharge le PDF et lance :
    - OCR via **Mistral OCR** → Markdown
    - Classification via **Phi‑4** (avec fallback possible) → JSON
4) Le résultat est **persisté dans Cosmos DB** (statut, classification, usage/coûts), puis visible dans le **dashboard**.

Pour les détails (RBAC, variables, exécution, CI/CD) : voir la section Documentation ci-dessous.

## 📚 Documentation

- Docs home (index) : [docs/INDEX.md](docs/INDEX.md)

### Parcours recommandé (à lire dans cet ordre)

Selon ton objectif :

- **Je veux tester le système E2E** (recommandé pour débuter)
    1. [docs/SCENARIO_E2E.md](docs/SCENARIO_E2E.md) — scénario complet (PDF → Blob → Event Grid → Service Bus → Worker → Cosmos → UI), en local et sur Azure
    2. [docs/LOCAL_RUN.md](docs/LOCAL_RUN.md) — exécution locale, variables `secrets.env`, upload/trigger
    3. [docs/TERRAFORM.md](docs/TERRAFORM.md) — provisionner l’infra Azure + récupérer les outputs

- **Je veux comprendre l’architecture** (deep dive)
    1. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — composants, RBAC, scaling
    2. [docs/PIPELINE.md](docs/PIPELINE.md) — logique de traitement (OCR → LLM → persistance), formats de messages
    3. [docs/MODELS.md](docs/MODELS.md) — endpoints, deployments, contraintes tokens, pricing config
    4. [docs/FINE_TUNING_DATA.md](docs/FINE_TUNING_DATA.md) — boucle de review + export JSONL + fine-tune

- **Je veux builder/déployer**
  - [docs/DEV_LOCAL_BUILD.md](docs/DEV_LOCAL_BUILD.md) — build/push image, déploiement ACA sans CI
  - [docs/CICD_GITHUB.md](docs/CICD_GITHUB.md) — CI/CD GitHub Actions

### Référence (liste complète)

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/PIPELINE.md](docs/PIPELINE.md)
- [docs/TERRAFORM.md](docs/TERRAFORM.md)
- [docs/MODELS.md](docs/MODELS.md)
- [docs/FINE_TUNING_DATA.md](docs/FINE_TUNING_DATA.md)
- [docs/CICD_GITHUB.md](docs/CICD_GITHUB.md)
- [docs/LOCAL_RUN.md](docs/LOCAL_RUN.md)
- [docs/DEV_LOCAL_BUILD.md](docs/DEV_LOCAL_BUILD.md)
- [docs/SCENARIO_E2E.md](docs/SCENARIO_E2E.md)
- [docs/USER_INTERFACE.md](docs/USER_INTERFACE.md)

## 🔗 References

- **Mistral Document AI Catalog:** <https://ai.azure.com/catalog/models/mistral-document-ai-2505>
- Pricing (Azure AI Foundry models): <https://azure.microsoft.com/fr-fr/pricing/details/ai-foundry-models/microsoft/>
- Fine-tuning (Azure AI Foundry / Azure OpenAI): <https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning?view=foundry-classic&tabs=oai-sdk%2Cazure-openai&pivots=programming-language-python>
- Phi Cookbook (community): <https://github.com/microsoft/PhiCookBookfin>
- Running Phi-4 locally (Foundry Local guide): <https://techcommunity.microsoft.com/blog/educatordeveloperblog/running-phi-4-locally-with-microsoft-foundry-local-a-step-by-step-guide/4466304>

## ⚠️ Mistral Document AI Limitations

**Document Size Limits:**

- **Maximum file size:** 30 MB
- **Maximum pages (OCR):** 30 pages
- **Maximum pages (Annotations):** 8 pages
- **Supported formats:** PDF, PPTX, DOCX, PNG, JPEG/JPG, AVIF

**Important Notes:**

- Pure OCR processes efficiently and quickly
- Annotation processes can be slower and may result in timeouts
- Content safety is applied for annotations only, not enforced for OCR outputs

For more details, see [docs/MODELS.md](docs/MODELS.md).

Ce projet implémente un pipeline de classification d'emails à haut volume et faible latence, capable de gérer des pics de charge (10k fichiers simultanés) grâce à une architecture événementielle découplée, avec un backend FastAPI et un frontend SPA (Vue 3 + Tailwind).

![Dashboard UI](https://raw.githubusercontent.com/olivMertens/classimail-agent/main/docs/assets/dashboard_preview.png)
<!-- (Note: add a screenshot to docs/assets if available, otherwise just text description below) -->

The new frontend provides a dark-mode enabled dashboard to:

- Monitor email processing metrics (including "Avg. Quality").
- Upload/drag-and-drop PDF files directly.
- Filter emails by **Category name** and **Confidence score** (e.g. "< 50%").
- Export data to **CSV** (direct download) or **JSONL** (for fine-tuning).
- Review and correct classifications with a side-by-side PDF viewer and markdown preview.
- Analyze costs and usage.
- Configure settings (Strategies including "Vision" or "Reasoning", Prices, and Fine-tune thresholds).
- **Danger Zone**: Reset environment (Blob/Cosmos) for clean demos.

```mermaid
flowchart TD
    user[User] -->|Upload PDF / Review| ui[SPA (Vue 3 + Tailwind)]
    ui -->|API calls| api[FastAPI API]
    api -->|Download PDF| blob[(Blob Storage)]
    blob -->|Event Grid| sbq[Service Bus Queue]
    sbq -->|Worker| api
    api -->|OCR document_base64| ocr[Mistral OCR]
    ocr -->|Markdown| api
    api -->|Classify intents| llm["Phi-4 (primary)<br/>Fallback: gpt-4o-mini"]
    llm -->|JSON| api
    api -->|Persist| cosmos[(Cosmos DB)]


## 🔧 Installation & Exécution (aperçu)

Voir [docs/LOCAL_RUN.md](docs/LOCAL_RUN.md) pour toutes les options (uv/poetry/pip) et le chargement de `secrets.env`.

```bash
uv sync
uv run uvicorn main:app --reload
```

CI/CD : [docs/CICD_GITHUB.md](docs/CICD_GITHUB.md) | GitLab : [docs/CICD_GITLAB.md](docs/CICD_GITLAB.md)

Tests rapides : voir [docs/LOCAL_RUN.md](docs/LOCAL_RUN.md#lancer-lappli)

1. **UI** : validation/correction (FastAPI Dashboard)
2. **Golden Dataset** : `classification.needs_review=false`, `reviewed=true`
3. **Export Foundry** : JSONL hebdomadaire
4. **Fine-Tune** : LoRA sur Phi-4
5. **Déploiement** : `Phi-4-Custom` (même endpoint)

---

## 🧪 Génération de données (POC / Demo)

Pour démontrer le POC (stress OCR + classification + boucle de review/fine-tuning), le repo inclut un générateur de PDFs « email-like » volontairement bruités :

- Script: [scripts/generate_dummy_pdfs.py](scripts/generate_dummy_pdfs.py)
- Objectif: produire 50–100 emails aléatoires, souvent longs (~300 mots), avec bruit (FR/EN/ES, argot, SMS, typos, forwards, multi-sujets…)

Exemples:

```bash
# Dépendance du générateur PDF (uniquement pour ce script)
pip install fpdf2

# Générer 1 PDF (pratique pour vérifier le nom unique/id) — le script affiche le chemin du fichier
python scripts/generate_dummy_pdfs.py --count 1 --out dataset/pdf

python scripts/generate_dummy_pdfs.py --count 75 --target-words 300
python scripts/generate_dummy_pdfs.py --count 100 --target-words 320 --out dataset/pdf
```

Notes:

- Les fichiers sont nommés avec un suffixe unique (timestamp + UUID court), par ex:
    `sample_001_<categorie>_<timestamp>_<id>.pdf`
- Quand `--count <= 3`, le script affiche le chemin complet des fichiers générés.

### Simuler un PDF corrompu (end-to-end)

Objectif: vérifier que le pipeline détecte un PDF illisible dès l'étape 1 (download) et que l'UI affiche clairement l'erreur.

Pré-requis:

- App démarrée (local ou ACA)
- Variables Storage configurées (`AZURE_STORAGE_ACCOUNT_URL`, `AZURE_STORAGE_CONTAINER`)

Exemples:

```bash
# Local
python scripts/simulate_corrupted_pdf.py --base-url http://localhost:8000

# ACA (remplacer l'URL)
python scripts/simulate_corrupted_pdf.py --base-url https://<your-app>.<region>.azurecontainerapps.io
```

Résultat attendu:

- Un item `status=ERROR` apparaît dans l'onglet `⚠ Erreurs`, avec `error_stage=download` + un petit `processing_log`.

### Option LLM (Azure OpenAI / Foundry compatible)

Le script peut générer/étendre le contenu via un LLM avant de créer les PDFs.

Variables d'environnement:

- `AZURE_OPENAI_ENDPOINT` (obligatoire)
- `AZURE_OPENAI_DEPLOYMENT` (optionnel, défaut: `gpt-4o-mini`)
- `AZURE_OPENAI_API_VERSION` (optionnel, défaut: `2024-10-01-preview`)
- `AZURE_OPENAI_TIMEOUT` (optionnel)

Exemple PowerShell:

```powershell
$env:AZURE_OPENAI_ENDPOINT = "https://<resource>.openai.azure.com"
$env:AZURE_OPENAI_DEPLOYMENT = "gpt-4o-mini"
# Optionnel (si auth par key)
$env:AZURE_OPENAI_API_KEY = "<key>"
```

Authentification (fallback automatique):

- **API key**: définir `AZURE_OPENAI_API_KEY`
- **Entra ID (recommandé)**: ne pas définir la key, et s'authentifier via `DefaultAzureCredential` (ex: `az login`).
- Scope configurable via `AZURE_OPENAI_SCOPE` (défaut: `https://cognitiveservices.azure.com/.default`).

```bash
python scripts/generate_dummy_pdfs.py --count 75 --target-words 300 --use-aoai
```

## 🧩 Backend FastAPI

### Endpoints

- `POST /webhook/ingest` : Webhook Event Grid → Service Bus.
- `GET /api/emails` : Liste (page, status, search), multi-intents.
- `GET /api/emails/{id}` : Détail (SAS, markdown, classification multi-intents).
- `PATCH /api/emails/{id}` : Validation (`intents` array, status=PROCESSED).

### Observability & Coûts

- **OpenTelemetry** (OTLP) via `OTEL_EXPORTER_OTLP_ENDPOINT`
- **Usage & coûts** stockés par email (`usage.phi4.usage`, `usage.phi4_cost_usd`, `usage.mistral.estimated_pages`, `usage.mistral.cost_usd`)

### Worker

- SB + `Semaphore(5)`, validation PDF (header `%PDF`) → base64
- **Mistral OCR** `document_base64`
- **Phi-4 multi-intents** JSON
- `needs_review` via règles (scores, intents count)
- Cosmos upsert
- **PDF corrompu / illisible (stage 1: download)**: l'item est marqué `status=ERROR`, sauvegardé dans Cosmos avec `error_stage=download`, et envoyé en DLQ.
- **Autres échecs (OCR / classify)**: `status=ERROR` + `error_stage=ocr|classify` (visible dans l'UI), DLQ.

### Export CSV

- CLI (recommandé): `python -m classificationg2s.cli --export-csv data/output.csv`
- Export fine-tuning JSONL: `python -m classificationg2s.cli --export-finetune-jsonl data/fine_tune.jsonl`
- Colonnes : `intents`, `needs_review`, `global_complexity`

---

## 💻 Frontend SPA (Vue 3 + Tailwind)

Le projet inclut une application frontend moderne dans le dossier `frontend/`.

- **Stack** : Vue 3, Vite, Tailwind CSS, Headless UI.
- **Features** :
  - Dashboard analytique (KPIs, graphes).
  - Vue liste avec filtres (statut, recherche full-text, dates).
  - Vue détail optimisée pour la review (PDF split-screen, Markdown, formulaire JSON).
  - Upload Drag & Drop.
  - Dark mode natif.
- **Build** : `npm run build` génère les assets dans `static/dist/`. FastAPI sert `index.html` comme point d'entrée SPA.

Ancien frontend (legacy) : `templates/index.html` (remplacé).

---

## 🔧 Installation & Exécution

### Setup Frontend (Dev)
Pour développer le frontend avec le Hot Module Replacement (HMR) :

```bash
cd frontend
npm install
npm run dev
```
L'URL locale sera typiquement `http://localhost:5173`. Configurez le proxy Vite ou CORS si nécessaire pour taper sur l'API Python (`http://localhost:8000`).

### Setup Backend (uv)

```bash
uv lock
uv sync
uv run uvicorn classificationg2s.app:app --reload
```
Le backend sert le frontend compilé à l'adresse racine `/`.

Entrypoint historique (si besoin): `uvicorn main:app --reload`

Note: Python 3.11/3.12 recommended (Azure SDK support on 3.13 may lag).

### Avec Poetry

```bash
poetry install
poetry run uvicorn main:app --reload
```

### Avec pip

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

### Remplir `secrets.env` après Terraform

Les valeurs proviennent des outputs Terraform (voir `terraform output`).

```dotenv
AI_ENDPOINT=https://<aifoundry>.cognitiveservices.azure.com/
AZURE_SERVICE_BUS_FQDN=<namespace>.servicebus.windows.net
AZURE_SERVICE_BUS_QUEUE=pdf-processing-queue
AZURE_STORAGE_ACCOUNT_URL=https://<storage>.blob.core.windows.net/
AZURE_STORAGE_CONTAINER=pdf-inputs
AZURE_COSMOS_ENDPOINT=https://<cosmos>.documents.azure.com:443/
AZURE_COSMOS_DB=emailsdb
AZURE_COSMOS_CONTAINER=emails

# If Cosmos RBAC is enabled (recommended), do NOT set AZURE_COSMOS_KEY.
# AZURE_COSMOS_KEY=

MISTRAL_ENDPOINT=$AI_ENDPOINT
PHI_ENDPOINT=$AI_ENDPOINT
ANONYMIZER_ENDPOINT=$AI_ENDPOINT
VISION_ENDPOINT=$AI_ENDPOINT
```

### CI/CD

CI/CD setup lives in:
- GitHub Actions: [docs/CICD_GITHUB.md](docs/CICD_GITHUB.md)

See the docs for the full YAML examples, authentication options (OIDC vs secrets), and recommended environment protections.


---

## ✨ Fonctionnalités Clés

- Ingestion Event Grid → Service Bus → Worker async (`Semaphore(5)`).
- OCR Mistral (`document_base64`), fallback inference `{deployment}:ocr`.
- Classification Phi‑4 multi-intentions (JSON strict) + `needs_review` (seuil 0.9).
- Fallback automatique vers un modèle long-contexte (ex: `gpt-4o-mini`) si le markdown OCR dépasse la fenêtre de contexte du modèle principal.
- Coûts & usage par email (pages, tokens, €), visibles UI + export CSV.
- Observabilité OpenTelemetry (HTTPx, spans custom `gen_ai.*`).
- CI/CD GitHub Actions (uv, ACR, Azure Container Apps).
- Terraform Foundry (Hub + Project + Deployments + RBAC `Cognitive Services User`).

Pour les détails (variables, logique, pricing), voir [docs/MODELS.md](docs/MODELS.md).

## 📄 Format RFAT (JSON)

```json
{
    "id": "pdf-inputs/2025/01/mail123.pdf",
    "file_url": "https://...",
    "classification": {
        "detected_intents": [
            {"intent": "Attestation habitation", "confidence": 0.97, "justification": "..."},
            {"intent": "Dommages électriques", "confidence": 0.91, "justification": "..."}
        ],
        "global_complexity": "Simple",
        "needs_review": false
    },
    "usage": {
        "phi4": {"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165},
        "phi4_cost_usd": 0.00012,
        "mistral": {"estimated_pages": 2, "cost_usd": 0.002}
    }
}
```

## 🛠 Fine-tuning Phi‑4 (LoRA) & GPT‑4o-mini (Azure)

Voir [docs/FINE_TUNING_DATA.md](docs/FINE_TUNING_DATA.md) pour les détails (anonymisation, format JSONL, split train/validation).

1. **Collecte** : `needs_review=false` (validations humaines) dans Cosmos DB.
2. **Export JSONL** (chat) :
    - CLI : `uv run python main.py --export-finetune-jsonl ./data/fine_tune_all.jsonl`
    - HTTP : `GET /api/emails/export-finetune-jsonl`
3. **Split** : produire **2 fichiers**
    - `data/training_set.jsonl`
    - `data/validation_set.jsonl`
    Exemple (90/10) dans la doc.
4. **Foundry / Azure AI** :
    - Créer datasets (train/validation)
    - Lancer fine-tune (LoRA `phi-4` ou GPT‑4o-mini) via UI/CLI
    - Déployer `phi-4-custom` ou `gpt-4o-mini-custom` (endpoint OpenAI Chat compatible)
5. **Configuration** : `PHI_DEPLOYMENT=phi-4-custom` (ou fallback `gpt-4o-mini-custom`), `PHI_ENDPOINT` = endpoint Foundry.

Références :
- Doc fine-tuning Azure AI Foundry/Azure OpenAI : <https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning?view=foundry-classic&tabs=oai-sdk%2Cazure-openai&pivots=programming-language-python>
- Tutoriel officiel (GPT-4o-mini, end-to-end) : <https://learn.microsoft.com/en-us/azure/ai-foundry/openai/tutorials/fine-tune?view=foundry-classic&tabs=command-line>

## 🧱 Terraform (Foundry)

- `infra/main.tf` : crée **Foundry** (AIServices), **Project**, **Deployments** (`phi-4`, `mistral-document-ai-2505`), **RBAC** `Cognitive Services User` pour l'identité `app_id`.
- Commandes :
    ```bash
    terraform init -upgrade
    terraform plan -out main.tfplan
    terraform apply main.tfplan
    ```

## 🔐 Lancement local (uv)

Créer `secrets.env` :

```dotenv
AZURE_SERVICE_BUS_FQDN=...
AZURE_SERVICE_BUS_QUEUE=pdf-processing-queue
AZURE_STORAGE_ACCOUNT_URL=...
AZURE_STORAGE_CONTAINER=pdf-inputs
AZURE_COSMOS_ENDPOINT=...
AZURE_COSMOS_KEY=...
MISTRAL_ENDPOINT=...
MISTRAL_DEPLOYMENT=mistral-document-ai-2505
MISTRAL_MODE=maas
MISTRAL_OCR_MAX_ATTEMPTS=3
PHI_ENDPOINT=...
PHI_DEPLOYMENT=phi-4
PHI_FALLBACK_ENDPOINT=...
PHI_FALLBACK_DEPLOYMENT=gpt-4o-mini
CHAT_ENDPOINT=... # (optionnel, défaut PHI_ENDPOINT)
CHAT_DEPLOYMENT=gpt-5.2-chat
CHAT_API_VERSION=2024-08-01-preview
ANONYMIZER_ENDPOINT=...
ANONYMIZER_DEPLOYMENT=gpt-4o-mini
ANONYMIZER_API_VERSION=2024-10-01-preview
VISION_ENDPOINT=...
VISION_DEPLOYMENT=gpt-4o
VISION_API_VERSION=2024-10-01-preview
PHI_PRIMARY_MAX_INPUT_TOKENS=8000
PHI_FALLBACK_MAX_INPUT_TOKENS=120000
PHI_RESERVED_OUTPUT_TOKENS=1000
PHI4_COST_PER_1K_INPUT=0.000107
PHI4_COST_PER_1K_OUTPUT=0.00043
FALLBACK_COST_PER_1K_INPUT=0
FALLBACK_COST_PER_1K_OUTPUT=0
MISTRAL_OCR_COST_PER_1K_PAGES=1.0
OTEL_EXPORTER_OTLP_ENDPOINT=...
UPLOAD_MAX_BYTES=31457280
```

```bash
uv sync
uv run --env-file secrets.env uvicorn main:app --reload
```

## 📜 Rôles & Accès (RBAC)

Le système utilise **Zero Trust** (via Managed Identity). Voici les rôles précis requis :

| Principal | Ressource | Rôle |
| --- | --- | --- |
| Identité managée ACA | Storage Account | **Storage Blob Data Contributor** |
| Identité managée ACA | Service Bus Namespace | **Azure Service Bus Data Receiver** (Worker) & **Sender** (API) |
| Identité managée ACA | Cosmos DB (SQL) | **Cosmos DB Built-in Data Contributor** (Role `00000000-0000-0000-0000-000000000002`) |
| Identité managée ACA | AI Foundry (AIServices) | **Cognitive Services User** |
| ACA (System) | Azure Container Registry | **AcrPull** |

Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#3-sécurité--accés-rbac) pour la matrice détaillée et les IDs de rôles.


## 🔐 Variables d’environnement

| Variable | Description |
| --- | --- |
| `AZURE_SERVICE_BUS_FQDN` | Namespace Service Bus (ex: `myns.servicebus.windows.net`) |
| `AZURE_SERVICE_BUS_QUEUE` | Nom de la queue (défaut: `pdf-processing-queue`) |
| `AZURE_STORAGE_ACCOUNT_URL` | URL compte storage (ex: `https://acct.blob.core.windows.net`) |
| `AZURE_STORAGE_CONTAINER` | Container des PDFs (défaut: `pdf-inputs`) |
| `AZURE_STORAGE_ACCOUNT_KEY` | (Optionnel) clé pour générer des SAS |
| `AZURE_COSMOS_ENDPOINT` | Endpoint Cosmos DB |
| `AZURE_COSMOS_KEY` | (Optionnel si MSI) clé Cosmos |
| `AZURE_COSMOS_DB` | DB Cosmos (défaut: `emailsdb`) |
| `AZURE_COSMOS_CONTAINER` | Container Cosmos (défaut: `emails`) |
| `MISTRAL_ENDPOINT` | Endpoint Mistral MaaS |
| `MISTRAL_DEPLOYMENT` | Nom du déploiement Mistral |
| `PHI_ENDPOINT` | Endpoint Phi MaaS |
| `PHI_DEPLOYMENT` | Nom du déploiement Phi |
| `PHI_FALLBACK_ENDPOINT` | Endpoint du modèle fallback (défaut: `PHI_ENDPOINT`) |
| `PHI_FALLBACK_DEPLOYMENT` | Déploiement fallback (ex: `gpt-4o-mini`) |
| `PHI_PRIMARY_MAX_INPUT_TOKENS` | Budget tokens prompt (modèle principal) |
| `PHI_FALLBACK_MAX_INPUT_TOKENS` | Budget tokens prompt (fallback long-contexte) |
| `PHI_RESERVED_OUTPUT_TOKENS` | Tokens réservés pour la réponse JSON |
| `AZURE_AI_KEY` | (Optionnel) Clé API modèle |
| `AZURE_AI_SCOPE` | Scope token (défaut `https://cognitiveservices.azure.com/.default`) |
| `AZURE_AI_API_VERSION` | API version (défaut `2024-08-01-preview`) |
| `CHAT_ENDPOINT` | Endpoint du modèle de chat (défaut: `PHI_ENDPOINT`) |
| `CHAT_DEPLOYMENT` | Déploiement du modèle de chat (défaut: `gpt-5.2-chat`) |
| `CHAT_API_VERSION` | Version API du modèle de chat (défaut: `2024-08-01-preview`) |
| `COSMOS_QUERY_MAX_LIMIT` | Limite max résultats par requête Cosmos (défaut: `20`) |
| `FALLBACK_COST_PER_1K_INPUT` | Prix input/1K tokens (fallback) (configurable) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | (Optional) Log traces to App Insights |
| `LOG_ANALYTICS_WORKSPACE_ID` | (Optional) Configure Telemetry Logs tab in Dashboard |

> Tous les services utilisent **DefaultAzureCredential** par défaut. Accorder les rôles nécessaires :
> - Storage: `Storage Blob Data Contributor`
> - Cosmos (RBAC recommandé): rôles data-plane Cosmos SQL (contributor) + pas de clé
> - Service Bus: `Service Bus Data Receiver/Sender`
> - AI MaaS: `Cognitive Services User`

---

## 🔄 Mécaniques de reprise / erreurs

1. **Corruption PDF** : vérification `%PDF` → `ValueError`. Le message est abandonné, retry automatique Service Bus. Après `maxDeliveryCount`, message en DLQ.
2. **Erreurs IA (Mistral/Phi)** : exceptions httpx → abandon message → retry. Mettre des alertes sur DLQ.
3. **Cosmos indisponible** : abandon message → retry. Cosmos haute disposibilité.
4. **Reprocess** : vider la DLQ vers la queue principale (`az servicebus message dead-letter`).

---

## 🛠 Déploiement

1. **Terraform** : `cd infra && terraform apply`
2. **App** : Deployer le conteneur Docker sur l'instance Container App créée.
3. **Configuration** : Identité Managée de l'App avec droits `Cognitive Services User`, `Service Bus Data Receiver/Sender`, `Storage Blob Data Contributor`, `Cosmos DB Data Contributor`.

### CI/CD GitHub Actions (uv + Azure Container Apps)

Voir `.github/workflows/deploy.yml`.

Secrets requis :
- `AZURE_CREDENTIALS` : JSON service principal (Azure login)
- `AZURE_SUBSCRIPTION_ID` : Subscription ID
- `AZURE_RESOURCE_GROUP` : RG cible
- `ACR_LOGIN_SERVER` : `<acrName>.azurecr.io`
- `ACR_USERNAME` / `ACR_PASSWORD` : crédentials ACR

Image : `${ACR_LOGIN_SERVER}/classimail-agent:${GITHUB_SHA}`
Déploiement : `azure/container-apps-deploy-action@v2` ingress externe, port 8000.

---

## 🧪 Tests rapides

```bash
uv run uvicorn main:app --reload
# puis
curl -X POST http://localhost:8000/webhook/ingest -H "Content-Type: application/json" -d '[{"eventType":"Microsoft.Storage.BlobCreated","data":{"url":"https://acct.blob.core.windows.net/pdf-inputs/my.pdf"}}]'
```

---

## 📦 Outils

- `pyproject.toml` (Poetry/uv)
- `requirements.txt`
- `uv.lock`
- `.gitignore` (Python + FastAPI + data/)
