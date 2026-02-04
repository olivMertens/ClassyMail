# Repository Copilot Instructions

- Always respect the DI pattern with `Clients` (no import-by-value of `sb_client`, `cosmos_container`, `blob_service_client`).
- Use `uv run ruff check .` and `uv run pytest` before suggesting completion is done.
- For infrastructure, prefer Terraform; keep `container_image` required, two ACAs (api/worker) with KEDA servicebus scaler.
- Health/ready endpoints: `/healthz` `/readyz` (aliases `/health` `/ready`).
- Avoid modifying `main.py` except to delegate to `classymail.app:app`.
- Default to Python 3.12.

## Azure Architecture Documentation Standards

- **Visuals**: Enforce strict usage of **CAE Icons (Flat Design)** in all diagrams.
- **Code Linking**: Use the `#` nomenclature to link descriptive text or diagrams to code (e.g., `#infra/main.tf` or `#src/app.py`).
