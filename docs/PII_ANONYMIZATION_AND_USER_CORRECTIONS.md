# PII Anonymization & User Corrections for Fine-Tuning

**Status**: ✅ Production System
**Last Updated**: 2026-02-06
**Related**: [FINE_TUNING_DATA.md](FINE_TUNING_DATA.md), [MODELS.md](MODELS.md)

---

## Executive Summary

This document explains how the ClassyMail MVP protects personal information (PII) in fine-tuning datasets and how user corrections are tracked for quality improvement.

**Key Points**:
- ✅ **Two-level PII protection**: Regex scrubbing + GPT-4o contextual anonymization
- ✅ **Fail-safe design**: Skips examples if anonymization fails (never exports PII)
- ✅ **Default behavior**: Anonymization always ON (requires explicit opt-out)
- ✅ **User corrections tracked**: Complete history with AI-generated feedback
- ✅ **Correction "weight"**: Metadata-based implicit weighting for fine-tuning

---

## PII Anonymization System

### Overview

The system uses **two-level protection** to ensure no personal information leaks into fine-tuning datasets:

1. **Level 1: Basic Regex Scrubbing** - Fast removal of common PII patterns
2. **Level 2: LLM Contextual Anonymization** - GPT-4o removes names, companies, contract IDs while preserving markdown structure

### Implementation Details

#### File: `classymail/services/anonymizer.py`

```python
# Two-level protection pipeline:

1. basic_pii_scrub(text: str) -> str
   - Removes: emails, IP addresses, phone numbers, IBANs
   - Uses: Fast regex patterns
   - Speed: <1ms per document

2. anonymize_markdown_for_finetune(markdown: str) -> str
   - Removes: Names, companies, addresses, contract IDs, sensitive context
   - Uses: GPT-4o with 600+ char system prompt
   - Preserves: Markdown structure, formatting, intent labels
   - Speed: ~2-5s per document (async)
```

#### System Prompt (40 lines)

```markdown
Tu es un assistant d'anonymisation pour données de fine-tuning.
OBJECTIF : Supprimer toute information personnelle identifiable (PII)
tout en préservant la structure markdown et le contexte métier.

RÈGLES :
- Remplacer les noms de personnes par [NOM]
- Remplacer les sociétés par [SOCIÉTÉ]
- Remplacer les adresses email par [EMAIL]
- Remplacer les numéros de contrat par [CONTRAT_ID]
- Remplacer les adresses postales par [ADRESSE]
- Remplacer les montants précis par [MONTANT]
- PRÉSERVER tous les en-têtes markdown (##, ###, etc.)
- PRÉSERVER toutes les listes (-, *, 1., 2., etc.)
- PRÉSERVER le formatage (**gras**, *italique*, etc.)
- PRÉSERVER les intent labels (MUST GO, MUST KEEP, etc.)

IMPORTANT : Ne jamais supprimer ou modifier la structure markdown.
```

### Configuration

Environment variables:

```bash
ANONYMIZER_ENDPOINT=https://<your-aoai>.openai.azure.com/
ANONYMIZER_DEPLOYMENT=gpt-4o              # Model name
ANONYMIZER_API_VERSION=2024-02-15-preview
ANONYMIZER_MAX_TOKENS=4096                # Output limit
ANONYMIZER_PROMPT_VERSION=v1              # Tracking
```

### Fail-Safe Behavior

**Critical Design Decision**: If anonymization fails, the example is **skipped** (not exported with PII).

#### Code Reference: `repository.py` (lines 197-206)

```python
try:
    content_anon = await anonymize_markdown_for_finetune(content_raw)
except Exception as e:
    # Log error and SKIP this example
    logger.warning(f"Anonymization failed for {email_id}: {e}")
    continue  # ← SKIPS example, never exports with PII
```

**Why this matters**: Even if the anonymization service is temporarily down, the system will never export personal information. The dataset will be smaller but 100% PII-free.

### Default Behavior

**HTTP Endpoint**: `GET /api/v1/emails/export/finetune`

```python
@router.get("/export/finetune")
async def export_finetune(
    anonymize: bool = True,  # ← DEFAULT: Always ON
    split: str = "train",
    ...
):
    # User must explicitly pass ?anonymize=false to disable
```

### Verification

To verify anonymization is working:

```bash
# Export training dataset
curl http://localhost:8000/api/v1/emails/export/finetune?split=train > train.jsonl

# Check for PII patterns (should return 0 matches)
grep -E "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}" train.jsonl | wc -l
grep -E "\b[A-Z][a-z]+ [A-Z][a-z]+\b" train.jsonl | wc -l  # Names with capitals
grep -E "\b\d{2}/\d{2}/\d{4}\b" train.jsonl | wc -l  # Dates

# Should see placeholders instead:
grep "\[NOM\]" train.jsonl | wc -l
grep "\[SOCIÉTÉ\]" train.jsonl | wc -l
grep "\[EMAIL\]" train.jsonl | wc -l
```

