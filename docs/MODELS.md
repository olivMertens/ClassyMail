# Models & Fallback

This repo uses a multi-step AI pipeline:

1) **OCR**: Mistral Document AI → Markdown
2) **Classification**: LLM (Phi-4 / GPT-4o-mini fallback) → strict JSON multi-intents
3) **Vector Search**: Text Embedding for RAG (Chatbot)
4) **Category Assessment**: GPT-5-nano (reasoning model) → AI-powered category quality analysis

---

## Required Models for MVP

**MANDATORY deployments in your Azure AI Foundry / Azure OpenAI resource:**

| Model | Deployment Name | Purpose | Max Tokens | Required |
|-------|----------------|---------|------------|----------|
| **Mistral Document AI 2505** | `mistral-document-ai-2512` | OCR + Vision extraction | N/A (page-based) | ✅ YES |
| **Phi-4** | `Phi-4` or `phi-4` | Primary classification (8K context) | 8,000 | ✅ YES |
| **GPT-4o-mini** | `gpt-4o-mini` | Fallback classification (120K context) | 120,000 | ✅ YES |
| **text-embedding-3-small** | `text-embedding-3-small` | Vector embeddings for RAG chatbot | N/A (embeddings) | ✅ YES |
| **GPT-5.2-chat** or **GPT-5-mini** | `gpt-5.2-chat` or `gpt-5-mini` | Chatbot (RAG conversational AI) | 200,000 | ⚠️ RECOMMENDED |
| **GPT-5-nano** | `gpt-5-nano` | Category assessment (reasoning model) | 200,000 | ⚠️ RECOMMENDED |

**API Version Requirements:**
- Mistral OCR: Uses Foundry serverless endpoint (not OpenAI API)
- Classification models: OpenAI Chat Completions API (`2024-08-01-preview` or later)
- Embeddings: OpenAI Embeddings API (`2024-08-01-preview` or later)
- Chatbot: OpenAI Chat Completions API (`2024-08-01-preview` or later)

**Cost Implications:**
- **OCR**: ~1 €/1K pages (Mistral Document AI pricing)
- **Classification**: ~0.11 €/1M input tokens (Phi-4), ~0.43 €/1M output tokens
- **Fallback**: ~0.15 €/1M input tokens (GPT-4o-mini), ~0.60 €/1M output tokens
- **Embeddings**: ~0.02 €/1M tokens (text-embedding-3-small)
- **Reasoning Models**: ~3.00 €/1M input tokens (GPT-5-mini), ~12.00 €/1M output tokens

---

## API Parameter Differences: Standard vs Reasoning Models

**CRITICAL:** GPT-5.x and o-series reasoning models use DIFFERENT API parameters than GPT-4.x models.

### Standard Models (GPT-4o, GPT-4o-mini, GPT-4.1, Phi-4)

**Supported Parameters:**
```json
{
  "model": "gpt-4o-mini",
  "messages": [...],
  "max_tokens": 1500,        // ✅ Use max_tokens
  "temperature": 0.3,        // ✅ Temperature supported
  "top_p": 1.0,              // ✅ Top-p supported
  "response_format": {"type": "json_object"}
}
```

### Reasoning Models (GPT-5.x, o1, o3, o4)

**Supported Parameters:**
```json
{
  "model": "gpt-5-nano",
  "messages": [...],
  "max_completion_tokens": 1500,  // ✅ Use max_completion_tokens (NOT max_tokens)
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
from classymail.core.llm_compat import build_chat_params

payload = {
    "model": deployment,
    "messages": [...],
    **build_chat_params(deployment, temperature=0.0, max_output_tokens=2000),
}
# Classic model → {"temperature": 0.0, "max_tokens": 2000}
# Reasoning model → {"max_completion_tokens": 2000}  (temperature omitted)
```

**Detected reasoning families:** `o1`, `o3`, `o4`, `gpt-5`, `gpt5`, `kimi`

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

Ensure this model is deployed in your Azure AI Foundry / Azure OpenAI resource for the chatbot to work.

## Mistral Document AI OCR

