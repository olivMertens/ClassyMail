# FINE_TUNING_DATA

Ce document répond aux questions suivantes :

- quoi logger pour l'évaluation RAG vs le fine-tuning
- à quoi ressemble un bon dataset JSON/JSONL pour fine-tuner un classifieur
- comment gérer la confidentialité (PII) et l'anonymisation du contenu email + markdown OCR

## Modèles supportés pour le fine-tuning

Ce repo recommande **Phi-4 avec LoRA** comme approche principale pour le fine-tuning de la classification. Plusieurs options sont disponibles :

### Option 1 : Phi-4 avec LoRA (Recommandée) ✅

- **Contexte** : 8K tokens
- **Méthode** : LoRA (Low-Rank Adaptation) via Azure AI Foundry
- **Coûts** : Faibles (petit modèle, itération rapide)
- **Performances** : Excellent pour la classification d'emails
- **Support** : Stable, bien documenté
- **Déploiement** : `phi-4-custom` (même endpoint OpenAI Chat API)

**Pourquoi LoRA ?**
- Itération rapide (entraînement plus rapide)
- Réduction des coûts de stockage et d'inference
- Qualité comparable au fine-tuning complet pour les tâches de classification

### Option 2 : gpt-4o-mini (Alternative coût-optimisée)

- **Contexte** : 128K tokens
- **Méthode** : Fine-tuning via API Azure OpenAI
- **Coûts d'entraînement** : $0.69/1M tokens
- **Support** : Pipeline le plus mature (fév. 2026)
- **Déploiement** : `gpt-4o-mini-custom`

### Option 3 : GPT-4.1 Nano (Performance maximale)

- **Contexte** : 1M+ tokens
- **Méthode** : Fine-tuning via Azure AI Foundry
- **Coûts d'entraînement** : $0.17/1M tokens (throughput élevé)
- **Déploiement** : `gpt-4_1-nano-custom`

**Recommandation** : Commencer avec **Phi-4 LoRA** pour la rapidité d'itération, puis **comparer avec gpt-5-mini** (non fine-tunable mais qualité supérieure : 0.89) en mode adversarial pour identifier les cas limites et améliorer vos données d'entraînement.

**Stratégie de validation :**
- Fine-tune Phi-4 sur vos données validées
- Activer le mode comparaison avec gpt-5-mini comme "oracle"
- Les désaccords entre Phi-4 fine-tuné et gpt-5-mini = excellent signal pour améliorer le dataset
- gpt-5-mini (score qualité 0.89) sert de référence pour évaluer les progrès du fine-tuning

## Boucle de renforcement humain → export JSONL anonymisé

Ce repo supporte un flux "validé par humain + anonymisé" pour générer des données de fine-tuning compatible avec Phi-4, gpt-4o-mini, et GPT-4.1 Nano.

Flux de données :

- Un humain corrige/valide les intentions d'un email dans l'UI ou via l'API.
- L'app marque l'enregistrement en `reviewed=true` et stocke les `classification.detected_intents` finales.
- L'exporteur ne récupère que les enregistrements validés et lance une passe d'anonymisation sur `markdown`.
- L'exporteur écrit du **JSONL au format chat** avec :
  - `system` : consigne de classification
  - `user` : markdown OCR anonymisé
  - `assistant` : label strict JSON (ground truth)

Pourquoi anonymiser via un modèle ?
Les regex seules ratent souvent des noms, organisations, adresses, numéros de sinistre/contrat, etc. L'anonymiseur utilise GPT‑4o avec un prompt strict “préserver le markdown”.

### Marquer un item comme "reviewed"

Quand vous faites un PATCH sur un email avec des `intents` corrigés, le backend met :

- `classification.needs_review=false`
- `reviewed=true`
- `reviewed_at=<timestamp iso utc>`

### Export en ligne de commande

Depuis la racine du repo :

- `uv run python main.py --export-finetune-jsonl ./data/fine_tune.jsonl`

### Export HTTP (bouton UI)

