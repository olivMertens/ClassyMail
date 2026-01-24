# FINE_TUNING_DATA

Ce document répond aux questions suivantes :

- quoi logger pour l'évaluation RAG vs le fine-tuning
- à quoi ressemble un bon dataset JSON/JSONL pour fine-tuner un classifieur
- comment gérer la confidentialité (PII) et l'anonymisation du contenu email + markdown OCR

## Boucle de renforcement humain → export JSONL anonymisé

Ce repo supporte un flux “validé par humain + anonymisé” pour générer des données de fine-tuning Phi.

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

- Minimum d'exemples : env `FINETUNE_MIN_EXAMPLES` (défaut `50`) ou query param `min_required`
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

## Génération de dataset POC (PDFs synthétiques)

Pour le POC/demo (pas de données de prod), le repo inclut un générateur de PDFs “email-like” volontairement bruités.
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

## Références Phi‑4 / Foundry

- Phi Cookbook (community) : https://github.com/microsoft/PhiCookBookfin
- Guide Foundry Local (Phi‑4 local) : https://techcommunity.microsoft.com/blog/educatordeveloperblog/running-phi-4-locally-with-microsoft-foundry-local-a-step-by-step-guide/4466304