**API Endpoint:**
- Uses Azure AI Foundry serverless endpoint (full URL in `MISTRAL_ENDPOINT`)
- **NOT** standard OpenAI Chat Completions API
- Payload format: `{"model": "...", "document": {"type": "document_url", "document_url": "data:application/pdf;base64,..."}}`
- Response format: `{"pages": [{"markdown": "...", "images": [...]}, ...]}`
- **Reference:** [Mistral Document AI on Azure AI Foundry](https://ai.azure.com/catalog/models/mistral-document-ai-2512)

**Document Size Limits:**
- **Maximum file size:** 30 MB
- **Maximum pages (OCR):** 30 pages
- **Maximum pages (Annotations):** 8 pages
- **Supported formats:** PDF, PPTX, DOCX, PNG, JPEG/JPG, AVIF

**Important Notes:**
- Pure OCR processes efficiently and quickly
- Annotation processes can be slower and may result in timeouts
- Content safety is applied for annotations only, not enforced for OCR outputs

**Reference:** [Mistral Document AI on Azure AI Foundry](https://ai.azure.com/catalog/models/mistral-document-ai-2512)

## Why fallback is needed

Some PDFs produce very large OCR markdown. If the markdown (prompt) exceeds the primary model’s context window, the API may fail or the model may truncate important parts.

The app includes a **fallback model** designed for:
- longer context
- low latency
- lower cost

Recommended default fallback: **gpt-4o-mini** (configure as an Azure OpenAI deployment).

## Configuration (env vars)

OCR (Mistral Document AI 25.05):
- `MISTRAL_DEPLOYMENT` (default: `mistral-document-ai-2512`)

Primary (fine-tunable):
- `PHI_ENDPOINT`
- `PHI_DEPLOYMENT` (supports `phi-4`, `gpt-4o`, `gpt-4.1-nano`)

Fallback/Audit (high quality):
- `PHI_FALLBACK_ENDPOINT` (defaults to `PHI_ENDPOINT`)
- `PHI_FALLBACK_DEPLOYMENT` (recommended: `gpt-5-mini` for adversarial comparison)

Context sizing:
- `PHI_PRIMARY_MAX_INPUT_TOKENS` (default: `8000` for Phi-4)
- `PHI_FALLBACK_MAX_INPUT_TOKENS` (default: `120000` for gpt-4o-mini; set to `200000` when using gpt-5-mini)
- `PHI_RESERVED_OUTPUT_TOKENS` (default: `1000`)

## Adversarial Comparison Strategy

**Recommended Configuration:**

```env
# Primary: Phi-4 (fine-tune with your domain data)
PHI_DEPLOYMENT=phi-4-custom
PHI_PRIMARY_MAX_INPUT_TOKENS=8000

# Audit: gpt-5-mini (high quality, general intelligence)
PHI_FALLBACK_DEPLOYMENT=gpt-5-mini
PHI_FALLBACK_MAX_INPUT_TOKENS=200000
```

**Why gpt-5-mini for adversarial comparison?**

Based on Azure AI Foundry benchmarks (Feb 2026):
- **Quality: 0.89** (vs 0.72 for gpt-4o-mini, 0.69 for gpt-4.1-nano)
- **Throughput: 127** (highest among compared models)
- **Safety: 0.53** (balanced)
- Even without fine-tuning, provides superior baseline detection
- Acts as "oracle" to validate fine-tuned Phi-4 classifications

**Workflow:**
1. Phi-4 (fine-tuned) processes emails → Your taxonomy
2. Enable comparison mode → gpt-5-mini also processes same emails
3. Compare results:
   - **Agreement** → High confidence, mark as validated
   - **Disagreement** → Review case, excellent training data for next iteration
4. gpt-5-mini's higher quality often reveals edge cases Phi-4 missed

## Fine-Tuning & LoRA Compatibility

**Fine-Tuning Support (Azure AI Foundry / Azure OpenAI):**

The following models support fine-tuning for custom classification tasks:

- ✅ **Phi-4** (LoRA via Azure AI Foundry, 8K context, **recommended for this project**)
- ✅ **Phi-3** family (LoRA via Azure AI Foundry, all variants)
- ✅ **gpt-4o-mini** (Azure OpenAI fine-tuning API, 128K context, cost-effective)
- ✅ **GPT-4.1 Nano** (Azure AI Foundry fine-tuning, 1M+ context, optimized throughput)

**Models NOT Supporting Fine-Tuning:**

- ❌ **GPT-5 Mini** (future preview model, fine-tuning not yet available as of Feb 2026)
- ❌ **Mistral OCR** (specialized for document understanding, not for classification fine-tuning)

**Fine-Tuning Process:**
1. Export validated emails to JSONL format (see [FINE_TUNING_DATA.md](FINE_TUNING_DATA.md))
2. Upload training/validation datasets to Azure AI Foundry
3. Create fine-tuning job with LoRA adapters (Foundry UI or Azure OpenAI CLI/SDK)
4. Deploy custom model (e.g., `phi-4-custom`, `gpt-4o-mini-custom`, `gpt-4_1-nano-custom`)
5. Update `PHI_DEPLOYMENT` or `PHI_FALLBACK_DEPLOYMENT` to use the custom deployment

**Recommended Fine-Tuning Strategy:**
- **Primary (Recommended)**: Fine-tune **Phi-4** with LoRA (fast iteration, lower cost, good results)
- **Cost-Optimized Alternative**: Fine-tune **gpt-4o-mini** (training cost: $0.69/1M tokens, best supported)
- **Performance-Optimized**: Fine-tune **GPT-4.1 Nano** (training cost: $0.17/1M tokens, highest throughput)

**Important Notes:**
- **Phi-4 LoRA** is the recommended approach for this classification pipeline (fast, cost-effective)
- Fine-tuned models maintain the same endpoint compatibility (OpenAI Chat API format)
- Always test custom models with the fallback mechanism enabled
- gpt-4o-mini has the most mature fine-tuning pipeline as of Feb 2026

**References:**
- Azure AI Foundry Fine-Tuning: https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning?view=foundry-classic&tabs=oai-sdk%2Cazure-openai&pivots=programming-language-python
- Phi-4 LoRA Best Practices: https://github.com/microsoft/PhiCookBook
- Azure OpenAI Fine-Tuning Guide: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/fine-tuning

## Future Models (Preview)

The system is ready for next-gen models. You can configure `PHI_DEPLOYMENT` or `PHI_FALLBACK_DEPLOYMENT` env vars to point to these deployments if available in your region:

- **GPT-4.1** (`gpt-4.1-preview`): High intelligence, fast reasoning.
- **GPT-5** (`gpt-5-preview`): Theoretical placeholder for next-gen reasoning capabilities.

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

**Reference:** See [ADR_OCR_STRATEGY.md](ADR_OCR_STRATEGY.md) for the full architectural decision record.

---

## Cost Analysis

For comprehensive pricing information, cost-benefit analysis of fine-tuned vs pre-trained models, and detailed cost tracking strategies, see [COSTS_LOGIC.md](COSTS_LOGIC.md).

Configuration reference:
- Set pricing via env vars: `PHI4_COST_PER_1K_INPUT`, `PHI4_COST_PER_1K_OUTPUT`, `FALLBACK_COST_PER_1K_INPUT`, `FALLBACK_COST_PER_1K_OUTPUT`
- Pricing varies by region/tenant; update env vars from your Azure portal to ensure accurate per-email cost tracking
