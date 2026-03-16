<script setup>
import { ref, watch, computed } from 'vue'
import { XMarkIcon, ArrowPathIcon, CheckIcon, TrashIcon, ClockIcon, ArrowsPointingOutIcon, ArrowsPointingInIcon, ExclamationCircleIcon, ShieldExclamationIcon } from '@heroicons/vue/24/outline'
import MarkdownIt from 'markdown-it'
import { useDialog } from '../composables/useDialog'
import { useI18n } from 'vue-i18n'
import { trackException, trackEvent } from '../services/telemetry'

const { t } = useI18n()

const props = defineProps({
  emailId: {
    type: String,
    default: null
  },
  isOpen: {
    type: Boolean,
    default: false
  }
})
const emit = defineEmits(['close', 'updated'])
const { confirm, alert: showAlert, prompt: showPrompt } = useDialog()

const md = new MarkdownIt({ html: true, linkify: true, breaks: true })

const email = ref(null)
const loading = ref(false)
const reprocessing = ref(false)
const reprocessModalOpen = ref(false)
const reprocessStrategy = ref('standard')
const intentsJson = ref('[]')
const availableCategories = ref([])
const adversarialModel = ref(null)
const primaryModel = ref('Phi-4')
const correctionReason = ref('')
const activeTab = ref('review') // review | comparison | history
const isFullWidth = ref(false)

const pdfUrl = computed(() => {
  const url = email.value?.file_url_proxy || email.value?.file_url_sas || email.value?.file_url || null
  // Append #toolbar=0 to hide the internal PDF viewer toolbar (save/print/etx)
  return url ? `${url}#toolbar=0` : null
})

// New Multi-select state
const selectedCategoryNames = ref([])
const customCategories = ref([])
const isComparing = ref(false)

const latestComparison = computed(() => {
  const results = email.value?.comparison_results
  if (!results) return null
  // Handle if it's an array (legacy) or single object (current Pydantic model)
  let comparison = null
  if (Array.isArray(results)) {
    comparison = results.length > 0 ? results[results.length - 1] : null
  } else {
    comparison = results
  }

  // Validate that comparison has meaningful data
  if (!comparison) return null

  // Check if comparison has valid model results (relaxed)
  const hasModels = comparison.model_results && Object.keys(comparison.model_results).length > 0

  return hasModels ? comparison : null
})

const allComparisons = computed(() => {
  const results = email.value?.comparison_results
  if (!results || !Array.isArray(results)) return []

  // Filter and validate all comparisons
  return results.filter(comparison => {
    if (!comparison) return false
    // Relaxed check: Just ensure we have model results
    const hasModels = comparison.model_results && Object.keys(comparison.model_results).length > 0
    return hasModels
  }).reverse() // Most recent first
})

const hasValidComparison = computed(() => {
  return latestComparison.value !== null
})

const comparisonCount = computed(() => {
  return allComparisons.value.length
})

const getModelStyles = (modelName) => {
  const n = (modelName || '').toLowerCase()
  let styleParams = {
    card: 'border-indigo-200 bg-indigo-50 dark:bg-indigo-900/10 dark:border-indigo-800',
    text: 'text-indigo-800 dark:text-indigo-300',
    border: 'border-indigo-200',
    badge: 'text-indigo-600 bg-indigo-100 dark:bg-indigo-900 dark:text-indigo-200'
  }

  if (n.includes('phi')) {
    styleParams = {
      card: 'border-blue-200 bg-blue-50 dark:bg-blue-900/10 dark:border-blue-800',
      text: 'text-blue-800 dark:text-blue-300',
      border: 'border-blue-200',
      badge: 'text-blue-600 bg-blue-100 dark:bg-blue-900 dark:text-blue-200'
    }
  } else if (n.includes('gpt')) {
    styleParams = {
      card: 'border-orange-200 bg-orange-50 dark:bg-orange-900/10 dark:border-orange-800',
      text: 'text-orange-800 dark:text-orange-300',
      border: 'border-orange-200',
      badge: 'text-orange-600 bg-orange-100 dark:bg-orange-900 dark:text-orange-200'
    }
  }

  return {
    displayName: modelName,
    ...styleParams
  }
}

const formatConfidence = (result) => {
  if (!result?.detected_intents?.length) return '0%'
  const maxConf = Math.max(...result.detected_intents.map(i => i.confidence || 0))
  return Math.round(maxConf * 100) + '%'
}

const loadSettings = async () => {
  try {
    const res = await fetch('/api/settings')
    if (res.ok) {
      const data = await res.json()
      availableCategories.value = data.categories || []
      adversarialModel.value = data.adversarial_model
      primaryModel.value = data.ai_model || 'Phi-4'
    }
  } catch (e) { console.error(e) }
}

