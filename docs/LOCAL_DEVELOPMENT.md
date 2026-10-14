# Local Development

## Prerequisites

Use Python 3.12 and Node.js 22, matching CI. Install uv and provide access to the
configured Azure services. The API is not an offline emulator: startup requires
Service Bus, Blob Storage, Cosmos DB, Mistral and the primary model endpoint.

## Install

From the repository root:

```powershell
uv sync --frozen --extra dev
npm --prefix frontend ci
npm --prefix frontend run build
```

On a managed workstation, do not regenerate the lockfile through an internal package
mirror and commit its URLs. If dependencies are already installed, `uv run --no-sync`
can run the existing environment, but does not verify compatibility with a newer lockfile.

## Configure And Run

Use [secrets.env.example](../secrets.env.example) as the configuration template. Keep
the local `secrets.env` untracked. The delegated entry point
[main.py](../main.py) loads it with python-dotenv; arbitrary shell sourcing is unnecessary.

Required endpoint names are defined in [config.py](../classymail/core/config.py):
`AZURE_SERVICE_BUS_FQDN`, `AZURE_STORAGE_ACCOUNT_URL`, `AZURE_COSMOS_ENDPOINT`,
`MISTRAL_ENDPOINT`, and `PHI_ENDPOINT` (or `AZURE_AI_ENDPOINT`). Queue, container,
database and deployment names must match the actual services.

Use your developer identity for local Azure access. A deployed managed identity's
client ID does not grant that identity to your workstation. Local RBAC helpers are
[assign_local_dev_roles.ps1](../scripts/assign_local_dev_roles.ps1) and
[assign_local_dev_roles.sh](../scripts/assign_local_dev_roles.sh); review them before
running because they change role assignments.

```powershell
uv run uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/`. For an integrated local worker, set
`$env:ENABLE_WORKER = "true"` before starting the API. Alternatively run
`uv run --env-file secrets.env python -m classymail.worker_main` in another terminal;
the worker module does not load that file itself. Do not unintentionally
run both workers when comparing processing behavior.

For frontend hot reload, run `npm --prefix frontend run dev` with the API running.
[vite.config.js](../frontend/vite.config.js) defines proxy and output paths.

## Tests

```powershell
uv run ruff check .
uv run pytest
uv run python scripts/validate_mermaid.py README.md docs/ARCHITECTURE.md docs/AGENTIC_CLASSIFICATION.md
```

Health and readiness routes are `/healthz` and `/readyz` (aliases `/health`, `/ready`).
Check both; a successful liveness response is not proof that processing dependencies work.

Use the UI's synthetic-email operation (`POST /api/admin/generate-synthetic`) or
upload a PDF with multipart field `files` to `POST /api/upload` for integration testing.
These operations write data and can incur model costs. See [integration](INTEGRATION.md)
and [data_ops.py](../classymail/api/routers/admin/data_ops.py) for synthetic generation;
[testing.py](../classymail/api/routers/admin/testing.py) owns connectivity diagnostics.

## CLI Helpers

[cli.py](../classymail/cli.py) implements these commands:

```powershell
uv run python -m classymail.cli --help
uv run python -m classymail.cli --export-csv ./data/output.csv
uv run python -m classymail.cli --export-finetune-jsonl ./data/fine_tune.jsonl --max-examples 50
uv run python -m classymail.cli --backfill-rag --max-items 50
```

Supply endpoint configuration in the process environment for the CLI; unlike
`main.py`, this module does not load `secrets.env` itself. The CSV helper uses a
legacy schema and is not interchangeable with the application's minimal CSV export.
Prefer the HTTP JSONL endpoint for train/test splitting and its richer target schema;
see [data and privacy](PII_ANONYMIZATION_AND_USER_CORRECTIONS.md).

Backfill writes embeddings and chunks and calls the embedding deployment. Confirm the
target database and expected costs before running it. Deployment belongs in the
[deployment guide](DEPLOY_FROM_SCRATCH.md), not the local setup path.