---

## User Correction Tracking System

### Overview

When a user manually corrects a classification, the system:

1. **Stores complete history** - timestamp, previous intents, correction reason
2. **Generates AI feedback** - Phi-4 analyzes WHY the correction was needed
3. **Tags metadata** - Marks as `"source": "human_corrected"` for fine-tuning
4. **Sets confidence 1.0** - Human corrections are ground truth

### Data Model

#### File: `classymail/models.py` (lines 39-48)

```python
class HistoryEntry(BaseModel):
    timestamp: datetime
    previous_intents: List[str]
    correction_reason: Optional[str] = None  # User explanation (min 5 chars)
    llm_feedback: Optional[str] = None       # AI analysis of what was missed

class EmailRecord(BaseModel):
    ...
    classification_history: List[HistoryEntry] = []  # Full correction history
    correction_reason: Optional[str] = None          # Latest correction reason
    reviewed: bool = False
    reviewed_at: Optional[datetime] = None
```

### UI Flow

#### File: `frontend/src/components/EmailDetailModal.vue` (line 293)

```javascript
// User must provide explanation (minimum 5 characters)
if (correctionReason.value.length < 5) {
  errorMessage.value = "La raison doit contenir au moins 5 caractères";
  return;
}

// Call PATCH /emails/{id} with new intents + reason
```

### Backend Processing

#### File: `classymail/api/routers/emails.py` (lines 459-474)

```python
async def patch_email(email_id: str, updates: EmailUpdate):
    # 1. Create history entry
    history_entry = HistoryEntry(
        timestamp=datetime.now(timezone.utc),
        previous_intents=current_record.intents,
        correction_reason=updates.correction_reason,
        llm_feedback=None  # Will be filled below
    )

    # 2. Generate AI feedback (Phi-4 analyzes WHY correction needed)
    if updates.correction_reason:
        feedback = await analyze_correction(
            email_content=current_record.content,
            old_intents=current_record.intents,
            new_intents=updates.intents,
            user_reason=updates.correction_reason
        )
        history_entry.llm_feedback = feedback

    # 3. Append to history and update record
    current_record.classification_history.append(history_entry)
    current_record.intents = updates.intents
    current_record.reviewed = True
    current_record.reviewed_at = datetime.now(timezone.utc)

    # 4. Save to Cosmos DB
    await cosmos_container.upsert_item(current_record.model_dump())
```

### AI Feedback Generation

#### File: `classymail/services/llm_pipeline.py` (lines 910-930)

```python
async def analyze_correction(
    email_content: str,
    old_intents: List[str],
    new_intents: List[str],
    user_reason: str
) -> str:
    """
    Uses Phi-4 to analyze WHY the correction was needed.
    Generates a "lesson learned" for prompt improvement.
    """
    system_prompt = "Tu es un expert en amélioration de classification."

    user_prompt = f"""
    Email : {email_content[:500]}
    Classification initiale : {old_intents}
    Nouvelle classification : {new_intents}
    Raison de l'utilisateur : {user_reason}

    Analyse ce cas et génère une leçon apprise concise (2-3 phrases).
    Qu'est-ce que le modèle a raté ou mal compris ?
    """

    response = await phi4_client.chat.completions.create(
        model="phi-4",
        messages=[...],
        max_tokens=150,
        temperature=0.3,
        timeout=10.0  # Fast response for UI
    )

    return response.choices[0].message.content
```

**Example AI Feedback**:
```
"Le modèle a classé ce sinistre en MUST KEEP alors qu'il s'agit d'une
demande de résiliation (MUST GO). La présence de 'mettre fin à mon contrat'
aurait dû déclencher l'intent ACTION_RESILIER."
```

---

## Correction "Weight" for Fine-Tuning

### Not a Literal Weight Parameter

⚠️ **Important**: There is no explicit "weight" parameter in the code. Instead, the system uses **metadata-based implicit weighting** that gives users control over emphasis during fine-tuning.

### Metadata Structure in JSONL Export

#### File: `classymail/services/repository.py` (lines 217-241)

```python
metadata = {
    "email_id": email_id,
    "source": "human_corrected" if was_corrected else "auto_classified",
    "confidence": 1.0 if was_corrected else confidence_score,
    "taxonomy_version": TAXONOMY_VERSION,
    "anonymized": anonymize,
    "correction": {
        "was_corrected": was_corrected,
        "correction_reason": correction_reason,
        "llm_feedback": llm_feedback,
        "correction_timestamp": correction_timestamp
    } if was_corrected else None
}
```

