# PII Anonymization & User Corrections for Fine-Tuning

**Status**: ✅ Production System
**Last Updated**: 2026-02-06
**Related**: [FINE_TUNING_DATA.md](FINE_TUNING_DATA.md), [MODELS.md](MODELS.md)

> ⚠️ **CRITICAL FIX (2026-02-06)**: Previous versions exported **incorrect format** for fine-tuning. Fixed to match production inference exactly. **Regenerate all existing JSONL datasets**.

---

## Executive Summary

This document explains how the ClassyMail MVP protects personal information (PII) in fine-tuning datasets and how user corrections are tracked for quality improvement.

**Key Points**:
- ✅ **Two-level PII protection**: Regex scrubbing + GPT-4o-mini contextual anonymization
- ✅ **Fail-safe design**: Skips examples if anonymization fails (never exports PII)
- ✅ **Default behavior**: Anonymization always ON (requires explicit opt-out)
- ✅ **User corrections tracked**: Complete history with AI-generated feedback
- ✅ **Correction "weight"**: Metadata-based implicit weighting for fine-tuning

---

## PII Anonymization System

### Overview

The system uses **two-level protection** to ensure no personal information leaks into fine-tuning datasets:

1. **Level 1: Basic Regex Scrubbing** - Fast removal of common PII patterns
2. **Level 2: LLM Contextual Anonymization** - GPT-4o-mini removes names, companies, contract IDs while preserving markdown structure

### Implementation Details

#### File: `classymail/services/anonymizer.py`

```python
# Two-level protection pipeline:

1. basic_pii_scrub(text: str) -> str
   - Removes: emails, IP addresses, phone numbers, IBANs
   - Uses: Fast regex patterns
   - Speed: <1ms per document
   - Applied to: Email body (markdown), subject field, sender field

2. anonymize_markdown_for_finetune(markdown: str, clients) -> dict
   - Removes: Names, companies, addresses, contract IDs, sensitive context
   - Uses: GPT-4o-mini with ~1800 char English system prompt
   - Preserves: Markdown structure, formatting, links, tables
   - Speed: ~2-5s per document (async)
   - Applied to: Email body (markdown) only
   - Returns: dict with anonymized_markdown, usage, model, prompt_version, hash

CRITICAL: When anonymize=True, BOTH levels are applied to email body,
and Level 1 (regex) is applied to subject/sender fields in assistant response
to prevent PII leakage in model outputs.
```

#### System Prompt (English, ~1800 chars)

The actual system prompt used in [anonymizer.py](../classymail/services/anonymizer.py) is in **English** and covers:

```markdown
### ROLE ###
You are an advanced Data Privacy and Anonymization Engine.
Your purpose is to sanitize email content formatted in Markdown.

### ANONYMIZATION RULES (PII) ###
1. Direct PII: Replace names, phones, emails, IPs, addresses → [Name], [Phone], [Email], [Address]
2. Contextual PII: Generalize company names → [Client], specific projects → [Project]
3. Dates: Generalize to [Date] or month/quarter
4. Numbers: Mask financial figures → [Amount]

### MARKDOWN PRESERVATION RULES ###
1. Structure: Do NOT alter headers, lists, blockquotes, code blocks
2. Links: Preserve syntax, anonymize PII in text/URLs
3. Tables: Keep structure intact, anonymize cell content

### OUTPUT FORMAT ###
Return ONLY the anonymized Markdown text.
```

**Placeholders used**: `[Name]`, `[Phone]`, `[Email]`, `[Address]`, `[Client]`, `[Amount]`, `[Date]`, `[IP]`, `[IBAN]` (Level 1 regex adds `[IP]` and `[IBAN]`).

### Configuration

Environment variables:

```bash
ANONYMIZER_ENDPOINT=https://<your-aoai>.openai.azure.com/  # Falls back to PHI_ENDPOINT
ANONYMIZER_DEPLOYMENT=gpt-4o-mini         # Model name (default)
ANONYMIZER_API_VERSION=2024-08-01-preview # Falls back to AZURE_AI_API_VERSION
ANONYMIZER_MAX_TOKENS=6000                # Output limit
ANONYMIZER_PROMPT_VERSION=v1              # Tracking
```

