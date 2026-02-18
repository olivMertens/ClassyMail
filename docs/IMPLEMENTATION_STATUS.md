# Implementation Summary: Feature Status & Roadmap

> 📋 **Last Updated**: February 2026
> **Status Overview**: Core Features ✅ | Advanced Features 🔄 | Future Enhancements 📋

---

## Recently Completed Features ✅

### 1. **Content Filter Handling & App Insights Fix** (Feb 2026) ✅
- **Location**: [telemetry.py](../classymail/core/telemetry.py), [llm_pipeline.py](../classymail/services/llm_pipeline.py), [pipeline.py](../classymail/services/pipeline.py), [models.py](../classymail/models.py), [DashboardView.vue](../frontend/src/views/DashboardView.vue), [EmailDetailModal.vue](../frontend/src/components/EmailDetailModal.vue), [main.tf](../infra/main.tf)
- **Features**:
  - **App Insights Logging Fix**: Removed `resource=` conflict and widened `logger_name` from `"classymail"` to `""` (root) in distro config; added `LoggerProvider` + `AzureMonitorLogExporter` to Tier 2 fallback; added `OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true` env var to both API and Worker ACAs
  - **Content Filter Detection**: New `ContentFilterError` exception in models.py; `_classify_with_single_model()` parses Azure OpenAI 400 responses for `content_filter` / `ResponsibleAIPolicyViolation` codes and raises `ContentFilterError` with structured filter result
  - **OTel Spans**: Content filter spans include `app.content_filter.triggered`, `app.content_filter.code`, and per-category `app.content_filter.{category}_filtered` attributes
  - **Pipeline Handling**: `ContentFilterError` caught before generic `Exception` in pipeline; returns `CONTENT_FILTERED` status record with `content_filter_result` dict instead of dead-lettering
  - **Frontend**: Purple `CONTENT_FILTERED` filter tab in dashboard; purple `ShieldExclamationIcon` status icon; detailed content filter panel in EmailDetailModal showing category grid (hate/jailbreak/self_harm/sexual/violence) with FILTERED/safe badges
  - **No Retry**: `retryable_httpx()` returns False for `ContentFilterError`; `classify_with_phi4()` re-raises immediately

### 2. **Category Assessment AI Advice** (Feb 2026) ✅
- **Location**: [category_assessment.py](../classymail/api/category_assessment.py), [SettingsView.vue](../frontend/src/views/SettingsView.vue)
- **Endpoint**: `POST /api/settings/categories/assess`
- **Model**: GPT-5 Nano (reasoning model)
- **Features**:
  - AI-powered category definition quality assessment
  - Rates categories as Good / Needs Improvement / Poor
  - Actionable advice with concrete rewriting examples
  - Explains WHY suggestions improve LLM classification accuracy
  - Copy-paste ready text snippets for prompts
  - Considers Standard, Reasoning, and Vision processing strategies
  - French/English UI support (settings.categories.form.*)
- **Implementation**:
  - Correct API parameters for GPT-5 reasoning models (`max_completion_tokens`, no `temperature`)
  - Comprehensive system prompt focused on LLM prompt engineering best practices
  - JSON response format with fields: quality_rating, strengths, weaknesses, suggestions, examples
- **Commit**: ca11109 (GPT-5 API parameters fix)

