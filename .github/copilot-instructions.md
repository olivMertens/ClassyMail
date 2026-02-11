# Repository Copilot Instructions

- Always respect the DI pattern with `Clients` (no import-by-value of `sb_client`, `cosmos_container`, `blob_service_client`).
- Use `uv run ruff check .` and `uv run pytest` before suggesting completion is done.
- For infrastructure, prefer Terraform; keep `container_image` required, two ACAs (api/worker) with KEDA servicebus scaler.
- **MANDATORY for all Terraform modifications**: Before creating or modifying any Terraform resource, fetch the Azure Verified Modules (AVM) registry at `https://azure.github.io/Azure-Verified-Modules/` using `fetch_webpage` to check for an official AVM module or latest best practices. Prefer AVM modules over raw `azurerm`/`azapi` resources when available.
- Health/ready endpoints: `/healthz` `/readyz` (aliases `/health` `/ready`).
- Avoid modifying `main.py` except to delegate to `classymail.app:app`.
- Default to Python 3.12.

## Azure Architecture Documentation Standards

- **Visuals**: Enforce strict usage of **CAE Icons (Flat Design)** in all diagrams.
- **Code Linking**: Use the `#` nomenclature to link descriptive text or diagrams to code (e.g., `#infra/main.tf` or `#src/app.py`).

## Mermaid Diagrams Best Practices

**CRITICAL**: When creating or modifying Mermaid diagrams in Markdown:

- ❌ **NEVER** use HTML tags like `<br/>`, `<br>`, `<b>`, `<i>` inside Mermaid node labels or edge labels
- ✅ **ALWAYS** use plain text with spaces, dashes, colons, or parentheses for multi-line labels
- ✅ Use `flowchart LR` or `flowchart TD` (not deprecated `graph LR`)
- ✅ Validate all diagrams with: `uv run python scripts/validate_mermaid.py <files>`

**Examples**:

```markdown
❌ BAD:
flowchart TD
A["API + UI<br/>(Container App)"] --> B["Service Bus<br/>Queue"]

✅ GOOD:
flowchart TD
A["API + UI - Container App"] --> B["Service Bus Queue"]

✅ GOOD (with line breaks in description):
flowchart TD
A["API + UI: Container App"] --> B["Service Bus: pdf-queue"]
```

**Validation workflow**:

1. Create/edit Mermaid diagram
2. Run `uv run python scripts/validate_mermaid.py <file.md>`
3. Fix any syntax errors before committing
