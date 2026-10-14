# Data, Privacy And Fine-Tuning Exports

## Detection Is Not Anonymization

Preprocessing can detect PII through an LLM, Azure AI Language, or both. These results
identify potentially sensitive fields; they do not erase the original PDF, extracted
Markdown or stored metadata. Detection is enabled in new default preprocessing settings,
but saved settings can override it. Neither a PII badge nor a model prompt establishes
GDPR compliance.

Owners: [#classymail/services/pii_detection.py](../classymail/services/pii_detection.py),
[pii_detection_azure.py](../classymail/services/pii_detection_azure.py) and
[settings_store.py](../classymail/services/settings_store.py). Review access controls,
retention, consent/lawful basis, residency and telemetry separately.

## Export Anonymization And Its Limits

[anonymizer.py](../classymail/services/anonymizer.py) first uses regular expressions for
email addresses, IPv4-like strings, phone-like numbers and IBANs. It then sends the
remaining Markdown to the configured LLM for contextual anonymization.

The LLM can still see names, addresses and other personal information that those
patterns do not remove. Failed anonymization calls cause examples to be skipped, but
a successful response is not independently checked for complete PII removal.

The HTTP exporter regex-scrubs `subject` and `sender`; it does not contextually anonymize
every classification justification, correction or metadata field. Inspect the whole
JSONL, including assistant messages and optional metadata, before distributing it.
`anonymize=false` / CLI `--no-anonymize` explicitly bypass this processing.

Anonymizer configuration: `ANONYMIZER_ENDPOINT` (defaults to primary endpoint),
`ANONYMIZER_DEPLOYMENT`, `ANONYMIZER_API_VERSION`, `ANONYMIZER_MAX_TOKENS` and
`ANONYMIZER_PROMPT_VERSION`. See [models](MODELS.md) for aliases and endpoint selection.

## Reviewed Examples And Corrections

Review through `PATCH /api/emails/{item_id}`. Correction history and reasons help explain
changes and feed retrieval examples; they are not automatic fine-tuning sample weights.
Model feedback is an interpretation, not evidence that the correction is correct.
Review behavior is owned by [emails.py](../classymail/api/routers/emails.py).

## HTTP JSONL Export

`GET /api/emails/export-finetune-jsonl` streams chat-style `messages` with
system/user/assistant roles. It selects processed, classified records with
`needs_review=false`, requiring `reviewed=true` unless `include_unreviewed=true`.
Records with empty intents are skipped. The readiness threshold defaults to five
examples (`finetune_min_examples`), not a guarantee of enough training data.

Useful parameters are `split=all|train|test`, `test_split_ratio` (default 0.2),
`anonymize` (default true), `max_examples`, `taxonomy_version` and `include_metadata`.
The deterministic ID-hash split targets roughly 80/20; it does not guarantee exact
counts or category balance. Export both splits against the same stable reviewed dataset.

For example, request these two URLs from a configured application:

```text
/api/emails/export-finetune-jsonl?split=train
/api/emails/export-finetune-jsonl?split=test
```

The assistant target includes intents, complexity and available subject/sender fields.
Optional metadata includes correction details and hashes. Before submitting to a training
service, check its accepted schema, encoding, metadata policy and minimum dataset size.
ClassyMail emits a UTF-8 BOM in this HTTP export; that implementation choice is not a
universal requirement of every fine-tuning service.

Owners: [export route](../classymail/api/routers/emails.py) and
[export_finetune_jsonl_iter](../classymail/services/repository.py).

## CLI And Training Eligibility

The [CLI](LOCAL_DEVELOPMENT.md#cli-helpers) can export JSONL too, but uses a smaller target
schema, always includes metadata and does not expose the HTTP train/test split. Do not
assume its output is identical to the HTTP exporter.

This repository generates data; it does not prove that any model is currently fine-tunable
in your region/subscription. Check the selected service's current model catalog and
validate a small sample before planning a job. Evaluate on held-out, reviewed examples;
avoid leaking near-duplicate email threads between train and test.
