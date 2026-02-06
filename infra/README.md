# Infra folder

Terraform and deployment documentation lives in [docs/INFRASTRUCTURE.md](../docs/INFRASTRUCTURE.md).

**Quick Reference:**
- **Deployment Guide**: Run `./infra/deploy.ps1` from repo root
- **Required Models**: See [docs/MODELS.md](../docs/MODELS.md#required-models-for-poc)
- **Model Deployments**: Must be created manually in Azure AI Foundry after Terraform provisioning

**Mandatory AI Model Deployments for POC:**
1. `mistral-document-ai-2505` - OCR + Vision extraction
2. `Phi-4` - Primary classification (8K context)
3. `gpt-4o-mini` - Fallback classification (120K context)
4. `text-embedding-3-small` - Vector embeddings for RAG chatbot
5. `gpt-5.2-chat` or `gpt-5-mini` - Chatbot (recommended)
6. `gpt-5-nano` - Category assessment AI (recommended)

See [docs/INFRASTRUCTURE.md#required-ai-model-deployments](../docs/INFRASTRUCTURE.md#required-ai-model-deployments) for deployment instructions.

---

Quick deploy from the repo root:

```powershell
./infra/deploy.ps1
```