Si vous exécutez l'application web, vous pouvez exporter directement via :

- `GET /api/emails/export-finetune-jsonl`

Cet endpoint streame du JSONL au format chat (un objet JSON par ligne, avec un tableau `messages`).
Il émet un BOM UTF‑8 et, par défaut, anonymise le markdown et impose un minimum d'exemples validés.

Contrôles :

- Minimum d'exemples : env `FINETUNE_MIN_EXAMPLES` (défaut `50`), configurable dans l'interface "Settings".
- Si le nombre d'exemples "reviewed" est inférieur à ce seuil, l'export HTTP renvoie une erreur 409 (ou désactive le bouton dans l'UI).
- Paramètres optionnels : `anonymize=true|false`, `max_examples=<n>`, `taxonomy_version=v1`, `include_metadata=true|false`

Options utiles (CLI) :

- `--max-examples 500`
- `--taxonomy-version v1`
- `--include-unreviewed` (non recommandé)
- `--no-anonymize` (NON recommandé ; risque de fuite de PII)

### Configuration requise de l'anonymiseur

Définir ces variables d'environnement pour pointer vers un endpoint/déploiement Azure OpenAI compatible :

- `ANONYMIZER_ENDPOINT`
- `ANONYMIZER_DEPLOYMENT` (défaut : `gpt-4o`)
- `ANONYMIZER_API_VERSION` (défaut : `2024-02-15-preview`)
- `ANONYMIZER_MAX_TOKENS` (défaut : `4096`)
- `ANONYMIZER_PROMPT_VERSION` (défaut : `v1`)

Optionnel :

- `FINETUNE_SYSTEM_PROMPT` (contrôle le message `system` dans le JSONL exporté)

## Génération de dataset MVP (PDFs synthétiques)

Pour le MVP/demo (pas de données de prod), le repo inclut un générateur de PDFs "email-like" volontairement bruités.
C'est pratique pour bootstrapper rapidement le pipeline et générer suffisamment d'exemples à reviewer afin de tester l'export fine-tuning.

- Script : [scripts/generate_dummy_pdfs.py](../scripts/generate_dummy_pdfs.py)
- Exécution typique : 50–100 PDFs, corps longs (~300 mots)

### Génération optionnelle via LLM

Le générateur peut créer/étendre le corps via un endpoint Azure OpenAI / Foundry compatible.

Variables d'environnement :

- `AZURE_OPENAI_ENDPOINT` (requis)
- `AZURE_OPENAI_DEPLOYMENT` (optionnel, défaut : `gpt-4o-mini`)
- `AZURE_OPENAI_API_VERSION` (optionnel)
- `AZURE_OPENAI_TIMEOUT` (optionnel)

Authentification :

- Si `AZURE_OPENAI_API_KEY` est défini, il est utilisé.
- Sinon, le script tente **Entra ID** via `DefaultAzureCredential` (ex : `az login` en local, ou Managed Identity sur Azure).
- Scope : `AZURE_OPENAI_SCOPE` (défaut : `https://cognitiveservices.azure.com/.default`).

## Distinction importante

- **RAG** : récupère des documents à l'inférence. On fine-tune moins souvent ; on évalue surtout la qualité de la recherche.
- **Fine-tuning** : apprend au modèle à produire votre format cible (ici : JSON strict multi-intentions).

Pour ce repo, la valeur principale est généralement :

1) une meilleure cohérence de classification
2) moins de cas “needs_review”

## Quoi logger (recommandé)

### A) Logs pour l'évaluation RAG / retrieval

Stocker un enregistrement par requête :

- `request_id`, `timestamp`, `tenant`, `environment`
- `user_query` (anonymisé)
- `retrieved_docs` : tableau de
  - `doc_id`
  - `chunk_id`
  - `source`
  - `score`
  - `snippet` (optionnel ; anonymisé)
- `final_prompt_template_version`
- `model` : nom/déploiement
- `response` : sortie du modèle (anonymisée)
- `labels` : feedback humain optionnel
  - `answer_correct` (bool)
  - `missing_context` (bool)
  - `hallucination` (bool)

