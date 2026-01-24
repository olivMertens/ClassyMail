
# POC Classification Emails : Azure AI Foundry & Mistral + FastAPI Dashboard

## 📚 Documentation

- [Docs home](docs/INDEX.md)
- [ARCHITECTURE](docs/ARCHITECTURE.md)
- [PIPELINE](docs/PIPELINE.md)
- [TERRAFORM](docs/TERRAFORM.md)
- [MODELS](docs/MODELS.md)
- [FINE_TUNING_DATA](docs/FINE_TUNING_DATA.md)
- [CICD_GITHUB](docs/CICD_GITHUB.md)
- [CICD_GITLAB](docs/CICD_GITLAB.md)
- [LOCAL_RUN](docs/LOCAL_RUN.md)

## 🔗 References

- Pricing (Azure AI Foundry models): https://azure.microsoft.com/fr-fr/pricing/details/ai-foundry-models/microsoft/
- Fine-tuning (Azure AI Foundry / Azure OpenAI): https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning?view=foundry-classic&tabs=oai-sdk%2Cazure-openai&pivots=programming-language-python
- Phi Cookbook (community): https://github.com/microsoft/PhiCookBookfin
- Running Phi-4 locally (Foundry Local guide): https://techcommunity.microsoft.com/blog/educatordeveloperblog/running-phi-4-locally-with-microsoft-foundry-local-a-step-by-step-guide/4466304

Ce projet implémente un pipeline de classification d'emails à haut volume et faible latence, capable de gérer des pics de charge (10k fichiers simultanés) grâce à une architecture événementielle découplée, avec un backend FastAPI et un frontend SPA (Vue 3 + Tailwind).

```mermaid
flowchart TD
    user[User] -->|Upload PDF| blob[(Blob Storage)]
    blob -->|Event Grid| sbq[Service Bus Queue]
    sbq -->|Worker| api[FastAPI Worker/API]
    api -->|Download PDF| blob
    api -->|OCR (document_base64)| ocr[Mistral OCR]
    ocr -->|Markdown| api
    api -->|Classify intents| llm[Phi-4 (primary)\\nFallback: gpt-4o-mini]
    llm -->|JSON| api
    api -->|Persist| cosmos[(Cosmos DB)]
    api -->|Dashboard UI| user
```

## 🚀 Composants Clés

| Composant | Service Azure | Rôle |
| :--- | :--- | :--- |
| **Ingestion** | Blob Storage | Stockage brut des PDF (froid). |
| **Buffer** | Service Bus | File d'attente pour lisser la charge (évite les 429 sur l'IA). |
| **OCR** | **Mistral Document AI** | Extraction structurelle (Markdown) à faible coût (~1$/1k pages). |
| **Cerveau** | **Phi-4** | Raisonnement et classification des intentions. |
| **Compute** | Container Apps | Hébergement du code Python (FastAPI) avec auto-scaling KEDA. |
| **Mémoire** | Cosmos DB | Stockage des résultats JSON et suivi de l'état (Processed/Review). |
| **Dashboard** | FastAPI + Vue 3 | SPA pour review/validation et recherche. |

## ♻️ Reinforcement Loop & Fine-Tuning Phi-4

### Stratégie Fine-Tuning (20 catégories)
- **Pertinence** : Oui, le prompt seul ne suffit plus (contexte long, confusions).
- **Données** : 50–100 exemples/catégorie ⇒ **1000–2000** emails.
- **Technique** : **LoRA** (30–60 min, low cost).
- **Workflow** :
    1. Zero-shot (Phi-4 base)
    2. Corrections humaines (Dashboard)
    3. `reviewed:true` dans Cosmos DB
    4. Export JSONL hebdo vers Foundry
    5. Fine-tune ⇒ `Phi-4-Custom-v1`
    6. Déploiement
- **ROI** : Précision **~85% ➜ >98%**, coût inference ~identique, validation humaine réduite.

### Prompt Multi-Intents (Phi-4)
```python
system_prompt = """
Tu es un assistant expert en classification d'emails d'assurance.
Ta tâche est d'analyser le contenu de l'email (fourni en markdown) et d'identifier TOUTES les intentions présentes.
LISTE DES INTENTIONS POSSIBLES :
1. Attestation habitation
2. Attestation scolaire
3. Relevé de compte
4. Dommages électriques
5. Événements naturels
FORMAT JSON UNIQUEMENT :
{
    "detected_intents": [
        {"intent": "...", "confidence": 0.95, "justification": "..."}
    ],
    "global_complexity": "Simple|Complexe"
}
"""
```

### Décision `needs_review`
- Aucune intention ➜ review
- Confidence < 0.85 ➜ review
- >3 intentions ➜ review