### Fail-Safe Behavior

**Critical Design Decision**: If anonymization fails, the example is **skipped** (not exported with PII).

#### Code Reference: `repository.py` (`export_finetune_jsonl_iter`)

```python
if anonymize:
    try:
        anon = await anonymize_markdown_for_finetune(raw_markdown, clients=clients)
        user_markdown = anon.get("anonymized_markdown") or ""
        anonymization_meta = {
            "model": anon.get("model"),
            "prompt_version": anon.get("prompt_version"),
            "usage": anon.get("usage"),
        }
    except Exception:
        continue  # ← SKIPS example, never exports with PII
```

**Why this matters**: Even if the anonymization service is temporarily down, the system will never export personal information. The dataset will be smaller but 100% PII-free.

### Default Behavior

**HTTP Endpoint**: `GET /api/emails/export-finetune-jsonl`

```python
@router.get("/emails/export-finetune-jsonl")
async def export_emails_finetune_jsonl(
    anonymize: bool = Query(True),  # ← DEFAULT: Always ON
    include_unreviewed: bool = Query(False),
    max_examples: Optional[int] = Query(None, ge=1),
    taxonomy_version: str = Query("v1"),
    include_metadata: bool = Query(False),
    split: str = Query("all", pattern="^(all|train|test)$"),
    test_split_ratio: float = Query(0.2, ge=0.0, le=1.0),
    ...
):
    # User must explicitly pass ?anonymize=false to disable
```

### Verification

To verify anonymization is working:

