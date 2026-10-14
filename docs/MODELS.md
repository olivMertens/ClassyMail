# Models & Fallback



This repo uses a multi-step AI pipeline:



1) **OCR**: Mistral Document AI → Markdown

2) **Classification**: LLM (Phi-4 / GPT-5.4-mini fallback) → strict JSON multi-intents

3) **Vector Search**: Text Embedding for RAG (Chatbot)

4) **Category Assessment**: GPT-6 Luna → AI-powered category quality analysis



---



## Required Models for MVP



**MANDATORY deployments in your Microsoft AI Foundry / Azure OpenAI resource:**



| Model | Deployment Name | Purpose | Max Tokens | Required |

|-------|----------------|---------|------------|----------|

| **Mistral Document AI 2512** | `mistral-document-ai-2512` | OCR + Vision extraction | N/A (page-based) | ✅ YES |

| **Phi-4** | `Phi-4` or `phi-4` | Primary classification (8K context) | 8,000 | ✅ YES |



**OPTIONAL deployments (enhanced features):**



| Model | Deployment Name | Purpose | Max Tokens | Required |

|-------|----------------|---------|------------|----------|

| **GPT-5.4-mini** | `gpt-5.4-mini` | Fallback classification, anonymization, vision, agent tier2 (version 2026-03-17, GA, retires 2027-09-21) | 400,000 (272,000 input) | ⚠️ For large emails |

| **text-embedding-3-small** | `text-embedding-3-small` | Vector embeddings for RAG chatbot (retires 2028-02-09) | N/A (embeddings) | ⚠️ For chat feature |

| **GPT-6 Sol** | `gpt-6-sol` | Chatbot reasoning model (RAG conversational AI), synthetic data, agentic tier3 + red team (version 2026-09-22, GA, retires 2028-03-11) | — | ⚠️ For chat feature |

| **GPT-6 Luna** | `gpt-6-luna` | Category assessment + agentic orchestration/tier1 (version 2026-09-22, GA, retires 2028-03-11) | — | ⚠️ For category AI analysis |

| **GPT-4.1 / GPT-4.1-mini / GPT-4.1-nano** | `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano` | Legacy (Deprecated, retires 2027-04-14; existing environments only) | 1,000,000 | Optional (legacy) |

| **GPT-5.1** | `gpt-5.1` | Legacy chat deployment (existing environments only; replaced by `gpt-6-sol`) | 200,000 | Optional (legacy) |



> **Minimum viable setup**: Only Phi-4 + Mistral Document AI 2512 are required. The pipeline works without fallback, embeddings, or chat models.



### Migration from GPT-4.1



The GPT-4.1 family (`gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano`, version `2025-04-14`) is legacy (Deprecated, retires 2027-04-14; existing environments only): only subscriptions that already deployed it can create new deployments. New defaults: `gpt-4.1-nano` → `gpt-6-luna`, `gpt-4.1-mini` → `gpt-5.4-mini`, `gpt-4.1` and `gpt-5.1` → `gpt-6-sol`. `gpt-5.4-mini` has a 400K context (272K input) instead of 1M.



- Saved settings are **not** rewritten: an environment whose settings still name `gpt-4.1-*` keeps using those deployments until 2027-04-14.

- Terraform `deploy_legacy_models = true` (default `false`; `-DeployLegacyModels` in `infra/deploy.ps1`, `--deploy-legacy-models` in `infra/deploy.sh`) keeps the `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano` and `gpt-5.1` deployments.

- `chat_deployment` (default `gpt-6-sol`) and `fallback_deployment` (default `gpt-5.4-mini`) drive `CHAT_DEPLOYMENT` / `PHI_FALLBACK_DEPLOYMENT` / `ANONYMIZER_DEPLOYMENT` / `VISION_DEPLOYMENT` on both Container Apps. To keep an existing environment unchanged: `deploy_legacy_models=true`, `chat_deployment="gpt-5.1"`, `fallback_deployment="gpt-4.1-mini"`.



> **Pricing in the UI is hardcoded**: The cost/quality comparison chart in Settings and the per-email cost estimates use hardcoded Azure rates (2025-2026 averages). Actual costs depend on your region and Azure agreement. To customize, edit `MODEL_PRICING` in `classymail/services/costing.py` (backend) and `frontend/src/views/SettingsView.vue` (frontend).



**API Version Requirements:**

- Mistral OCR: Uses Foundry serverless endpoint (not OpenAI API)