### B) Dataset de fine-tuning (classification)

Ici, on veut des *labels ground truth*.

Champs recommandés :

- `example_id`
- `input_markdown` (markdown OCR anonymisé)
- `target_json` (sortie JSON strict attendue)
- `metadata`
  - `language`
  - `num_pages`
  - `source_channel` (email/import)
  - `policy_version` (version de la taxonomie)

## Format de dataset (JSONL)

La plupart des systèmes de fine-tuning attendent du **JSONL** : un objet JSON par ligne.

### JSONL au format chat (recommandé)

```json
{"messages":[
  {"role":"system","content":"Tu classes des emails d'assurance en intentions et tu renvoies uniquement du JSON strict."},
  {"role":"user","content":"<MARKDOWN OCR ANONYMISÉ ICI>"},
  {"role":"assistant","content":"{\"detected_intents\":[...],\"global_complexity\":\"Simple\"}"}
],"metadata":{"taxonomy_version":"v1","language":"fr"}}
```

Référence :

- Doc fine-tuning Azure AI Foundry/Azure OpenAI : https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning?view=foundry-classic&tabs=oai-sdk%2Cazure-openai&pivots=programming-language-python
- Tutoriel officiel (GPT-4o-mini, end-to-end) : https://learn.microsoft.com/en-us/azure/ai-foundry/openai/tutorials/fine-tune?view=foundry-classic&tabs=command-line

## Pourquoi 2 fichiers JSONL (train + validation) ?

Dans Azure AI Foundry / Azure OpenAI, un job de fine-tuning attend typiquement :

- un fichier **training_set.jsonl** (apprentissage)
- un fichier **validation_set.jsonl** (évaluation pendant l'entraînement)

Le format de chaque ligne reste identique (chat JSONL avec `{"messages": [...]}`), c'est juste la **séparation** des exemples.

Recommandations :

- Split simple : **90/10** (train/validation) ou **95/5** si vous avez peu d'exemples.
- La validation doit être représentative (toutes les intentions, différentes longueurs OCR, etc.).
- Garder la validation **figée** (même split) pour comparer les runs.

### Comment produire les 2 fichiers depuis ce repo

1) Exporter un fichier complet (anonymisé + reviewed uniquement) :

- CLI : `uv run python main.py --export-finetune-jsonl ./data/fine_tune_all.jsonl`

ou

- HTTP : `GET /api/emails/export-finetune-jsonl` puis sauvegarder le flux dans `./data/fine_tune_all.jsonl`.

2) Splitter en train/validation (exemple Python reproductible) :

```bash
uv run python - <<'PY'
import random
from pathlib import Path

src = Path('data/fine_tune_all.jsonl')
train = Path('data/training_set.jsonl')
val = Path('data/validation_set.jsonl')

lines = src.read_text(encoding='utf-8-sig').splitlines()
lines = [l for l in lines if l.strip()]

rng = random.Random(42)
rng.shuffle(lines)

split = int(len(lines) * 0.9)
train.write_text('\n'.join(lines[:split]) + '\n', encoding='utf-8')
val.write_text('\n'.join(lines[split:]) + '\n', encoding='utf-8')

print(f'total={len(lines)} train={split} val={len(lines)-split}')
PY
```

Ensuite, utilisez `data/training_set.jsonl` et `data/validation_set.jsonl` dans Foundry/Azure OpenAI (upload + job de fine-tune).

## Lancer un job de fine-tuning Phi-4 avec LoRA

### Via Azure AI Foundry (Interface graphique)

1. **Créer les datasets** :
   - Dans Foundry, naviguer vers votre projet
   - Sélectionner "Fine-tuning" > "Datasets"
   - Uploader `training_set.jsonl` et `validation_set.jsonl`

2. **Configurer le job LoRA** :
   - Modèle de base : `Phi-4`
   - Méthode : `LoRA`
   - Paramètres recommandés :
     - `lora_rank`: 8 ou 16 (8 pour commencer)
     - `epochs`: 3-5 (3 pour commencer)
     - `batch_size`: 4-8
     - `learning_rate`: 1e-4 ou 2e-5