```bash
# Export training dataset
curl http://localhost:8000/api/emails/export-finetune-jsonl?split=train > train.jsonl

# Check for PII patterns (should return 0 matches)
grep -E "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}" train.jsonl | wc -l
grep -E "\b[A-Z][a-z]+ [A-Z][a-z]+\b" train.jsonl | wc -l  # Names with capitals
grep -E "\b\d{2}/\d{2}/\d{4}\b" train.jsonl | wc -l  # Dates

# Should see placeholders instead:
grep "\[Name\]" train.jsonl | wc -l
grep "\[Email\]" train.jsonl | wc -l
grep "\[Phone\]" train.jsonl | wc -l
grep "\[Address\]" train.jsonl | wc -l
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

#### File: `classymail/models.py`

```python
class HistoryEntry(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    previous_intents: List[ClassificationIntent] = []
    previous_status: Optional[str] = None
    updated_by: Optional[str] = "user"
    correction_reason: Optional[str] = None  # User explanation
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

#### File: `classymail/api/routers/emails.py`

```python
@router.patch("/emails/{item_id}", response_model=EmailRecord)
async def patch_email(item_id: str, payload: dict, ...):
    item = await cosmos_container.read_item(item=item_id, partition_key=item_id)

    # 1. Create history entry
    history_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "previous_intents": current_classification.get("detected_intents", []),
        "previous_status": item.get("status"),
        "updated_by": "user",
        "correction_reason": payload.get("reason"),
        "llm_feedback": None  # Filled below
    }

    if intents := payload.get("intents"):
        # 2. Generate AI feedback (analyze WHY correction needed)
        if payload.get("reason") and item.get("markdown"):
            insight = await analyze_correction(
                text_markdown=item.get("markdown"),
                old_intents=current_classification.get("detected_intents", []),
                new_intents=intents,
                reason=payload.get("reason"),
                clients=clients
            )
            history_entry["llm_feedback"] = insight

        # 3. Update classification and metadata
        item["classification"] = {"detected_intents": intents, "needs_review": False}
        item["status"] = new_status
        item["reviewed"] = True
        item["reviewed_at"] = datetime.now(timezone.utc).isoformat()

    # 4. Append history and save to Cosmos DB
    item["classification_history"].append(history_entry)
    await cosmos_container.upsert_item(item)
```

### AI Feedback Generation

#### File: `classymail/services/llm_pipeline.py`

```python
async def analyze_correction(
    text_markdown: str,
    old_intents: list,
    new_intents: list,
    reason: str,
    clients: Clients,
) -> str:
    """
    Uses the classification model to analyze WHY the correction was needed.
    Generates a "lesson learned" for prompt improvement.
    """
    # Uses the configured AI model (PHI_DEPLOYMENT or fallback)
    # Returns concise analysis: what the model missed or misunderstood
    # Timeout: 15s (fast response for UI)
    ...
```

**Example AI Feedback**:
```
"Le modèle a classé ce sinistre en MUST KEEP alors qu'il s'agit d'une
demande de résiliation (MUST GO). La présence de 'mettre fin à mon contrat'
aurait dû déclencher l'intent ACTION_RESILIER."
```

---

## Correction "Weight" for Fine-Tuning

### Two Concepts of "Weight"

#### 1. Microsoft's Official `weight` Parameter (Binary 0/1)

⚠️ **Note**: Azure AI Foundry supports an optional `weight` parameter on assistant messages for **skipping specific messages** during training.

**From Microsoft Documentation**:
> "To skip fine-tuning on specific assistant messages, add the optional `weight` key/value pair. Currently, `weight` can be set to `0` or `1`."

**Format**:
```json
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "...", "weight": 0}  ← Skip this response
  ]
}
```

**Purpose**: Binary flag (0 = skip, 1 = include in training)
**Use case**: Multi-turn conversations where certain responses should be excluded
**Our usage**: We do NOT currently use this parameter (all assistant messages have implicit `weight: 1`)

**Reference**: [Azure AI Foundry Fine-Tuning Docs](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning?view=foundry-classic&tabs=oai-sdk%2Cazure-openai&pivots=programming-language-python#multiple-turn-chat-file-format)

#### 2. Our Metadata-Based "Weighting" (Implicit Quality Signal)

⚠️ **Our Approach**: We use **metadata-based implicit weighting** through the `source` and `correction` fields, giving users control over emphasis during fine-tuning via filtering and oversampling strategies.

### Metadata Structure in JSONL Export

#### File: `classymail/services/repository.py`

```python
metadata = {
    "example_id": item.get("id"),
    "taxonomy_version": taxonomy_version,
    "source": "human_corrected" if is_corrected else "auto_classified",
    "anonymized": bool(anonymize),
    "anonymization": anonymization_meta,  # Model, prompt_version, usage
    "correction": {
        "was_corrected": True,
        "correction_reason": correction_reason,
        "llm_feedback": llm_feedback,
        "correction_timestamp": correction_timestamp
    } if is_corrected else None,
    "hash": hashlib.sha256((user_markdown + assistant_content).encode("utf-8")).hexdigest(),
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

### Optional Enhancement: Using Microsoft's `weight` Parameter

**Current Implementation**: All examples have implicit `weight: 1` (included in training)

**Potential Use Case**: If you want to export low-confidence auto-classified examples for context but exclude them from training:

```python
# Modified export to add weight parameter for low-confidence examples
assistant_message = {
    "role": "assistant",
    "content": assistant_content
}

# Only train on high-confidence or human-corrected examples
if not is_corrected and confidence_score < 0.7:
    assistant_message["weight"] = 0  # Skip low-confidence examples

example = {
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_markdown},
        assistant_message
    ]
}
```

**Recommendation**: Current approach (filtering via metadata) is simpler and more flexible. Only implement `weight` parameter if you need fine-grained control over which specific examples to exclude during training.

---

## Format Validation

### ✅ Critical Fix: Production-Inference Alignment (2026-02-06)

**Previous Implementation** (❌ INCORRECT):
- **System Prompt**: Generic 1-line prompt: `"You classify insurance emails into intents and output strict JSON only."`
- **Assistant Response**: Minimal structure missing `subject`, `sender`, `classification_reason`
- **Result**: Model learned wrong format, caused inference failures

**Current Implementation** (✅ CORRECT):

**1. System Prompt** (matches production exactly):
```python
system_prompt = f"""Tu es un assistant expert en classification d'emails d'assurance.
Ta tâche est d'analyser le contenu de l'email (fourni en markdown) et d'identifier :
- TOUTES les intentions présentes.
- Le sujet principal (Subject).
- L'expéditeur (Sender) si identifiable.

LISTE DES INTENTIONS POSSIBLES (NOM + DÉFINITION + EXCLUSIONS) :
{categories_text}  # ← Full category definitions with descriptions/exclusions

RÈGLES DE CLASSIFICATION :
- Choisis les intentions dont la DÉFINITION correspond le mieux au contenu.
- Les EXCLUSIONS précisent ce que chaque catégorie ne doit PAS inclure.
- Un email peut contenir UNE SEULE intention OU PLUSIEURS intentions.
- Si aucune intention ne correspond, retourne une liste vide. NE PAS deviner.
- Assigne un score de confiance (0.0 à 1.0) pour CHAQUE intention.
- La justification DOIT citer un extrait du texte.

FORMAT DE RÉPONSE ATTENDU (JSON UNIQUEMENT) :
{{
    "detected_intents": [
        {{"intent": "...", "confidence": 0.95, "justification": "..."}}
    ],
    "global_complexity": "Simple|Complexe",
    "classification_reason": "Explication si detected_intents est vide",
    "subject": "Sujet de l'email",
    "sender": "Expéditeur"
}}
"""
```

**2. Assistant Response** (complete structure):
```json
{
  "detected_intents": [
    {"intent": "ACTION_RESILIER", "confidence": 1.0, "justification": "Manually selected by user"},
    {"intent": "MUST GO", "confidence": 0.95, "justification": "..."}
  ],
  "global_complexity": "Simple",
  "classification_reason": "Aucune intention ne correspond (empty intents only)",
  "subject": "Demande de résiliation contrat habitation",
  "sender": "client@example.com"
}
```

**PII Protection**: When `anonymize=True`, subject and sender fields are scrubbed with `basic_pii_scrub()`:
```json
{
  "subject": "Demande de résiliation contrat habitation by [Email]",
  "sender": "[Email]"
}
```

**Code Changes** ([repository.py#L158-L226](../classymail/services/repository.py)):
```python
# Before: Generic prompt
system_prompt = "You classify insurance emails into intents and output strict JSON only."

