# Local Development Guidance

## Prérequis
- Python 3.12 (uv powered)
- Node 18+ (frontend)
- Azure CLI logged in (si RBAC utilisé) ou `AZURE_STORAGE_ACCOUNT_KEY`

## Setup
```bash
uv sync --frozen --extra dev
cd frontend && npm install
```

## Build & run local server
```bash
cd frontend && npm run build
cd ..
uv run uvicorn main:app --port 8011
```

## Tests & lint
```bash
uv run pytest -q
uv run ruff check .
```

## Upload & pipeline test
- UI: Upload tab, drop PDF
- API: `POST /api/upload` with `files` (multipart)

## Diagnostics
- `GET /api/admin/diagnostics`
- `GET /api/admin/deadletter`
- `GET /api/admin/blob-info?blob_url=...`

## Email Details
- Each email exposes `id` (Cosmos key, also visible in dashboard card footer `#abcdef`)
- API: `GET /api/emails/{id}` returns `file_url`, `file_url_sas`, `markdown`, `classification`
- Chatbot: `get_email_by_id` now returns `_links.view` and `_links.api`

## Chatbot markdown
- Responses render markdown in UI (bold/italic now visible)

## Known configs
- Ensure `AZURE_STORAGE_ACCOUNT_URL` and `BLOB_CONTAINER_INPUT` exist
- If private storage: set `AZURE_STORAGE_ACCOUNT_KEY` or RBAC (`Storage Blob Data Reader` + `Contributor`)
```