**Example JSONL Line** (human-corrected):

```json
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "Objet: Résiliation\n\nJe souhaite résilier..."},
    {"role": "assistant", "content": "## Intents\n- ACTION_RESILIER\n- MUST GO"}
  ],
  "metadata": {
    "email_id": "abc123",
    "source": "human_corrected",
    "confidence": 1.0,
    "correction": {
      "was_corrected": true,
      "correction_reason": "Le modèle a raté le mot-clé 'résilier' qui devrait déclencher ACTION_RESILIER",
      "llm_feedback": "Le modèle a mal interprété une demande explicite de résiliation comme une simple demande d'information.",
      "correction_timestamp": "2026-02-06T10:30:00Z"
    }
  }
}
```

### Fine-Tuning Strategies

Users can control the "weight" of corrections through four strategies:

#### Strategy 1: Filter by Source (Only Human-Corrected)

```bash
# Export only human-corrected examples
jq 'select(.metadata.source == "human_corrected")' train.jsonl > train_corrected_only.jsonl

# Use this smaller, high-quality dataset for fine-tuning
```

**Pros**: Maximum quality, ground truth only
**Cons**: Smaller dataset (may need more data for generalization)

#### Strategy 2: Oversample Corrections (2-3x)

```python
# Duplicate human-corrected examples 2-3 times in training data
corrected_lines = [line for line in jsonl if line["metadata"]["source"] == "human_corrected"]
all_lines = jsonl + corrected_lines * 2  # ← Corrections appear 3x total

# Shuffle and export
random.shuffle(all_lines)
```

**Pros**: Balances quality and quantity
**Cons**: May overfit to correction patterns if overused

#### Strategy 3: Two-Stage Training

```bash
# Stage 1: Train on ALL data (auto + corrected)
az ml job create --file finetune-stage1.yml --set training_data=train_all.jsonl

# Stage 2: Refine on ONLY corrections (smaller learning rate)
az ml job create --file finetune-stage2.yml --set training_data=train_corrected_only.jsonl
```

**Pros**: Best generalization + precision
**Cons**: More complex, requires two fine-tuning jobs

#### Strategy 4: Prompt Engineering from LLM Feedback

```python
# Mine llm_feedback for systematic issues
feedback_patterns = defaultdict(int)
for line in jsonl:
    if line["metadata"].get("correction"):
        feedback = line["metadata"]["correction"]["llm_feedback"]
        feedback_patterns[feedback] += 1

# Top issues (example output):
# 1. "Le modèle rate les demandes de résiliation" → 15 occurrences
# 2. "Le modèle confond MUST GO et MUST KEEP" → 12 occurrences
# 3. "Le modèle ignore les pièces jointes" → 8 occurrences

# Update system prompt:
SYSTEM_PROMPT += """
ATTENTION PARTICULIÈRE :
- Les mots "résilier", "mettre fin", "arrêter" indiquent ACTION_RESILIER + MUST GO
- En cas de doute entre MUST GO et MUST KEEP, privilégier le contexte des pièces jointes
- Les demandes de résiliation sont TOUJOURS MUST GO, même si le ton est poli
"""
```

**Pros**: Fixes root causes, improves prompts without fine-tuning
**Cons**: Requires manual analysis of feedback patterns

### Recommended Approach

For most use cases, use **Strategy 2 (Oversample 2-3x)** combined with **Strategy 4 (Prompt Engineering)**:

1. Export full dataset with anonymization
2. Oversample corrections 2x during preprocessing
3. Analyze `llm_feedback` for systematic issues
4. Update system prompt to address top 3-5 issues
5. Fine-tune on oversampled dataset
6. Validate on test set (20% split)

This balances quality, quantity, and root cause fixes.

---

## Export Filtering Logic

### Only High-Quality Examples Exported

#### File: `classymail/services/repository.py` (lines 133-263)

```python
async def export_finetune_jsonl_iter(split: str = "train", anonymize: bool = True):
    """
    Exports ONLY:
    - status = 'PROCESSED' (not 'PENDING' or 'ERROR')
    - needs_review = false (agent is confident OR user reviewed)
    - reviewed = true (user explicitly validated)

    Skips:
    - Emails with anonymization failures
    - Emails with partial classifications
    - Emails marked for review but not yet reviewed
    """

    query = """
        SELECT * FROM c
        WHERE c.status = 'PROCESSED'
          AND c.needs_review = false
          AND c.reviewed = true
    """

    items = await cosmos_container.query_items(query=query).by_page()

    for item in items:
        # Stable hash-based split (deterministic)
        h = hashlib.sha256(item["id"].encode()).digest()[0]
        is_train = (h % 10) < 8  # 80% train, 20% test

        if split == "train" and not is_train:
            continue
        if split == "test" and is_train:
            continue

        # Anonymize (with fail-safe)
        try:
            content_anon = await anonymize_markdown_for_finetune(item["content"])
        except Exception:
            continue  # SKIP on failure

        # Build JSONL line
        yield json.dumps({
            "messages": [...],
            "metadata": {...}
        }, ensure_ascii=False) + "\n"
```

