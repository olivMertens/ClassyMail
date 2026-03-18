# OCR & Vision Strategy

This document consolidates the OCR architecture decision (ADR 001) and the Vision strategy performance analysis.

## Table of Contents
- [ADR 001: OCR & Classification Strategy](#adr-001-ocr--classification-strategy)
- [OCR Fallback — Document Intelligence](#ocr-fallback--document-intelligence)
- [Vision Strategy Performance Analysis](#vision-strategy-performance-analysis)
- [Recommendations](#recommendations)

---

## ADR 001: OCR & Classification Strategy

### Context
We need to extract intents and metadata (Sender, Subject) from PDF emails (images/scanned).
We considered two approaches for the Mistral/AI pipeline:

1. **Mistral Document AI (Structured)**: Using specific endpoints to extract key-value pairs directly.
2. **Mistral OCR (Markdown) + LLM Classification**: Using Mistral to generate a full Markdown representation of the document, then feeding that into a reasoning LLM (Phi-4) for classification.

### Decision
We chose **Mistral OCR (Markdown) + LLM Classification**.

### Rationale

#### 1. Token Efficiency & Context
- **Document AI** is excellent for rigid forms (e.g., extracting "Invoice Total" or "Tax ID").
- **Email Classification** requires understanding the *nuance* and *tone* of the text.
- By converting the PDF to **Markdown**, we preserve the structure (headers, lists, bold text) which is critical for understanding the document's hierarchy, but we provide the LLM with the *full text* so it can reason about "implied" intents (e.g., a customer sounding angry about a delay, even if they don't explicitly say "Complaint").

#### 2. Image & Vision Capabilities
- **Current State**: Mistral Document AI (`mistral-document-ai-2512`) already analyzes images within the PDF and describes them in the Markdown output (e.g., `![Image: Company Logo]`).
- **Future Vision**: If we need to analyze specific damage photos (e.g., a car crash photo attached), the Markdown approach allows us to see *where* the image is. We can then upgrade our pipeline to send the specific image slices to a Vision-Language Model (VLM) like `Pixtral` or `GPT-4o` only when necessary, rather than processing every pixel of every page as an image (which is cost-prohibitive).

#### 3. Flexibility
- Markdown is a universal format. If we switch LLMs (e.g., from Phi-4 to GPT-4o or Llama 3), the input format stays the same.
- Structured Document AI output often requires re-training or complex schema definitions for every new intent we want to discover.

### Processing Strategies
We have implemented a **"Processing Strategy"** setting in the UI to allow flexibility:

- **Standard (Text/Markdown)**: Best balance of speed and cost. Relies on text and layout.
- **Deep Reasoning (CoT)**: Adds a "Chain of Thought" requirement to the LLM prompt. It asks the AI to "Think step-by-step" before deciding. This improves accuracy for complex/ambiguous emails but increases output token costs.
- **Vision (Future)**: Placeholder for full VLM integration.

---

## OCR Fallback — Document Intelligence

To improve resilience, a **fallback OCR provider** has been added using **Azure Document Intelligence** (FormRecognizer, prebuilt-layout model), accessed **via the AI Foundry endpoint**.

### How it works
1. Pipeline attempts Mistral OCR first (2 attempts with exponential retry).
2. If Mistral fails (timeout, 429 quota, circuit breaker open, ConnectTimeout), the pipeline automatically falls back to Document Intelligence REST API.
3. Document Intelligence extracts text-only Markdown (no images) using the `prebuilt-layout` model.
4. The `ocr_provider` field on `EmailRecord` tracks which provider was used.

### Standalone Document Intelligence Resource (Recommended)
- **Default (current)**: `deploy_document_intelligence = true` in `#infra/terraform.tfvars` deploys a dedicated `FormRecognizer` resource (`<prefix>-doc-intel`).
- **Why standalone**: The AI Foundry v2 generic endpoint (`https://<prefix>-aifoundry.cognitiveservices.azure.com/`) does **not** reliably serve the `/documentintelligence/documentModels/...` REST path, returning `400 Bad Request`. A dedicated FormRecognizer resource exposes the correct REST API natively.
- **RBAC**: Terraform automatically assigns `Cognitive Services User` to the User-Assigned Managed Identity on the standalone DI resource.
- **Endpoint**: `https://<prefix>-doc-intel.cognitiveservices.azure.com/` — auto-injected into both ACA containers by Terraform.

### Trade-offs
- **Mistral OCR** produces richer Markdown (image descriptions, alt-text, layout hints). Best for classification accuracy.
- **Document Intelligence** produces clean text Markdown. Sufficient for classification but loses image context.
- Fallback is transparent to the classification stage — both providers output Markdown.

### Configuration
- Terraform: `deploy_document_intelligence = true` in `terraform.tfvars` (recommended)
- Environment: `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` (auto-set by Terraform to standalone DI endpoint)
- API version: `DOC_INTELLIGENCE_API_VERSION=2024-11-30` (v4.0 GA, default)
- Circuit breaker: `doc_intelligence_breaker` (fail_max=3, reset_timeout=30s)

---

## Vision Strategy Performance Analysis

### Problem Statement
Vision strategy in the tenant logs shows significantly longer processing times than standard or reasoning strategies when reprocessing emails.

### Root Cause Analysis

#### 1. PDF-to-JPEG Image Conversion (Computational Bottleneck)

**Location**: [classymail/services/llm_pipeline.py](../classymail/services/llm_pipeline.py#L340)

```python
pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x resolution = CPU-heavy
img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
buf = io.BytesIO()
img.save(buf, format="JPEG", quality=85)  # Quality 85 = slower compression
img_b64 = base64.b64encode(buf.getvalue()).decode()
```

**Impact Per Page**:
- 2x resolution rendering: **50-150ms per page** (CPU-heavy, scales with page complexity)
- JPEG compression (quality=85): **20-50ms per page**
- Base64 encoding: **5-10ms per page**
- **Total per page: 75-210ms**

**For a 10-page document: 750ms - 2.1s added overhead**

#### 2. Mistral Document AI API Requests (Network I/O)

**Location**: [classymail/services/llm_pipeline.py](../classymail/services/llm_pipeline.py#L378-L400)

Vision strategy sends each page/chunk as a separate HTTP POST request with:
- `"type": "image_url"` (instead of document_url for PDFs >= 30 pages)
- `"enable_vision_enrichment": true` (activates bbox annotation processing)
- `"include_image_base64": true`

**Network Latency**:
- Per-request latency: **2-4 seconds** (includes network + Mistral processing)
- With rate limiting (MISTRAL_RPM=30): **2 additional requests per second**
- Concurrent processing: Pages processed in batches but still sequential per batch

**For a 10-page document**:
- Pages sent in concurrent batches of ~3: **3-4 API requests**
- Time: **6-16 seconds**

#### 3. Vision Enrichment Overhead

**Location**: [classymail/services/llm_pipeline.py](../classymail/services/llm_pipeline.py#L347)

BBox annotation processing by Mistral adds **1-2 seconds per API request** (complex spatial analysis).

#### 4. Rate Limiting Bottleneck
From [ACA_ENVIRONMENT_VARIABLES.md](ACA_ENVIRONMENT_VARIABLES.md):
```
MISTRAL_RPM=30   (0.5 requests/second = minimum 2s per request)
MISTRAL_TPM=60000
```

### Performance Comparison

```
STRATEGY TIMING BREAKDOWN (10-page PDF estimate):

STANDARD STRATEGY:
  OCR (Mistral Doc AI): 5-8s   (1-2 chunks, PDF format)
  Classification (Phi-4): 2-4s
  Embeddings: 1-2s
  TOTAL: 8-14 seconds

REASONING STRATEGY:
  OCR (Mistral Doc AI): 5-8s   (same as standard)
  Classification (Phi-4 + CoT): 3-6s  (slightly longer due to chain-of-thought)
  Embeddings: 1-2s
  TOTAL: 9-16 seconds

VISION STRATEGY:
  PDF-to-JPEG Conversion: 0.75-2.1s
  OCR (Mistral Doc AI): 12-16s  (vision enrichment + image API calls)
  Classification (Phi-4): 2-4s
  Embeddings: 1-2s
  TOTAL: 17-28 seconds (2-3x slower)
```

### Summary Table

| Aspect | Standard | Vision | Why? |
|--------|----------|--------|------|
| **Conversion** | 0ms | 750-2100ms | PDF-to-JPEG 2x rendering |
| **OCR API Time** | 5-8s | 12-16s | Image requests slower + BBox |
| **API Calls** | 1-2 | 3-4 | Per-page images vs document |
| **Total** | 8-14s | 17-28s | **2-3x slower** |
| **Cost** | ~0.10-0.30 | ~0.20-0.50 | Vision = higher token usage |

---

## Recommendations

### Immediate Optimizations (No Architectural Change)

1. **Reduce image resolution**: Change `fitz.Matrix(2, 2)` to `fitz.Matrix(1, 1)` (-50% overhead)
2. **Lower JPEG quality**: Change `quality=85` to `quality=70` (-30% image size)
3. **Page sampling**: Only convert first 3-5 pages for vision enrichment

**Expected Improvement**: -3-7 seconds (from 18-28s to 12-18s)

### Short-Term Improvements

4. **Increase MISTRAL_RPM** in Foundry (if allowed) — Impact: -2-3 seconds
5. **Add processing strategy detection**: Use vision strategy ONLY when email has embedded images or classification confidence < 0.75

### Long-Term Architecture

6. **Hybrid Vision Strategy**: Run standard pipeline first, only trigger vision for low-confidence results (<0.60)
7. **Vision as per-email override**: Allow users to mark specific emails for vision analysis
8. **Cache image conversions**: Store base64-encoded JPEGs in Cosmos alongside original PDF

---

## References
- [llm_pipeline.py — Vision Image Conversion](../classymail/services/llm_pipeline.py#L330-L360)
- [pipeline.py — Strategy Selector](../classymail/services/pipeline.py#L164)
- [worker.py — ProcessingTimer](../classymail/services/worker.py#L98-L107)
- [MODELS.md](MODELS.md) — OCR Fallback: Document Intelligence section