3. **Lancer l'entraînement** :
   - La durée dépend du nombre d'exemples (~10-30 min pour 50-200 exemples)
   - Surveiller les métriques de validation (accuracy, loss)

4. **Déployer le modèle custom** :
   - Une fois terminé, déployer vers un endpoint
   - Nom de déploiement : `phi-4-custom` (ou votre choix)
   - Mettre à jour `PHI_DEPLOYMENT=phi-4-custom` dans votre config

### Via Azure CLI / SDK (Automatisation)

```bash
# Créer un job de fine-tuning
az ml job create --file fine-tune-job.yml --workspace-name <workspace> --resource-group <rg>
```

Exemple de fichier `fine-tune-job.yml` :
```yaml
type: fine_tuning
model: Phi-4
method: lora
training_data: azureml:training_set:1
validation_data: azureml:validation_set:1
hyperparameters:
  lora_rank: 8
  epochs: 3
  batch_size: 4
  learning_rate: 1e-4
```

### Comparaison avec gpt-4o-mini fine-tuning

Si vous voulez comparer les performances :

```python
# Fine-tuning gpt-4o-mini via Azure OpenAI SDK
from openai import AzureOpenAI

client = AzureOpenAI(
    azure_endpoint="https://<resource>.openai.azure.com",
    api_version="2024-08-01-preview"
)

job = client.fine_tuning.jobs.create(
    training_file="file-abc123",  # ID du fichier uploadé
    validation_file="file-def456",
    model="gpt-4o-mini",
    hyperparameters={
        "n_epochs": 3,
        "batch_size": 4
    }
)
```

## Confidentialité & anonymisation

### Est-ce un problème si l'email doit être totalement anonyme ?

Non : ce n'est pas seulement "ok" — c'est souvent une **exigence**.

Approche recommandée :

- Retirer les identifiants directs : noms, emails, téléphones, adresses, numéros de contrat, IBAN, numéros de sinistre.
- Remplacer par des placeholders cohérents pour préserver la structure :
  - `John Doe` → `[PERSON_1]`
  - `john@example.com` → `[EMAIL_1]`
  - `+33 6 ...` → `[PHONE_1]`
  - `FR76 ...` → `[IBAN_1]`
- Conserver les signaux utiles à l'intention : type de produit, type de demande, dates (éventuellement généralisées), description de l'évènement.

### Outillage pratique

- Utiliser une redaction déterministe (même token → même placeholder) pour garder la cohérence intra-exemple.
- Conserver une table de mapping séparée si vous avez besoin de réversibilité (souvent non nécessaire).

## Références Fine-Tuning

### Phi-4 & LoRA
- Phi Cookbook (community) : https://github.com/microsoft/PhiCookBook
- Guide Foundry Local (Phi‑4 local) : https://techcommunity.microsoft.com/blog/educatordeveloperblog/running-phi-4-locally-with-microsoft-foundry-local-a-step-by-step-guide/4466304
- LoRA Paper : https://arxiv.org/abs/2106.09685

### Azure AI Foundry & Azure OpenAI
- Fine-Tuning Guide (officiel) : https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning?view=foundry-classic&tabs=oai-sdk%2Cazure-openai&pivots=programming-language-python
- Tutoriel End-to-End (gpt-4o-mini) : https://learn.microsoft.com/en-us/azure/ai-foundry/openai/tutorials/fine-tune?view=foundry-classic&tabs=command-line
- Azure OpenAI Fine-Tuning : https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/fine-tuning

### Best Practices
- Data Quality > Data Quantity (50-200 exemples bien validés suffisent souvent)
- Toujours anonymiser les données sensibles (PII)
- Maintenir un validation set fixe pour comparer les runs
- Monitorer les métriques de validation (overfitting si train >> val)
- Tester le modèle fine-tuné avec le fallback activé (sécurité)
