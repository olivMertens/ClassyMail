# Cost Logic Analysis

## Overview

The cost UI in the "Costs" tab allows projecting monthly Azure infrastructure costs based on projected email volume. It offers two calculation modes:

1. **Fixed Estimate (MVP Demo)** - Default mode
2. **Azure Retail Prices API** - Advanced mode

## Logic Architecture

### 1. User Inputs

```typescript
// frontend/src/views/CostsView.vue
const emailsPerMonth = ref(10000)  // Projected volume
const pricingSource = ref('fixed')  // Calculation mode
```

### 2. Cost Calculation (Backend)

The calculation is performed in **3 steps**:

#### Step 1: Retrieve actual observed costs

```python
# Actual AI costs recorded in Cosmos DB
phi4_usd = await sum_phi4_cost_usd(clients=clients)
mistral_usd = await sum_mistral_cost_usd(clients=clients)
emails_with_usage = await count_items_with_any_usage_cost(clients=clients)

# Calculate per-email average
avg_ai_usd_per_email = (phi4_usd + mistral_usd) / emails_with_usage
```

**Example**: If 100 emails were processed with a total cost of 1.50 USD, the average is **0.015 USD/email**.

#### Step 2: Project variable AI costs

```python
projected_ai_usd = avg_ai_usd_per_email * emails_per_month
```

**Example**: For 10,000 emails/month → 0.015 × 10,000 = **150 USD/month**

##### AI Cost Breakdown by Component

**LLM-based PII Detection** (optional):
- Model: GPT-4.1-mini JSON mode
- Average cost: ~€0.002/email (~0.500 tokens input + 100 tokens output)
- Included in `avg_ai_usd_per_email` when enabled

**Azure AI Language PII Detection** (optional):
- Service: Azure AI Language Text Analytics API
- Cost: €1.00 per 1,000 text records (Standard tier)
- Estimate: 1 email = 1 text record → €0.001/email
- Deployment: Controlled by `deploy_language_service` (Terraform)
- **Note**: Not included in current costs (requires telemetry update)

**Hybrid Mode** (both methods):
- Combined cost: ~€0.003/email (LLM + Azure Language)
- Advantage: Better accuracy, automatic deduplication

#### Step 3: Add fixed infrastructure costs

##### "Fixed Estimate (MVP Demo)" Mode

Uses configurable fixed estimates via environment variables:

```python
# Default values
COST_FIXED_SERVICE_BUS_USD_MONTH = 9.0
COST_FIXED_STORAGE_USD_MONTH = 5.0
COST_FIXED_CONTAINER_APPS_USD_MONTH = 20.0
COST_FIXED_APP_INSIGHTS_USD_MONTH = 0.0
COST_FIXED_COSMOS_USD_MONTH = 0.0

# Fixed total = 34 USD/month
```

##### "Azure Retail Prices API" Mode

Calculates actual costs by querying the Azure pricing API:

```python
# Container Apps: calculation based on vCPU/GiB-seconds
worker_cost = vcpu_seconds * vcpu_price + gib_seconds * gib_price

# Service Bus: calculation based on number of operations
sb_cost = (emails_per_month * ops_per_email) * ops_price

# Log Analytics: calculation based on data volume
log_cost = (emails_per_month * gb_per_email) * gb_price
```

### 3. Final Result

```json
{
  "projection_monthly_usd": {
    "emails_per_month": 10000,
    "ai_variable": 150.0,      // Variable AI costs (projected)
    "fixed": 34.0,              // Fixed infrastructure costs
    "total": 184.0,             // Projected monthly total
    "breakdown": [              // Per-resource breakdown
      {"resource": "Mistral OCR (variable)", "usd": 100.0},
      {"resource": "Phi-4 / LLM (variable)", "usd": 50.0},
      {"resource": "Service Bus (fixed)", "usd": 9.0},
      ...
    ]
  }
}
```

## Validation

### Automated Tests

The tests in `tests/test_costs_analysis.py` validate:

✅ **Test 1: Fixed Mode**
- Verifies per-email average calculation
- Verifies variable AI projection
- Verifies addition of fixed costs
- Verifies total consistency

✅ **Test 2: Retail Mode**
- Verifies integration with Azure Retail Prices API
- Verifies dynamic infrastructure estimates
- Verifies presence of all calculated costs

✅ **Test 3: Edge Case (zero emails)**
- Verifies behavior with no processed emails
- Verifies that fixed costs remain present
- Verifies that division by zero is handled

✅ **Test 4: Breakdown Consistency**
- Verifies that the breakdown sum equals the total
- Verifies that all resources are present

### Test Results

```bash
$ uv run pytest tests/test_costs_analysis.py -v
tests/test_costs_analysis.py::test_costs_summary_fixed_mode PASSED
tests/test_costs_analysis.py::test_costs_summary_retail_mode PASSED
tests/test_costs_analysis.py::test_costs_summary_zero_emails PASSED
tests/test_costs_analysis.py::test_costs_breakdown_consistency PASSED

======================== 4 passed in 4.12s ========================
```

