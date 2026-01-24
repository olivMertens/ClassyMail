# Models & Fallback

This repo uses a 2-step AI pipeline:

1) OCR: Mistral Document AI → Markdown
2) Classification: LLM → strict JSON multi-intents

## Why fallback is needed

Some PDFs produce very large OCR markdown. If the markdown (prompt) exceeds the primary model’s context window, the API may fail or the model may truncate important parts.

The app includes a **fallback model** designed for:
- longer context
- low latency
- lower cost

Recommended default fallback: **gpt-4o-mini** (configure as an Azure OpenAI deployment).

## Configuration (env vars)

Primary (existing):
- `PHI_ENDPOINT`
- `PHI_DEPLOYMENT`

Fallback (new):
- `PHI_FALLBACK_ENDPOINT` (defaults to `PHI_ENDPOINT`)
- `PHI_FALLBACK_DEPLOYMENT` (example: `gpt-4o-mini`)

Context sizing (new):
- `PHI_PRIMARY_MAX_INPUT_TOKENS` (example: `8000`)
- `PHI_FALLBACK_MAX_INPUT_TOKENS` (example: `120000`)
- `PHI_RESERVED_OUTPUT_TOKENS` (example: `1000`)

Cost tracking (configurable):
- `PHI4_COST_PER_1K_INPUT`, `PHI4_COST_PER_1K_OUTPUT`
- `FALLBACK_COST_PER_1K_INPUT`, `FALLBACK_COST_PER_1K_OUTPUT`

The code logs which model was used and stores usage + estimated cost in Cosmos.

## Cost display

Pricing changes by region/tenant and can differ between Azure AI Foundry vs Azure OpenAI. This repo treats prices as configuration (env vars). Set them from your Azure pricing page/portal so the per-email costs stay accurate.

## References

- Azure AI Foundry models pricing: https://azure.microsoft.com/fr-fr/pricing/details/ai-foundry-models/microsoft/
