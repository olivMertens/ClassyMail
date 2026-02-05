# Client G2S Integration Guide

**Document Version:** 1.0
**Last Updated:** 2026-02-05
**Target Release:** Production v2.0

---

## Table of Contents

1. [Overview](#overview)
2. [Business Requirements](#business-requirements)
3. [Category Management](#category-management)
4. [Email Preprocessing](#email-preprocessing)
5. [PII Detection (GDPR)](#pii-detection-gdpr)
6. [CSV Export Formats](#csv-export-formats)
7. [Configuration Guide](#configuration-guide)
8. [Migration from v1.x](#migration-from-v1x)
9. [Validation Checklist](#validation-checklist)
10. [Troubleshooting](#troubleshooting)

---

## Overview

This document describes the enhanced classification system designed for Client G2S compatibility, implementing professional-grade email processing with:

- **Category Definitions & Exclusions**: Professional taxonomy with "what it IS" vs "what it ISN'T"
- **Technical Slugs**: Stable identifiers for CSV export (independent of display names)
- **Email Preprocessing**: LLM-based intelligent extraction (subject, conversation, signatures)
- **PII Detection**: GDPR-compliant personal information extraction
- **Dual CSV Formats**: Minimal (client compatible) and Enriched (full audit trail)

---

## Business Requirements

### Current API Behavior (Reference)

**Endpoint:** `GET /api/emails`

**Response Format:**
```json
{
  "items": [
    {
      "id": "uuid-12345",
      "classification": {
        "detected_intents": [
          {"intent": "Attestation habitation", "confidence": 0.95},
          {"intent": "Relevé de compte", "confidence": 0.85}
        ]
      },
      "processing_time_ms": 1234,
      "pii_detected": true,
      "pii_data": {
        "names": ["Jean Dupont"],
        "emails": ["jean.dupont@example.com"],
        "phones": ["+33 6 12 34 56 78"]
      }
    }
  ]
}
```

### Best Practices for Category Definitions

- **Use concrete keywords** in descriptions (for example: "foudre, surtension, court-circuit" instead of "problèmes électriques").
- **Make exclusions explicit** with edge cases (for example: "Ne pas inclure X, Y, Z").
- **Test ambiguous cases** and refine exclusions when categories overlap.
- **Validate with all 3 strategies**:
  - **Standard** for speed
  - **Reasoning** for accuracy checks
  - **Vision** for documents with photos

### CSV Output Requirements

Client G2S requires CSV export with:
- **Primary Format**: `ID;INTENTIONS` (semicolon delimiter, UTF-8 BOM)
- **Intentions Format**: Technical slugs separated by commas (e.g., `attestation_habitation,releve_compte`)
- **Optional Enriched Format**: Additional columns for audit and quality control

---

## Category Management

### Category Model Structure

Each category now includes four fields:

| Field | Type | Purpose | Example |
|-------|------|---------|---------|
| `name` | String | Display name (UI) | "Attestation habitation" |
| `slug` | String | Technical ID (CSV) | "attestation_habitation" |
| `description` | String | What it IS (definition) | "Documents certifiant la résidence ou l'assurance habitation" |
| `exclusions` | String | What it ISN'T (boundaries) | "Ne concerne pas les attestations professionnelles ou véhicules" |

### Slug Naming Convention

**Rules:**
- Lowercase only
- Underscores for spaces
- Alphanumeric characters + underscore only
- No accents (é→e, è→e, à→a)

**Auto-Generation:**
If slug is not provided, it's automatically generated from the name:
```python
slug = name.lower().replace(" ", "_").replace("é", "e").replace("è", "e").replace("à", "a")
slug = "".join(ch for ch in slug if ch.isalnum() or ch == "_")
```

### Professional Prompt Format

Categories are presented to the LLM in this format (no emojis):

```
1. Attestation habitation
   DÉFINITION: Documents certifiant la résidence ou l'assurance habitation
   EXCLUSIONS: Ne concerne pas les attestations professionnelles ou véhicules

2. Relevé de compte
   DÉFINITION: Relevés bancaires et transactions financières
   EXCLUSIONS: Ne concerne pas les factures ou contrats
```

### UI Configuration

Navigate to **Settings → Classification Tab**:

1. Click on existing category to expand accordion
2. Edit fields:
   - **Name (Display)**: User-facing label
   - **Slug (Technical ID)**: CSV identifier
   - **Definition (What it IS)**: LLM classification criteria
   - **Exclusions (What it ISN'T)**: Negative examples

3. Click **Save Changes to System** to commit

---

## Email Preprocessing

### Overview

Email preprocessing uses **GPT-4o-mini** to intelligently extract relevant content before classification:

1. **Subject Extraction**: Identifies email subject from markdown
2. **Conversation Extraction**: Removes history, signatures, boilerplate
3. **Content Assembly**: Combines subject + last conversation

### Configuration

Navigate to **Settings → Processing Tab → Email Preprocessing**:

| Toggle | Description | Default | Cost Impact |
|--------|-------------|---------|-------------|
| **Enable Preprocessing** | Master switch | ✓ Enabled | +€0.001/email |
| **Include Email Subject** | Extract subject line | ✓ Enabled | None |
| **Extract Last Conversation** | Remove history/signatures | ✓ Enabled | +€0.001/email |
| **Detect PII** | Extract personal information | ✗ Disabled | +€0.002/email |

### Processing Flow

```
Original Email (5000 chars)
    ↓
[1. Extract Subject]
    ↓
Subject: "Re: Claim #12345"
    ↓
[2. LLM Extraction: Remove History/Signatures]
    ↓
Clean Content (1200 chars)
    ↓
[3. Combine]
    ↓
Final Input: "Subject: Re: Claim #12345\n\nBonjour, je souhaite..."
    ↓
[Classification]
```

### Technical Implementation

**Preprocessing Service:** `classymail/services/email_preprocessing.py`

**LLM Prompt for Conversation Extraction:**
```
Extract ONLY the last meaningful conversation from an email thread.

REMOVE:
- All quoted replies (lines starting with '>', 'On ... wrote:', etc.)
- Email signatures (contact info, disclaimers, legal notices)
- Automatic reply tags and boilerplate text
- Thread history and previous messages

KEEP:
- The actual message content from the most recent sender
- Any attachments mentions relevant to this message
```

**Response Format:**
```json
{
  "preprocessing_metadata": {
    "preprocessing_enabled": true,
    "subject_included": true,
    "conversation_extracted": true,
    "original_length": 5000,
    "processed_length": 1200,
    "subject": "Re: Claim #12345"
  }
}
```

---

## PII Detection (GDPR)

### Purpose

Extract Personal Identifiable Information for GDPR compliance audits.

### Detected Categories

| Category | Examples | Use Case |
|----------|----------|----------|
| **names** | "Jean Dupont", "Marie Martin" | Identity verification |
| **emails** | "jean.dupont@example.com" | Contact masking |
| **phones** | "+33 6 12 34 56 78" | Anonymization |
| **addresses** | "15 Rue de la Paix, 75001 Paris" | Data localization |
| **contract_ids** | "POL-2024-001234", "CLAIM-5678" | Reference extraction |
| **dates** | "1985-03-15", "2024-01-20" | Timeline analysis |
| **other** | SSN, passport numbers | Sensitive data flag |

### LLM Integration

**Model:** GPT-4o-mini (JSON mode)
**Cost:** ~€0.002 per email
**Latency:** +200-500ms

**Response Format:**
```json
{
  "names": ["Jean Dupont", "Marie Martin"],
  "emails": ["jean.dupont@example.com"],
  "phones": ["+33 6 12 34 56 78"],
  "addresses": ["15 Rue de la Paix, 75001 Paris"],
  "contract_ids": ["POL-2024-001234"],
  "dates": ["1985-03-15"],
  "other": []
}
```

### Storage in EmailRecord

```python
class EmailRecord(BaseModel):
    pii_detected: bool  # True if any PII found
    pii_data: dict      # Full structured extraction
    preprocessing_metadata: dict  # Processing details
```

---

## CSV Export Formats

### Minimal Format (Client G2S Compatible)

**Usage:** Production exports for client systems

**Columns:** `ID;INTENTIONS`

**Example:**
```csv
ID;INTENTIONS
uuid-12345;attestation_habitation,releve_compte
uuid-67890;unclassified
uuid-11111;dommages_electriques
```

**Characteristics:**
- Semicolon delimiter (`;`)
- UTF-8 BOM encoding (Excel compatible)
- Technical slugs (stable identifiers)
- Comma-separated multi-category

### Enriched Format (Full Audit Trail)

**Usage:** Quality control, GDPR audits, model debugging

**Columns:**
```
ID;INTENTIONS;CONFIDENCES;MODEL;JUSTIFICATION;EXCLUSION_REASON;PROCESSING_TIME_MS;PII_DETECTED;PII_TYPES;PII_COUNT
```

**Example:**
```csv
ID;INTENTIONS;CONFIDENCES;MODEL;JUSTIFICATION;EXCLUSION_REASON;PROCESSING_TIME_MS;PII_DETECTED;PII_TYPES;PII_COUNT
uuid-12345;attestation_habitation;0.95;phi4;Mentions "assurance habitation";;1234;True;names,emails,phones;5
uuid-67890;unclassified;;;;"No clear insurance category";2100;False;;0
```

**Column Descriptions:**

| Column | Type | Description |
|--------|------|-------------|
| `ID` | String | Unique email identifier |
| `INTENTIONS` | String | Comma-separated category slugs |
| `CONFIDENCES` | String | Comma-separated confidence scores (0.0-1.0) |
| `MODEL` | String | Classification model used |
| `JUSTIFICATION` | String | LLM reasoning (pipe-separated if multiple) |
| `EXCLUSION_REASON` | String | Why no category was assigned |
| `PROCESSING_TIME_MS` | Integer | Total processing duration |
| `PII_DETECTED` | Boolean | Personal information found |
| `PII_TYPES` | String | Comma-separated PII categories detected |
| `PII_COUNT` | Integer | Total number of PII items extracted |

### Export API

**Endpoint:** `GET /api/emails/export/csv`

**Parameters:**
```
?status=all          # all | REVIEW_REQUIRED | PROCESSED | ERROR
&format=enriched     # minimal | enriched
```

**Response Headers:**
```
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename=emails_export_enriched_20260205_143000.csv
```

---

## Configuration Guide

### Recommended Configuration Profiles

#### Profile 1: Full Business Processing (Default)
```json
{
  "email_preprocessing": {
    "enabled": true,
    "include_subject": true,
    "extract_last_conversation": true,
    "detect_pii": false
  }
}
```
- **Use Case:** Standard production workflow
- **Cost:** ~€0.002/email
- **Benefits:** Clean input, better classification accuracy

#### Profile 2: GDPR Audit Mode
```json
{
  "email_preprocessing": {
    "enabled": true,
    "include_subject": true,
    "extract_last_conversation": true,
    "detect_pii": true
  }
}
```
- **Use Case:** GDPR compliance audits
- **Cost:** ~€0.004/email
- **Benefits:** Full PII extraction + preprocessing

#### Profile 3: Raw Processing (Legacy Compatible)
```json
{
  "email_preprocessing": {
    "enabled": false,
    "include_subject": false,
    "extract_last_conversation": false,
    "detect_pii": false
  }
}
```
- **Use Case:** Testing, comparison with v1.x
- **Cost:** €0/email (no preprocessing overhead)
- **Benefits:** Direct classification on raw OCR output

---

## Migration from v1.x

### Breaking Changes

#### 1. Category Model
**Old (v1.x):**
```json
{"name": "Attestation habitation", "description": ""}
```

**New (v2.0):**
```json
{
  "name": "Attestation habitation",
  "slug": "attestation_habitation",
  "description": "Documents certifiant la résidence...",
  "exclusions": "Ne concerne pas les attestations professionnelles..."
}
```

**Migration:** Automatic! The system auto-generates slugs from names for old categories.

#### 2. CSV Format
**Old:** Category names in plain text
**New:** Technical slugs (stable identifiers)

**Impact:** Client systems must update parsing logic to use slugs.

### Backward Compatibility

The system maintains backward compatibility through:
- **API**: Unchanged response structure (new fields are optional)
- **Settings**: Old categories are auto-migrated on first load
- **CSV**: Slugs auto-generated if missing

---

## Validation Checklist

### Pre-Production Testing

- [ ] **Category Configuration**
  - [ ] All categories have slugs defined
  - [ ] Definitions and exclusions are populated
  - [ ] Prompt format verified (no emojis, professional structure)

- [ ] **Email Preprocessing**
  - [ ] Toggle configuration tested
  - [ ] Subject extraction validated
  - [ ] Conversation extraction accuracy checked
  - [ ] Cost monitoring enabled

- [ ] **PII Detection** (if enabled)
  - [ ] Sample emails tested
  - [ ] All PII types extracted correctly
  - [ ] Performance impact acceptable (<1s overhead)

- [ ] **CSV Export**
  - [ ] Minimal format tested (ID;INTENTIONS)
  - [ ] Enriched format validated (all 10 columns)
  - [ ] UTF-8 BOM encoding verified (Excel compatible)
  - [ ] Slug mapping correct

- [ ] **Integration Testing**
  - [ ] End-to-end flow: Upload → Process → Export
  - [ ] Client G2S system can parse CSV
  - [ ] GDPR audit reports generated successfully

---

## Troubleshooting

### Issue: Slugs not appearing in CSV

**Cause:** Old categories without slugs
**Solution:** Edit each category in Settings and save (triggers auto-migration)

### Issue: Preprocessing not working

**Symptoms:** Full email content in classification
**Check:**
1. Settings → Processing → Email Preprocessing enabled
2. Check logs for LLM preprocessing errors
3. Verify GPT-4o-mini deployment exists

### Issue: PII detection returning empty results

**Possible Causes:**
1. PII detection toggle disabled
2. Email genuinely contains no PII
3. LLM endpoint unavailable

**Debug:**
```bash
# Check preprocessing metadata in response
GET /api/emails/{id}

# Look for:
"preprocessing_metadata": {
  "preprocessing_enabled": true,
  "conversation_extracted": true
},
"pii_detected": false,
"pii_data": null
```

### Issue: CSV export shows wrong categories

**Cause:** Slug mapping mismatch
**Solution:**
1. Verify category slugs in Settings
2. Re-export with updated slugs
3. Check category name→slug mapping

---

## Support

For technical support or questions about this integration:

- **Documentation:** [docs/README_DIAGRAMS.md](./README_DIAGRAMS.md)
- **Architecture:** [docs/ARCHITECTURE.md](./ARCHITECTURE.md)
- **API Reference:** `GET /api/docs` (OpenAPI)

---

**End of Document**