## Relevance and Recommendations

### ✅ Valid Logic

The current logic is **correct and relevant** for an MVP:

1. **Actual AI costs**: Based on observed usage (very accurate)
2. **Linear projection**: Simple and effective for estimates
3. **Fixed costs**: Appropriate for stable infrastructure
4. **Two modes**: Provides flexibility (MVP Demo vs Production Scale)

### 📊 Recommended Usage

#### For MVP/Demo (≤ 1,000 emails/month)
→ Use **"Fixed Estimate (MVP Demo)"**
- Quick and simple estimates
- No external API required
- Fixed costs are sufficiently accurate

#### For Production Scale (> 1,000 emails/month)
→ Use **"Azure Retail Prices API"**
- Calculations based on actual per-region pricing
- Accounts for real usage (vCPU, GiB, operations)
- More accurate for large-scale projections

### 🔧 Possible Improvements

#### Short Term
1. **Add visual indicators**:
   ```vue
   <div v-if="costs.counts.emails_with_usage < 50">
     ⚠️ Small sample size: projection less accurate
   </div>
   ```

2. **Display variance**:
   ```python
   "confidence": "low" if emails_with_usage < 100 else "high"
   ```

#### Long Term
1. **Cost history**: Monthly trend chart
2. **Budget alerts**: Notification if projection exceeds threshold
3. **Suggested optimizations**: Recommendations to reduce costs

---

## Estimation Rules by Strategy and Model

### **Costs per 10,000 Emails** (typical 2-page PDFs)

#### Standard Mode (Text/OCR Optimized)

| Model | Cost / 10K | Accuracy | Recommended Usage |
|--------|-----------|-----------|------------------|
| **Phi-4** | $2-5 | 0.82 | MVP, predictable costs |
| **gpt-4o-mini** | $2-4 | 0.84 | Cost-conscious production |
| **gpt-4.1-nano** | ~$1 | 0.72 | Extreme budget / agent tier1 |
| **gpt-4.1-mini** | ~$4-8 | 0.86 | Current fallback/anonymizer/vision default |
| **gpt-4.1** | ~$20-40 | 0.92 | Agentic tier3 + red-team |
| **gpt-5.1** | ~$25-50 | 0.91 | RAG chat reasoning |
| **gpt-5-nano** | $1-2 | 0.79 | Ultra low-cost |
| **gpt-5-mini** | $8-12 | 0.89 | Complex categories |
| **gpt-4o** | $30-60 | 0.92 | Critical accuracy |

**⚠️ Note**: If you change the model in Settings, update the environment variables:
```bash
PHI4_COST_PER_1K_INPUT=0.0004  # Example for gpt-5-mini
PHI4_COST_PER_1K_OUTPUT=0.0016
FALLBACK_COST_PER_1K_INPUT=0.0004  # gpt-4.1-mini
FALLBACK_COST_PER_1K_OUTPUT=0.0016
```

#### Reasoning Mode (Chain-of-Thought)
- **2-3x more tokens** → **2-3x cost**
- **Usage**: Legal contracts, complex analysis
- **Example**: gpt-5-mini $8-12 → Reasoning **$16-36**

#### Vision Mode (Visual Analysis)
- **4-6x more tokens** → **4-6x cost**
- **Usage**: Scanned documents, images
- **Example**: Phi-4 $2-5 → Vision **$8-30**

### Reprocessing Impact
- **Each reprocess = full pipeline cost**
- **Strategy change = multiplied cost**
- ⚠️ **Historical costs overwritten** (only the latest cost is retained)

## Production Configuration

### 1. Adjust fixed costs

```bash
# In secrets.env or Azure environment variables
COST_FIXED_SERVICE_BUS_USD_MONTH=15.0
COST_FIXED_STORAGE_USD_MONTH=10.0
COST_FIXED_CONTAINER_APPS_USD_MONTH=50.0
COST_FIXED_APP_INSIGHTS_USD_MONTH=5.0
COST_FIXED_COSMOS_USD_MONTH=25.0  # Serverless RU depends heavily on volume
```

### 2. Enable Retail mode

```typescript
// frontend/src/views/CostsView.vue
const pricingSource = ref('retail')  // Production mode
```

### 3. Monitor and adjust

```bash
# Compare actual vs projected costs each month
az costmanagement query \
  --type Usage \
  --dataset-filter "ResourceGroup eq '<prefix>-rg'" \
  --timeframe MonthToDate
```

## Conclusion

✅ **The logic is solid and well-tested**
✅ **Relevant for both MVP and Production**
✅ **Easily configurable via environment variables**
✅ **Two modes suited to different needs**

**Recommendation**: Keep the current logic and use the "Fixed Estimate (MVP Demo)" mode for demonstrations, then switch to "Retail" mode for production projections.