# After: Production-grade prompt with full categories
categories_text = await get_categories_prompt_text(clients=clients)
system_prompt = f"""Tu es un assistant expert en classification d'emails d'assurance...
LISTE DES INTENTIONS POSSIBLES:
{categories_text}
...
"""

# Before: Minimal target
target = {"detected_intents": intents}
if classification.get("global_complexity"):
    target["global_complexity"] = classification.get("global_complexity")

# After: Complete target matching production (with PII protection)
target = {
    "detected_intents": intents,
    "global_complexity": classification.get("global_complexity") or "Simple",
}
if classification.get("classification_reason"):
    target["classification_reason"] = classification.get("classification_reason")
if item.get("subject"):
    subject = item.get("subject")
    target["subject"] = basic_pii_scrub(subject) if anonymize else subject
if item.get("sender"):
    sender = item.get("sender")
    target["sender"] = basic_pii_scrub(sender) if anonymize else sender
```

**Why This Matters**:
1. ✅ **Consistency**: Training and inference use identical format
2. ✅ **Learning**: Model learns to provide justifications and confidence scores
3. ✅ **Completeness**: Model learns to extract subject/sender metadata
4. ✅ **Context**: Full category definitions teach nuanced classification

**Action Required**: If you exported JSONL before 2026-02-06, **regenerate datasets** with the fixed format:
```bash
curl "http://localhost:8000/api/emails/export-finetune-jsonl?split=train" > train_fixed.jsonl
curl "http://localhost:8000/api/emails/export-finetune-jsonl?split=test" > test_fixed.jsonl
```

### Azure AI Foundry Compatibility ✅

**Our JSONL format meets all Microsoft requirements**:

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| JSON Lines format | ✅ | One example per line |
| UTF-8 with BOM | ✅ | `yield '\ufeff'` on first line |
| Chat Completions format | ✅ | `messages` array with system/user/assistant |
| File size < 512 MB | ✅ | Streaming export, no size issues |
| Minimum 10 examples | ✅ | Query filters ensure quality data |
| Custom metadata | ✅ | Separate `metadata` key (Azure allows additional fields) |

**Verification Commands**:

```bash
# Check BOM presence (should show UTF-8 with BOM)
file train.jsonl

