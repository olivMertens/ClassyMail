# Implementation Summary: Adversarial Model Comparison Feature

> 📋 **Phase Completion Status**: Backend & Documentation ✅ | Frontend 🔄 | Worker Handler 🔄

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
  - ✅ [README.md](../README.md#-adversarial-model-comparison) - Quick start guide
  - ✅ [docs/COMPARISON_ADVERSARIAL.md](../docs/COMPARISON_ADVERSARIAL.md) - Full guide (when/how/why)
  - ✅ [docs/RBAC_AUDIT.md](../docs/RBAC_AUDIT.md) - Identity & permissions
  - ✅ [classymail/core/config.py](../classymail/core/config.py) - Data Zone config

- **Updated Diagrams** (9 total):
  1. ✅ README.md: Main pipeline flowchart (token decision + comparison fork)
  2. ✅ ARCHITECTURE.md: Solution flowchart (token + comparison)
  3. ✅ ARCHITECTURE.md: Sequence diagram (comparison message path)
  4. ✅ ARCHITECTURE.md: API/Worker separation (comparison handler note)
  5. ✅ ARCHITECTURE.md: Identity flow (unchanged, reference only)
  6. ✅ PIPELINE.md: High-level pipeline included in ARCHITECTURE.md (token + comparison fork)
  7. ✅ PIPELINE.md: Message-driven sequence included in ARCHITECTURE.md (opt-in comparison)
  8. ✅ INFRASTRUCTURE.md: Event Grid config (comparison note)
  9. ✅ SCENARIO_E2E.md: Complete E2E flow (comparison path)

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