### 3. **Per-Email Reprocessing Modal** (Feb 2026) ✅
- **Location**: [emails.py](../classymail/api/routers/emails.py#L298), [DashboardView.vue](../frontend/src/views/DashboardView.vue)
- **Endpoint**: `POST /api/emails/{id}/reclassify`
- **Parameters**:
  ```json
  {
    "model": "phi-4" | "gpt-4o-mini" | "gpt-5-mini" | "both",
    "strategy": "standard" | "reasoning" | "vision",
    "mode": "sync" | "async"
  }
  ```
- **Features**:
  - Reprocess individual emails with different model/strategy combinations
  - Sync mode: Wait for results (~20-30s), returns immediately
  - Async mode: Queue message, returns 202 Accepted, check back later
  - Comparison mode: Run both models in parallel (when model="both")
  - Strategy override: Change processing approach per email
- **Use Cases**:
  - Test different models on edge cases
  - Fix OCR errors by re-running with vision mode
  - Compare Phi-4 vs GPT-4o-mini vs GPT-5-mini on same email
  - A/B testing for fine-tuning data selection
- **Commits**: 1fd6861, 53f1d80

### 4. **PII Detection & Dashboard Indicators** (Feb 2026) ✅
- **Location**: [DashboardView.vue](../frontend/src/views/DashboardView.vue), [llm_pipeline.py](../classymail/services/llm_pipeline.py#L642)
- **Database**: `EmailRecord.pii_detected`, `EmailRecord.pii_data`
- **Features**:
  - Automatic PII detection during email preprocessing
  - Visual indicators in dashboard:
    - Card view: Amber shield icon (ShieldExclamationIcon) with tooltip
    - Table view: "DCP" badge (FR) / "PII" badge (EN)
  - Stores structured PII metadata for GDPR compliance
  - Configurable via `email_preprocessing.detect_pii` setting
  - Detects: names, emails, phone numbers, addresses, NIR, IBAN
- **Translations**:
  - dashboard.pii.detected, dashboard.pii.badge_label, dashboard.pii.tooltip
  - French: "Données à Caractère Personnel (DCP)"
  - English: "Personal Identifiable Information (PII)"
- **Commit**: c2c9763

### 5. **Dynamic Model-Aware Cost Tracking** (Feb 2026) ✅
- **Location**: [costing.py](../classymail/services/costing.py), [CostsView.vue](../frontend/src/views/CostsView.vue)
- **Features**:
  - MODEL_PRICING map with 12+ models (Phi-4, GPT-4o/4o-mini, GPT-5-mini/nano, GPT-4.1-nano, Mistral)
  - Dynamic pricing based on actual model used (not hardcoded assumptions)
  - Tracks input/output tokens separately per model
  - Cost breakdown per email: OCR + Classification + Embeddings
  - Export CSV with cost columns for financial audit
  - Configurable pricing via Settings UI (region/tenant-specific)
  - Disclaimer: "Costs are configurable and region-dependent"
- **Pricing Sources**: Azure AI Foundry Models pricing page (as of Feb 2026)
- **Documentation**: [COSTS_LOGIC.md](../docs/COSTS_LOGIC.md)
- **Commit**: 7b99c7d

### 6. **French Translation Improvements** (Feb 2026) ✅
- **Location**: [fr.json](../frontend/src/locales/fr.json), [SettingsView.vue](../frontend/src/views/SettingsView.vue)
- **Changes**:
  - Category form fields fully translated (14 new keys: settings.categories.form.*)
  - Confidence level terminology refined:
    - "Tout Niveau" (Any Level) - more natural than "Toute Confiance"
    - "Niveau de Confiance Faible/Élevé" (Low/High Confidence Level) - more professional
  - PII indicator translations: "DCP" badge, tooltips
  - Synchronization verified: `check_i18n.py` passes (500+ keys EN/FR)
- **Commits**: 16e85a4, c2c9763

### 7. **CSV Export Bug Fix** (Feb 2026) ✅
- **Location**: [emails.py](../classymail/api/routers/emails.py#L820), [repository.py](../classymail/services/repository.py#L558)
- **Issue**: `enable_cross_partition_query=True` caused error (deprecated parameter in azure-cosmos 4.7.0+)
- **Fix**: Removed deprecated parameter (cross-partition queries enabled by default in SDK 4.7.0+)
- **Impact**: Both CSV export and RAG vector queries now work correctly
- **Commit**: 7fbd13f

### 8. **CSV Export Streaming (Performance Fix)** (Feb 2026) ✅
- **Location**: [emails.py](../classymail/api/routers/emails.py#L863)
- **Issue**: `/emails/export/csv` buffered ALL Cosmos DB items into memory before building CSV, causing 502 gateway timeouts on large datasets
- **Root Cause**: `items = []; async for item: items.append(item)` + `iter([csv_bytes])` = no streaming
- **Fix**: Converted to true async streaming with `async def _stream_csv()` generator — rows are yielded as they arrive from Cosmos DB, no full-dataset buffering
- **Impact**: Eliminates 502 timeouts for large exports (1000+ emails), constant memory usage regardless of dataset size

### 9. **OCR Provider Source in CSV Export** (Feb 2026) ✅
- **Location**: [emails.py](../classymail/api/routers/emails.py), [settings_store.py](../classymail/services/settings_store.py), [SettingsView.vue](../frontend/src/views/SettingsView.vue)
- **Feature**: New `SOURCE_OCR` column in enriched CSV export showing which OCR provider processed each document
- **Values**: `mistral_ocr` (primary, default) or `document_intelligence` (DI fallback)
- **Toggle**: Controlled by `g2s_export.show_ocr_provider` setting with UI checkbox
- **Backward Compatible**: Older records without `ocr_provider` field default to `mistral_ocr`

### 10. **Batch Reprocess All Emails** (Feb 2026) ✅
- **Location**: [admin.py](../classymail/api/routers/admin.py), [SettingsView.vue](../frontend/src/views/SettingsView.vue)
- **Endpoint**: `POST /api/admin/reprocess-all`
- **Features**:
  - Re-enqueue all PROCESSED + REVIEW_REQUIRED emails for classification with new LLM settings
  - Auto-saves settings before reprocessing so workers use updated configuration
  - Replays DLQ messages in the same operation
  - Double-dialog confirmation in UI (model/strategy details + final warning)
  - Optional `processing_strategy` parameter (standard/reasoning/vision)
- **Frontend**: Amber-styled button in Settings → Processing tab with spinning icon during execution

### 11. **GPT-5 Reasoning Model Support** (Feb 2026) ✅
- **Location**: [llm_compat.py](../classymail/core/llm_compat.py), [category_assessment.py](../classymail/api/category_assessment.py#L140-L163), [chat_agent.py](../classymail/services/chat_agent.py#L508-L515)
- **API Parameter Handling**:
  - Standard models (GPT-4o, Phi-4): `max_tokens`, `temperature` supported
  - Reasoning models (GPT-5.x, o1, o3, o4, Kimi): `max_completion_tokens` only, NO `temperature`
- **Detection Logic** (centralized in `llm_compat.py`):
  ```python
  _REASONING_FAMILIES = ("o1", "o3", "o4", "gpt-5", "gpt5", "kimi")
  ```
- **Helpers**: `is_reasoning_model()`, `build_chat_params()`, `extract_message_content()`
- **Implementation**: All LLM calls use `build_chat_params()` from `llm_compat.py`
- **Commit**: ca11109

---

## What's Been Implemented ✅

### 1. **Backend API Endpoint** (Ready for Use)
- **Location**: [classymail/api/routers/emails.py](../classymail/api/routers/emails.py#L298)
- **Endpoint**: `POST /api/emails/{id}/reclassify`
- **Parameters**:
  ```json
  {
    "model": "phi-4" | "gpt-4o-mini" | "both",
    "mode": "sync" | "async"
  }
  ```
- **Behavior**:
  - `model="both" mode="sync"`: Waits for both Phi-4 and gpt-4o-mini results (~20-30s)
  - `model="both" mode="async"`: Enqueues message with `comparison=true` tag, returns 202 Accepted
  - Returns response with `comparison_results` field containing dual-model results

### 2. **LLM Pipeline Core Function** (Ready for Use)
- **Location**: [classymail/services/llm_pipeline.py](../classymail/services/llm_pipeline.py#L330)
- **New Function**: `_call_model_with_endpoint()`
  - Generic model caller for any Azure OpenAI-compatible endpoint
  - Handles retry logic, token budgeting, and fallback
  - Used by both Phi-4 and gpt-4o-mini classification

- **Modified Function**: `classify_with_phi4()`
  - New parameters: `force_model`, `run_comparison`
  - When `run_comparison=True`, executes both models in parallel using `asyncio.gather()`
  - Returns `ComparisonResult` in response dict

### 3. **Data Model Schema** (Ready for Database)
- **Location**: [classymail/models.py](../classymail/models.py#L21)
- **New Class**: `ComparisonResult`
  ```python
  class ComparisonResult(BaseModel):
      phi4: Optional[ClassificationResult]
      gpt4o_mini: Optional[ClassificationResult]
      confidence_delta: Optional[float]  # |phi4_conf - gpt4o_conf|
      agreement: bool  # True if same intent detected
      executed_at: Optional[datetime]
      mode: str  # "sync" or "async"
      processing_time_ms: Optional[float]
  ```
- **Updated**: `EmailRecord` now includes `comparison_results: Optional[ComparisonResult]`

### 4. **Documentation** (Complete)
- **Updated Files**:
  - ✅ [README.md](../README.md) - Added all new features section
  - ✅ [docs/USER_INTERFACE.md](../docs/USER_INTERFACE.md) - Comprehensive UI guide with new features
  - ✅ [docs/MODELS.md](../docs/MODELS.md) - Required models + API parameter differences
  - ✅ [docs/INFRASTRUCTURE.md](../docs/INFRASTRUCTURE.md) - Required AI model deployments section
  - ✅ [docs/COMPARISON_ADVERSARIAL.md](../docs/COMPARISON_ADVERSARIAL.md) - Full guide (when/how/why)
  - ✅ [docs/RBAC_AUDIT.md](../docs/RBAC_AUDIT.md) - Identity & permissions
  - ✅ [docs/COSTS_LOGIC.md](../docs/COSTS_LOGIC.md) - Dynamic cost tracking logic
  - ✅ [classymail/core/config.py](../classymail/core/config.py) - Data Zone config

---

## What Remains to Implement 🔄

### Phase 2: Frontend Vue Components (3-4 hours)

**Location**: `frontend/src/components/` and `frontend/src/views/`

#### 2.1 `SettingsView.vue` Enhancement
```vue
<!-- Add section under "Advanced Settings" -->
<section name="Model Comparison">
  <div class="setting-group">
    <h4>Model Selection Strategy</h4>
    <div class="radio-group">
      <input type="radio" name="model_mode" value="auto" v-model="modelMode" />
      <label>Auto (Phi-4, fallback to gpt-4o-mini)</label>
      <p class="help">Token-based fallback: use Phi-4 for <8K tokens, gpt-4o-mini for longer emails</p>
    </div>
    <div class="radio-group">
      <input type="radio" name="model_mode" value="phi4" v-model="modelMode" />
      <label>Always Phi-4 (Fast, 8K context)</label>
    </div>
    <div class="radio-group">
      <input type="radio" name="model_mode" value="gpt4o" v-model="modelMode" />
      <label>Always gpt-4o-mini (Slow, 120K context)</label>
    </div>
  </div>

  <div class="setting-group">
    <h4>Adversarial Comparison</h4>
    <input type="checkbox" v-model="enableComparison" />
    <label>Enable automatic model comparison (run both models in parallel)</label>
    <p class="warning">⚠️ +20-30% latency per classification. Cost: 10-30x more expensive.</p>
  </div>

  <div class="setting-group">
    <h4>Data Zone Compliance</h4>
    <select v-model="dataZone">
      <option value="eu-central">EU Central (Data Zone Europe)</option>
      <option value="eastus">US East</option>
      <option value="global">Global (Any Region)</option>
    </select>
    <p class="help">Phi-4, gpt-4o-mini, and Mistral OCR are available in all zones.</p>
  </div>

  <button @click="saveSettings" class="btn-primary">Save Settings</button>
</section>
```

#### 2.2 `EmailDetailModal.vue` Enhancement
```vue
<!-- Add new "Comparison" tab (Tab 4) -->
<div class="tabs">
  <button @click="activeTab = 'details'">📄 Details</button>
  <button @click="activeTab = 'classification'">🧠 Classification</button>
  <button @click="activeTab = 'pdf'">📄 PDF Viewer</button>
  <button @click="activeTab = 'comparison'">⚖️ Comparison</button>
</div>

<div v-if="activeTab === 'comparison'" class="tab-content">
  <div v-if="email.comparison_results" class="comparison-container">
    <div class="comparison-header">
      <h3>Model Comparison Results</h3>
      <div class="stats">
        <span class="badge" :class="{'agreement': email.comparison_results.agreement}">
          {{ email.comparison_results.agreement ? '🤝 Agreement' : '⚠️ Disagreement' }}
        </span>
        <span class="stat">Confidence delta: {{ (email.comparison_results.confidence_delta * 100).toFixed(1) }}%</span>
        <span class="stat">Time: {{ email.comparison_results.processing_time_ms }}ms</span>
      </div>
    </div>

    <div class="comparison-results">
      <div class="model-result phi4">
        <h4>🔶 Phi-4 (Primary)</h4>
        <intent-display :result="email.comparison_results.phi4" />
      </div>

      <div class="model-divider">VS</div>

      <div class="model-result gpt4o">
        <h4>🟢 gpt-4o-mini (Fallback)</h4>
        <intent-display :result="email.comparison_results.gpt4o_mini" />
      </div>
    </div>

    <div class="comparison-actions">
      <button @click="exportComparison" class="btn-secondary">📥 Export</button>
      <button @click="runComparisonAgain" class="btn-primary">🔄 Run Again</button>
    </div>
  </div>

  <div v-else class="no-comparison">
    <p>No comparison results available.</p>
    <button @click="runComparison('sync')" class="btn-primary">Run Comparison Now (sync)</button>
    <button @click="runComparison('async')" class="btn-secondary">Run in Background (async)</button>
  </div>
</div>
```

#### 2.3 `ModelComparisonModal.vue` (New Component)
```vue
<template>
  <div class="modal modal-comparison">
    <div class="modal-content">
      <h2>🧪 Run Model Comparison</h2>
      <p>Compare Phi-4 and gpt-4o-mini classification results for this email.</p>

      <div class="options">
        <label>
          <input type="radio" name="mode" value="sync" v-model="selectedMode" />
          <strong>Sync</strong> - Wait for results ({{ estimatedTime }}s)
          <p class="help">Blocks until both models complete. Results shown immediately.</p>
        </label>

        <label>
          <input type="radio" name="mode" value="async" v-model="selectedMode" />
          <strong>Async</strong> - Background processing
          <p class="help">Returns immediately (202). Results ready in 30-60s. Check back later.</p>
        </label>
      </div>

      <div class="comparison-info">
        <h4>What's Being Compared</h4>
        <ul>
          <li>🔶 <strong>Phi-4</strong> (8K token context, fast)</li>
          <li>🟢 <strong>gpt-4o-mini</strong> (120K token context, slower)</li>
          <li>📊 Confidence delta (agreement/disagreement)</li>
          <li>⏱️ Processing time comparison</li>
        </ul>
      </div>

      <div class="modal-actions">
        <button @click="close()" class="btn-secondary">Cancel</button>
        <button @click="runComparison()" class="btn-primary">
          {{ selectedMode === 'sync' ? '▶️ Run Sync' : '⏳ Run Async' }}
        </button>
      </div>

      <div v-if="loading" class="loading-indicator">
        <div class="spinner"></div>
        <p>Running comparison... ({{ progress }}%)</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useEmailApi } from '@/composables/emailApi'

const props = defineProps({
  emailId: String
})

const emit = defineEmits(['close', 'done'])

const selectedMode = ref('sync')
const estimatedTime = ref(25)
const loading = ref(false)
const progress = ref(0)
const emailApi = useEmailApi()

const runComparison = async () => {
  loading.value = true
  try {
    const response = await emailApi.reclassifyWithComparison(props.emailId, {
      model: 'both',
      mode: selectedMode.value
    })

    if (selectedMode.value === 'sync') {
      emit('done', response)
    } else {
      // Async: poll for results
      emit('done', response)
    }
  } catch (error) {
    console.error('Comparison failed:', error)
  } finally {
    loading.value = false
  }
}

const close = () => emit('close')
</script>
```

### Phase 3: Worker Async Comparison Handler (2-3 hours)

**Location**: `classymail/services/worker.py` and `classymail/services/pipeline.py`

#### Changes Required:

```python
# In worker.py, modify handle_queue_message():
async def handle_queue_message(receiver, msg, *, get_settings, clients: Clients):
    # ... existing code ...

    # Extract comparison flag from message properties or tags
    comparison_enabled = msg.application_properties.get("comparison", False) if hasattr(msg, "application_properties") else False

    # Pass comparison flag to pipeline
    result = await run_classification_pipeline(
        blob_url,
        settings=settings,
        clients=clients,
        run_comparison=comparison_enabled  # NEW PARAMETER
    )
```

```python
# In pipeline.py, modify run_classification_pipeline():
async def run_classification_pipeline(..., run_comparison: bool = False) -> EmailRecord:
    # ... existing OCR logic ...

    # Classification with optional comparison
    classification_result = await llm_pipeline.classify_with_phi4(
        markdown_text,
        force_model=None,
        run_comparison=run_comparison  # NEW PARAMETER
    )

    # Extract comparison results if generated
    if classification_result.get("comparison_results"):
        email.comparison_results = ComparisonResult(**classification_result["comparison_results"])
    # ... rest of code ...
```

#### Testing:

```bash
# Test async comparison via API
curl -X POST http://localhost:8000/api/emails/{id}/reclassify \
  -H "Content-Type: application/json" \
  -d '{
    "model": "both",
    "mode": "async"
  }'
# Response: 202 Accepted

# Check results after ~30-60s
curl http://localhost:8000/api/emails/{id} | jq '.comparison_results'
```

---

## Validation Checklist ✅

### Code Quality
- ✅ Python syntax validated (py_compile)
- ✅ No critical linting errors (ruff E/F)
- ✅ Models import cleanly (Pydantic schemas)
- ✅ Config loads without errors

### Functionality (Manual Testing Required)
- ⚠️ API endpoint `/api/emails/{id}/reclassify` (endpoint exists, not tested in live environment)
- ⚠️ Sync mode execution (code ready, needs environment)
- ⚠️ Async mode queueing (code ready, needs Service Bus)
- ⚠️ Cosmos DB persistence (schema ready, not tested)

### Documentation
- ✅ All diagrams updated (9/9)
- ✅ Comparison guide created
- ✅ RBAC audit documentation
- ✅ README sections added
- ✅ Config variables documented

---

## Quick Start for Remaining Work

### To Complete Frontend (Next Dev)
1. Install Vue component templates from [frontend/src/components/](../frontend/src/components/)
2. Copy code from Phase 2 above into:
   - `SettingsView.vue`
   - `EmailDetailModal.vue`
   - Create new `ModelComparisonModal.vue`
3. Wire up API calls using existing `emailApi` composable
4. Add CSS styles (use existing Tailwind classes)

### To Complete Worker Handler (Next Dev)
1. Read `classymail/services/worker.py` (line 22+)
2. Modify `handle_queue_message()` to extract `comparison` flag
3. Pass to `run_classification_pipeline(run_comparison=...)`
4. Test with: `mode=async` API calls

### To Run Full E2E Test
```bash
# 1. Start API
uv run uvicorn main:app --reload

# 2. In another terminal, start worker
python -m classymail.worker_main

# 3. Test sync comparison
curl -X POST http://localhost:8000/api/emails/test-123/reclassify \
  -d '{"model":"both", "mode":"sync"}'

# 4. Test async comparison
curl -X POST http://localhost:8000/api/emails/test-456/reclassify \
  -d '{"model":"both", "mode":"async"}'

# 5. Check Cosmos DB results
curl http://localhost:8000/api/emails/test-456 | jq '.comparison_results'
```

---

## Files Modified Summary

| File | Changes | Status |
|------|---------|--------|
| `classymail/models.py` | Added `ComparisonResult` class, updated `EmailRecord` | ✅ |
| `classymail/core/config.py` | Added `AZURE_PREFERRED_DATA_ZONE`, `AZURE_REGION` | ✅ |
| `classymail/services/llm_pipeline.py` | Added `_call_model_with_endpoint()`, modified `classify_with_phi4()` | ✅ |
| `classymail/api/routers/emails.py` | Added `POST /api/emails/{id}/reclassify` endpoint | ✅ |
| `classymail/services/worker.py` | Ready for comparison flag extraction (not yet modified) | 🔄 |
| `classymail/services/pipeline.py` | Ready for `run_comparison` parameter (not yet modified) | 🔄 |
| `frontend/src/views/SettingsView.vue` | Code template provided above | 🔄 |
| `frontend/src/components/EmailDetailModal.vue` | Code template provided above | 🔄 |
| `frontend/src/components/ModelComparisonModal.vue` | New component template provided above | 🔄 |
| `README.md` | Added comparison section + Data Zone table | ✅ |
| `docs/ARCHITECTURE.md` | Updated 5 diagrams (flowcharts, sequence) | ✅ |
| `docs/PIPELINE.md` | Updated 2 diagrams (pipeline, sequence) | ✅ |
| `docs/INFRA_CONFIGURATION.md` | Updated 1 diagram (Event Grid) | ✅ |
| `docs/SCENARIO_E2E.md` | Updated 1 diagram (E2E flow) | ✅ |
| `docs/RBAC_AUDIT.md` | New file: comprehensive RBAC guide | ✅ |
| `docs/COMPARISON_ADVERSARIAL.md` | New file: comparison feature guide | ✅ |

---

## Next Steps for Sprint

**Immediate** (0-1 day):
- [ ] Frontend developer: Implement Vue components (Settings + EmailDetail + Modal)
- [ ] Backend developer: Add comparison flag extraction in worker
- [ ] QA lead: Set up test environment (local + ACA)

**This Week** (1-3 days):
- [ ] Integration testing (sync + async modes)
- [ ] Load testing (parallel model execution overhead)
- [ ] Fine-tuning dataset export validation

**Next Week**:
- [ ] Production deployment (canary → full rollout)
- [ ] Fine-tuning workflow setup
- [ ] User training sessions

---

**See Also**:
- [README.md](../README.md) - Main documentation
- [docs/COMPARISON_ADVERSARIAL.md](../docs/COMPARISON_ADVERSARIAL.md) - Feature guide
- [docs/RBAC_AUDIT.md](../docs/RBAC_AUDIT.md) - Identity troubleshooting
- [docs/LOCAL_DEVELOPMENT.md](../docs/LOCAL_DEVELOPMENT.md) - Local setup
