# Model Comparison & Adversarial Testing Guide

> 🧪 **Purpose**: Enable side-by-side evaluation of dual-model results (Phi-4 vs gpt-4o-mini) for quality assurance, fine-tuning dataset creation, and confidence validation.

---

## Table of Contents

1. [Overview](#overview)
2. [When to Use Comparison](#when-to-use-comparison)
3. [Enabling Comparison](#enabling-comparison)
4. [Using Comparison](#using-comparison)
5. [Interpreting Results](#interpreting-results)
6. [Fine-Tuning Dataset Export](#fine-tuning-dataset-export)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting](#troubleshooting)

---

## Overview

### Two Classification Models

| Model | Speed | Context | Cost | Use Case |
|-------|-------|---------|------|----------|
| 🔶 **Phi-4** | ⚡ Fast (1-3s) | 8K tokens | Low (~$0.0001/1K) | Primary: Most emails, real-time |
| 🟢 **gpt-4o-mini** | 🐢 Slower (5-15s) | 120K tokens | Medium (~$0.003/1K) | Fallback: Long emails, complex cases |

### Automatic Fallback (Always Enabled)

The system automatically selects models based on **token budget**:

```python
if estimate_tokens(content) <= 8000:
    use_model = "Phi-4"        # Fast path
else:
    use_model = "gpt-4o-mini"  # Fallback for long emails
```

### Dual-Model Comparison (Optional)

When **comparison mode** is enabled, both models execute in **parallel**:

```python
if comparison_enabled:
    phi4_result, gpt4o_result = await asyncio.gather(
        call_phi4(content),
        call_gpt4o_mini(content)
    )
    return ComparisonResult(
        phi4=phi4_result,
        gpt4o_mini=gpt4o_result,
        confidence_delta=abs(phi4_conf - gpt4o_conf),
        agreement=phi4_intent == gpt4o_intent
    )
```

**Time Overhead**: Only ~20-30% additional latency (parallel execution).

---

## When to Use Comparison

### ✅ **Enable Comparison Mode For**:

1. **Quality Assurance (QA Phase)**
   - Validate new classification categories
   - Verify Phi-4 accuracy on edge cases
   - Detect hallucinations or disagreement patterns

2. **Fine-Tuning Dataset Creation**
   - Collect emails where both models **agree** (high confidence data)
   - Collect emails where both models **disagree** (for improvement study)
   - Export for LoRA (Low-Rank Adaptation) training on Phi-4

3. **Large/Complex Emails**
   - Where Phi-4 context window may be tight (6K-8K tokens)
   - Verify fallback model validates the same intent
   - Confidence comparison shows certainty level

4. **Safety-Critical Classifications**
   - High-stakes intents (fraud, legal, security)
   - Ensure both models detect the same intent
   - Flag disagreement for manual review

5. **Confidence Dips**
   - When Phi-4 confidence < 0.70
   - Cross-check with gpt-4o-mini confidence
   - Confidence delta reveals model certainty alignment

### ❌ **Disable Comparison For**:

1. **Real-Time / High-Throughput Processing**
   - If latency budget < 5 seconds per email
   - Cost-sensitive batch processing
   - Enable only for review workflows

2. **Fine-Tuned Custom Models**
   - When using Phi-4-Custom (already optimized)
   - Comparison overhead not justified
   - Use only during re-tuning cycles

---

## Enabling Comparison

### Option 1: Global Setting (UI)

Navigate to **⚙️ Settings** → **Advanced** → **Model Comparison**:

```
☑️ Enable Automatic Model Comparison

This will run both Phi-4 and gpt-4o-mini on ALL classifications.

⚠️ Warning: +20-30% latency per classification
```

When enabled globally, every email is automatically compared.

### Option 2: Per-Email Override (API)

Classify a single email with comparison:

```bash
# Sync mode (waits for results, ~20-30s total)
curl -X POST http://localhost:8000/api/emails/{email_id}/reclassify \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {token}" \
  -d '{
    "model": "both",
    "mode": "sync"
  }'

# Response:
{
  "id": "email-123",
  "status": "PROCESSED",
  "classification": {
    "detected_intents": [
      {"intent": "invoice_request", "confidence": 0.92}
    ]
  },
  "comparison_results": {
    "phi4": {
      "detected_intents": [
        {"intent": "invoice_request", "confidence": 0.92}
      ]
    },
    "gpt4o_mini": {
      "detected_intents": [
        {"intent": "invoice_request", "confidence": 0.88}
      ]
    },
    "confidence_delta": 0.04,
    "agreement": true,
    "execution_time_ms": 8500,
    "mode": "sync"
  }
}
```

### Option 3: Async Mode (Background Processing)

For batch comparison without blocking:

```bash
# Async mode (returns 202, processes in Service Bus queue)
curl -X POST http://localhost:8000/api/emails/{email_id}/reclassify \
  -H "Content-Type: application/json" \
  -d '{
    "model": "both",
    "mode": "async"
  }'

# Response: 202 Accepted
# Check result later with GET /api/emails/{email_id}
# comparison_results field will be populated when ready
```

---

## Using Comparison

### View Results in UI

1. Open an email in **EmailDetailModal**
2. Click the **Comparison** tab (4th tab)
3. See side-by-side results:

```
┌─────────────────────────────────────────────────┐
│ COMPARISON RESULTS                              │
├─────────────────────────────────────────────────┤
│                                                 │
│ 🔶 Phi-4 (Primary)   │  🟢 gpt-4o-mini (Fallback) │
│ ─────────────────────┼──────────────────────── │
│ invoice_request: 92% │  invoice_request: 88%   │
│ confidence: HIGH     │  confidence: HIGH       │
│                                                 │
│ 🤝 Agreement: YES                               │
│ 📊 Confidence delta: 4%                         │
│ ⏱️  Execution time: 8.5s                         │
│                                                 │
│ [🔄 Run Again] [📥 Export]                       │
└─────────────────────────────────────────────────┘
```

### Export Comparison Data

Click **[📥 Export]** to download as JSON:

```json
{
  "email_id": "email-123",
  "subject": "Invoice #INV-2024-001",
  "comparison_results": {
    "phi4": {
      "detected_intents": [
        {
          "intent": "invoice_request",
          "confidence": 0.92,
          "justification": "Email contains invoice number and request for processing."
        }
      ],
      "global_complexity": "simple",
      "needs_review": false
    },
    "gpt4o_mini": {
      "detected_intents": [
        {
          "intent": "invoice_request",
          "confidence": 0.88,
          "justification": "Detected invoice-related intent with high likelihood."
        }
      ],
      "global_complexity": "simple",
      "needs_review": false
    },
    "agreement": true,
    "confidence_delta": 0.04,
    "executed_at": "2024-12-01T10:30:45Z",
    "mode": "sync",
    "processing_time_ms": 8500
  }
}
```

---

## Interpreting Results

### Confidence Delta

**Definition**: Absolute difference in top-intent confidence between the two models.

```
confidence_delta = |phi4_confidence - gpt4o_confidence|
```

| Delta Range | Meaning | Action |
|-----------|---------|--------|
| 0.00 - 0.05 | Perfect agreement | ✅ High confidence result |
| 0.05 - 0.15 | Close agreement | ⚠️ Review if needed |
| 0.15 - 0.30 | Moderate disagreement | 🔍 Investigate, may need manual review |
| > 0.30 | Significant disagreement | ❌ Flag for manual review + fine-tuning |

### Agreement Flag

**True** = Both models detected the **same intent** as top choice

```python
agreement = (phi4_top_intent == gpt4o_top_intent)
```

| Agreement | Delta | Decision |
|-----------|-------|----------|
| ✅ Yes | < 0.10 | Confident: use result, skip review |
| ✅ Yes | 0.10-0.25 | Good: use result, low review priority |
| ⚠️ No | < 0.15 | Disagreement on intent: manual review |
| ❌ No | > 0.15 | Conflict: flag as needs_review=true |

### Example Interpretation

**Scenario 1: Perfect Agreement (Delta < 0.05)**
```
Phi-4: invoice_request (confidence: 0.93)
gpt-4o: invoice_request (confidence: 0.91)
agreement: true
delta: 0.02
→ ✅ Result is reliable. No review needed.
```

**Scenario 2: Good Agreement (Delta < 0.15)**
```
Phi-4: invoice_request (confidence: 0.89)
gpt-4o: invoice_request (confidence: 0.82)
agreement: true
delta: 0.07
→ ⚠️ Result is likely correct. Low priority review.
```

**Scenario 3: Disagreement (Delta > 0.25)**
```
Phi-4: invoice_request (confidence: 0.76)
gpt-4o: general_inquiry (confidence: 0.68)
agreement: false
delta: 0.08 (but different intents!)
→ ❌ Major disagreement. Flag for manual review.
   Email content is ambiguous. Use manual classification.
```

---

## Fine-Tuning Dataset Export

### Creating High-Confidence Training Data

1. **Enable comparison for 100-200 emails** (representative sample)
2. **Filter by agreement = true AND delta < 0.10** (high-confidence pairs)
3. **Export as JSONL** for fine-tuning

#### Export Script

```bash
# API endpoint to export fine-tuning dataset
curl -X GET "http://localhost:8000/api/stats/export-finetune-dataset?min_agreement=true&max_delta=0.10&limit=200" \
  -H "Authorization: Bearer {token}" \
  --output finetune_dataset.jsonl
```

#### JSONL Format (for LoRA)

```jsonl
{"messages": [{"role": "system", "content": "You are an email classification expert."}, {"role": "user", "content": "Classify the intent of this email: Invoice #INV-2024-001. Please process..."}, {"role": "assistant", "content": "{\"detected_intents\": [{\"intent\": \"invoice_request\", \"confidence\": 0.92}]}"}]}
{"messages": [{"role": "system", "content": "You are an email classification expert."}, {"role": "user", "content": "Subject: Payment Status Update. We have processed your..."}, {"role": "assistant", "content": "{\"detected_intents\": [{\"intent\": \"payment_status\", \"confidence\": 0.88}]}"}]}
...
```

#### Fine-Tuning on Phi-4

```bash
# Use Foundry fine-tuning API (or UI)
# Training data: finetune_dataset.jsonl (LoRA)
# Model: Phi-4 (base)
# Epochs: 3
# Learning rate: 0.0001
# Output: Phi-4-Custom (new deployment)

# After training, deploy as "phi-4-custom" in Foundry
# Then update config:
# PHI_DEPLOYMENT=phi-4-custom
```

---

## Performance Considerations

### Latency Impact

```
Without comparison:
  Phi-4: 2-3 seconds
  gpt-4o-mini (fallback): 5-15 seconds

With comparison (parallel):
  Total: ~8-18 seconds (depends on content size)
  Latency increase: ~20-30% (due to parallel execution)
```

### Cost Impact

```
Cost per classification:

Without comparison (Phi-4 only):
  $0.0001 × (content_tokens / 1000) = ~$0.0001-0.0005 per email

With comparison (both models):
  Phi-4: $0.0001 × (content_tokens / 1000)
  gpt-4o: $0.003 × (content_tokens / 1000)
  Total: ~$0.003-0.015 per email

Cost multiplier: ~10-30x more expensive than Phi-4 alone
```

### Optimization Tips

1. **Use async mode** for batch comparisons (non-blocking)
   ```bash
   mode=async  # Returns 202, results ready in 30-60 seconds
   ```

2. **Limit comparison to subset**
   - Enable only for `needs_review=true` emails
   - Or for specific high-risk categories
   - Not every email needs dual-model validation

3. **Schedule off-peak**
   - Run comparison during low-traffic periods
   - Prevents latency impact on end users

---

## Troubleshooting

### Issue: Comparison takes > 30 seconds

**Cause**: Large email, gpt-4o-mini processing long context

**Solution**:
```bash
# Switch to async mode
mode=async

# Or specify shorter timeout
timeout_ms=20000  # Kill request after 20s, use partial results
```

### Issue: Constant disagreement (delta > 0.25)

**Cause 1**: Classification categories are ambiguous
- Email content straddles multiple categories
- Requires domain expert labeling

**Cause 2**: Email is too long or complex
- Phi-4 struggles with 7K-8K token emails
- gpt-4o-mini maintains quality at 100K tokens
- Consider longer context for all emails

**Solution**:
```python
# Always use gpt-4o-mini for long emails (instead of fallback on demand)
if estimate_tokens(content) > 6000:
    use_model = "gpt-4o-mini"  # Avoid Phi-4 context limit
```

### Issue: Comparison results not saved

**Cause**: Worker didn't process async message properly

**Solution**:
```bash
# Check Service Bus message status
az servicebus queue show \
  --namespace-name sbemailpoc \
  --name pdf-processing-queue \
  --resource-group rg-email-poc

# Check dead-letter queue for failed messages
az servicebus queue show \
  --namespace-name sbemailpoc \
  --name pdf-processing-queue/$DeadLetterQueue

# Reprocess manually
curl -X POST http://localhost:8000/api/emails/{email_id}/reclassify \
  -d '{"model": "both", "mode": "sync"}'
```

### Issue: Phi-4 vs gpt-4o-mini endpoints different regions

**Cause**: Models deployed in different Azure regions (data residency issue)

**Solution**:
```bash
# Check endpoint regions
AZURE_PREFERRED_DATA_ZONE=eu-central

# Ensure both endpoints in same region
PHI_ENDPOINT=https://ai-eu-central.openai.azure.com/
PHI_FALLBACK_ENDPOINT=https://ai-eu-central.openai.azure.com/

# System will log warning if endpoints in different zones
```

---

## Summary

| Feature | Syntax | Use Case |
|---------|--------|----------|
| Global comparison | UI Settings → Enable | QA phase, discovery |
| Per-email sync | `POST /reclassify {"model":"both", "mode":"sync"}` | Ad-hoc validation |
| Per-email async | `POST /reclassify {"model":"both", "mode":"async"}` | Batch processing |
| Export dataset | `GET /stats/export-finetune-dataset` | Fine-tuning prep |
| Filter results | `agreement=true AND delta < 0.10` | High-confidence data |

---

**See Also**:
- [README.md](../README.md#-adversarial-model-comparison) - Quick start
- [MODELS.md](./MODELS.md) - Model specifications
- [LOCAL_DEVELOPMENT.md](./LOCAL_DEVELOPMENT.md) - Local testing
- [RBAC_AUDIT.md](./RBAC_AUDIT.md) - Identity & permission troubleshooting
