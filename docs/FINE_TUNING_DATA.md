# Fine-Tuning Data Guide

## Overview

ClassyMail supports exporting classification data in JSONL format for fine-tuning language models on Microsoft AI Foundry. This guide covers dataset generation, anonymization, and best practices.

## Supported Models for Fine-Tuning

| Model | Fine-Tuning Support | Notes |
|-------|-------------------|-------|
| Phi-4 | Yes | Primary target for domain-specific tuning |
| GPT-4o-mini | Yes | Higher quality baseline |
| GPT-4.1-nano | Yes | Cost-effective option |

## Export Format

The JSONL export follows the Microsoft AI Foundry chat completion format:

``json
{"messages": [{"role": "system", "content": "You are an email classifier..."}, {"role": "user", "content": "Email content here..."}, {"role": "assistant", "content": "{\"detected_intents\": [...]}"}]}
``

### Export Commands

``bash
# Export training set (anonymized by default)
curl "http://localhost:8000/api/emails/export-finetune-jsonl?split=train" > train.jsonl

# Export test set
curl "http://localhost:8000/api/emails/export-finetune-jsonl?split=test" > test.jsonl

# Export without anonymization (not recommended for shared datasets)
curl "http://localhost:8000/api/emails/export-finetune-jsonl?split=train&anonymize=false" > train_raw.jsonl
``

### Train/Test Split

- **Train set** (`split=train`): 80% of processed emails
- **Test set** (`split=test`): 20% of processed emails
- Split is deterministic based on document ID hash

## Anonymization

All exports are anonymized by default using a two-layer approach:

1. **Regex layer** (<1ms): Removes emails, phone numbers, IPs, IBANs
2. **LLM layer** (GPT-4o-mini): Contextual anonymization of names, companies, addresses, amounts

The LLM anonymizer never sees raw PII -- it only processes content already scrubbed by the regex layer. If anonymization fails for any example, that example is skipped (fail-safe: never leak PII).

See [PII_ANONYMIZATION_AND_USER_CORRECTIONS.md](PII_ANONYMIZATION_AND_USER_CORRECTIONS.md) for technical details.

## Minimum Dataset Size

- **Recommended minimum**: 50 examples per category
- **Ideal**: 200+ examples per category for robust fine-tuning
- **Quality over quantity**: Manually reviewed and corrected examples produce better models

## Best Practices

1. **Use corrected data**: Only export emails that have been manually reviewed and corrected
2. **Balance categories**: Ensure roughly equal representation across categories
3. **Include edge cases**: Difficult emails that required review are the most valuable training examples
4. **Anonymize always**: Never share datasets with real PII, even internally
5. **Version your datasets**: Keep dated copies of each export for reproducibility

## Categories

See [CUSTOMIZATION.md](CUSTOMIZATION.md#business-category-taxonomy) for the full category taxonomy.
