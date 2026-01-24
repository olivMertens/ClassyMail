# CICD_GITLAB

This document describes a GitLab CI/CD approach for building the container and running Terraform.

## Recommended auth: OIDC (no long-lived secrets)

Prefer GitLab → Azure workload identity federation (OIDC) so pipelines avoid client secrets.

High level:
1) Create an Entra app registration / service principal.
2) Configure a federated credential for your GitLab project.
3) Assign RBAC roles scoped to the resource group.

References:
- Workload identity federation trust (Microsoft Learn): https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation-create-trust

If OIDC is not possible, fall back to a short-lived service principal secret stored in GitLab CI variables.

## Pipeline structure

- **build**: build/push container image (ACR)
- **validate**: run `python -m py_compile` / tests
- **terraform:plan**: plan infra changes
- **terraform:apply**: manual apply job

## Minimal example (skeleton)

```yaml
stages:
  - validate
  - build
  - terraform

validate:
  stage: validate
  image: python:3.11
  script:
    - pip install -r requirements.txt
    - python -m py_compile main.py

terraform_plan:
  stage: terraform
  image: hashicorp/terraform:1.7
  script:
    - terraform -chdir=infra init -upgrade
    - terraform -chdir=infra validate
    - terraform -chdir=infra plan -var "subscription_id=$AZURE_SUBSCRIPTION_ID" -out tfplan
  artifacts:
    paths:
      - infra/tfplan

terraform_apply:
  stage: terraform
  image: hashicorp/terraform:1.7
  when: manual
  script:
    - terraform -chdir=infra init -upgrade
    - terraform -chdir=infra apply -auto-approve tfplan
```

## Important best practices

- Avoid local state for CI; prefer remote backend + locking.
- Keep Azure permissions minimal and scoped.
- Protect apply jobs with branch rules and approvals.