const loadEmail = async () => {
  if (!props.emailId) return
  loading.value = true
  correctionReason.value = ''
  selectedCategoryNames.value = []
  customCategories.value = []
  isComparing.value = false

  try {
    const res = await fetch(`/api/emails/${props.emailId}`)
    if (res.ok) {
      email.value = await res.json()
      intentsJson.value = JSON.stringify(email.value.classification?.detected_intents || [], null, 2)
      correctionReason.value = email.value.correction_reason || ''

      // Populate selection from current intent
      const currentIntents = email.value.classification?.detected_intents || []
      currentIntents.forEach(i => {
        const name = i.intent
        if (availableCategories.value.find(c => c.name === name)) {
          if (!selectedCategoryNames.value.includes(name)) {
            selectedCategoryNames.value.push(name)
          }
        } else {
          // It's a custom or old category
          if (!customCategories.value.includes(name)) {
            customCategories.value.push(name)
            if (!selectedCategoryNames.value.includes(name)) {
              selectedCategoryNames.value.push(name)
            }
          }
        }
      })
    }
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

const toggleCategory = (name) => {
  if (selectedCategoryNames.value.includes(name)) {
    selectedCategoryNames.value = selectedCategoryNames.value.filter(n => n !== name)
  } else {
    selectedCategoryNames.value.push(name)
  }
}

const addCustomCategory = async () => {
  const name = await showPrompt("Enter new category name:")
  if (name) {
    if (!customCategories.value.includes(name)) {
      customCategories.value.push(name)
    }
    if (!selectedCategoryNames.value.includes(name)) {
      selectedCategoryNames.value.push(name)
    }
  }
}

const runComparison = async () => {
  if (!email.value) return
  isComparing.value = true
  try {
    const res = await fetch(`/api/emails/${email.value.id}/reclassify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'both', mode: 'sync' })
    })
    if (res.ok) {
      // Reload email to get updated comparison results
      await loadEmail()
      activeTab.value = 'comparison'
    } else {
      showAlert('Error running comparison')
    }
  } catch (e) {
    trackException(e)
    showAlert('Error running comparison: ' + e.message)
  } finally {
    isComparing.value = false
  }
}

const reprocess = async () => {
  if (!email.value) return
  reprocessStrategy.value = email.value.processing_strategy || 'standard'
  reprocessModalOpen.value = true
}

const confirmReprocess = async () => {
  if (!email.value) return
  reprocessModalOpen.value = false
  reprocessing.value = true
  try {
    const res = await fetch(`/api/emails/${email.value.id}/reprocess`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ processing_strategy: reprocessStrategy.value }),
    })
    if (res.ok) {
      await showAlert(t('dashboard.reprocess.success'))
      emit('close')
    } else {
      showAlert('Error reprocessing')
    }
  } catch (e) {
    trackException(e)
    showAlert('Error reprocessing: ' + e.message)
  } finally {
    reprocessing.value = false
  }
}

const strategyBadge = (strategy) => {
  const map = {
    standard: { icon: '📄', color: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 border-gray-200 dark:border-gray-600' },
    reasoning: { icon: '🧠', color: 'bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300 border-purple-200 dark:border-purple-700' },
    vision: { icon: '👁', color: 'bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300 border-teal-200 dark:border-teal-700' },
  }
  return map[strategy] || map.standard
}

const ocrProviderBadge = (provider) => {
  if (!provider || provider === 'mistral_ocr') return null
  const map = {
    document_intelligence: { icon: '📄', color: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 border-amber-200 dark:border-amber-700', key: 'document_intelligence' },
  }
  return map[provider] || null
}

const formatDuration = (email) => {
  const ms = email?.processing_time_ms
  if (!ms) return null
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  return `${(s / 60).toFixed(1)}min`
}

const durationTooltip = (email) => {
  const st = email?.stage_timings
  if (!st) return formatDuration(email) ? t('dashboard.time.total_only') : ''
  const fmtMs = (ms) => {
    if (!ms && ms !== 0) return '—'
    if (ms < 1000) return `${ms.toFixed(0)}ms`
    const s = ms / 1000
    if (s < 60) return `${s.toFixed(1)}s`
    return `${(s / 60).toFixed(1)}min`
  }
  const lines = []
  const stages = [
    { key: 'download', icon: '📥', label: t('dashboard.time.download') },
    { key: 'ocr', icon: '🔍', label: t('dashboard.time.ocr') },
    { key: 'extraction', icon: '📋', label: t('dashboard.time.extraction') },
    { key: 'classify', icon: '🧠', label: t('dashboard.time.classify') },
    { key: 'embedding', icon: '📐', label: t('dashboard.time.embedding') },
  ]
  for (const s of stages) {
    if (st[s.key] !== undefined) {
      lines.push(`${s.icon} ${s.label}: ${fmtMs(st[s.key])}`)
    }
  }
  const reasons = []
  if (st.pages && st.pages > 10) reasons.push(t('dashboard.time.reason_large_pdf', { pages: st.pages }))
  if (st.ocr_detail?.fallback_provider) reasons.push(t('dashboard.time.reason_ocr_fallback', { provider: st.ocr_detail.fallback_provider }))
  if (st.ocr_detail?.mistral_skip_reason === 'circuit_breaker_open') reasons.push(t('dashboard.time.reason_circuit_breaker'))
  if (st.ocr_detail?.mistral_error_type) reasons.push(t('dashboard.time.reason_mistral_error', { error: st.ocr_detail.mistral_error_type }))
  if (st.classify_detail?.fallback_used) reasons.push(t('dashboard.time.reason_llm_fallback', { model: st.classify_detail.model || 'gpt-4o-mini' }))
  if (reasons.length) {
    lines.push('')
    lines.push(`⚠️ ${t('dashboard.time.slow_reasons')}:`)
    reasons.forEach(r => lines.push(`  • ${r}`))
  }
  return lines.join('\n')
}

const markAsInvalid = async () => {
  if (!await confirm("Are you sure you want to mark this email as Invalid/Garbage?")) return;

  if (!correctionReason.value || !correctionReason.value.trim() || correctionReason.value.trim().length < 5) {
    showAlert("Please provide a reason or comment for marking this email as Invalid (at least 5 characters).")
    return
  }

  try {
    const payload = { status: 'INVALID', reason: correctionReason.value }
    const res = await fetch(`/api/emails/${email.value.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    if (res.ok) {
      emit('updated')
      emit('close')
    }
  } catch (e) {
    trackException(e)
    showAlert("Error saving: " + e.message)
  }
}

const saveIntents = async () => {
  if (!email.value) return

  // Validation: Require correction reason ALWAYS if validating manually
  // The user requirement is "obligation of a comment for the user" when verifying/reassigning
  if (!correctionReason.value || !correctionReason.value.trim() || correctionReason.value.trim().length < 5) {
    showAlert("Please provide a valid reason or comment for this classification (at least 5 characters). This is required for reinforcement learning.")
    return
  }

  try {
    // Construct intents from selection
    // We assume 1.0 confidence for manual selection
    const newIntents = selectedCategoryNames.value.map(name => ({
      intent: name,
      confidence: 1.0,
      justification: "Manually selected by user"
    }))

    const payload = { intents: newIntents, reason: correctionReason.value }
    const res = await fetch(`/api/emails/${email.value.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    if (res.ok) {
      emit('updated')
      emit('close')
    }
  } catch (e) {
    trackException(e)
    showAlert('Error Saving: ' + e.message)
  }
}

watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    loadSettings().then(loadEmail)
  } else {
    email.value = null
    activeTab.value = 'review'
  }
})

const parseArrivalDate = (fileUrl) => {
  if (!fileUrl) return null
  try {
    const m = fileUrl.match(/uploads\/(\d{4})\/(\d{2})\/(\d{2})\//)
    if (m) {
      const [, y, mo, d] = m
      return new Date(`${y}-${mo}-${d}T00:00:00Z`)
    }
  } catch (e) {
    console.error(e)
  }
  return null
}

const renderMarkdown = (text) => md.render(text || '')

// --- Vision Analysis helpers ---
const isFilenameLike = (summary) => {
  if (!summary || !summary.trim()) return true
  return /^img[-_]?\d+\.?(jpe?g|png|gif|bmp|webp|svg)?$/i.test(summary.trim())
}

const visionStats = computed(() => {
  const items = email.value?.vision_analysis || []
  if (!items.length) return null
  const described = items.filter(i => i.summary && !isFilenameLike(i.summary)).length
  const filenameOnly = items.length - described
  const pages = [...new Set(items.map(i => (i.page_index || 0) + 1))].sort((a, b) => a - b)
  const relevant = items.filter(i => i.is_relevant).length
  return { total: items.length, described, filenameOnly, pages, relevant }
})

// Track vision detail view in App Insights
watch(() => email.value, (val) => {
  if (val && val.vision_analysis && val.vision_analysis.length) {
    const stats = visionStats.value
    trackEvent('vision_detail_viewed', {
      emailId: val.id,
      strategy: val.processing_strategy,
      totalImages: stats?.total,
      describedImages: stats?.described,
      filenameOnlyImages: stats?.filenameOnly,
      relevantImages: stats?.relevant,
    })
  }
})
</script>

<template>
  <div
    v-if="isOpen"
    class="relative z-50"
    aria-labelledby="modal-title"
    role="dialog"
    aria-modal="true"
  >
    <div class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" />

    <div class="fixed inset-0 z-10 w-screen overflow-y-auto">
      <div class="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
        <div
          class="relative transform overflow-hidden rounded-lg bg-white dark:bg-gray-900 text-left shadow-xl transition-all sm:my-8 h-[90vh] flex flex-col"
          :class="isFullWidth ? 'sm:w-full sm:max-w-[95vw]' : 'sm:w-full sm:max-w-6xl'"
        >
          <!-- Header -->
          <div
            class="bg-gray-50 dark:bg-gray-800 px-4 py-3 sm:px-6 flex justify-between items-center border-b border-gray-200 dark:border-gray-700"
          >
            <h3
              id="modal-title"
              class="text-base font-semibold leading-6 text-gray-900 dark:text-white truncate max-w-lg"
            >
              {{ email?.subject || 'Loading...' }}
            </h3>
            <div class="flex gap-2">
              <button
                type="button"
                class="rounded-md bg-white dark:bg-gray-800 text-gray-400 hover:text-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 mr-2"
                :title="isFullWidth ? 'Minimize width' : 'Full width'"
                @click="isFullWidth = !isFullWidth"
              >
                <ArrowsPointingInIcon
                  v-if="isFullWidth"
                  class="h-5 w-5"
                />
                <ArrowsPointingOutIcon
                  v-else
                  class="h-5 w-5"
                />
              </button>
              <button
                :disabled="reprocessing"
                class="text-green-600 hover:text-green-500 dark:text-green-400 font-medium text-sm flex items-center gap-1"
                @click="reprocess"
              >
                <ArrowPathIcon
                  class="h-4 w-4"
                  :class="{ 'animate-spin': reprocessing }"
                />
                {{ t('email_detail.reprocess') }}
              </button>
              <span
                v-if="email.processing_strategy"
                class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border"
                :class="strategyBadge(email.processing_strategy).color"
                :title="t('email_detail.processing_mode') + ': ' + t('dashboard.strategy.' + email.processing_strategy)"
              >
                {{ strategyBadge(email.processing_strategy).icon }} {{ t('dashboard.strategy.' +
                  email.processing_strategy) }}
              </span>
              <span
                v-if="ocrProviderBadge(email.ocr_provider)"
                class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border"
                :class="ocrProviderBadge(email.ocr_provider).color"
                :title="t('dashboard.ocr_provider.' + email.ocr_provider)"
              >
                {{ ocrProviderBadge(email.ocr_provider).icon }} {{ t('dashboard.ocr_provider.' +
                  ocrProviderBadge(email.ocr_provider).key) }}
              </span>
              <span
                v-if="formatDuration(email)"
                class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border cursor-help bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 border-blue-200 dark:border-blue-700"
                :title="durationTooltip(email)"
              >
                ⏱ {{ formatDuration(email) }}
              </span>
              <button
                type="button"
                class="rounded-md bg-white dark:bg-gray-800 text-gray-400 hover:text-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
                @click="$emit('close')"
              >
                <span class="sr-only">Close</span>
                <XMarkIcon
                  class="h-6 w-6"
                  aria-hidden="true"
                />
              </button>
            </div>
          </div>

          <!-- Content -->
          <div class="flex-1 flex flex-col md:flex-row overflow-hidden">
            <!-- Left: PDF -->
            <div
              class="md:w-1/2 h-1/2 md:h-full border-b md:border-b-0 md:border-r border-gray-200 dark:border-gray-700 bg-gray-100 dark:bg-gray-800 flex flex-col"
            >
              <div class="flex-1 flex flex-col">
                <iframe
                  v-if="pdfUrl"
                  :src="pdfUrl"
                  class="w-full flex-1"
                  title="PDF Preview"
                />
                <div
                  v-else
                  class="flex-1 flex items-center justify-center text-gray-500"
                >
                  {{ loading ? 'Loading PDF...' : 'No PDF URL available' }}
                </div>
              </div>
              <div
                v-if="pdfUrl"
                class="p-2 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-xs text-primary-600 dark:text-primary-300 flex justify-between items-center"
              >
                <span>Having trouble? Open in a new tab:</span>
                <a
                  :href="pdfUrl"
                  target="_blank"
                  rel="noopener"
                  class="font-semibold hover:underline"
                >
                  Open PDF
                </a>
              </div>
            </div>

            <!-- Right: Data -->
            <div class="md:w-1/2 h-1/2 md:h-full overflow-y-auto bg-white dark:bg-gray-900 flex flex-col">
              <!-- Tabs -->
              <div class="border-b border-gray-200 dark:border-gray-700">
                <nav
                  class="flex -mb-px"
                  aria-label="Tabs"
                >
                  <button
                    :class="[activeTab === 'review' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400', 'w-1/3 py-4 px-1 text-center border-b-2 font-medium text-sm']"
                    @click="activeTab = 'review'"
                  >
                    Review & Classify
                  </button>
                  <button
                    :class="[activeTab === 'comparison' ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400', 'w-1/3 py-4 px-1 text-center border-b-2 font-medium text-sm']"
                    @click="activeTab = 'comparison'"
                  >
                    Comparison (Adversarial)
                  </button>
                  <button
                    :class="[activeTab === 'history' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400', 'w-1/3 py-4 px-1 text-center border-b-2 font-medium text-sm']"
                    @click="activeTab = 'history'"
                  >
                    History
                  </button>
                </nav>
              </div>

              <!-- Tab Content -->
              <div class="p-6 flex-1">
                <div
                  v-if="loading && !email"
                  class="space-y-4"
                >
                  <div class="animate-pulse bg-gray-200 dark:bg-gray-700 h-8 rounded w-3/4" />
                  <div class="animate-pulse bg-gray-200 dark:bg-gray-700 h-32 rounded" />
                </div>

                <!-- Review Tab -->
                <div
                  v-else-if="activeTab === 'review' && email"
                  class="space-y-6"
                >
                  <!-- Meta Info -->
                  <div class="grid grid-cols-2 gap-2 text-xs text-gray-500 dark:text-gray-400">
                    <div><span class="font-semibold">Subject:</span> {{ email.subject || '—' }}</div>
                    <div><span class="font-semibold">Sender:</span> {{ email.sender || '—' }}</div>
                    <div>
                      <span class="font-semibold">Arrived:</span> {{ email.created_at ? new
                        Date(email.created_at).toLocaleString() : (parseArrivalDate(email.file_url || email.file_url_sas)
                          ? parseArrivalDate(email.file_url || email.file_url_sas).toLocaleString() : '—') }}
                    </div>
                    <div>
                      <span class="font-semibold">Processed:</span> {{ email.updated_at ? new
                        Date(email.updated_at).toLocaleString() : '—' }}
                    </div>
                  </div>

                  <!-- PII Detection Summary -->
                  <div
                    v-if="email.pii_detected && email.pii_data"
                    class="rounded-md bg-amber-50 dark:bg-amber-900/20 p-3 border border-amber-200 dark:border-amber-800"
                  >
                    <div class="flex items-center gap-2 mb-2">
                      <ShieldExclamationIcon class="h-5 w-5 text-amber-500" />
                      <span class="text-sm font-semibold text-amber-800 dark:text-amber-200">PII Détecté</span>
                    </div>
                    <div class="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                      <div
                        v-for="(items, key) in email.pii_data"
                        :key="key"
                      >
                        <template v-if="items && items.length">
                          <span class="font-semibold text-amber-700 dark:text-amber-300 capitalize">{{ {
                            names: 'Noms',
                            emails: 'Emails', phones: 'Téléphones', addresses: 'Adresses', contract_ids: 'N° contrat',
                            dates: 'Dates', other: 'Autre'
                          }[key] || key }}:</span>
                          <span class="text-amber-600 dark:text-amber-400 ml-1">{{ items.slice(0, 3).join(', ') }}{{
                            items.length > 3 ? ` (+${items.length - 3})` : '' }}</span>
                        </template>
                      </div>
                    </div>
                  </div>

                  <!-- Debug URLs -->
                  <div class="mt-2 text-xs text-gray-400 dark:text-gray-500">
                    <div v-if="email.file_url">
                      <span class="font-semibold">Blob URL:</span>
                      <code class="break-all">{{ email.file_url }}</code>
                    </div>
                    <div v-if="email.file_url_sas">
                      <span class="font-semibold">SAS URL:</span>
                      <code class="break-all">{{ email.file_url_sas }}</code>
                    </div>
                  </div>

                  <!-- Content Filter Alert -->
                  <div
                    v-if="email.status === 'CONTENT_FILTERED' && email.content_filter_result"
                    class="rounded-md bg-purple-50 dark:bg-purple-900/20 p-3 border border-purple-200 dark:border-purple-800"
                  >
                    <div class="flex items-center gap-2 mb-2">
                      <ShieldExclamationIcon class="h-5 w-5 text-purple-500" />
                      <span class="text-sm font-semibold text-purple-800 dark:text-purple-200">Content Safety Filter</span>
                    </div>
                    <p class="text-xs text-purple-700 dark:text-purple-300 mb-2">
                      Azure OpenAI content safety blocked classification of this document.
                    </p>
                    <div class="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                      <div
                        v-for="category in ['hate', 'jailbreak', 'self_harm', 'sexual', 'violence']"
                        :key="category"
                      >
                        <span
                          class="font-semibold capitalize"
                          :class="email.content_filter_result[category]?.filtered ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'"
                        >
                          {{ category.replace('_', ' ') }}:
                        </span>
                        <span
                          class="ml-1 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium"
                          :class="email.content_filter_result[category]?.filtered
                            ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                            : 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'"
                        >
                          {{ email.content_filter_result[category]?.filtered ? 'FILTERED' : 'safe' }}
                        </span>
                        <span
                          v-if="email.content_filter_result[category]?.severity"
                          class="ml-1 text-gray-500 dark:text-gray-400"
                        >
                          ({{ email.content_filter_result[category].severity }})
                        </span>
                      </div>
                    </div>
                  </div>

                  <!-- Error Box -->
                  <div
                    v-if="email.error"
                    class="rounded-md bg-red-50 dark:bg-red-900/20 p-4 border border-red-200 dark:border-red-800 space-y-3"
                  >
                    <p class="text-sm text-red-700 dark:text-red-200">
                      {{ email.error }}
                    </p>
                    <div
                      v-if="email.processing_log?.length"
                      class="mt-2 text-xs text-gray-700 dark:text-gray-200"
                    >
                      <div class="font-semibold mb-1">
                        Processing Log
                      </div>
                      <div class="space-y-2">
                        <div
                          v-for="(entry, idx) in email.processing_log"
                          :key="idx"
                          class="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded p-2 font-mono"
                        >
                          <div>Status: {{ entry.status_code }} | Attempt: {{ entry.attempt }}</div>
                          <div>Headers: {{ entry.headers }}</div>
                          <div class="mt-1 whitespace-pre-wrap">
                            {{ entry.text_snippet }}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div>
                    <h4 class="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-2">
                      🧾 OCR Text / Texte OCR
                    </h4>
                    <div
                      class="prose dark:prose-invert max-w-none text-sm max-h-60 overflow-y-auto border border-gray-100 dark:border-gray-700 rounded p-2 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100"
                    >
                      <!-- eslint-disable-next-line vue/no-v-html -->
                      <div v-html="renderMarkdown(email.markdown)" />
                    </div>
                  </div>

                  <!-- Vision Analysis -->
                  <div v-if="email.vision_analysis && email.vision_analysis.length">
                    <h4
                      class="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-3 mt-4 flex items-center gap-2"
                    >
                      👁 {{ t('email_detail.vision_title') }}
                      <span class="text-xs font-normal text-gray-500">({{ email.vision_analysis.length }} image{{
                        email.vision_analysis.length !== 1 ? 's' : '' }})</span>
                    </h4>

                    <!-- Vision Overview Banner -->
                    <div
                      v-if="visionStats"
                      class="mb-3 p-2.5 rounded-lg text-xs flex flex-wrap items-center gap-3"
                      :class="visionStats.described > 0
                        ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800/50 text-green-800 dark:text-green-300'
                        : 'bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/50 text-amber-800 dark:text-amber-300'"
                    >
                      <span class="font-semibold">{{ t('email_detail.vision_quality') }}:</span>
                      <span v-if="visionStats.described === visionStats.total">
                        ✓ {{ t('email_detail.vision_all_described') }}
                      </span>
                      <span v-else-if="visionStats.described > 0">
                        ⚠ {{ visionStats.described }}/{{ visionStats.total }} {{
                          t('email_detail.vision_partially_described') }}
                      </span>
                      <span v-else>
                        ⚠ {{ t('email_detail.vision_no_descriptions') }}
                      </span>
                      <span class="text-gray-500 dark:text-gray-400">|</span>
                      <span>{{ t('email_detail.vision_pages') }}: {{ visionStats.pages.join(', ') }}</span>
                      <span v-if="visionStats.relevant > 0">
                        <span class="text-gray-500 dark:text-gray-400">|</span>
                        {{ visionStats.relevant }} {{ t('email_detail.vision_relevant') }}
                      </span>
                    </div>

                    <div
                      class="space-y-2 border border-green-100 dark:border-green-900/30 rounded-lg p-3 bg-green-50/50 dark:bg-green-900/10"
                    >
                      <div
                        v-for="(item, idx) in email.vision_analysis"
                        :key="item.id || `vis-${idx}`"
                        class="text-sm p-2.5 rounded bg-white dark:bg-gray-800 border border-green-200 dark:border-green-800/50"
                      >
                        <!-- Header: Page + Type + ID + Relevance Badge -->
                        <div class="flex justify-between items-start mb-2 gap-2">
                          <div class="flex items-center gap-1 flex-wrap">
                            <span class="font-semibold text-xs text-green-700 dark:text-green-300">
                              Page {{ (item.page_index || 0) + 1 }}
                            </span>
                            <span
                              v-if="item.image_type"
                              class="text-xs text-gray-600 dark:text-gray-400 capitalize"
                            >
                              • {{ item.image_type }}
                            </span>
                            <span
                              v-if="item.id"
                              class="text-[10px] text-gray-400 dark:text-gray-500 font-mono"
                            >
                              ({{ item.id }})
                            </span>
                          </div>
                          <div class="flex items-center gap-1.5 flex-shrink-0">
                            <span
                              v-if="item.summary && !isFilenameLike(item.summary)"
                              class="text-[10px] bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300 px-1.5 py-0.5 rounded-full border border-green-200 dark:border-green-800 font-medium"
                            >
                              ✓ {{ t('email_detail.vision_described') }}
                            </span>
                            <span
                              v-else
                              class="text-[10px] bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300 px-1.5 py-0.5 rounded-full border border-amber-200 dark:border-amber-800 font-medium"
                            >
                              ⚠ {{ t('email_detail.vision_pending') }}
                            </span>
                            <span
                              v-if="item.is_relevant"
                              class="text-[10px] bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300 px-1.5 py-0.5 rounded-full border border-green-200 dark:border-green-800 font-medium"
                            >
                              ✓ {{ t('email_detail.vision_relevant_badge') }}
                            </span>
                          </div>
                        </div>

                        <!-- Summary: Main description -->
                        <div
                          v-if="item.summary && !isFilenameLike(item.summary)"
                          class="mb-2 text-gray-900 dark:text-gray-100 text-sm leading-relaxed"
                        >
                          <strong class="block text-xs text-gray-700 dark:text-gray-300 mb-1">{{
                            t('email_detail.vision_summary')
                          }}:</strong>
                          {{ item.summary }}
                        </div>

                        <!-- Filename-like summary: Show meaningful message -->
                        <div
                          v-else-if="item.summary && isFilenameLike(item.summary)"
                          class="mb-2 text-amber-700 dark:text-amber-300 text-xs bg-amber-50 dark:bg-amber-900/20 p-2 rounded border border-amber-100 dark:border-amber-800/30"
                        >
                          <span class="font-semibold">{{ t('email_detail.vision_no_ai_desc') }}</span>
                          <span class="text-gray-500 dark:text-gray-400 ml-1">({{ t('email_detail.vision_source_ref')
                          }}: {{ item.summary
                          }})</span>
                          <div class="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                            {{ t('email_detail.vision_reprocess_hint') }}
                          </div>
                        </div>

                        <!-- Details: Additional context -->
                        <div
                          v-if="item.details"
                          class="text-xs text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-900/30 p-2.5 rounded border border-green-100 dark:border-green-800/30"
                        >
                          <span class="font-semibold block mb-1 text-green-700 dark:text-green-400">{{
                            t('email_detail.vision_details')
                          }}:</span>
                          {{ item.details }}
                        </div>

                        <!-- BBox info -->
                        <div
                          v-if="item.bbox"
                          class="mt-1.5 text-[10px] text-gray-400 dark:text-gray-500 font-mono"
                        >
                          📐 BBox: x{{ Math.round(item.bbox.x_min || 0) }},y{{ Math.round(item.bbox.y_min || 0) }} → x{{
                            Math.round(item.bbox.x_max || 0) }},y{{ Math.round(item.bbox.y_max || 0) }}
                        </div>

                        <!-- Fallback: Show image_type if no summary at all -->
                        <div
                          v-if="!item.summary && !item.details && item.image_type"
                          class="text-xs italic text-gray-500 dark:text-gray-400"
                        >
                          {{ t('email_detail.vision_type_detected') }}: <strong>{{ item.image_type }}</strong>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- Category Selection -->
                  <div>
                    <h4 class="text-sm font-medium text-gray-900 dark:text-white mb-3">
                      Catégories
                    </h4>
                    <div class="flex flex-wrap gap-2 mb-3">
                      <button
                        v-for="cat in availableCategories"
                        :key="cat.name"
                        :class="selectedCategoryNames.includes(cat.name) ? 'bg-primary-100 text-primary-800 ring-primary-500 dark:bg-primary-900 dark:text-primary-200' : 'bg-gray-100 text-gray-700 ring-gray-200 dark:bg-gray-800 dark:text-gray-300'"
                        class="inline-flex items-center rounded-md px-2.5 py-1.5 text-sm font-medium ring-1 ring-inset transition-colors"
                        @click="toggleCategory(cat.name)"
                      >
                        <CheckIcon
                          v-if="selectedCategoryNames.includes(cat.name)"
                          class="w-4 h-4 mr-1.5"
                        />
                        {{ cat.name }}
                      </button>
                      <button
                        v-for="cat in customCategories"
                        :key="cat"
                        :class="selectedCategoryNames.includes(cat) ? 'bg-indigo-100 text-indigo-800 ring-indigo-500 dark:bg-indigo-900 dark:text-indigo-200' : 'bg-gray-100 text-gray-700 ring-gray-200 dark:bg-gray-800 dark:text-gray-300'"
                        class="inline-flex items-center rounded-md px-2.5 py-1.5 text-sm font-medium ring-1 ring-inset transition-colors"
                        @click="toggleCategory(cat)"
                      >
                        <CheckIcon
                          v-if="selectedCategoryNames.includes(cat)"
                          class="w-4 h-4 mr-1.5"
                        />
                        {{ cat }} (Manual)
                      </button>
                      <button
                        class="inline-flex items-center rounded-md px-2.5 py-1.5 text-sm font-medium bg-white text-gray-500 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 border-dashed dark:bg-gray-800 dark:text-gray-400"
                        @click="addCustomCategory"
                      >
                        + Custom
                      </button>
                    </div>
                  </div>

                  <!-- IA Reasoning -->
                  <div v-if="email.classification?.detected_intents?.some(i => i.justification)">
                    <h4 class="text-sm font-medium text-gray-900 dark:text-white mb-2">
                      Raisonnement IA
                    </h4>
                    <ul class="text-xs text-gray-600 dark:text-gray-300 space-y-1">
                      <li
                        v-for="i in email.classification.detected_intents.filter(i => i.justification)"
                        :key="i.intent"
                      >
                        <strong>{{ i.intent }} ({{ Math.round((i.confidence || 0) * 100) }}%) :</strong> {{
                          i.justification
                        }}
                      </li>
                    </ul>
                  </div>

                  <!-- No Category Reason -->
                  <div
                    v-if="(!email.classification?.detected_intents?.length) && email.classification?.classification_reason"
                  >
                    <h4 class="text-sm font-medium text-gray-900 dark:text-white mb-2">
                      Raisonnement (Aucune catégorie)
                    </h4>
                    <div
                      class="text-xs text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 p-2 rounded border border-gray-200 dark:border-gray-700 italic"
                    >
                      {{ email.classification.classification_reason }}
                    </div>
                  </div>

                  <!-- Reason -->
                  <div>
                    <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white mb-2">Raison /
                      Commentaire</label>
                    <textarea
                      v-model="correctionReason"
                      rows="2"
                      class="mt-1 block w-full rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-700"
                      placeholder="Pourquoi cette correction ? (Apprentissage)"
                    />
                  </div>

                  <!-- Actions -->
                  <div class="flex justify-between pt-4 border-t border-gray-200 dark:border-gray-700">
                    <button
                      class="text-red-600 hover:text-red-500 text-sm font-medium flex items-center"
                      @click="markAsInvalid"
                    >
                      <TrashIcon class="w-4 h-4 mr-1" />
                      Mark as Garbage/Invalid
                    </button>
                    <button
                      class="rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600 disabled:opacity-50"
                      :disabled="selectedCategoryNames.length === 0"
                      @click="saveIntents"
                    >
                      Validate & Save
                    </button>
                  </div>
                </div>

                <!-- Comparison Tab -->
                <div
                  v-else-if="activeTab === 'comparison' && email"
                  class="space-y-6"
                >
                  <div class="flex justify-between items-center">
                    <div>
                      <h3 class="text-lg font-medium text-gray-900 dark:text-white">
                        Adversarial Model Comparison
                      </h3>
                      <p
                        v-if="comparisonCount > 0"
                        class="text-sm text-gray-500 dark:text-gray-400"
                      >
                        {{ comparisonCount }} comparison{{ comparisonCount > 1 ? 's' : '' }} executed
                      </p>
                    </div>
                    <div class="flex flex-col items-end gap-1">
                      <button
                        :disabled="isComparing || !adversarialModel"
                        class="rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:opacity-50 flex items-center gap-2"
                        :title="!adversarialModel ? 'Configure Adversarial Model in Settings first' : ''"
                        @click="runComparison"
                      >
                        <ArrowPathIcon
                          v-if="isComparing"
                          class="h-4 w-4 animate-spin"
                        />
                        {{ isComparing ? 'Running Models...' : 'Run New Comparison' }}
                      </button>
                      <span
                        v-if="!adversarialModel"
                        class="text-[10px] text-red-500"
                      >
                        Requires "Adversarial Model" in Settings
                      </span>
                    </div>
                  </div>

                  <div
                    v-if="hasValidComparison"
                    class="space-y-4"
                  >
                    <!-- Loop through all comparisons -->
                    <div
                      v-for="(comparison, index) in allComparisons"
                      :key="index"
                      class="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden"
                    >
                      <!-- Comparison Header -->
                      <div class="px-4 py-3 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                        <div class="flex justify-between items-center">
                          <div class="flex items-center gap-3">
                            <span class="text-xs font-semibold text-gray-500 dark:text-gray-400">
                              #{{ comparisonCount - index }}
                            </span>
                            <div
                              class="flex items-center gap-2 text-sm"
                              :class="comparison.agreement ? 'text-green-700 dark:text-green-400' : 'text-red-700 dark:text-red-400'"
                            >
                              <span class="text-lg">{{ comparison.agreement ? '✅' : '⚠️' }}</span>
                              <span class="font-medium">
                                {{ comparison.agreement ? 'Agreement' : 'Divergence' }}
                              </span>
                            </div>
                            <span class="text-xs text-gray-500 dark:text-gray-400">
                              Δ {{ comparison.confidence_delta != null ? comparison.confidence_delta.toFixed(2) : 'N/A' }}
                            </span>
                            <span class="text-xs text-gray-500 dark:text-gray-400">
                              {{ comparison.processing_time_ms != null ? comparison.processing_time_ms + 'ms' : 'N/A' }}
                            </span>
                          </div>
                          <div class="text-xs text-gray-500 dark:text-gray-400">
                            {{ comparison.executed_at ? new Date(comparison.executed_at).toLocaleString() :
                              'Unknown' }}
                          </div>
                        </div>
                        <!-- Models badges -->
                        <div class="flex gap-2 mt-2">
                          <span
                            v-for="modelName in Object.keys(comparison.model_results || {})"
                            :key="modelName"
                            class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
                            :class="getModelStyles(modelName).badge"
                          >
                            {{ modelName }}
                          </span>
                        </div>
                      </div>

                      <!-- Comparison Results -->
                      <div class="p-4">
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                          <div
                            v-for="(result, modelName) in comparison.model_results"
                            :key="modelName"
                            class="rounded-lg border p-4"
                            :class="getModelStyles(modelName).card"
                          >
                            <div
                              class="flex justify-between mb-3 border-b pb-2"
                              :class="getModelStyles(modelName).border"
                            >
                              <h4
                                class="font-bold"
                                :class="getModelStyles(modelName).text"
                              >
                                {{ getModelStyles(modelName).displayName }}
                              </h4>
                              <div class="flex gap-2">
                                <span
                                  class="text-xs px-2 py-0.5 rounded-full border"
                                  :class="getModelStyles(modelName).badge"
                                  title="Max Confidence"
                                >
                                  {{ formatConfidence(result) }}
                                </span>
                                <span
                                  class="text-xs px-2 py-0.5 rounded-full"
                                  :class="getModelStyles(modelName).badge"
                                >
                                  {{ result.global_complexity || 'N/A' }}
                                </span>
                              </div>
                            </div>
                            <div class="space-y-3">
                              <div
                                v-for="intent in result.detected_intents"
                                :key="intent.intent"
                                class="bg-white dark:bg-gray-800 p-3 rounded shadow-sm"
                              >
                                <div class="flex justify-between items-start">
                                  <span class="font-semibold text-gray-900 dark:text-white">{{ intent.intent }}</span>
                                  <span class="text-xs font-mono bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded">{{
                                    Math.round(intent.confidence * 100) }}%</span>
                                </div>
                                <p class="text-xs text-gray-600 dark:text-gray-400 mt-1 italic">
                                  {{ intent.justification }}
                                </p>
                              </div>
                              <div
                                v-if="result.error"
                                class="text-xs text-red-500 dark:text-red-400 italic"
                              >
                                ⚠ Model error: {{ result.error }}
                              </div>
                              <div
                                v-else-if="!result.detected_intents?.length"
                                class="text-xs text-gray-500 italic"
                              >
                                No intents detected.
                                <div v-if="result.classification_reason">
                                  Reason: {{ result.classification_reason }}
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div
                    v-else
                    class="text-center py-12 bg-gray-50 dark:bg-gray-800 rounded-lg border border-dashed border-gray-300 dark:border-gray-700"
                  >
                    <ClockIcon class="mx-auto h-12 w-12 text-gray-400" />
                    <h3 class="mt-2 text-sm font-semibold text-gray-900 dark:text-white">
                      No comparison data
                    </h3>
                    <p class="mt-1 text-sm text-gray-500">
                      Run an adversarial check to compare {{ primaryModel }} with {{ adversarialModel || 'configured model' }}.
                    </p>
                    <div class="mt-6 flex flex-col items-center gap-2">
                      <button
                        type="button"
                        class="inline-flex items-center rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:opacity-50"
                        :disabled="!adversarialModel"
                        @click="runComparison"
                      >
                        <ArrowPathIcon
                          class="-ml-0.5 mr-1.5 h-5 w-5"
                          aria-hidden="true"
                        />
                        Run Comparison
                      </button>
                      <p
                        v-if="!adversarialModel"
                        class="text-xs text-red-500"
                      >
                        Please configure an Adversarial Model in Settings first.
                      </p>
                    </div>
                  </div>
                </div>

                <!-- History Tab -->
                <div
                  v-else-if="activeTab === 'history' && email"
                  class="space-y-6"
                >
                  <h3 class="text-sm font-medium text-gray-900 dark:text-white">
                    Classification History / Historique des corrections
                  </h3>
                  <div class="flow-root">
                    <ul
                      role="list"
                      class="-mb-8"
                    >
                      <li
                        v-for="(entry, idx) in (email.classification_history || []).slice().reverse()"
                        :key="idx"
                      >
                        <div class="relative pb-8">
                          <span
                            v-if="idx !== email.classification_history.length - 1"
                            class="absolute top-4 left-4 -ml-px h-full w-0.5 bg-gray-200 dark:bg-gray-700"
                            aria-hidden="true"
                          />
                          <div class="relative flex space-x-3">
                            <div>
                              <span
                                class="h-8 w-8 rounded-full bg-gray-100 flex items-center justify-center ring-8 ring-white dark:ring-gray-900 dark:bg-gray-800"
                              >
                                <ClockIcon
                                  class="h-5 w-5 text-gray-500"
                                  aria-hidden="true"
                                />
                              </span>
                            </div>
                            <div class="flex min-w-0 flex-1 justify-between space-x-4 pt-1.5">
                              <div>
                                <p class="text-sm text-gray-500 dark:text-gray-400">
                                  Updated by <span class="font-medium text-gray-900 dark:text-white">{{ entry.updated_by
                                  }}</span>
                                </p>
                                <div class="mt-2 text-sm text-gray-700 dark:text-gray-300">
                                  <p v-if="entry.previous_intents?.length">
                                    Previous Intents:
                                    <span
                                      v-for="i in entry.previous_intents"
                                      :key="i.intent"
                                      class="inline-flex items-center rounded-md bg-gray-50 dark:bg-gray-700 px-2 py-1 text-xs font-medium text-gray-600 dark:text-gray-300 ring-1 ring-inset ring-gray-500/10 mr-1"
                                    >
                                      {{ i.intent }}
                                    </span>
                                  </p>
                                  <p
                                    v-else
                                    class="italic text-gray-400"
                                  >
                                    No previous intents
                                  </p>

                                  <div
                                    v-if="entry.correction_reason"
                                    class="mt-2 text-xs border-l-2 border-gray-300 pl-2"
                                  >
                                    <span class="font-semibold">Reason:</span> {{ entry.correction_reason }}
                                  </div>

                                  <div
                                    v-if="entry.llm_feedback"
                                    class="mt-2 text-xs bg-blue-50 dark:bg-blue-900/30 p-2 rounded border border-blue-100 dark:border-blue-800 text-blue-800 dark:text-blue-200"
                                  >
                                    <span class="font-bold">🤖 LLM Insight:</span> {{ entry.llm_feedback }}
                                  </div>
                                </div>
                              </div>
                              <div class="whitespace-nowrap text-right text-sm text-gray-500">
                                <time :datetime="entry.timestamp">{{ new Date(entry.timestamp).toLocaleDateString()
                                }}</time>
                              </div>
                            </div>
                          </div>
                        </div>
                      </li>
                      <li v-if="!email.classification_history?.length">
                        <p class="text-sm text-gray-500 italic">
                          No history available.
                        </p>
                      </li>
                    </ul>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Reprocess Strategy Modal -->
  <Teleport to="body">
    <div
      v-if="reprocessModalOpen"
      class="fixed inset-0 z-[70] flex items-center justify-center bg-black/40"
      @click.self="reprocessModalOpen = false"
    >
      <div class="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <ArrowPathIcon class="h-5 w-5 text-primary-600" />
            {{ t('dashboard.reprocess.title') }}
          </h3>
          <p
            v-if="email?.processing_strategy"
            class="text-xs text-gray-500 dark:text-gray-400 mt-1"
          >
            {{ t('dashboard.reprocess.current') }} {{ t('dashboard.strategy.' + email.processing_strategy) }}
          </p>
        </div>
        <div class="px-6 py-4 space-y-3">
          <p class="text-sm font-medium text-gray-700 dark:text-gray-300">
            {{ t('dashboard.reprocess.select_strategy') }}
          </p>
          <label
            v-for="s in ['standard', 'reasoning', 'vision']"
            :key="s"
            class="flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all"
            :class="reprocessStrategy === s
              ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20 dark:border-primary-400'
              : 'border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-700 hover:border-gray-300 dark:hover:border-gray-600'"
          >
            <input
              v-model="reprocessStrategy"
              type="radio"
              :value="s"
              class="mt-0.5 accent-primary-600"
            >
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span
                  class="text-sm font-medium"
                  :class="reprocessStrategy === s
                    ? 'text-primary-900 dark:text-white'
                    : 'text-gray-900 dark:text-white'"
                >
                  {{ t('dashboard.strategy.' + s) }}
                </span>
                <span
                  v-if="s === 'vision'"
                  class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
                >
                  {{ t('dashboard.strategy.experimental') }}
                </span>
              </div>
              <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                {{ t('dashboard.strategy.' + s + '_desc') }}
              </p>
            </div>
          </label>
          <div
            v-if="reprocessStrategy === 'vision'"
            class="flex items-start gap-2 p-2 rounded-md bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-xs text-amber-800 dark:text-amber-200"
          >
            <ExclamationCircleIcon class="h-4 w-4 flex-shrink-0 mt-0.5" />
            <span>{{ t('dashboard.reprocess.warning_vision') }}</span>
          </div>
        </div>
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
          <button
            class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors"
            @click="reprocessModalOpen = false"
          >
            {{ t('dashboard.reprocess.cancel') }}
          </button>
          <button
            class="px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-lg hover:bg-green-700 transition-colors flex items-center gap-2"
            @click="confirmReprocess"
          >
            <ArrowPathIcon class="h-4 w-4" />
            {{ t('dashboard.reprocess.confirm') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
