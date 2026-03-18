# Customization Guide

> 🏢 **Purpose**: This document collects all ClassyMail-specific configuration, tagging, category taxonomy, and integration details. If you are deploying ClassyMail for a different organization, you can **skip or replace** everything in this file.
>
> For generic deployment instructions, see [DEPLOY_FROM_SCRATCH.md](DEPLOY_FROM_SCRATCH.md).

## Table of Contents

1. [Corporate Mandatory Tags](#corporate-mandatory-tags)
2. [Azure Policy Enforcement](#azure-policy-enforcement)
3. [Business Category Taxonomy](#business-category-taxonomy)
4. [Organization Branding](#organization-branding)
5. [Client Integration (CSV / Slug)](#client-integration)
6. [Customization Checklist for Other Organizations](#customization-checklist)

---

## ClassyMail Mandatory Tags

All Azure resources deployed by Terraform are tagged with ClassyMail corporate standards via `local.common_tags` in `infra/main.tf`:

| Tag | Value | Description |
|-----|-------|-------------|
| `cp-code-sa` | `devin` | Application service code — DEVIN project (email classification MVP) |
| `cp-deploiement` | `terraform` | Deployment method (Infrastructure as Code) |
| `cp-environnement` | `d` | Environment: **d** (development), **t** (test), **p** (production) |
| `cp-proprietaire` | `classymail` | Resource owner (Technical Direction — Platform & Tools) |
| `cp-responsable` | `classymail` | Technical manager of the resource |
| `cp-supervision` | `oui` | Enable supervision/monitoring (Application Insights, Azure Monitor) |

### Terraform Implementation

```terraform
# infra/main.tf — locals block
locals {
  common_tags = var.custom_tags_enabled ? {
    "cp-code-sa"       = "devin"
    "cp-deploiement"   = "terraform"
    "cp-environnement" = "d"
    "cp-proprietaire"  = "classymail"
    "cp-responsable"   = "classymail"
    "cp-supervision"   = "oui"
  }: {}
}

# Tags are propagated to all resources via: tags = local.common_tags
```

**To disable ClassyMail tags** for non-ClassyMail deployments:

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

ClassyMail uses an Azure Policy (`infra/policy.tf`) to automatically add mandatory tags to any resource that is missing them. This ensures compliance even for resources created outside Terraform.

- **Policy name**: `add-mandatory-tags`
- **Scope**: Resource Group or Subscription (configurable via `var.tag_policy_scope`)
- **Action**: `modify` — auto-fills missing tags with ClassyMail default values
- **Remediation**: Applies tags to pre-existing resources

**Controls:**

| Variable | Default | Description |
|----------|---------|-------------|
| `custom_tags_enabled` | `true` | Enable ClassyMail mandatory tags on all resources + policy definition |
| `tag_policy_enabled` | `true` | Enable the tag policy **assignment** (requires `custom_tags_enabled`) |
| `tag_policy_scope` | `resource_group` | Scope for policy assignment: `resource_group` or `subscription` |

**To fully disable** for non-ClassyMail deployments:

```hcl
# terraform.tfvars
custom_tags_enabled   = false   # No ClassyMail tags on resources
tag_policy_enabled = false   # No tag enforcement policy
```

---

## Business Category Taxonomy

ClassyMail uses the following French business email categories for classification:

| Category | Description (EN) |
|----------|-----------------|
| **Billing inquiry** | Housing business certificates |
| **Cancellation** | Contract cancellations |
| **Technical support** | Electrical damage claims |
| **Service escalation** | Water damage claims |
| **Contract modification** | Contract modifications |
| **Quote request** | Quote requests |
| **Complaint** | Complaints |

### Slug Convention

French characters are normalized for technical slugs:

| Input | Slug |
|-------|------|
| Billing inquiry | `billing-inquiry` |
| Cancellation | `cancellation` |
| Service escalation | `service-escalation` |

Rules: `é→e`, `è→e`, `à→a`, `ê→e`, lowercase, spaces→dashes.

### Email Generation for Testing

The test data generators use these ClassyMail categories:

```bash
# Generate ClassyMail-specific test emails
uv run python scripts/generate_realistic_emails.py --count 50

# Generate for specific ClassyMail categories
uv run python scripts/generate_realistic_emails.py \
  --count 20 --categories "Billing inquiry" "Cancellation"
```

Each generated email includes business-specific vocabulary: addresses, contract numbers, dates, amounts, and proper French formatting.

### Fine-Tuning with ClassyMail Categories

The JSONL fine-tuning export uses a ClassyMail-specific system prompt:

```json
{"messages":[
  {"role":"system","content":"You classify emails into intents and return strict JSON only."},
  {"role":"user","content":"<ANONYMIZED OCR MARKDOWN>"},
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
| `ORGANIZATION_NAME` | `ClassyMail Business` | `ClassyMail` | UI header, env var |
| `var.organization_name` | `ClassyMail Business` | `ClassyMail` | `infra/main.tf` |

Set via Terraform:

```hcl
# terraform.tfvars
organization_name = "ClassyMail Business"
```

Or via environment variable:

```bash
export ORGANIZATION_NAME="ClassyMail Business"
```

---

## Client Integration

Full client integration documentation (CSV export format, slug rules, category definitions, migration guide) is in:

📄 **[INTEGRATION.md](INTEGRATION.md)**

Key integration features:
- **CSV export format**: Semicolon-delimited (`ID;INTENTIONS`) for locale compatibility
- **Structured prompt format**: `DEFINITION` / `EXCLUSIONS` blocks per category
- **PII detection**: GDPR-compliant with dual-band anonymization
- **Configuration profiles**: Dev, staging, production with environment-specific defaults

---

## Customization Checklist

When adapting ClassyMail for your organization:

| # | Action | Files to Modify |
|---|--------|----------------|
| 1 | Set `custom_tags_enabled = false` in `terraform.tfvars` | `infra/terraform.tfvars` |
| 2 | Set `tag_policy_enabled = false` in `terraform.tfvars` | `infra/terraform.tfvars` |
| 3 | Change `organization_name` to your company | `infra/terraform.tfvars` |
| 4 | Replace categories with your domain | `scripts/generate_realistic_emails.py`, classification config |
| 5 | Update fine-tuning system prompt | `FINETUNE_SYSTEM_PROMPT` env var |
| 6 | Customize CSV export delimiter if needed | Client integration code |
| 7 | Update slug rules for your locale | Slug generation code |

---

## See Also

- [INTEGRATION.md](INTEGRATION.md) — Full ClassyMail client API & CSV format
- [INFRASTRUCTURE.md](INFRASTRUCTURE.md) — Terraform deployment (generic)
- [DEPLOY_FROM_SCRATCH.md](DEPLOY_FROM_SCRATCH.md) — Fresh tenant deployment guide
- [PII_ANONYMIZATION_AND_USER_CORRECTIONS.md](PII_ANONYMIZATION_AND_USER_CORRECTIONS.md) — Fine-tuning methodology and PII protection
- [TESTING_EMAIL_GENERATION.md](TESTING_EMAIL_GENERATION.md) — Email generation for testing (generic)
