# CLI for RAG Operations

> 🛠️ Use these commands to verify infrastructure, backfill embeddings, and troubleshoot RAG.

## Verify Infrastructure & RBAC

### Bash (Linux/WSL/Cloud Shell)
```bash
# Set env overrides if needed
export RESOURCE_GROUP=email-poc-rg
export PREFIX=email-poc
# Run verification (checks resources, assigns roles if missing, placeholder for policies)
scripts/verify_infra.sh
```

### PowerShell (Windows/Azure Cloud Shell)
```pwsh
$env:RESOURCE_GROUP="email-poc-rg"
$env:PREFIX="email-poc"
./scripts/verify_infra.ps1
```

**What it does**
- Verifies presence of Resource Group, Storage, Service Bus, Cosmos, AI account, Container Apps
- Ensures Managed Identity has roles: Cognitive Services User, Storage Blob Data Contributor, Service Bus Data Sender/Receiver, Cosmos DB Built-in Data Contributor (and AcrPull if ACR exists)
- Connectivity checks to Cosmos/Storage/Service Bus
- 🚧 Policy check placeholder (add policy assignments when available)

## Backfill Embeddings & Chunks

```bash
uv run python -m classymail.cli --backfill-rag --max-items 50
```
- Regenerates email embeddings and stores chunk embeddings for RAG

## Run in Azure Cloud Shell
- Open https://shell.azure.com
- Clone repo or mount storage
- Run `az login` (Cloud Shell is usually pre-authenticated)
- Execute the scripts as above (bash or pwsh)

## Run in GitHub Actions
- Use `azure/login@v1` then run `scripts/verify_infra.sh`
- Ensure `AZURE_CREDENTIALS` secret is configured

## Related Docs
- [CLI_SETUP](CLI_SETUP.md)
- [RBAC_AUDIT](RBAC_AUDIT.md)
- [INFRASTRUCTURE](INFRASTRUCTURE.md)
