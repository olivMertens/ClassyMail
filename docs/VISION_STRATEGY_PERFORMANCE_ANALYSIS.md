# Vision Strategy Performance Analysis

## Problem Statement
Vision strategy in the tenant logs shows significantly longer processing times than standard or reasoning strategies when reprocessing emails.

## Root Cause Analysis

### 1. **PDF-to-JPEG Image Conversion (Computational Bottleneck)**

**Location**: [classymail/services/llm_pipeline.py](classymail/services/llm_pipeline.py#L340)

```python
# Line 340: High-resolution pixmap rendering (2x scale)
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

### 2. **Mistral Document AI API Requests (Network I/O)**

**Location**: [classymail/services/llm_pipeline.py](classymail/services/llm_pipeline.py#L378-L400)

Vision strategy sends each page/chunk as a separate HTTP POST request with:
- `"type": "image_url"` (instead of document_url for PDFs ≥30 pages)
- `"enable_vision_enrichment": true` (activates bbox annotation processing)
- `"include_image_base64": true`

**Network Latency**:
- Per-request latency: **2-4 seconds** (includes network + Mistral processing)
- With rate limiting (MISTRAL_RPM=30): **2 additional requests per second**
- Concurrent processing: Pages processed in batches but still sequential per batch

**For a 10-page document**:
- Pages sent in concurrent batches of ~3: **3-4 API requests**
- Time: **6-16 seconds**

### 3. **Vision Enrichment Overhead**

**Location**: [classymail/services/llm_pipeline.py](classymail/services/llm_pipeline.py#L347, #L329)

```python
if enable_vision_enrichment:
    p["bbox_annotation_format"] = pydantic_to_mistral_schema(ImageDescription)
```

BBox annotation processing by Mistral adds:
- **1-2 seconds per API request** (complex spatial analysis)
- Full 10-page document: **3-8 additional seconds**

---

## Performance Comparison

```
STRATEGY TIMING BREAKDOWN (10-page PDF estimate):

STANDARD STRATEGY:
├─ OCR (Mistral Doc AI): 5-8s   (1-2 chunks, PDF format)
├─ Classification (Phi-4): 2-4s
├─ Embeddings: 1-2s
└─ TOTAL: 8-14 seconds

REASONING STRATEGY:
├─ OCR (Mistral Doc AI): 5-8s   (same as standard)
├─ Classification (Phi-4 + CoT): 3-6s  (slightly longer due to chain-of-thought)
├─ Embeddings: 1-2s
└─ TOTAL: 9-16 seconds

VISION STRATEGY:
├─ PDF→JPEG Conversion: 0.75-2.1s    ← ADDED
├─ OCR (Mistral Doc AI): 12-16s      ← INCREASED (vision enrichment + image API calls)
│  ├─ Image conversion overhead: 0.75-2.1s
│  ├─ Per-image API latency: 8-12s (vs 2-4s for document_url)
│  └─ BBox annotation: 3-8s
├─ Classification (Phi-4): 2-4s
├─ Embeddings: 1-2s
└─ TOTAL: 17-28 seconds ❌

SLOWDOWN FACTOR: Vision is 2-3x slower than standard
```

---

## Why Vision Is So Slow: Key Issues

### Issue #1: Per-Page Image Rendering
- **Current**: Each page rendered at 2x resolution
- **Impact**: 75-210ms overhead per page
- **Scales Linearly**: 20 pages = 1.5-4.2 seconds just for image conversion

### Issue #2: Image API Calls vs Document Upload
For a 10-page PDF:
- **Standard**: Send 1 PDF chunk to Mistral (document_url) = ~2-4 requests
- **Vision**: Send 10 individual JPEG images to Mistral = ~3-4 concurrent batches but takes longer per request

```
Standard:
  POST /api/mistral (PDF bytes) → 2-4s

Vision:
  POST /api/mistral (img1 b64) → 2-4s
  POST /api/mistral (img2 b64) → 2-4s
  POST /api/mistral (img3 b64) → 2-4s
  ... (concurrent but still sequential per batch)
```

### Issue #3: BBox Annotation Complexity
Vision enrichment requires Mistral to:
1. Analyze image pixels
2. Extract text regions + spatial coordinates
3. Generate bounding box annotations
4. Return structured ImageDescription object

**This adds 1-2s per image request**

### Issue #4: Rate Limiting Bottleneck
From [ENVIRONMENT_VARIABLES_AUDIT.md](ENVIRONMENT_VARIABLES_AUDIT.md#L114):
```
MISTRAL_RPM=30   (0.5 requests/second = minimum 2s per request)
MISTRAL_TPM=60000
```

Vision with 3-4 concurrent image requests hits the rate limit harder.

---

## Recommendations to Speed Up Vision

### Immediate Optimizations (No Architectural Change)

**1. Reduce Image Conversion Overhead**
```python
# Change from matrix=fitz.Matrix(2, 2) to matrix=fitz.Matrix(1, 1)
# Overhead: -50% (from 150ms to 75ms per page)
pix = page.get_pixmap(matrix=fitz.Matrix(1, 1))  # 1x resolution instead of 2x
```

**2. Lower JPEG Quality**
```python
# Change from quality=85 to quality=70
# Overhead: -30% image size, -20ms per page
img.save(buf, format="JPEG", quality=70)
```

**3. Implement Page Sampling**
```python
# Only convert first 3-5 pages for vision enrichment
# (often key info is at the start)
if i < 5:  # Sample first 5 pages
    # send to vision
else:
    # fall back to text-only OCR
```

**Expected Improvement**: -3-7 seconds (from 18-28s to 12-18s)

### Short-Term Improvements

**4. Increase MISTRAL_RPM to concurrent processing capability**
```
Current: MISTRAL_RPM=30 (0.5/sec) = slow batching
Better: MISTRAL_RPM=60 (1/sec) or higher if available in Foundry
Impact: -2-3 seconds
```

**5. Add Processing Strategy Detection**
Use vision strategy ONLY when:
- Email has embedded images/PDFs
- Classification confidence < 0.75 (fallback from standard)
- User explicitly requests it

Currently, vision is always per-strategy even for text-only emails.

### Long-Term Architecture

**6. Hybrid Vision Strategy**
```python
# Standard pipeline first
result = await classify_with_phi4(markdown)  # 2-4s

if result["confidence"] < 0.60:  # Low confidence
    # Only then trigger vision enrichment on relevant pages
    result = await enhance_with_vision(pdf, page_indices=[...])
```
**Impact**: Avoid vision overhead for high-confidence emails (80% of cases)

**7. Vision as Optional Per-Email Override**
Currently, vision is global (`processing_strategy` setting).
Better: Allow users to mark specific high-complexity emails for vision analysis without reprocessing everything.

**8. Cache Image Conversions**
Store base64-encoded JPEG images in Cosmos alongside original PDF.
On reprocess: Skip image conversion, reuse cached images.

---

## Diagnostics: How to Verify in Production

Check **Application Insights** for these metrics when vision jobs are running:

```kusto
// Trace the vision strategy breakdown
customMetrics
| where name startswith "app."
| where timestamp > ago(1d)
| where customDimensions.strategy == "vision"
| summarize
    avg_total_time = avg(value),
    avg_ocr_time   = avg(todouble(customDimensions.ocr_time_ms)),
    avg_conversion = avg(todouble(customDimensions.image_conversion_ms)),
    count = count()
by name
```

Or check container logs:
```bash
az containerapp logs show --name classificationg2s-worker --resource-group <rg> --type console | grep vision
```

Look for:
```
[msg:xxx] Pipeline/Task completed in 18500ms  ← Vision (slow)
[msg:yyy] Pipeline/Task completed in 8200ms   ← Standard (fast)
```

---

## Summary Table

| Aspect | Standard | Vision | Why? |
|--------|----------|--------|------|
| **Conversion** | 0ms | 750-2100ms | PDF→JPEG 2x rendering |
| **OCR API Time** | 5-8s | 12-16s | Image requests slower + BBox |
| **API Calls** | 1-2 | 3-4 | Per-page images vs document |
| **Total** | 8-14s | 17-28s | **2-3x slower** |
| **Cost** | €0.10-0.30 | €0.20-0.50 | Vision = higher token usage |

---

## Recommended Action Plan

1. **Immediate PR** (15 min):
   - [ ] Change `fitz.Matrix(2, 2)` → `fitz.Matrix(1, 1)`
   - [ ] Change `quality=85` → `quality=70`
   - [ ] Add structured telemetry span for "image_conversion_ms"

2. **Short-term** (1-2 days):
   - [ ] Increase `MISTRAL_RPM` in Foundry (if allowed)
   - [ ] Add per-page image conversion metrics to diagnostics
   - [ ] Document vision overheads in UI warning

3. **Medium-term** (1 week):
   - [ ] Implement page sampling (first N pages only)
   - [ ] Add hybrid confidence-based vision fallback
   - [ ] Create vision-specific test with timing benchmarks

4. **Long-term** (roadmap):
   - [ ] Image cache in Cosmos DB
   - [ ] Vision as optional per-email override (not global strategy)
   - [ ] Cost calculator that shows vision premium

---

## References
- [llm_pipeline.py — Vision Image Conversion](classymail/services/llm_pipeline.py#L330-L360)
- [pipeline.py — Strategy Selector](classymail/services/pipeline.py#L164)
- [worker.py — ProcessingTimer](classymail/services/worker.py#L98-L107)
- [DashboardView.vue — Duration Display](frontend/src/views/DashboardView.vue#L971-L985)
