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

## ACR Build & Deploy

When asked to build and deploy, use the optimized ACR cloud build workflow — **never send the full repo** as build context:

```powershell
# 1. Create minimal build context (excludes docs, tests, scripts, infra, data, node_modules, .venv)
tar -czf build-context.tar.gz \
  --exclude='.git' --exclude='.venv' --exclude='node_modules' \
  --exclude='.ruff_cache' --exclude='.pytest_cache' \
  --exclude='infra' --exclude='docs' --exclude='tests' \
  --exclude='scripts' --exclude='data' --exclude='dataset' \
  --exclude='examples' --exclude='CU' --exclude='.github' \
  --exclude='.vscode' --exclude='.devcontainer' --exclude='.githooks' \
  --exclude='static/dist' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='*.log' --exclude='secrets.env' \
  -C . .

# 2. Extract into .tmp directory
mkdir -p .tmp && tar -xzf build-context.tar.gz -C .tmp

# 3. Cloud build via ACR Tasks (~2-3 min)
# Pass build args so the About dialog + /api/admin/version show real metadata
# (Dockerfile bakes COMMIT_SHA/BUILD_TIMESTAMP; defaults are "unknown" otherwise).
az acr build --registry <ACR_NAME> \
  --image classymail:latest --image classymail:<COMMIT_SHA> \
  --build-arg COMMIT_SHA=<COMMIT_SHA> \
  --build-arg BUILD_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --platform linux/amd64 .tmp

# 4. Update Container Apps (also set APP_VERSION so /api/admin/version != "unknown")
az containerapp update --name <PREFIX>-api --resource-group <PREFIX>-rg \
  --image <ACR_LOGIN_SERVER>/classymail:<COMMIT_SHA> \
  --set-env-vars APP_VERSION=<COMMIT_SHA>
az containerapp update --name <PREFIX>-worker --resource-group <PREFIX>-rg \
  --image <ACR_LOGIN_SERVER>/classymail:<COMMIT_SHA> \
  --set-env-vars APP_VERSION=<COMMIT_SHA>

# 5. Verify health
curl https://<API_FQDN>/healthz

# 6. Clean up
rm -rf .tmp build-context.tar.gz
```

- The `.dockerignore` is optimized — context should be ~500 KB, not 100+ MB.
- Temporary build artifacts go in `.tmp/` (gitignored + dockerignored). Never use `.build-context/`.
- Always tag with both `latest` and the short commit SHA.
- Both ACAs (api/worker) use the **same image** — the entrypoint differs via `CMD` override in Terraform.
- CI/CD uses `#.github/workflows/` — see `docs/CICD_GITHUB.md` for OIDC + GitHub Actions details.
