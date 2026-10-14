# ClassyMail Documentation

Start with the guide for your task. Each topic has one canonical home; examples
describe repository behavior, not proof that a particular Azure environment is deployed.

| Task | Guide |
| --- | --- |
| Install, run and test locally; use CLI helpers | [Local development](LOCAL_DEVELOPMENT.md) |
| Provision infrastructure, configure identity and CI/CD | [Deployment](DEPLOY_FROM_SCRATCH.md) |
| Understand components, ingestion and storage | [Architecture](ARCHITECTURE.md) |
| Configure multi-agent classification and AI Search examples | [Agentic classification](AGENTIC_CLASSIFICATION.md) |
| Configure model deployments, OCR and chat | [Models](MODELS.md) |
| Use the UI, customize categories and integrate the API/CSV | [Integration](INTEGRATION.md) |
| Review corrections, privacy limits and JSONL exports | [Data and privacy](PII_ANONYMIZATION_AND_USER_CORRECTIONS.md) |
| Understand usage-based cost estimates | [Costs](COSTS_LOGIC.md) |
| Diagnose failures and Terraform state drift | [Troubleshooting](TROUBLESHOOTING_MAP.md) |

Implementation references are linked in each guide. Environment variables are owned
by [configuration](../classymail/core/config.py); persisted defaults by
[settings](../classymail/services/settings_store.py); deployment resources by
[Terraform](../infra/main.tf). Consult those sources when exact defaults change.

The editable architecture source is
[classymail-architecture.drawio](assets/classymail-architecture.drawio), with
[SVG](assets/classymail-architecture.svg) and [PNG](assets/classymail-architecture.png) exports.

Model availability, quotas, prices and fine-tuning eligibility depend on the selected
subscription, region and service catalog. The code's model aliases do not establish
service availability. Historical migration proposals and environment-specific cleanup
instructions are not operational prerequisites.
