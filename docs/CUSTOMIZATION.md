# Customization Guide

> 🏢 **Purpose**: This document collects all ClassyMail-specific configuration, tagging, category taxonomy, and integration details. If you are deploying ClassyMail for a different organization, you can **skip or replace** everything in this file.
>
> For generic deployment instructions, see [DEPLOY_FROM_SCRATCH.md](DEPLOY_FROM_SCRATCH.md).

## Table of Contents

1. [ClassyMail Mandatory Tags](#classymail-mandatory-tags)
2. [Azure Policy Enforcement](#azure-policy-enforcement)
3. [Insurance Category Taxonomy](#insurance-category-taxonomy)
4. [Organization Branding](#organization-branding)
5. [Client Integration (CSV / Slug)](#client-integration)
6. [Customization Checklist for Other Organizations](#customization-checklist)

---

## Corporate Mandatory Tags

All Azure resources deployed by Terraform are tagged with ClassyMail corporate standards via `local.common_tags` in `infra/main.tf`:

| Tag | Valeur | Description |
|-----|--------|-------------|
| `cp-code-sa` | `devin` | Code service applicatif — Projet DEVIN (email classification MVP) |
| `cp-deploiement` | `terraform` | Méthode de déploiement (Infrastructure as Code) |
| `cp-environnement` | `d` | Environnement : **d** (développement), **t** (test), **p** (production) |
| `cp-proprietaire` | `my-org-team` | Propriétaire de la ressource (Direction Technique — Plateforme & Outils) |
| `cp-responsable` | `my-org-team` | Responsable technique de la ressource |
| `cp-supervision` | `oui` | Activer la supervision/monitoring (Application Insights, Azure Monitor) |

### Terraform Implementation

```terraform
# infra/main.tf — locals block
locals {
  common_tags = var.custom_tags_enabled ? {
    "cp-code-sa"       = "devin"
    "cp-deploiement"   = "terraform"
    "cp-environnement" = "d"
    "cp-proprietaire"  = "my-org-team"
    "cp-responsable"   = "my-org-team"
    "cp-supervision"   = "oui"
  } : {}
}

# Tags are propagated to all resources via: tags = local.common_tags
```

**To disable corporate tags** for non-tagged deployments:

```hcl
# terraform.tfvars
custom_tags_enabled = false
```

### Verification

```bash
# List all resources with a ClassyMail tag
az resource list --tag "cp-code-sa=devin" --query "[].{name:name, type:type}" -o table

# Show tags on a specific resource
az resource show --ids <RESOURCE_ID> --query tags -o json
```

---

## Azure Policy Enforcement

The system uses an Azure Policy (`infra/policy.tf`) to automatically add mandatory tags to any resource that is missing them. This ensures compliance even for resources created outside Terraform.

- **Policy name**: `add-mandatory-tags`
- **Scope**: Resource Group or Subscription (configurable via `var.tag_policy_scope`)
- **Action**: `modify` — auto-fills missing tags with ClassyMail default values
- **Remediation**: Applies tags to pre-existing resources

**Controls:**

| Variable | Default | Description |
|----------|---------|-------------|
| `custom_tags_enabled` | `true` | Enable corporate tags on all resources + policy definition |
| `tag_policy_enabled` | `true` | Enable the tag policy **assignment** (requires `custom_tags_enabled`) |
| `tag_policy_scope` | `resource_group` | Scope for policy assignment: `resource_group` or `subscription` |

**To fully disable** for non-tagged deployments:

```hcl
# terraform.tfvars
custom_tags_enabled   = false   # No corporate tags on resources
tag_policy_enabled = false   # No tag enforcement policy
```

---

## Insurance Category Taxonomy

The system uses the following French insurance email categories for classification:

| Category | Description (EN) |
|----------|-----------------|
| **Attestation habitation** | Housing insurance certificates |
| **Résiliation** | Contract cancellations |
| **Dommages électriques** | Electrical damage claims |
| **Sinistre dégât des eaux** | Water damage claims |
| **Modification contrat** | Contract modifications |
| **Demande de devis** | Quote requests |
| **Réclamation** | Complaints |

### Slug Convention

French characters are normalized for technical slugs:

| Input | Slug |
|-------|------|
| Attestation habitation | `attestation-habitation` |
| Résiliation | `resiliation` |
| Sinistre dégât des eaux | `sinistre-degat-des-eaux` |

Rules: `é→e`, `è→e`, `à→a`, `ê→e`, lowercase, spaces→dashes.

### Email Generation for Testing

The test data generators use these ClassyMail categories:

```bash
# Generate ClassyMail-specific test emails
uv run python scripts/generate_realistic_emails.py --count 50

# Generate for specific ClassyMail categories
uv run python scripts/generate_realistic_emails.py \
  --count 20 --categories "Attestation habitation" "Résiliation"
```

Each generated email includes insurance-specific vocabulary: addresses, contract numbers, dates, amounts, and proper French formatting.

### Fine-Tuning with ClassyMail Categories

The JSONL fine-tuning export uses a ClassyMail-specific system prompt:

```json
{"messages":[
  {"role":"system","content":"Tu classes des emails d'assurance en intentions et tu renvoies uniquement du JSON strict."},
  {"role":"user","content":"<MARKDOWN OCR ANONYMISÉ>"},
  {"role":"assistant","content":"{\"detected_intents\":[...],\"global_complexity\":\"Simple\"}"}
]}
```

For other organizations, customize:
- The system prompt in `FINETUNE_SYSTEM_PROMPT` env var
- The category list in the application configuration
- The email templates in `scripts/generate_realistic_emails.py`

---

## Organization Branding

| Variable | ClassyMail Value | Default | Location |
|----------|-----------|---------|----------|
| `ORGANIZATION_NAME` | `ClassyMail` | `ClassyMail` | UI header, env var |
| `var.organization_name` | `ClassyMail` | `ClassyMail` | `infra/main.tf` |

Set via Terraform:

```hcl
# terraform.tfvars
organization_name = "ClassyMail"
```

Or via environment variable:

```bash
export ORGANIZATION_NAME="ClassyMail"
```

---

## Client Integration

Full ClassyMail client integration documentation (CSV export format, slug rules, category definitions, migration guide) is in:

📄 **[INTEGRATION.md](INTEGRATION.md)**

Key ClassyMail-specific integration features:
- **CSV export format**: Semicolon-delimited (`ID;INTENTIONS`) for French locale compatibility
- **Professional prompt format**: `DÉFINITION` / `EXCLUSIONS` blocks per category
- **PII detection**: GDPR-compliant with dual-band anonymization
- **Configuration profiles**: Dev, staging, production with ClassyMail-specific defaults

---

## Customization Checklist

When adapting ClassyMail for a non-tagged organization:

| # | Action | Files to Modify |
|---|--------|----------------|
| 1 | Set `custom_tags_enabled = false` in `terraform.tfvars` | `infra/terraform.tfvars` |
| 2 | Set `tag_policy_enabled = false` in `terraform.tfvars` | `infra/terraform.tfvars` |
| 3 | Change `organization_name` to your company | `infra/terraform.tfvars` |
| 4 | Replace insurance categories with your domain | `scripts/generate_realistic_emails.py`, classification config |
| 5 | Update fine-tuning system prompt | `FINETUNE_SYSTEM_PROMPT` env var |
| 6 | Customize CSV export delimiter if needed | Client integration code |
| 7 | Update slug rules if non-French | Slug generation code |

---

## See Also

- [INTEGRATION.md](INTEGRATION.md) — Full ClassyMail client API & CSV format
- [INFRASTRUCTURE.md](INFRASTRUCTURE.md) — Terraform deployment (generic)
- [DEPLOY_FROM_SCRATCH.md](DEPLOY_FROM_SCRATCH.md) — Fresh tenant deployment guide
- [FINE_TUNING_DATA.md](FINE_TUNING_DATA.md) — Fine-tuning methodology (generic)
- [TESTING_EMAIL_GENERATION.md](TESTING_EMAIL_GENERATION.md) — Email generation for testing (generic)