- Classification models: OpenAI Chat Completions API (`2024-08-01-preview` or later)

- Embeddings: OpenAI Embeddings API (`2024-08-01-preview` or later)

- Chatbot: Azure OpenAI **v1 surface** via `agent_framework` `OpenAIChatClient` — requires `CHAT_API_VERSION=preview` (dated versions like `2024-08-01-preview` return `400 "API version not supported"`)



**Cost Implications:**

- **OCR**: ~1 €/1K pages (Mistral Document AI pricing)

- **Classification**: ~0.11 €/1M input tokens (Phi-4), ~0.43 €/1M output tokens

- **Fallback**: $0.75/1M input tokens (GPT-5.4-mini, Global), $4.50/1M output tokens

- **Category assessment / agentic tier1**: $0.10/1M input, $0.50/1M output (GPT-6 Luna, Global)

- **Chat / agentic tier3 / red team**: $2/1M input, $10/1M output (GPT-6 Sol, Global)

- **Embeddings**: ~0.02 €/1M tokens (text-embedding-3-small)

- **Reasoning Models**: ~3.00 €/1M input tokens (GPT-5-mini), ~12.00 €/1M output tokens



---



## API Parameter Differences: Standard vs Reasoning Models



**CRITICAL:** GPT-5.x and o-series reasoning models use DIFFERENT API parameters than GPT-4.x models.



### Standard Models (Phi-4; legacy GPT-4.1 family)



**Supported Parameters:**

```json

{

  "model": "phi-4",

  "messages": [...],

  "max_tokens": 1500,        // ✅ Use max_tokens

  "temperature": 0.3,        // ✅ Temperature supported

  "top_p": 1.0,              // ✅ Top-p supported

  "response_format": {"type": "json_object"}

}

```



### Reasoning Models (GPT-5.x, GPT-6.x, o1, o3, o4)



**Supported Parameters:**

```json

{

  "model": "gpt-6-sol",

  "messages": [...],

  "max_completion_tokens": 1500,  // ✅ Use max_completion_tokens (NOT max_tokens)

  "reasoning_effort": "none",     // ✅ Default for fast classification calls (GPT-5.1+ / GPT-6)

  // ❌ NO temperature parameter (rejected with HTTP 400)

  // ❌ NO top_p parameter

  "response_format": {"type": "json_object"}

}

```



**Why the Difference?**

- Reasoning models use internal Chain-of-Thought (CoT) processing

- They generate intermediate reasoning tokens before the final answer

- `max_completion_tokens` limits only the VISIBLE output tokens

- Temperature/top_p would interfere with the reasoning process



### Centralized Compatibility Layer (`classymail/core/llm_compat.py`)



All LLM calls use `build_chat_params()` to produce the correct parameters automatically:



```python

from classymail.services.openai_client_factory import build_chat_params



payload = {

    "model": deployment,

    "messages": [...],

    **build_chat_params(deployment, temperature=0.0, max_output_tokens=2000),

}

# Classic model → {"temperature": 0.0, "max_tokens": 2000}

# Reasoning model → {"max_completion_tokens": 2000, "reasoning_effort": "none"}  (temperature omitted)

```



**Detected reasoning families:** `o1`, `o3`, `o4`, `gpt-5`, `gpt5`, `gpt-6`, `gpt6`, `kimi`



`reasoning_effort="none"` is sent by default on all fast classification calls (GPT-5.1+ and GPT-6 accept it; it is dropped for models that reject it), so latency/cost stay comparable to the former gpt-4.1-nano/mini defaults. The agentic `reasoning_effort` setting (default `none`) still applies to specialized agents.



**Additional Helper — `extract_message_content()`:**

Some reasoning models (e.g. Kimi-K2.5, certain o-series) return output in `reasoning_content` instead of `content`. The `extract_message_content(message)` helper checks both fields and returns whichever is non-empty.



**Implementation References:**

- [llm_compat.py](../classymail/core/llm_compat.py): Centralized helpers (`is_reasoning_model`, `build_chat_params`, `extract_message_content`)

- [test_llm_compat.py](../tests/test_llm_compat.py): 29 tests covering model detection and parameter construction



---



## Vector Search & Embeddings



The "Chat with Email" feature uses **Retrieval Augmented Generation (RAG)**.

- It requires an embedding model to convert email content into vectors.

- Vectors are stored in Cosmos DB (NoSQL API) with vector index enabled.



**Required Model:**