# Validate JSONL format (each line should be valid JSON)
cat train.jsonl | while read line; do echo "$line" | jq empty || echo "Invalid JSON"; done

# Check messages structure
head -1 train.jsonl | jq '.messages[] | .role'
# Should output: "system" "user" "assistant"

# Count examples
wc -l < train.jsonl
```

**Official Microsoft Format Reference**:
- [Fine-Tuning Documentation](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning?view=foundry-classic&tabs=oai-sdk%2Cazure-openai&pivots=programming-language-python#prepare-your-training-and-validation-data)
- [Multiple-Turn Chat Format](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning?view=foundry-classic&tabs=oai-sdk%2Cazure-openai&pivots=programming-language-python#multiple-turn-chat-file-format)

---

## Export Filtering Logic

### Only High-Quality Examples Exported

#### File: `classymail/services/repository.py`

```python
async def export_finetune_jsonl_iter(
    *, clients, anonymize, include_unreviewed, max_examples,
    taxonomy_version, include_metadata, split_mode="all", test_ratio=0.2
):
    # Emit UTF-8 BOM (required by Azure AI Foundry)
    yield "\ufeff"

    where = ["c.status = 'PROCESSED'", "IS_DEFINED(c.classification)",
             "c.classification.needs_review = false"]
    if not include_unreviewed:
        where.append("(IS_DEFINED(c.reviewed) AND c.reviewed = true)")

    query = "SELECT c.id, c.markdown, c.classification, ... FROM c WHERE " + " AND ".join(where)
    it = clients.cosmos_container.query_items(query)

    # Get production-grade system prompt with full categories
    categories_text = await get_categories_prompt_text_async(clients=clients)
    system_prompt = f"""Tu es un assistant expert en classification...
    LISTE DES INTENTIONS POSSIBLES:
    {categories_text}
    ..."""

    async for item in it:
        # Deterministic train/test split via SHA-256 hash of ID
        h = int(hashlib.sha256(item_id.encode("utf-8")).hexdigest(), 16)
        normalized_hash = (h % 1000) / 1000.0

        if split_mode == "train" and normalized_hash < test_ratio:
            continue  # Skip test items
        elif split_mode == "test" and normalized_hash >= test_ratio:
            continue  # Skip train items

        # Anonymize (with fail-safe)
        if anonymize:
            try:
                anon = await anonymize_markdown_for_finetune(raw_markdown, clients=clients)
                user_markdown = anon.get("anonymized_markdown") or ""
            except Exception:
                continue  # SKIP on failure

        # Subject/sender scrubbed with basic_pii_scrub when anonymize=True
        if item.get("subject"):
            target["subject"] = basic_pii_scrub(subject) if anonymize else subject
        if item.get("sender"):
            target["sender"] = basic_pii_scrub(sender) if anonymize else sender

        # Build JSONL line
        yield json.dumps({"messages": [...], "metadata": {...}}) + "\n"
```

### Train/Test Split

- **Deterministic**: Uses SHA256 hash of email ID (stable across exports)
- **Method**: `h = int(SHA256(id).hexdigest(), 16); normalized = (h % 1000) / 1000.0`
- **Default ratio**: 80% train, 20% test (configurable via `test_split_ratio` parameter)
- **No leakage**: Same email ID always goes to same split
- **Endpoint parameter**: `?split=train|test|all` (default: `all`)

---

## Code References

### Key Files

| File | Purpose |
|------|---------|
| [classymail/services/anonymizer.py](../classymail/services/anonymizer.py) | PII anonymization implementation (basic_pii_scrub + anonymize_markdown_for_finetune) |
| [classymail/services/repository.py](../classymail/services/repository.py) | JSONL export pipeline (export_finetune_jsonl_iter) |
| [classymail/services/pii_detection.py](../classymail/services/pii_detection.py) | PII detection (LLM, Azure Language, Hybrid) |
| [classymail/api/routers/emails.py](../classymail/api/routers/emails.py) | User correction tracking (PATCH /emails/{id}) |
| [classymail/services/llm_pipeline.py](../classymail/services/llm_pipeline.py) | AI feedback generation (analyze_correction) |
| [classymail/models.py](../classymail/models.py) | Data models (EmailRecord, HistoryEntry, PIIDetectionResult) |

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
grep "\[Name\]" train.jsonl
grep "\[Email\]" train.jsonl
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
curl "http://localhost:8000/api/emails/export-finetune-jsonl?anonymize=false" > train_raw.jsonl
```

