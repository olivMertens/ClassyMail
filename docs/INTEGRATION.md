# Using And Integrating ClassyMail

## Dashboard And Review

The Vue dashboard lists processed emails and supports filtering, PDF/text inspection,
classification review, reprocessing, exports and chat. Open an email to inspect its
extracted Markdown and classification before validating it. Record a correction reason
when changing categories; reviewed data and correction history are useful for evaluation.

Settings configure organization branding, output locale, category definitions, model
selection, processing strategy, OCR provider, preprocessing, PII detection and CSV
columns. Inspect current defaults through `GET /api/settings/defaults`; existing saved
settings can differ from new defaults. See [#frontend/src/views/SettingsView.vue](../frontend/src/views/SettingsView.vue)
and [#classymail/services/settings_store.py](../classymail/services/settings_store.py).

Admin operations can generate test data, reprocess records, rebuild indexes, replay or
purge the DLQ, and reset data. Read confirmations carefully: reset and purge are destructive,
and reprocessing/index rebuilding can incur model costs. Administrative routes must not
be exposed to untrusted clients without appropriate ingress controls.

## Categories And Customization

Each category has a display `name`, technical `slug`, `description` and `exclusions`.
Define what belongs and what does not, with representative ambiguous examples. Keep
slugs stable: exports and per-category retrieval depend on them. The default taxonomy
is in [settings_store.py](../classymail/services/settings_store.py), not a fixed
customer-specific category list.

Use `GET /api/settings` and `POST /api/settings` for runtime configuration. Category
assessment and import implementations are in
[category_assessment.py](../classymail/api/category_assessment.py) and
[categories_import.py](../classymail/api/categories_import.py). Inspect their request
schemas in `/openapi.json` rather than relying on old example payloads.

Branding uses `ORGANIZATION_NAME`; feature visibility uses `UI_SHOW_INFO_MODAL` and
`UI_SHOW_DEVELOPER_TAB`. Deployment tags/policies are separate from UI customization;
their variables live in [#infra/main.tf](../infra/main.tf) and [#infra/policy.tf](../infra/policy.tf).

## API And Ingestion

Use `/docs` or `/openapi.json` for current request/response schemas. Key routes are:

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/upload` | Upload PDFs using multipart field `files` |
| GET | `/api/emails` | List records |
| GET / PATCH | `/api/emails/{item_id}` | Read / review a record |
| POST | `/api/emails/{item_id}/reprocess` | Enqueue reprocessing |
| POST | `/api/emails/batch-reprocess` | Reprocess a selection |
| POST | `/api/emails/{item_id}/reinforce` | Add positive retrieval examples |
| GET | `/api/emails/{item_id}/file` | Retrieve original document |
| GET | `/api/emails/export/csv` | Export minimal or enriched CSV |
| POST | `/api/chat` | Single-response chat |
| POST | `/api/chat/stream` | Streaming chat |

[upload.py](../classymail/api/routers/upload.py) accepts at most 20 files per batch and
100 MiB total; each file is also bounded by `UPLOAD_MAX_BYTES` (default 10 MiB).
Check each entry in `results`: HTTP success does not mean every file was accepted.
Successful uploads are written to Blob Storage; Event Grid queues processing.

`POST /webhook/ingest` handles Event Grid subscription validation and BlobCreated events.
It is not a generic inbound-email or SendGrid attachment endpoint. Its exact event
contract is in [webhook.py](../classymail/api/routers/webhook.py).

## CSV Exports

`GET /api/emails/export/csv?format=minimal` returns the integration format;
`format=enriched` includes more metadata. The HTTP exporter uses a semicolon delimiter
and UTF-8 BOM. Minimal headers are `ID;INTENTIONS;CONFIDENCE_MOYENNE`. `ID` is the PDF
filename, intents are comma-separated technical slugs, and confidence is the mean
label confidence formatted as a percentage. Settings control the enriched columns
and unclassified label.

The legacy CLI CSV helper has a different schema. Verify headers in your integration
tests rather than treating both exporters as interchangeable. See
[emails.py](../classymail/api/routers/emails.py) for filtering and column construction.

## Feedback And Retrieval

Human corrections can add positive examples for newly selected categories and negative
examples for removed categories. Reinforcement adds positive examples for current labels.
These are retrieval updates, not model retraining or a guarantee of improved accuracy.
Use reviewed examples, avoid duplicates and protect sensitive content placed in indexes.
Index management and retrieval settings are covered in
[agentic classification](AGENTIC_CLASSIFICATION.md#per-category-ai-search).

Fine-tuning exports, anonymization limits and privacy considerations have one home:
[data and privacy](PII_ANONYMIZATION_AND_USER_CORRECTIONS.md).