- **Model:** `text-embedding-3-small` (or equivalent)

- **Deployment Name:** `text-embedding-3-small` (configure via `EMBEDDING_DEPLOYMENT` env var)

- **Endpoint:** Uses `EMBEDDING_ENDPOINT` (or defaults to `PHI_ENDPOINT`)



Ensure this model is deployed in your Microsoft AI Foundry / Azure OpenAI resource for the chatbot to work.



## Mistral Document AI OCR



**API Endpoint:**

- Uses Microsoft AI Foundry serverless endpoint (full URL in `MISTRAL_ENDPOINT`)

- **NOT** standard OpenAI Chat Completions API

- Payload format: `{"model": "...", "document": {"type": "document_url", "document_url": "data:application/pdf;base64,..."}}`

- Response format: `{"pages": [{"markdown": "...", "images": [...]}, ...]}`

- **Reference:** [Mistral Document AI on Microsoft AI Foundry](https://ai.azure.com/catalog/models/mistral-document-ai-2512)



**Document Size Limits:**

- **Maximum file size:** 30 MB

- **Maximum pages (OCR):** 30 pages

- **Maximum pages (Annotations):** 8 pages

- **Supported formats:** PDF, PPTX, DOCX, PNG, JPEG/JPG, AVIF



**Important Ratings:**

- Pure OCR processes efficiently and quickly

- Annotation processes can be slower and may result in timeouts

- Content safety is applied for annotations only, not enforced for OCR outputs



**Reference:** [Mistral Document AI on Microsoft AI Foundry](https://ai.azure.com/catalog/models/mistral-document-ai-2512)



## Why fallback is needed



Some PDFs produce very large OCR markdown. If the markdown (prompt) exceeds the primary model's context window, the API may fail or the model may truncate important parts.



The app includes a **fallback model** designed for:

- longer context

- low latency

- lower cost



Recommended default fallback: **gpt-5.4-mini** (configure as an Azure OpenAI deployment; version 2026-03-17, GA, retires 2027-09-21).



## Configuration (env vars)



OCR (Mistral Document AI 25.05):

- `MISTRAL_DEPLOYMENT` (default: `mistral-document-ai-2512`)



Primary (fine-tunable):

- `PHI_ENDPOINT`

- `PHI_DEPLOYMENT` (supports `phi-4`, `gpt-6-luna`)



Fallback/Audit (high quality):

- `PHI_FALLBACK_ENDPOINT` (defaults to `PHI_ENDPOINT`)

- `PHI_FALLBACK_DEPLOYMENT` (recommended: `gpt-5.4-mini` for fallback classification)



Context sizing:

- `PHI_PRIMARY_MAX_INPUT_TOKENS` (default: `8000` for Phi-4)

- `PHI_FALLBACK_MAX_INPUT_TOKENS` (default: `120000`, within the 272K input limit of gpt-5.4-mini; set higher only after validating quota)

- `PHI_RESERVED_OUTPUT_TOKENS` (default: `1000`)



## Fine-Tuning & LoRA Compatibility



**Fine-Tuning Support (Microsoft AI Foundry / Azure OpenAI):**



The following models support fine-tuning for custom classification tasks:



- ✅ **Phi-4** (LoRA via Microsoft AI Foundry, 8K context, **recommended for this project**)

- ✅ **Phi-3** family (LoRA via Microsoft AI Foundry, all variants)

- ✅ **gpt-4.1-mini** (Azure OpenAI fine-tuning API, 1M context; base model legacy — Deprecated, retires 2027-04-14)

- ✅ **GPT-4.1 Nano** (Microsoft AI Foundry fine-tuning, 1M+ context; base model legacy — Deprecated, retires 2027-04-14)



**Models NOT Supporting Fine-Tuning:**



- ❌ **GPT-5 Mini** (future preview model, fine-tuning not yet available as of Feb 2026)

- ❌ **Mistral OCR** (specialized for document understanding, not for classification fine-tuning)



**Fine-Tuning Process:**

1. Export validated emails to JSONL format (see [PII_ANONYMIZATION_AND_USER_CORRECTIONS.md](PII_ANONYMIZATION_AND_USER_CORRECTIONS.md))

2. Upload training/validation datasets to Microsoft AI Foundry

3. Create fine-tuning job with LoRA adapters (Foundry UI or Azure OpenAI CLI/SDK)

4. Deploy custom model (e.g., `phi-4-custom`; legacy GPT-4.1 base models until 2027-04-14: `gpt-4.1-mini-custom`, `gpt-4_1-nano-custom`)

5. Update `PHI_DEPLOYMENT` or `PHI_FALLBACK_DEPLOYMENT` to use the custom deployment



**Recommended Fine-Tuning Strategy:**

- **Primary (Recommended)**: Fine-tune **Phi-4** with LoRA (fast iteration, lower cost, good results)

- **Cost-Optimized Alternative** (legacy, existing environments only until 2027-04-14): Fine-tune **gpt-4.1-mini** (training cost varies by region)

- **Performance-Optimized** (legacy, existing environments only until 2027-04-14): Fine-tune **GPT-4.1 Nano** (training cost: $0.17/1M tokens)



**Important Ratings:**

- **Phi-4 LoRA** is the recommended approach for this classification pipeline (fast, cost-effective)

- Fine-tuned models maintain the same endpoint compatibility (OpenAI Chat API format)

- Always test custom models with the fallback mechanism enabled

- gpt-5.4-mini is the recommended Azure OpenAI fallback/anonymizer model for this project



**References:**

- Microsoft AI Foundry Fine-Tuning: https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning?view=foundry-classic&tabs=oai-sdk%2Cazure-openai&pivots=programming-language-python

- Phi-4 LoRA Best Practices: https://github.com/microsoft/PhiCookBook

- Azure OpenAI Fine-Tuning Guide: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/fine-tuning



## Current GPT Family Options



The system is ready for current GPT deployments. You can configure `PHI_DEPLOYMENT`, `PHI_FALLBACK_DEPLOYMENT`, or agentic settings to point to these deployments if available in your region:



- **GPT-6 Sol** (`gpt-6-sol`): Agentic tier3, red-team, RAG chat reasoning and synthetic data model (version 2026-09-22, GA, retires 2028-03-11; use `CHAT_API_VERSION=preview`).

- **GPT-6 Luna** (`gpt-6-luna`): Category assessment, agentic orchestrator and tier1 (version 2026-09-22, GA, retires 2028-03-11).

- **GPT-5.4-mini** (`gpt-5.4-mini`): Fallback, anonymizer, vision, agentic tier2 (version 2026-03-17, GA, retires 2027-09-21).

- **GPT-4.1** / **GPT-5.1** (`gpt-4.1`, `gpt-5.1`): legacy (GPT-4.1 Deprecated, retires 2027-04-14; existing environments only, see [Migration from GPT-4.1](#migration-from-gpt-41)).



If selected, the UI will reflect the capabilities usage. Ensure your Azure OpenAI quota supports these models.



Cost tracking (configurable):

- `PHI4_COST_PER_1K_INPUT`, `PHI4_COST_PER_1K_OUTPUT`

- `FALLBACK_COST_PER_1K_INPUT`, `FALLBACK_COST_PER_1K_OUTPUT`



The code logs which model was used and stores usage + estimated cost in Cosmos.



## OCR Fallback: Document Intelligence via AI Foundry



When Mistral OCR fails (timeout, quota, circuit breaker open), the system can fall back to **Azure Document Intelligence** for OCR.



**Configuration:**

- `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` — Endpoint for DI (uses AI Foundry endpoint by default; set `deploy_document_intelligence=true` in Terraform for a dedicated resource)

- `DOC_INTELLIGENCE_API_VERSION` — API version (default: `2024-11-30`)



**Behavior:**

- If `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` is set, Mistral OCR failures automatically trigger DI fallback

- If not set, OCR failures raise `OCRFailed` without fallback

- DI uses the `prebuilt-read` model (Layout API) and returns Markdown output

- Authentication via managed identity (`Cognitive Services User` role on the AI Foundry account or dedicated DI resource)



**Reference:** See [OCR_VISION_STRATEGY.md](OCR_VISION_STRATEGY.md) for the full architectural decision record.



---



## Cost Analysis



For comprehensive pricing information, cost-benefit analysis of fine-tuned vs pre-trained models, and detailed cost tracking strategies, see [COSTS_LOGIC.md](COSTS_LOGIC.md).



Configuration reference:

- Set pricing via env vars: `PHI4_COST_PER_1K_INPUT`, `PHI4_COST_PER_1K_OUTPUT`, `FALLBACK_COST_PER_1K_INPUT`, `FALLBACK_COST_PER_1K_OUTPUT`

- Pricing varies by region/tenant; update env vars from your Azure portal to ensure accurate per-email cost tracking