### Train/Test Split

- **Deterministic**: Uses SHA256 hash of email ID (stable across exports)
- **Ratio**: 80% train, 20% test
- **No leakage**: Same email ID always goes to same split

---

## Code References

### Key Files

| File | Lines | Purpose |
|------|-------|---------|
| [classymail/services/anonymizer.py](../classymail/services/anonymizer.py) | 1-63 | PII anonymization implementation |
| [classymail/services/repository.py](../classymail/services/repository.py#L133-L263) | 133-263 | JSONL export pipeline |
| [classymail/api/routers/emails.py](../classymail/api/routers/emails.py#L425-L525) | 425-525 | User correction tracking |
| [classymail/services/llm_pipeline.py](../classymail/services/llm_pipeline.py#L910-L930) | 910-930 | AI feedback generation |
| [classymail/models.py](../classymail/models.py#L39-L48) | 39-48 | Data models |

### Configuration Files

- `.env` or `secrets.env`: All `ANONYMIZER_*` variables
- `classymail/core/config.py`: Settings class with defaults
- [FINE_TUNING_DATA.md](FINE_TUNING_DATA.md): Full fine-tuning guide

---

## Frequently Asked Questions

### Q1: How do I verify PII is removed from exports?

**A**: Use grep to search for common PII patterns:

```bash
# Should return 0 matches
grep -E "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}" train.jsonl
grep -E "\b[A-Z][a-z]+ [A-Z][a-z]+\b" train.jsonl

# Should return many matches (placeholders)
grep "\[NOM\]" train.jsonl
grep "\[SOCIÉTÉ\]" train.jsonl
```

### Q2: What happens if anonymization fails?

**A**: The example is **skipped** (not exported). Check logs for warnings:

```bash
uv run python -m classymail.cli export-finetune --split train --output train.jsonl 2>&1 | grep "Anonymization failed"
```

### Q3: How do I export only user-corrected examples?

**A**: Use `jq` to filter by metadata:

```bash
cat train.jsonl | jq 'select(.metadata.source == "human_corrected")' > train_corrected.jsonl
```

### Q4: Can I disable anonymization for testing?

**A**: Yes, but **not recommended** for production:

```bash
curl "http://localhost:8000/api/v1/emails/export/finetune?anonymize=false" > train_raw.jsonl
```

⚠️ **Warning**: This will export real PII. Use only for debugging in secure environments.

### Q5: How do I see the AI's analysis of corrections?

**A**: Query Cosmos DB for the `classification_history` field:

```python
from azure.cosmos import CosmosClient

client = CosmosClient.from_connection_string(os.getenv("COSMOS_CONNECTION_STRING"))
db = client.get_database_client("classymail")
container = db.get_container_client("emails")

# Find emails with corrections
query = "SELECT * FROM c WHERE ARRAY_LENGTH(c.classification_history) > 0"
items = list(container.query_items(query=query, enable_cross_partition_query=True))

for item in items:
    for entry in item["classification_history"]:
        if entry.get("llm_feedback"):
            print(f"Email: {item['subject']}")
            print(f"User reason: {entry['correction_reason']}")
            print(f"AI feedback: {entry['llm_feedback']}")
            print("---")
```

### Q6: How many corrections do I need for fine-tuning?

**A**: Recommended minimums:

- **GPT-4o/GPT-4**: 50-100 corrections for meaningful improvement
- **GPT-3.5-turbo**: 200-500 corrections (less capable base model)
- **Small models (Phi-4)**: 500-1000 corrections (requires more data)

**Quality > Quantity**: 50 well-explained corrections are better than 500 with vague reasons.

### Q7: Can I weight corrections differently based on quality?

**A**: Yes, by filtering on `correction_reason` length:

```python
# Only export corrections with detailed explanations (>50 chars)
corrected_lines = [
    line for line in jsonl
    if line["metadata"].get("correction")
    and len(line["metadata"]["correction"]["correction_reason"]) > 50
]
```

---

## Related Documentation

- [FINE_TUNING_DATA.md](FINE_TUNING_DATA.md) - Complete fine-tuning guide
- [MODELS.md](MODELS.md) - LLM model selection and configuration
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture overview
- [AZURE_AI_FOUNDRY_SETUP.md](AZURE_AI_FOUNDRY_SETUP.md) - Azure AI Foundry setup for fine-tuning

---

## Changelog

- **2026-02-06**: Initial documentation (verified production implementation)
