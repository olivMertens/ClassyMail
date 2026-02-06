# Infra folder

Terraform and deployment documentation lives in [docs/INFRASTRUCTURE.md](../docs/INFRASTRUCTURE.md).

**Quick Reference:**
- **Deployment Guide**: Run `./infra/deploy.ps1` from repo root
- **Required Models**: See [docs/MODELS.md](../docs/MODELS.md#required-models-for-poc)
- **Model Deployments**: Must be created manually in Azure AI Foundry after Terraform provisioning
- **Mandatory G2S Tags**: All resources are tagged with G2S standards (cp-code-sa=devin, cp-deploiement=terraform, etc.)

**Mandatory AI Model Deployments for POC:**
1. `mistral-document-ai-2505` - OCR + Vision extraction
2. `Phi-4` - Primary classification (8K context)
3. `gpt-4o-mini` - Fallback classification (120K context)
4. `text-embedding-3-small` - Vector embeddings for RAG chatbot
5. `gpt-5.2-chat` or `gpt-5-mini` - Chatbot (recommended)
6. `gpt-5-nano` - Category assessment AI (recommended)

See [docs/INFRASTRUCTURE.md#required-ai-model-deployments](../docs/INFRASTRUCTURE.md#required-ai-model-deployments) for deployment instructions.

---

## Tags Obligatoires G2S

Toutes les ressources Azure déployées par Terraform sont automatiquement tagées avec les valeurs suivantes :

| Tag | Valeur | Description |
|-----|--------|-------------|
| `cp-code-sa` | `devin` | Code service applicatif (projet DEVIN) |
| `cp-deploiement` | `terraform` | Méthode de déploiement |
| `cp-environnement` | `d` | Environnement de développement |
| `cp-proprietaire` | `g2s-dtpo-iaf` | Propriétaire de la ressource |
| `cp-responsable` | `g2s-dtpo-iaf` | Responsable technique |
| `cp-supervision` | `oui` | Activer la supervision |

Ces tags sont appliqués via :
1. **`local.common_tags`** dans `main.tf` (propagation aux ressources)
2. **Azure Policy** dans `policy.tf` (application automatique sur ressources existantes)

---

Quick deploy from the repo root:

```powershell
./infra/deploy.ps1
```