### Reinforcement Loop
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
python scripts/generate_dummy_pdfs.py --count 75 --target-words 300
python scripts/generate_dummy_pdfs.py --count 100 --target-words 320 --out dataset/pdf
```

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

- SB + `Semaphore(5)`, `%PDF` check → base64
- **Mistral OCR** `document_base64`
- **Phi-4 multi-intents** JSON
- `needs_review` via règles (scores, intents count)
- Cosmos upsert
- **OCR fail** → DLQ, sinon abandon/retry

### Export CSV

- CLI : `python main.py --export-csv data/output.csv`
- Colonnes : `intents`, `needs_review`, `global_complexity`

---

## 💻 Frontend SPA (Vue 3 + Tailwind)

- Route `/` sert `templates/index.html` (une seule page) :
    - Header stats (total, à valider)
    - Onglets `Tout`, `🔴 À Valider`, `✅ Traités`
    - Recherche temps réel
    - Grille de cartes (sujet, expéditeur, date, badge score couleur)
    - Modale plein écran : PDF (iframe SAS), markdown rendu, formulaire de correction + bouton valider

---

## 🔧 Installation & Exécution

### Avec uv
```bash
uv lock
uv sync
uv run uvicorn main:app --reload
```

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
```

### CI/CD

CI/CD setup lives in:
- GitHub Actions: [docs/CICD_GITHUB.md](docs/CICD_GITHUB.md)
- GitLab CI: [docs/CICD_GITLAB.md](docs/CICD_GITLAB.md)

See the docs for the full YAML examples, authentication options (OIDC vs secrets), and recommended environment protections.


---

## ✨ Fonctionnalités Clés
- Ingestion Event Grid → Service Bus → Worker async (`Semaphore(5)`).
- OCR Mistral (`/v1/ocr` MaaS, `document_base64`), fallback inference `{deployment}:ocr`.
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

## 🛠 Fine-tuning Phi‑4 (LoRA) avec Microsoft Foundry
1. **Collecte** : `needs_review=false` (validations humaines) dans Cosmos DB.
2. **Export JSONL** : `python main.py --export-csv` (adapter exporter JSONL si besoin).
3. **Foundry** :
     - Créer Dataset JSONL dans le **Project**.
     - Lancer Fine-tune LoRA sur `phi-4` (Foundry UI ou CLI) avec dataset (1000–2000 exemples, 50–100/catégorie).
     - Déployer `phi-4-custom` (endpoint compatible OpenAI Chat).
4. **Configuration** : mettre `PHI_DEPLOYMENT=phi-4-custom` et `PHI_ENDPOINT` du Foundry Hub.

## 🧱 Terraform (Foundry)
- `infra/main.tf` : crée **Foundry** (AIServices), **Project**, **Deployments** (`phi-4`, `mistral-ocr-2505`), **RBAC** `Cognitive Services User` pour l'identité `app_id`.
- Commandes :
    ```bash
    terraform init -upgrade
    terraform plan -out main.tfplan
    terraform apply main.tfplan
    ```

## 🔐 Lancement local (uv)
Créer `secrets.env` :
```
AZURE_SERVICE_BUS_FQDN=...
AZURE_SERVICE_BUS_QUEUE=pdf-processing-queue
AZURE_STORAGE_ACCOUNT_URL=...
AZURE_STORAGE_CONTAINER=pdf-inputs
AZURE_COSMOS_ENDPOINT=...
AZURE_COSMOS_KEY=...
MISTRAL_ENDPOINT=...
MISTRAL_DEPLOYMENT=mistral-ocr-2505
MISTRAL_MODE=maas
PHI_ENDPOINT=...
PHI_DEPLOYMENT=phi-4
PHI_FALLBACK_ENDPOINT=...
PHI_FALLBACK_DEPLOYMENT=gpt-4o-mini
PHI_PRIMARY_MAX_INPUT_TOKENS=8000
PHI_FALLBACK_MAX_INPUT_TOKENS=120000
PHI_RESERVED_OUTPUT_TOKENS=1000
PHI4_COST_PER_1K_INPUT=0.000107
PHI4_COST_PER_1K_OUTPUT=0.00043
FALLBACK_COST_PER_1K_INPUT=0
FALLBACK_COST_PER_1K_OUTPUT=0
MISTRAL_OCR_COST_PER_1K_PAGES=1.0
OTEL_EXPORTER_OTLP_ENDPOINT=...
```

```bash
uv sync
uv run --env-file secrets.env uvicorn main:app --reload
```

## 📜 Rôles & Accès (RBAC)

| Principal | Ressource | Rôle |
| --- | --- | --- |
| Identité managée ACA | Storage Account | Storage Blob Data Reader |
| Identité managée ACA | Service Bus Namespace | Azure Service Bus Data Receiver/Sender |
| Identité managée ACA | Cosmos DB (SQL) | Cosmos SQL Built-in Data Contributor (RBAC) |
| Identité managée ACA | AI Foundry (AIServices) | Cognitive Services User |
| Event Grid | Service Bus Queue | Event delivery via system topic subscription |
| ACA (pull image) | Azure Container Registry | AcrPull |


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
| `FALLBACK_COST_PER_1K_INPUT` | Prix input/1K tokens (fallback) (configurable) |
| `FALLBACK_COST_PER_1K_OUTPUT` | Prix output/1K tokens (fallback) (configurable) |

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

1.  **Terraform** : `cd infra && terraform apply`
2.  **App** : Deployer le conteneur Docker sur l'instance Container App créée.
3.  **Configuration** : Identité Managée de l'App avec droits `Cognitive Services User`, `Service Bus Data Receiver/Sender`, `Storage Blob Data Contributor`, `Cosmos DB Data Contributor`.

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

