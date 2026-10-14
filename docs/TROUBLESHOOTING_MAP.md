# Troubleshooting

## Start With The Failing Stage

Check `/healthz` for liveness and `/readyz` for readiness. Then inspect
`/api/admin/diagnostics`, `/api/admin/version`, processing history and the actual
API/worker revision logs. Do not equate a successful CI validation or image build with
a healthy deployed worker. Admin diagnostics can expose operational information;
restrict access appropriately.

| Symptom | First checks |
| --- | --- |
| API will not start | Required variables in [app.py](../classymail/app.py), credentials, dependency versions |
| PDF uploaded but no record appears | Per-file upload result, BlobCreated subscription, queue delivery and worker |
| Queued records do not finish | Worker revision, queue configuration, identity and model errors |
| Cosmos 403 | Data-plane role, principal/scope and firewall; management IAM alone is insufficient |
| Storage or Service Bus 403 | Runtime identity and data-plane roles; allow for propagation |
| OCR errors | Primary provider configuration, response/quota, standalone DI fallback endpoint |
| Model 404 / unsupported API version | Actual deployment alias and endpoint/API surface, not just model family name |
| Chat API-version error | OpenAI v1 chat uses `CHAT_API_VERSION=preview` |
| Poor classifications | Category descriptions/exclusions, OCR content, retrieval examples, saved settings |
| JSONL export refused/empty | Reviewed-ready threshold, processed records, nonempty intents and anonymizer errors |
| Blank UI | Frontend build output, asset loading and API responses |
| Costs unexpectedly zero | Usage-bearing sample count, rate configuration and omitted cost components |

Owners: [worker.py](../classymail/services/worker.py),
[pipeline.py](../classymail/services/pipeline.py),
[llm_pipeline.py](../classymail/services/llm_pipeline.py),
[diagnostics.py](../classymail/api/routers/admin/diagnostics.py).

## Model And OCR Diagnostics

`GET /api/admin/deployments` lists deployments discovered by the implementation.
`GET /api/admin/validate-aca-env` checks configuration; model-test and connectivity
operations live in [testing.py](../classymail/api/routers/admin/testing.py). Some tests
call billable services or create data. Availability in a catalog is not proof that a
runtime identity can invoke a deployment. See [models](MODELS.md).

Prefer a dedicated Document Intelligence resource for its fallback endpoint. Do not
assume a generic Foundry endpoint serves the Document Intelligence REST path.
Content Understanding is opt-in and requires its own endpoint configuration.

## Dead Letters And Reprocessing

Inspect `/api/admin/deadletter` before replaying. Fix the underlying endpoint, quota,
network or payload problem first. Replay, purge, reset and bulk reprocessing are
different operations; purge/reset delete data. Their implementations are in
[data_ops.py](../classymail/api/routers/admin/data_ops.py). Do not use reset to diagnose
one failed email.

## Terraform State Drift

If a plan proposes duplicate Container Apps or unexpected replacement, stop before apply.
Check the selected subscription, workspace/backend, `prefix`, `app_name`, actual app
resource IDs and [CI target names](../.github/workflows/deploy.yml).

```powershell
terraform -chdir=infra state list
terraform -chdir=infra state show azurerm_container_app.api
terraform -chdir=infra state show azurerm_container_app.worker
terraform -chdir=infra plan
```

Back up state securely before repairs; it may contain secrets. Import only a resource
whose exact Azure ID and Terraform address have been verified. Do not remove resources
from state merely because an old runbook says they were deleted. Review a new plan after
any import and reject unintended destroy/recreate. Image drift is intentionally ignored
by Terraform for CI image rollouts; that does not mean every other drift is harmless.

## Build, CI And Local Dependencies

OIDC failures: verify client/tenant/subscription values and federation subject.
ACR auth, registry firewall and runner network failures are distinct from Dockerfile
failures. Do not weaken security controls to bypass `connectivity_forbidden`.
See [deployment](DEPLOY_FROM_SCRATCH.md#github-actions-cicd).

If a managed workstation blocks package downloads, use the approved package feed and
do not bypass quarantine/TLS controls. Running tests with `--no-sync` checks installed
dependencies only, not a freshly updated lockfile. Keep this distinction in release
verification. Avoid committing internally resolved package-feed URLs.