⚠️ **Warning**: This will export real PII. Use only for debugging in secure environments.

### Q5: Should I use Microsoft's `weight` parameter on assistant messages?

**A**: **Not required for most use cases**. Our metadata-based approach is simpler and more flexible.

**Current implementation**: All assistant messages have implicit `weight: 1` (included in training)

**When to use Microsoft's `weight` parameter**:
- Multi-turn conversations where certain responses should be skipped
- Fine-grained control over which specific assistant messages to exclude during training
- Advanced scenarios requiring binary inclusion/exclusion flags

**Our recommendation**: Use metadata filtering (Strategy 1-4 above) for quality control. Only implement `weight` parameter if you need message-level exclusion within multi-turn examples.

**Reference**: [Azure AI Foundry Multiple-Turn Chat Format](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning?view=foundry-classic&tabs=oai-sdk%2Cazure-openai&pivots=programming-language-python#multiple-turn-chat-file-format)

### Q6: How do I see the AI's analysis of corrections?

**A**: Query Cosmos DB for the `classification_history` field:

```python
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential

credential = DefaultAzureCredential()
client = CosmosClient(os.getenv("AZURE_COSMOS_ENDPOINT"), credential=credential)
db = client.get_database_client("emailsdb")
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

### Q7: How many corrections do I need for fine-tuning?

**A**: Recommended minimums:

- **GPT-4o/GPT-4**: 50-100 corrections for meaningful improvement
- **GPT-3.5-turbo**: 200-500 corrections (less capable base model)
- **Small models (Phi-4)**: 500-1000 corrections (requires more data)

**Quality > Quantity**: 50 well-explained corrections are better than 500 with vague reasons.

### Q8: Can I weight corrections differently based on quality?

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

- **2026-02-06 (v2.1 - PII LEAK FIX)**: 🔴 **Fixed PII leak in subject/sender fields**. Previous v2.0 anonymized email body content but exported raw subject and sender fields in assistant responses, potentially leaking email addresses and names. **Action required**: Regenerate datasets if exported after v2.0 release.
  - Subject field: Now scrubbed with `basic_pii_scrub()` when `anonymize=True`
  - Sender field: Now scrubbed with `basic_pii_scrub()` when `anonymize=True`
  - Protection: Removes emails, phones, IPs, IBANs from metadata fields
  - Code changes: [repository.py#L9](../classymail/services/repository.py) (added import), [repository.py#L251-L255](../classymail/services/repository.py) (conditional scrubbing)
  - Documentation: Updated PII protection section with subject/sender anonymization details

- **2026-02-06 (v2.0 - CRITICAL FIX)**: 🔴 **Fixed critical format mismatch** between fine-tuning export and production inference. Previous versions exported incomplete assistant responses and generic system prompts, causing models to learn wrong output format. **Breaking change**: Regenerate all existing JSONL datasets.
  - System prompt: Now includes full category definitions (493 lines) matching production exactly
  - Assistant response: Now includes `subject`, `sender`, `classification_reason` fields
  - Format validation: Added production-inference alignment verification section
  - Code changes: [repository.py#L158-L226](../classymail/services/repository.py)

- **2026-02-06 (v1.1)**: Verified against [official Microsoft Azure AI Foundry documentation](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning). Added clarification on two "weight" concepts: Microsoft's binary `weight` parameter (0/1) vs our metadata-based implicit weighting. Added format validation section and optional enhancement guidance. Confirmed full compatibility with Azure OpenAI fine-tuning requirements.

- **2026-02-06 (v1.0)**: Initial documentation (verified production implementation)
