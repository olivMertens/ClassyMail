# Infra folder

Terraform and deployment documentation lives in [docs/INFRASTRUCTURE.md](../docs/INFRASTRUCTURE.md).

**Quick Reference:**
- **Deployment Guide**: Run `./infra/deploy.ps1` from repo root
- **Fresh Tenant**: See [docs/DEPLOY_FROM_SCRATCH.md](../docs/DEPLOY_FROM_SCRATCH.md) for complete onboarding
- **Required Models**: See [docs/MODELS.md](../docs/MODELS.md#required-models-for-poc)
- **Model Deployments**: Must be created manually in Azure AI Foundry after Terraform provisioning
- **Custom Tags**: Configurable via `g2s_tags_enabled` variable (see [G2S_CUSTOMIZATION.md](../docs/G2S_CUSTOMIZATION.md#g2s-mandatory-tags))

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
