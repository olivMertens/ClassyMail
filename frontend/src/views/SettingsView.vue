<script setup>
import { ref, computed, onMounted } from 'vue'
import {
  CheckCircleIcon,
  MoonIcon,
  SunIcon,
  PlusIcon,
  TrashIcon,
  ExclamationTriangleIcon,
  SwatchIcon,
  CpuChipIcon,
  AdjustmentsHorizontalIcon,
  QueueListIcon,
  ArrowPathIcon,
  QuestionMarkCircleIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  CommandLineIcon,
  InformationCircleIcon,
  MagnifyingGlassIcon,
  Cog6ToothIcon
} from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import { useDialog } from '../composables/useDialog'
import { trackException } from '../services/telemetry'
import AppearanceTab from '../components/settings/AppearanceTab.vue'
import GeneralTab from '../components/settings/GeneralTab.vue'
import FinetuningTab from '../components/settings/FinetuningTab.vue'
import DangerZoneTab from '../components/settings/DangerZoneTab.vue'

const { t, locale } = useI18n()
const { confirm, alert: showAlert } = useDialog() // Rename alert because it conflicts with window.alert if not careful, though in setup scope it shadows it.

// Tabs
const activeTab = ref('general')
const showStrategyHelp = ref(false)

// Config Data
const settings = ref({
  processing_strategy: 'standard',
  ai_model: 'phi-4', // Default
  finetune_min_examples: 50,
  ocr_max_attempts: 3,
  ocr_provider: 'mistral',
  categories: [],
  email_preprocessing: {
    enabled: true,
    include_subject: true,
    extract_last_conversation: true,
    detect_pii: false,
    pii_llm_model: 'auto'
  },
  csv_export: {
    unclassified_label: 'unclassified',
    show_model: true,
    show_pii: true,
    show_justification: true,
    show_visual_proofs: true,
    show_quality: true,
    show_time: true,
    show_ocr_provider: true
  },
  ai_assessment_model: 'gpt-4.1-nano',
  data_generation_model: 'gpt-5.2-chat',
  generation_reasoning_effort: 'none',
  agentic: {
    enabled: false,
    orchestrator_model: 'gpt-4.1-nano',
    orchestrator_routing_mode: 'balanced',
    orchestrator_model_subset: [],
    agent_tier1_model: 'gpt-4.1-nano',
    agent_tier2_model: 'gpt-4.1-mini',
    agent_tier3_model: 'gpt-4.1',
    red_team_model: 'gpt-4.1',
    red_team_threshold: 0.7,
    red_team_conflict_delta: 0.15,
    max_parallel_agents: 6,
    retrieval_mode: 'semantic',
    search_top_k: 5,
    reasoning_effort: 'none',
    enabled_indexes: {}
  }
})
const defaults = ref({
  ocr_max_attempts: 3
})
const loading = ref(false)
const saved = ref(false)

// --- Danger zone handled by DangerZoneTab component ---

// ── Token & pricing hypothesis (mirrors MODEL_PRICING in costing.py) ──
// Prices are per 1 K tokens (input, output) — Azure OpenAI / Foundry, 2025
const MODEL_PRICING = {
  'phi-4': { label: 'Phi-4', input: 0.000107, output: 0.00043, quality: 0.82 },
  'gpt-4o': { label: 'GPT-4o', input: 0.0025, output: 0.010, quality: 0.92 },
  'gpt-4o-mini': { label: 'GPT-4o Mini', input: 0.00015, output: 0.0006, quality: 0.84 },
  'gpt-4.1': { label: 'GPT-4.1', input: 0.002, output: 0.008, quality: 0.93 },
  'gpt-4.1-nano': { label: 'GPT-4.1 Nano', input: 0.0001, output: 0.0004, quality: 0.72 },
  'gpt-4.1-mini': { label: 'GPT-4.1 Mini', input: 0.0004, output: 0.0016, quality: 0.85 },
  'gpt-5-nano': { label: 'GPT-5 Nano', input: 0.00005, output: 0.0004, quality: 0.79 },
  'gpt-5-mini': { label: 'GPT-5 Mini', input: 0.0004, output: 0.0016, quality: 0.89 },
  'gpt-5.1': { label: 'GPT-5.1', input: 0.002, output: 0.008, quality: 0.94 },
  'gpt-5.2-chat': { label: 'GPT-5.2 Chat', input: 0.002, output: 0.008, quality: 0.94 },
  'kimi-k2.5': { label: 'Kimi-K2.5', input: 0.0006, output: 0.003, quality: 0.88 },
}

// Case-insensitive pricing lookup
const getModelPricing = (key) => MODEL_PRICING[key] || MODEL_PRICING[key?.toLowerCase()] || MODEL_PRICING[key?.toLowerCase()?.replace(/_/g, '-')]

// Dynamic deployments fetched from Microsoft AI Foundry (populated on mount)
const availableDeployments = ref([])
const deploymentsLoaded = ref(false)
const assessmentEnabled = ref(true)

// Merged model options: model-router first, then real deployments, then MODEL_PRICING keys as fallback
const MODEL_ROUTER_OPTION = { value: 'model-router', label: 'Model Router (Auto)' }
const modelOptions = computed(() => {
  if (availableDeployments.value.length > 0) {
    const opts = availableDeployments.value.map(d => {
      const pricing = getModelPricing(d.id) || getModelPricing(d.model) || Object.values(MODEL_PRICING).find(p => d.id.toLowerCase().startsWith(p.label.toLowerCase().replace(/ /g, '-')))
      return {
        value: d.id,
        label: pricing ? `${pricing.label} (${d.model})` : `${d.id} (${d.model})`,
      }
    }).filter(d => !d.value.includes('embedding') && !d.value.includes('mistral'))
    return [MODEL_ROUTER_OPTION, ...opts]
  }
  // Fallback: use hardcoded MODEL_PRICING keys
  return [MODEL_ROUTER_OPTION, ...Object.entries(MODEL_PRICING).map(([key, m]) => ({
    value: key,
    label: m.label,
  }))]
})

const loadDeployments = async () => {
  try {
    const res = await fetch('/api/admin/deployments')
    if (res.ok) {
      const data = await res.json()
      availableDeployments.value = data.deployments || []
    }
  } catch (e) {
    console.warn('Could not fetch deployments, using defaults:', e.message)
  } finally {
    deploymentsLoaded.value = true
    // Check if assessment model is among available deployments
    if (availableDeployments.value.length > 0) {
      const assessModel = settings.value.ai_assessment_model || 'gpt-4.1-nano'
      assessmentEnabled.value = availableDeployments.value.some(d => d.id === assessModel || d.model === assessModel)
    }
  }
}

// --- Category Management & Sanitization ---

const expandedCategories = ref(new Set())
const newCategory = ref({ name: '', slug: '', description: '', exclusions: '' })
const newCategoryExpanded = ref(false)
const categoryAssessments = ref(new Map()) // Map<categoryIndex, { advice, quality_score, specific_suggestions, loading, progress }>
const assessingCategory = ref(null) // Current category being assessed
const assessProgress = ref(0) // 0-100 progress simulation
let assessProgressTimer = null

// Display name for the assessment model
const assessmentModelLabel = computed(() => {
  const key = settings.value.ai_assessment_model || 'gpt-4.1-nano'
  const pricing = getModelPricing(key)
  return pricing ? pricing.label : key
})

// Toggle per-category AI Search index for agentic RAG
const toggleCategoryIndex = (slug, enabled) => {
  if (!settings.value.agentic.enabled_indexes) {
    settings.value.agentic.enabled_indexes = {}
  }
  settings.value.agentic.enabled_indexes[slug] = enabled
}

// ── AI Search Index Management ──────────────────────────────────────
const showAISearchInfo = ref(false)
const aiSearchIndexes = ref({}) // { slug: { status, doc_count, loading } }
const aiSearchExamples = ref({}) // { slug: { items: [], loading, expanded } }
const newExample = ref({}) // { slug: { content, is_positive, correction_reason } }
const addingExample = ref({}) // { slug: boolean }

const loadAISearchIndexes = async () => {
  try {
    const res = await fetch('/api/admin/ai-search/indexes')
    if (!res.ok) return
    const data = await res.json()
    if (!data.enabled) return
    for (const ix of (data.indexes || [])) {
      aiSearchIndexes.value[ix.slug] = { status: 'exists', doc_count: ix.doc_count, loading: false }
    }
  } catch { /* ignore */ }
}

const ensureCategoryIndex = async (slug) => {
  aiSearchIndexes.value[slug] = { ...(aiSearchIndexes.value[slug] || {}), loading: true }
  try {
    const res = await fetch('/api/admin/ai-search/indexes/ensure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug })
    })
    const data = await res.json()
    aiSearchIndexes.value[slug] = { status: data.status, doc_count: aiSearchIndexes.value[slug]?.doc_count || 0, loading: false }
  } catch (e) {
    aiSearchIndexes.value[slug] = { status: 'error', doc_count: 0, loading: false }
    trackException(e)
  }
}

const toggleExamplesPanel = async (slug) => {
  if (!aiSearchExamples.value[slug]) {
    aiSearchExamples.value[slug] = { items: [], loading: true, expanded: true }
  } else {
    aiSearchExamples.value[slug].expanded = !aiSearchExamples.value[slug].expanded
    if (!aiSearchExamples.value[slug].expanded) return
  }
  await loadExamples(slug)
}

const loadExamples = async (slug) => {
  if (!aiSearchExamples.value[slug]) {
    aiSearchExamples.value[slug] = { items: [], loading: true, expanded: true }
  }
  aiSearchExamples.value[slug].loading = true
  try {
    const res = await fetch(`/api/admin/ai-search/indexes/${encodeURIComponent(slug)}/examples?top=20`)
    if (res.ok) {
      const data = await res.json()
      aiSearchExamples.value[slug].items = data.examples || []
    }
  } catch { /* ignore */ }
  aiSearchExamples.value[slug].loading = false
}

const initNewExample = (slug) => {
  if (!newExample.value[slug]) {
    newExample.value[slug] = { content: '', is_positive: true, correction_reason: '' }
  }
}

const addExample = async (slug) => {
  const ex = newExample.value[slug]
  if (!ex || !ex.content?.trim()) return
  addingExample.value[slug] = true
  try {
    // Auto-ensure index first
    await ensureCategoryIndex(slug)
    const res = await fetch(`/api/admin/ai-search/indexes/${encodeURIComponent(slug)}/examples`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: ex.content.trim(),
        is_positive: ex.is_positive,
        correction_reason: ex.is_positive ? '' : (ex.correction_reason || '').trim(),
        label_source: 'human_verified'
      })
    })
    if (res.ok) {
      newExample.value[slug] = { content: '', is_positive: true, correction_reason: '' }
      await loadExamples(slug)
      // Update doc count
      if (aiSearchIndexes.value[slug]) {
        aiSearchIndexes.value[slug].doc_count = (aiSearchIndexes.value[slug].doc_count || 0) + 1
      }
    }
  } catch (e) {
    trackException(e)
  }
  addingExample.value[slug] = false
}

const deleteExample = async (slug, docId) => {
  try {
    await fetch(`/api/admin/ai-search/indexes/${encodeURIComponent(slug)}/examples/${encodeURIComponent(docId)}`, { method: 'DELETE' })
    await loadExamples(slug)
    if (aiSearchIndexes.value[slug]) {
      aiSearchIndexes.value[slug].doc_count = Math.max(0, (aiSearchIndexes.value[slug].doc_count || 1) - 1)
    }
  } catch (e) {
    trackException(e)
  }
}

// Orchestrator prompt preview (read-only)
const showOrchestratorPrompt = ref(false)
const orchestratorPromptData = ref(null)
const loadingOrchestratorPrompt = ref(false)
const activePromptTab = ref('orchestrator')

const loadOrchestratorPrompt = async () => {
  if (orchestratorPromptData.value) {
    showOrchestratorPrompt.value = !showOrchestratorPrompt.value
    return
  }
  loadingOrchestratorPrompt.value = true
  try {
    const res = await fetch('/api/settings/agentic-prompt')
    if (res.ok) {
      orchestratorPromptData.value = await res.json()
      showOrchestratorPrompt.value = true
    }
  } catch (e) {
    console.warn('Failed to load orchestrator prompt:', e)
  } finally {
    loadingOrchestratorPrompt.value = false
  }
}

// Model advice dialog
const showModelAdvice = ref(false)

// Auto-populate enabled_indexes from categories when agentic is first activated
const ensureIndexToggles = () => {
  if (!settings.value.agentic.enabled_indexes) {
    settings.value.agentic.enabled_indexes = {}
  }
  for (const cat of (settings.value.categories || [])) {
    if (!(cat.slug in settings.value.agentic.enabled_indexes)) {
      settings.value.agentic.enabled_indexes[cat.slug] = true
    }
  }
}

const sanitizeInput = (str, type) => {
  if (!str) return ''
  let cleaned = str
  cleaned = cleaned.replace(/"""/g, '"').replace(/'''/g, "'")
  cleaned = cleaned.trim()

  if (type === 'name') {
    cleaned = cleaned.replace(/[\r\n]+/g, ' ')
    if (cleaned.length > 50) cleaned = cleaned.substring(0, 50)
  } else {
    if (cleaned.length > 2000) cleaned = cleaned.substring(0, 2000)
  }
  return cleaned
}

const toggleExpanded = (index) => {
  if (expandedCategories.value.has(index)) {
    expandedCategories.value.delete(index)
  } else {
    expandedCategories.value.add(index)
  }
}

const updateCategory = (index, field, value) => {
  const cleanValue = sanitizeInput(value, field)
  settings.value.categories[index][field] = cleanValue
}

const addNewCategory = () => {
  const name = sanitizeInput(newCategory.value.name, 'name')
  let slug = sanitizeInput(newCategory.value.slug, 'name')
  const desc = sanitizeInput(newCategory.value.description, 'description')
  const excl = sanitizeInput(newCategory.value.exclusions, 'description')

  // Auto-generate slug if empty
  if (!slug && name) {
    slug = name.toLowerCase().replace(/ /g, '_').replace(/é/g, 'e').replace(/è/g, 'e').replace(/à/g, 'a')
    slug = slug.replace(/[^a-z0-9_]/g, '')
  }

  if (name && slug) {
    if (!settings.value.categories) settings.value.categories = []
    settings.value.categories.push({ name, slug, description: desc, exclusions: excl })
    // Auto-enable AI Search index for new category
    if (settings.value.agentic?.enabled_indexes) {
      settings.value.agentic.enabled_indexes[slug] = true
    }
    newCategory.value = { name: '', slug: '', description: '', exclusions: '' }
    newCategoryExpanded.value = false
    saveSettings()
  }
}

const removeCategory = async (index) => {
  if (await confirm(t('settings.categories.form.remove_confirm'))) {
    const removedSlug = settings.value.categories[index]?.slug
    settings.value.categories.splice(index, 1)
    if (removedSlug) {
      // Remove AI Search index toggle
      if (settings.value.agentic?.enabled_indexes) {
        delete settings.value.agentic.enabled_indexes[removedSlug]
      }
      // Delete the AI Search index in the background
      try {
        await fetch(`/api/admin/ai-search/indexes/${encodeURIComponent(removedSlug)}`, { method: 'DELETE' })
      } catch { /* best-effort */ }
      delete aiSearchIndexes.value[removedSlug]
      delete aiSearchExamples.value[removedSlug]
      delete newExample.value[removedSlug]
    }
    expandedCategories.value.delete(index)
    categoryAssessments.value.delete(index)
    saveSettings()
  }
}

const assessCategory = async (index) => {
  const category = settings.value.categories[index]
  if (!category) return

  assessingCategory.value = index
  assessProgress.value = 0
  categoryAssessments.value.set(index, { loading: true, progress: 0 })

  // Start progress simulation (fast start, slows down toward 90%)
  if (assessProgressTimer) clearInterval(assessProgressTimer)
  assessProgressTimer = setInterval(() => {
    if (assessProgress.value < 90) {
      // Fast at start, decelerating curve
      const remaining = 90 - assessProgress.value
      const step = Math.max(0.5, remaining * 0.08)
      assessProgress.value = Math.min(90, assessProgress.value + step)
      const current = categoryAssessments.value.get(index)
      if (current) current.progress = assessProgress.value
    }
  }, 200)

  try {
    const res = await fetch('/api/admin/assess-category', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: category.name,
        slug: category.slug,
        description: category.description || '',
        exclusions: category.exclusions || '',
        language: locale.value || 'en',
        model: settings.value.ai_assessment_model || 'gpt-4.1-nano'
      })
    })

    if (res.ok) {
      const data = await res.json()
      // Complete the progress bar
      assessProgress.value = 100
      categoryAssessments.value.set(index, {
        loading: false,
        progress: 100,
        advice: data.advice,
        quality_score: data.quality_score,
        specific_suggestions: data.specific_suggestions || [],
        parsed_suggestions: data.parsed_suggestions || []
      })
      // Results now shown inline - no alert dialog
    } else {
      const err = await res.json().catch(() => null)
      const detail = err?.detail || `HTTP ${res.status} – ${res.statusText || 'Unknown error'}`
      console.error('[assess-category] Server error:', res.status, detail)
      categoryAssessments.value.delete(index)
      await showAlert(`Assessment Failed (${res.status}): ${detail}`)
    }
  } catch (e) {
    console.error('[assess-category] Network/client error:', e)
    trackException(e)
    categoryAssessments.value.delete(index)
    await showAlert(`Assessment Error: ${e.message || 'Network error – check console for details'}`)
  } finally {
    if (assessProgressTimer) {
      clearInterval(assessProgressTimer)
      assessProgressTimer = null
    }
    assessingCategory.value = null
  }
}

/**
 * Parse an AI suggestion and apply it to the category's definition or exclusions field.
 * Uses server-parsed structured data (parsed_suggestions) when available for robust
 * multilingual support. Falls back to client-side regex parsing for legacy responses.
 */
const applySuggestion = (catIndex, suggestionIndex) => {
  const cat = settings.value.categories[catIndex]
  if (!cat) return

  const assessment = categoryAssessments.value.get(catIndex)
  if (!assessment) return

  const suggestion = assessment.specific_suggestions?.[suggestionIndex]
  const parsed = assessment.parsed_suggestions?.[suggestionIndex]

  let action, field, content

  if (parsed?.action && parsed?.field && parsed?.content) {
    // Use server-parsed structured data (robust, multilingual)
    action = parsed.action
    field = parsed.field === 'definition' ? 'description' : parsed.field
    content = parsed.content
  } else if (suggestion) {
    // Fallback: client-side parsing (legacy responses without parsed_suggestions)
    const text = suggestion.trim()

    // Detect target field (multilingual: FR, EN, DE, ES, IT)
    const isExclusions = /champ\s*['"]?Exclusions['"]?|'Exclusions'\s*field|Exclusions\s*field|Ausschl[uü]sse|Esclusioni/i.test(text)

    // Detect action: REWRITE (replace) vs ADD (append) - multilingual
    const isAdd = /^(?:AJOUTER|ADD\b|HINZUF[UÜ]GEN|A[NÑ]ADIR|AGGIUNGERE)/i.test(text)

    content = ''
    const parenColonMatch = text.match(/\)\s*:\s*(.+)$/s)
    if (parenColonMatch) {
      content = parenColonMatch[1].trim()
    } else {
      const colonMatch = text.match(/:\s*(.+)$/s)
      if (colonMatch) content = colonMatch[1].trim()
    }

    // Strip leading labels (multilingual)
    content = content
      .replace(/^DEFINITION\s+/i, '')
      .replace(/^DEFINICI[OÓ]N\s+/i, '')
      .replace(/^DEFINIZIONE\s+/i, '')
      .replace(/^EXCLUSIONS?\s*[-–]\s*/i, '')
      .replace(/^AUSSCHL[UÜ]SSE?\s*[-–]\s*/i, '')
      .replace(/^ESCLUSIONI\s*[-–]\s*/i, '')

    action = isAdd ? 'add' : 'rewrite'
    field = isExclusions ? 'exclusions' : 'description'
  } else {
    return
  }

  if (!content) return

  if (action === 'rewrite') {
    cat[field] = content
  } else if (action === 'add') {
    const current = (cat[field] || '').trimEnd()
    cat[field] = current ? current + content : content
  } else {
    cat[field] = content
  }

  // Mark the suggestion as applied in the assessment data
  if (!assessment.appliedSuggestions) assessment.appliedSuggestions = new Set()
  assessment.appliedSuggestions.add(suggestion)
}

const isSuggestionApplied = (catIndex, suggestion) => {
  const assessment = categoryAssessments.value.get(catIndex)
  return assessment?.appliedSuggestions?.has(suggestion) || false
}

// --- API Calls ---



const loadDefaults = async () => {
  try {
    const res = await fetch('/api/settings/defaults')
    if (res.ok) {
      defaults.value = await res.json()
    }
  } catch (e) {
    console.error(e)
    trackException(e)
  }
}

const loadSettings = async () => {
  loading.value = true
  try {
    await loadDefaults()
    const res = await fetch('/api/settings')
    if (res.ok) {
      const data = await res.json()
      settings.value = data
      // Normalize model aliases to canonical deployment names
      const modelAliases = { 'phi4': 'phi-4', 'gpt4o-mini': 'gpt-4o-mini', 'gpt4o_mini': 'gpt-4o-mini' }
      if (settings.value.ai_model && modelAliases[settings.value.ai_model]) {
        settings.value.ai_model = modelAliases[settings.value.ai_model]
      }
      // Enforce default model if missing
      if (!settings.value.ai_model) {
        settings.value.ai_model = 'phi-4'
      }
      // Ensure csv_export defaults
      if (!settings.value.csv_export) {
        settings.value.csv_export = {
          unclassified_label: 'unclassified',
          show_model: true,
          show_pii: true,
          show_justification: true,
          show_visual_proofs: true,
          show_quality: true,
          show_time: true,
          show_ocr_provider: true
        }
      }
    }
  } catch (e) {
    console.error(e)
    trackException(e)
  } finally {
    loading.value = false
  }
}

const saveSettings = async () => {
  loading.value = true
  saved.value = false
  try {
    const payload = {
      processing_strategy: settings.value.processing_strategy,
      ai_model: settings.value.ai_model,
      ai_assessment_model: settings.value.ai_assessment_model,
      data_generation_model: settings.value.data_generation_model,
      generation_reasoning_effort: settings.value.generation_reasoning_effort,
      finetune_min_examples: settings.value.finetune_min_examples ? Number(settings.value.finetune_min_examples) : 50,
      ocr_max_attempts: settings.value.ocr_max_attempts ? Number(settings.value.ocr_max_attempts) : 3,
      ocr_provider: settings.value.ocr_provider || 'mistral',
      categories: settings.value.categories,
      email_preprocessing: settings.value.email_preprocessing,  // FIX: Include email_preprocessing settings
      csv_export: settings.value.csv_export,  // CSV export customization
      agentic: settings.value.agentic,  // Agentic classification config
      default_locale: locale.value || 'en'  // Default language for classification output
    }

    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    if (res.ok) {
      localStorage.setItem('ClassyMail-settings', JSON.stringify(payload))
      saved.value = true

      // Show success dialog for categories tab
      if (activeTab.value === 'classification') {
        await showAlert('✓ Categories Saved Successfully!\n\nChanges are now active and will be used for all future email classifications.')
      }

      setTimeout(() => saved.value = false, 3000)
    } else {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
      await showAlert(`Failed to save settings: ${err.detail || 'Unknown error'}`)
    }
  } catch (e) {
    console.error(e)
    trackException(e)
    await showAlert('Failed to save settings: ' + e.message)
  } finally {
    loading.value = false
  }
}

// --- Danger zone + appearance functions moved to child components ---

onMounted(() => {
  loadSettings()
  loadDeployments()
  loadAISearchIndexes()
})
</script>

<template>
  <div class="w-full space-y-6">
    <div class="md:flex md:items-center md:justify-between">
      <div class="min-w-0 flex-1">
        <h2
          class="text-2xl font-bold leading-7 text-gray-900 dark:text-white sm:truncate sm:text-3xl sm:tracking-tight">
          {{ t('settings.title') }}
        </h2>
      </div>
    </div>

    <!-- Tabs -->
    <div class="border-b border-gray-200 dark:border-gray-700 overflow-x-auto overflow-y-hidden">
      <nav class="-mb-px flex space-x-8" aria-label="Tabs">
        <button
          :class="[activeTab === 'general' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'general'">
          <Cog6ToothIcon class="h-4 w-4" />
          {{ t('settings.tabs.general') }}
        </button>
        <button
          :class="[activeTab === 'classification' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'classification'">
          <QueueListIcon class="h-4 w-4" />
          {{ t('settings.categories.tab_name') }}
        </button>
        <button
          :class="[activeTab === 'processing' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'processing'">
          <CpuChipIcon class="h-4 w-4" />
          {{ t('settings.tabs.processing') }}
        </button>
        <button
          :class="[activeTab === 'finetuning' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'finetuning'">
          <AdjustmentsHorizontalIcon class="h-4 w-4" />
          {{ t('settings.tabs.finetuning') }}
        </button>
        <button
          :class="[activeTab === 'design' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'design'">
          <SwatchIcon class="h-4 w-4" />
          {{ t('settings.appearance') }}
        </button>

        <div class="flex-1"></div>
        <button
          :class="[activeTab === 'danger' ? 'border-red-500 text-red-600 dark:text-red-400' : 'border-transparent text-red-400/60 hover:border-red-300 hover:text-red-500 dark:text-red-500/50 dark:hover:text-red-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'danger'">
          <ExclamationTriangleIcon class="h-4 w-4" />
          {{ t('settings.tabs.danger') }}
        </button>
      </nav>
    </div>

    <!-- Design / Appearance Tab -->
    <div v-show="activeTab === 'design'">
      <AppearanceTab />
    </div>

    <!-- Processing Strategy Tab -->
    <div v-show="activeTab === 'processing'" class="bg-white dark:bg-gray-800 shadow sm:rounded-lg">
      <div class="px-4 py-5 sm:p-6">
        <h3 class="text-lg font-bold text-gray-900 dark:text-white">
          {{ t('settings.processing.title') }}
        </h3>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400 mb-6">
          {{ t('settings.processing.desc') }}
        </p>

        <!-- Section: Processing Strategy (FIRST — determines what's shown below) -->
        <div class="rounded-lg border border-gray-200 dark:border-gray-700 p-5 mb-6 bg-gray-50/50 dark:bg-gray-900/20">
          <h4 class="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2 mb-4">
            <AdjustmentsHorizontalIcon class="h-5 w-5 text-purple-500" />
            {{ t('settings.processing.title') }}
            <button class="text-gray-400 hover:text-primary-500 transition-colors" title="How these strategies work"
              @click="showStrategyHelp = true">
              <QuestionMarkCircleIcon class="h-5 w-5" />
            </button>
          </h4>
          <div class="space-y-4">
            <div class="flex items-center">
              <input id="strategy-standard" v-model="settings.processing_strategy" name="processing_strategy"
                type="radio" value="standard"
                class="h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
              <label for="strategy-standard"
                class="ml-3 block text-sm font-medium leading-6 text-gray-900 dark:text-white">
                {{ t('settings.processing.strategy.standard') }}
              </label>
            </div>
            <div class="flex items-center">
              <input id="strategy-reasoning" v-model="settings.processing_strategy" name="processing_strategy"
                type="radio" value="reasoning"
                class="h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
              <label for="strategy-reasoning"
                class="ml-3 block text-sm font-medium leading-6 text-gray-900 dark:text-white">
                {{ t('settings.processing.strategy.reasoning') }}
              </label>
            </div>
            <div class="flex items-center">
              <input id="strategy-vision" v-model="settings.processing_strategy" name="processing_strategy" type="radio"
                value="vision"
                class="h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
              <label for="strategy-vision"
                class="ml-3 block text-sm font-medium leading-6 text-gray-900 dark:text-white">
                {{ t('settings.processing.strategy.vision') }}
              </label>
            </div>
            <div class="flex items-center">
              <input id="strategy-agentic" v-model="settings.processing_strategy" name="processing_strategy"
                type="radio" value="agentic"
                class="h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
              <label for="strategy-agentic"
                class="ml-3 block text-sm font-medium leading-6 text-gray-900 dark:text-white">
                Agentic (Multi-Agent)
              </label>
            </div>
            <p v-if="settings.processing_strategy === 'agentic'"
              class="mt-2 text-xs text-purple-600 dark:text-purple-400">
              Orchestrator selects top intents, specialized agents classify in parallel, optional Red Team quality gate.
            </p>
          </div>
        </div>

        <!-- Section: AI Model Selection (hidden when Agentic — replaced by orchestrator model) -->
        <div v-if="settings.processing_strategy !== 'agentic'"
          class="rounded-lg border border-gray-200 dark:border-gray-700 p-5 mb-6 bg-gray-50/50 dark:bg-gray-900/20">
          <h4 class="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2 mb-4">
            <CpuChipIcon class="h-5 w-5 text-blue-500" />
            {{ t('settings.processing.model_select') }}
          </h4>
          <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white mb-2">{{
            t('settings.processing.model_select') }}</label>
          <div class="mt-2">
            <select v-model="settings.ai_model"
              class="block w-full max-w-xs rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600">
              <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>
          <div v-if="!['gpt-4o', 'gpt-4o-mini', 'gpt-4.1-nano'].includes(settings.ai_model)"
            class="mt-2 flex items-center gap-2 text-amber-600 dark:text-amber-400 text-sm">
            <ExclamationTriangleIcon class="h-4 w-4" />
            <span>{{ t('settings.processing.finetuning_not_supported') }}</span>
          </div>
          <div v-else class="mt-2 flex items-center gap-2 text-green-600 dark:text-green-400 text-sm">
            <CheckCircleIcon class="h-4 w-4" />
            <span>{{ t('settings.processing.finetuning_available') }}</span>
          </div>

        </div> <!-- End AI Model Section -->

        <!-- Section: Agentic Configuration (visible only when agentic strategy selected) -->
        <div v-if="settings.processing_strategy === 'agentic'"
          class="rounded-lg border border-purple-200 dark:border-purple-700 p-5 mb-6 bg-purple-50/30 dark:bg-purple-900/10"
          @vue:mounted="ensureIndexToggles()">
          <h4 class="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2 mb-4">
            <AdjustmentsHorizontalIcon class="h-5 w-5 text-purple-500" />
            Agentic Pipeline Configuration
            <button @click="showModelAdvice = true"
              class="ml-auto inline-flex items-center gap-1.5 text-[11px] font-medium text-purple-600 dark:text-purple-400 hover:text-purple-800 dark:hover:text-purple-200 border border-purple-300 dark:border-purple-600 rounded-md px-2.5 py-1 hover:bg-purple-50 dark:hover:bg-purple-900/30 transition-colors">
              <QuestionMarkCircleIcon class="h-4 w-4" />
              {{ t('settings.agentic.advice_button') }}
            </button>
          </h4>

          <!-- Agent System Prompts Preview (read-only) -->
          <div class="mb-4">
            <button @click="loadOrchestratorPrompt"
              class="flex items-center gap-2 text-xs font-medium text-purple-600 dark:text-purple-400 hover:text-purple-800 dark:hover:text-purple-200 transition-colors">
              <CommandLineIcon class="h-4 w-4" />
              <span v-if="loadingOrchestratorPrompt">Loading prompts...</span>
              <span v-else>{{ showOrchestratorPrompt ? 'Hide' : 'View' }} Agent System Prompts</span>
              <span
                class="text-[10px] bg-gray-100 dark:bg-gray-800 text-gray-500 px-1.5 py-0.5 rounded">read-only</span>
            </button>
            <div v-if="showOrchestratorPrompt && orchestratorPromptData" class="mt-2">
              <div class="flex items-center gap-3 mb-2 text-[10px] text-gray-500 dark:text-gray-400">
                <span>Model: <code
                    class="bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 px-1 rounded">{{
                      orchestratorPromptData.model }}</code></span>
                <span>Max agents: <strong>{{ orchestratorPromptData.max_agents }}</strong></span>
                <span>Categories: <strong>{{ orchestratorPromptData.categories_count }}</strong></span>
              </div>
              <!-- Prompt Tabs -->
              <div class="flex gap-1 mb-2">
                <button v-for="tab in ['orchestrator', 'specialized', 'red_team']" :key="tab"
                  @click="activePromptTab = tab"
                  class="px-2.5 py-1 text-[10px] font-medium rounded-md transition-colors" :class="activePromptTab === tab
                    ? 'bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300'
                    : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'">
                  {{ tab === 'orchestrator' ? '🎯 Orchestrator' : tab === 'specialized' ? '🔍 Specialized Agent' : '🛡️ Red Team' }}
                </button>
              </div>
              <pre
                class="text-[11px] leading-relaxed text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg p-4 overflow-x-auto max-h-80 overflow-y-auto whitespace-pre-wrap font-mono">
        {{ orchestratorPromptData[activePromptTab]?.prompt || '' }}</pre>
              <p class="mt-1.5 text-[10px] text-gray-400 dark:text-gray-500 italic flex items-center gap-1">
                <span v-if="orchestratorPromptData[activePromptTab]?.source === 'file'" class="text-green-500">📁</span>
                <span v-else class="text-amber-500">⚠️ fallback</span>
                {{ orchestratorPromptData[activePromptTab]?.template_file || '' }}
                <span v-if="activePromptTab === 'orchestrator'">— Categories are injected at runtime from your configured categories.</span>
                <span v-else-if="activePromptTab === 'specialized'">— Template: variables like intent_name,
                  intent_description
                  are resolved per category agent.</span>
                <span v-else>— Red Team receives the agent results and all available intents for review.</span>
              </p>
            </div>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <!-- Orchestrator Model -->
            <div>
              <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Orchestrator Model</label>
              <select v-model="settings.agentic.orchestrator_model"
                class="block w-full rounded-md border-0 py-2 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm dark:bg-gray-700 dark:text-white dark:ring-gray-600">
                <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
              <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">Fast routing model. Phi-4 not recommended here.
              </p>
              <!-- GPT-5 latency disclaimer -->
              <div v-if="settings.agentic.orchestrator_model?.startsWith('gpt-5')"
                class="mt-1.5 flex items-start gap-1.5 text-[11px] text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded p-2">
                <span class="text-sm">⚠️</span>
                <span>{{ t('settings.agentic.gpt5_warning') }}</span>
              </div>
            </div>

            <!-- Routing Mode (model-router only) -->
            <div v-if="settings.agentic.orchestrator_model === 'model-router'">
              <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Routing Mode</label>
              <select v-model="settings.agentic.orchestrator_routing_mode"
                class="block w-full rounded-md border-0 py-2 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm dark:bg-gray-700 dark:text-white dark:ring-gray-600">
                <option value="balanced">Balanced (quality/cost)</option>
                <option value="cost">Cost (max savings)</option>
                <option value="quality">Quality (best model)</option>
              </select>
            </div>

            <!-- Agent Tier 1 -->
            <div>
              <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 flex items-center gap-1">
                Agent Tier 1 (Simple)
                <span class="relative group">
                  <InformationCircleIcon class="h-3.5 w-3.5 text-gray-400 cursor-help" />
                  <span
                    class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 w-56 p-2 text-[10px] bg-gray-900 text-white rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity z-50 pointer-events-none">
                    Orchestrator confidence &gt; 80%. Clear emails — cheap model is enough.
                  </span>
                </span>
              </label>
              <select v-model="settings.agentic.agent_tier1_model"
                class="block w-full rounded-md border-0 py-2 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm dark:bg-gray-700 dark:text-white dark:ring-gray-600">
                <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
            </div>

            <!-- Agent Tier 2 -->
            <div>
              <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 flex items-center gap-1">
                Agent Tier 2 (Ambiguous)
                <span class="relative group">
                  <InformationCircleIcon class="h-3.5 w-3.5 text-gray-400 cursor-help" />
                  <span
                    class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 w-56 p-2 text-[10px] bg-gray-900 text-white rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity z-50 pointer-events-none">
                    Orchestrator confidence 50-80%. Subtle signals — a more capable model resolves ambiguity.
                  </span>
                </span>
              </label>
              <select v-model="settings.agentic.agent_tier2_model"
                class="block w-full rounded-md border-0 py-2 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm dark:bg-gray-700 dark:text-white dark:ring-gray-600">
                <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
            </div>

            <!-- Agent Tier 3 -->
            <div>
              <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 flex items-center gap-1">
                Agent Tier 3 (Critical)
                <span class="relative group">
                  <InformationCircleIcon class="h-3.5 w-3.5 text-gray-400 cursor-help" />
                  <span
                    class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 w-56 p-2 text-[10px] bg-gray-900 text-white rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity z-50 pointer-events-none">
                    Orchestrator confidence &lt; 50%. Complex or business-critical — most robust model for accuracy.
                  </span>
                </span>
              </label>
              <select v-model="settings.agentic.agent_tier3_model"
                class="block w-full rounded-md border-0 py-2 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm dark:bg-gray-700 dark:text-white dark:ring-gray-600">
                <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
            </div>

            <!-- Red Team Model -->
            <div>
              <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Red Team Model</label>
              <select v-model="settings.agentic.red_team_model"
                class="block w-full rounded-md border-0 py-2 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm dark:bg-gray-700 dark:text-white dark:ring-gray-600">
                <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
            </div>

            <!-- Retrieval Mode -->
            <div>
              <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">RAG Retrieval Mode</label>
              <select v-model="settings.agentic.retrieval_mode"
                class="block w-full rounded-md border-0 py-2 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm dark:bg-gray-700 dark:text-white dark:ring-gray-600">
                <option value="vector">Vector (fastest)</option>
                <option value="hybrid">Hybrid (balanced)</option>
                <option value="semantic">Semantic (highest quality)</option>
              </select>
            </div>

            <!-- Max Parallel Agents -->
            <div>
              <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Max Parallel Agents</label>
              <input v-model.number="settings.agentic.max_parallel_agents" type="number" min="1" max="10"
                class="block w-full rounded-md border-0 py-2 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm dark:bg-gray-700 dark:text-white dark:ring-gray-600">
            </div>

            <!-- Red Team Threshold -->
            <div>
              <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                Red Team Threshold: {{ settings.agentic.red_team_threshold }}
              </label>
              <input v-model.number="settings.agentic.red_team_threshold" type="range" min="0" max="1" step="0.05"
                class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700">
              <p class="mt-1 text-xs text-gray-500">Quality gate triggered when max confidence is below this value</p>
            </div>

            <!-- Reasoning Effort (for gpt-5 family) -->
            <div>
              <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1 flex items-center gap-1">
                {{ t('settings.agentic.reasoning_effort_label') }}
                <span class="relative group">
                  <InformationCircleIcon class="h-3.5 w-3.5 text-gray-400 cursor-help" />
                  <span
                    class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 w-56 p-2 text-[10px] bg-gray-900 text-white rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity z-50 pointer-events-none">
                    {{ t('settings.agentic.reasoning_effort_help') }}
                  </span>
                </span>
              </label>
              <select v-model="settings.agentic.reasoning_effort"
                class="block w-full rounded-md border-0 py-2 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm dark:bg-gray-700 dark:text-white dark:ring-gray-600">
                <option value="none">None (no reasoning, fastest)</option>
                <option value="low">Low (light reasoning)</option>
                <option value="medium">Medium (balanced)</option>
                <option value="high">High (deep reasoning, slowest)</option>
              </select>
            </div>
          </div>

          <!-- Per-Category AI Search Index Toggles -->
          <div v-if="settings.categories && settings.categories.length"
            class="mt-5 border-t border-purple-200 dark:border-purple-700 pt-4">
            <h5 class="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1 flex items-center gap-2">
              <MagnifyingGlassIcon class="h-4 w-4 text-purple-500" />
              {{ t('settings.agentic.ai_search.title') }}
              <button @click="showAISearchInfo = true"
                class="ml-1 text-purple-400 hover:text-purple-600 dark:hover:text-purple-300 transition-colors"
                :title="t('settings.agentic.ai_search.info_tooltip')">
                <InformationCircleIcon class="h-4 w-4" />
              </button>
            </h5>
            <p class="text-xs text-gray-500 dark:text-gray-400 mb-3">
              {{ t('settings.agentic.ai_search.desc') }}
            </p>

            <div class="space-y-2">
              <div v-for="cat in settings.categories" :key="cat.slug"
                class="rounded-lg border transition-colors" :class="settings.agentic.enabled_indexes[cat.slug] !== false
                  ? 'border-purple-300 dark:border-purple-600 bg-purple-50/50 dark:bg-purple-900/20'
                  : 'border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 opacity-60'">
                <!-- Category header row -->
                <div class="flex items-start gap-3 p-3">
                  <input :id="'idx-' + cat.slug" type="checkbox"
                    :checked="settings.agentic.enabled_indexes[cat.slug] !== false"
                    @change="toggleCategoryIndex(cat.slug, $event.target.checked)"
                    class="mt-0.5 h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500 dark:bg-gray-700 dark:border-gray-600">
                  <div class="flex-1 min-w-0">
                    <label :for="'idx-' + cat.slug" class="text-xs font-medium text-gray-800 dark:text-gray-200 block">
                      {{ cat.name }}
                    </label>
                    <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5">
                      <code class="text-[10px] text-purple-600 dark:text-purple-400 bg-purple-100 dark:bg-purple-900/40 px-1 rounded">classymail-intent-{{ cat.slug }}</code>
                      <code class="text-[10px] text-indigo-600 dark:text-indigo-400 bg-indigo-100 dark:bg-indigo-900/40 px-1 rounded">search_{{ cat.slug.replaceAll('-', '_') }}()</code>
                      <span v-if="aiSearchIndexes[cat.slug]?.doc_count > 0"
                        class="text-[10px] text-green-600 dark:text-green-400 bg-green-100 dark:bg-green-900/40 px-1.5 rounded font-medium">
                        {{ aiSearchIndexes[cat.slug].doc_count }} {{ t('settings.agentic.ai_search.examples') }}
                      </span>
                      <span v-else-if="aiSearchIndexes[cat.slug]?.status === 'exists'"
                        class="text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-700 px-1.5 rounded">
                        0 {{ t('settings.agentic.ai_search.examples') }}
                      </span>
                    </div>
                  </div>
                  <div class="flex items-center gap-1.5 shrink-0">
                    <!-- Ensure Index button -->
                    <button v-if="!aiSearchIndexes[cat.slug] || aiSearchIndexes[cat.slug]?.status === 'error'"
                      @click="ensureCategoryIndex(cat.slug)"
                      :disabled="aiSearchIndexes[cat.slug]?.loading"
                      class="text-[10px] font-medium text-purple-600 dark:text-purple-400 border border-purple-300 dark:border-purple-600 rounded px-2 py-0.5 hover:bg-purple-50 dark:hover:bg-purple-900/30 transition-colors disabled:opacity-50">
                      <span v-if="aiSearchIndexes[cat.slug]?.loading">{{ t('settings.agentic.ai_search.creating') }}</span>
                      <span v-else>{{ t('settings.agentic.ai_search.create_index') }}</span>
                    </button>
                    <span v-else-if="aiSearchIndexes[cat.slug]?.status === 'exists' || aiSearchIndexes[cat.slug]?.status === 'created'"
                      class="text-[10px] text-green-600 dark:text-green-400">
                      <CheckCircleIcon class="h-3.5 w-3.5 inline" />
                    </span>
                    <!-- Manage Examples toggle -->
                    <button @click="toggleExamplesPanel(cat.slug); initNewExample(cat.slug)"
                      class="text-[10px] font-medium text-indigo-600 dark:text-indigo-400 border border-indigo-300 dark:border-indigo-600 rounded px-2 py-0.5 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 transition-colors">
                      {{ aiSearchExamples[cat.slug]?.expanded ? t('settings.agentic.ai_search.hide') : t('settings.agentic.ai_search.examples') }}
                    </button>
                  </div>
                </div>

                <!-- Manage Examples panel (expandable) -->
                <div v-if="aiSearchExamples[cat.slug]?.expanded"
                  class="border-t border-purple-200 dark:border-purple-700 px-3 pb-3 pt-2 space-y-2">
                  <!-- Loading state -->
                  <div v-if="aiSearchExamples[cat.slug]?.loading" class="text-xs text-gray-400 py-2 text-center">
                    {{ t('settings.agentic.ai_search.loading') }}
                  </div>

                  <!-- Existing examples list -->
                  <div v-if="aiSearchExamples[cat.slug]?.items?.length" class="space-y-1 max-h-48 overflow-y-auto">
                    <div v-for="ex in aiSearchExamples[cat.slug].items" :key="ex.id"
                      class="flex items-start gap-2 p-2 rounded text-[11px]"
                      :class="ex.is_positive
                        ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800'
                        : 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800'">
                      <span :class="ex.is_positive ? 'text-green-600' : 'text-red-600'" class="font-bold shrink-0 mt-0.5">
                        {{ ex.is_positive ? '+' : '-' }}
                      </span>
                      <div class="flex-1 min-w-0">
                        <p class="text-gray-700 dark:text-gray-300 line-clamp-2">{{ ex.content }}</p>
                        <p v-if="ex.correction_reason" class="text-red-500 dark:text-red-400 mt-0.5 italic">
                          {{ t('settings.agentic.ai_search.reason') }}: {{ ex.correction_reason }}
                        </p>
                        <div class="flex items-center gap-2 mt-0.5 text-[10px] text-gray-400">
                          <span>{{ ex.label_source }}</span>
                          <span v-if="ex.created_at">{{ new Date(ex.created_at).toLocaleDateString() }}</span>
                        </div>
                      </div>
                      <button @click="deleteExample(cat.slug, ex.id)"
                        class="text-gray-400 hover:text-red-500 transition-colors shrink-0" title="Remove example">
                        <TrashIcon class="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                  <div v-else-if="!aiSearchExamples[cat.slug]?.loading" class="text-xs text-gray-400 py-1">
                    {{ t('settings.agentic.ai_search.no_examples') }}
                  </div>

                  <!-- Add new example form -->
                  <div v-if="newExample[cat.slug]" class="border-t border-purple-100 dark:border-purple-800 pt-2 space-y-2">
                    <div class="flex items-center gap-3">
                      <label class="flex items-center gap-1.5 text-[11px] cursor-pointer">
                        <input type="radio" :name="'ex-type-' + cat.slug" :value="true"
                          v-model="newExample[cat.slug].is_positive"
                          class="h-3 w-3 text-green-600 focus:ring-green-500">
                        <span class="text-green-700 dark:text-green-400 font-medium">{{ t('settings.agentic.ai_search.good_example') }}</span>
                      </label>
                      <label class="flex items-center gap-1.5 text-[11px] cursor-pointer">
                        <input type="radio" :name="'ex-type-' + cat.slug" :value="false"
                          v-model="newExample[cat.slug].is_positive"
                          class="h-3 w-3 text-red-600 focus:ring-red-500">
                        <span class="text-red-700 dark:text-red-400 font-medium">{{ t('settings.agentic.ai_search.bad_example') }}</span>
                      </label>
                    </div>
                    <textarea v-model="newExample[cat.slug].content"
                      :placeholder="newExample[cat.slug].is_positive
                        ? t('settings.agentic.ai_search.good_placeholder')
                        : t('settings.agentic.ai_search.bad_placeholder')"
                      rows="3"
                      class="w-full text-xs rounded-md border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white focus:ring-purple-500 focus:border-purple-500 resize-y" />
                    <textarea v-if="!newExample[cat.slug].is_positive"
                      v-model="newExample[cat.slug].correction_reason"
                      :placeholder="t('settings.agentic.ai_search.reason_placeholder')"
                      rows="1"
                      class="w-full text-xs rounded-md border-red-300 dark:border-red-600 dark:bg-gray-700 dark:text-white focus:ring-red-500 focus:border-red-500 resize-y" />
                    <button @click="addExample(cat.slug)"
                      :disabled="!newExample[cat.slug]?.content?.trim() || addingExample[cat.slug]"
                      class="inline-flex items-center gap-1 text-[11px] font-medium text-white bg-purple-600 hover:bg-purple-700 rounded px-3 py-1 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                      <PlusIcon class="h-3.5 w-3.5" />
                      {{ addingExample[cat.slug] ? t('settings.agentic.ai_search.adding') : t('settings.agentic.ai_search.add_button') }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- AI Search Info Modal -->
          <Teleport to="body">
            <div v-if="showAISearchInfo" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" @click.self="showAISearchInfo = false">
              <div class="bg-white dark:bg-gray-800 rounded-xl shadow-2xl max-w-lg w-full max-h-[80vh] overflow-y-auto p-6 space-y-4">
                <div class="flex items-center justify-between">
                  <h3 class="text-base font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                    <MagnifyingGlassIcon class="h-5 w-5 text-purple-500" />
                    {{ t('settings.agentic.ai_search.info_title') }}
                  </h3>
                  <button @click="showAISearchInfo = false" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
                    <span class="text-lg">&times;</span>
                  </button>
                </div>

                <div class="text-xs text-gray-600 dark:text-gray-300 space-y-3">
                  <div>
                    <h4 class="font-semibold text-gray-800 dark:text-gray-100 mb-1">{{ t('settings.agentic.ai_search.info_what_title') }}</h4>
                    <p>{{ t('settings.agentic.ai_search.info_what_desc') }}</p>
                  </div>

                  <div>
                    <h4 class="font-semibold text-gray-800 dark:text-gray-100 mb-1">{{ t('settings.agentic.ai_search.info_how_title') }}</h4>
                    <ol class="list-decimal ml-4 space-y-1">
                      <li v-html="t('settings.agentic.ai_search.info_step1')" />
                      <li v-html="t('settings.agentic.ai_search.info_step2')" />
                      <li v-html="t('settings.agentic.ai_search.info_step3')" />
                      <li>{{ t('settings.agentic.ai_search.info_step4') }}</li>
                    </ol>
                  </div>

                  <div>
                    <h4 class="font-semibold text-gray-800 dark:text-gray-100 mb-1">{{ t('settings.agentic.ai_search.info_quality_title') }}</h4>
                    <div class="grid grid-cols-2 gap-2">
                      <div class="bg-green-50 dark:bg-green-900/20 rounded p-2 border border-green-200 dark:border-green-800">
                        <p class="font-medium text-green-700 dark:text-green-400 mb-1">{{ t('settings.agentic.ai_search.info_works_well') }}</p>
                        <ul class="text-green-600 dark:text-green-300 space-y-0.5">
                          <li>{{ t('settings.agentic.ai_search.info_good1') }}</li>
                          <li>{{ t('settings.agentic.ai_search.info_good2') }}</li>
                          <li>{{ t('settings.agentic.ai_search.info_good3') }}</li>
                          <li>{{ t('settings.agentic.ai_search.info_good4') }}</li>
                        </ul>
                      </div>
                      <div class="bg-red-50 dark:bg-red-900/20 rounded p-2 border border-red-200 dark:border-red-800">
                        <p class="font-medium text-red-700 dark:text-red-400 mb-1">{{ t('settings.agentic.ai_search.info_avoid') }}</p>
                        <ul class="text-red-600 dark:text-red-300 space-y-0.5">
                          <li>{{ t('settings.agentic.ai_search.info_bad1') }}</li>
                          <li>{{ t('settings.agentic.ai_search.info_bad2') }}</li>
                          <li>{{ t('settings.agentic.ai_search.info_bad3') }}</li>
                          <li>{{ t('settings.agentic.ai_search.info_bad4') }}</li>
                        </ul>
                      </div>
                    </div>
                  </div>

                  <div>
                    <h4 class="font-semibold text-gray-800 dark:text-gray-100 mb-1">{{ t('settings.agentic.ai_search.info_flow_title') }}</h4>
                    <div class="bg-gray-50 dark:bg-gray-700 rounded p-2 font-mono text-[10px] leading-relaxed">
                      Agent calls search_billing_inquiry("invoice discrepancy")<br/>
                      &rarr; AI Search returns positive + negative examples<br/>
                      &rarr; Agent sees: "POSITIVE: [human_verified] Invoice #INV-4782..."<br/>
                      &rarr; Agent sees: "NEGATIVE: [human_corrected] Password reset... REASON: NOT billing"<br/>
                      &rarr; Agent calibrates confidence based on similarity
                    </div>
                  </div>

                  <div class="bg-purple-50 dark:bg-purple-900/20 rounded p-2 border border-purple-200 dark:border-purple-800">
                    <p class="text-purple-700 dark:text-purple-300">
                      <strong>{{ t('settings.agentic.ai_search.info_tip_label') }}</strong> {{ t('settings.agentic.ai_search.info_tip') }}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </Teleport>
        </div>

        <!-- Section: OCR Configuration -->
        <div class="rounded-lg border border-gray-200 dark:border-gray-700 p-5 mb-6 bg-gray-50/50 dark:bg-gray-900/20">
          <h4 class="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2 mb-3">
            <ArrowPathIcon class="h-5 w-5 text-amber-500" />
            {{ t('settings.processing.ocr_title') }}
          </h4>

          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            {{ t('settings.processing.ocr_provider') }}
          </label>
          <select v-model="settings.ocr_provider"
            class="block w-full max-w-xs rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600">
            <option value="mistral">Mistral Document AI (mistral-document-ai-2512)</option>
            <option value="content_understanding">Azure AI Content Understanding</option>
          </select>
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {{ t('settings.processing.ocr_provider_help') }}
          </p>
          <p v-if="settings.ocr_provider === 'content_understanding' && defaults.content_understanding_configured === false"
            class="mt-1 text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1">
            <ExclamationTriangleIcon class="h-4 w-4 flex-shrink-0" />
            {{ t('settings.processing.ocr_provider_cu_warning') }}
          </p>

          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mt-4 mb-1">
            {{ t('settings.processing.ocr_retries') }}
          </label>
          <input v-model="settings.ocr_max_attempts" type="number" min="1" max="10"
            class="block w-full max-w-xs rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600"
            :placeholder="defaults.ocr_max_attempts ?? 3">
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {{ t('settings.processing.ocr_retries_help') }}
          </p>
        </div>

        <!-- Section: Email Preprocessing -->
        <div class="rounded-lg border border-gray-200 dark:border-gray-700 p-5 bg-gray-50/50 dark:bg-gray-900/20">
          <h4 class="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2 mb-2">
            <InformationCircleIcon class="h-5 w-5 text-green-500" />
            Email Preprocessing
          </h4>
          <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
            Configure intelligent email content extraction using LLM-based preprocessing
          </p>

          <div class="space-y-4">
            <div class="flex items-start">
              <div class="flex items-center h-5">
                <input id="preprocessing-enabled" v-model="settings.email_preprocessing.enabled" type="checkbox"
                  class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
              </div>
              <div class="ml-3 text-sm">
                <label for="preprocessing-enabled" class="font-medium text-gray-700 dark:text-gray-300">
                  Enable Email Preprocessing
                </label>
                <p class="text-gray-500 dark:text-gray-400">
                  Apply intelligent extraction before classification (recommended)
                </p>
              </div>
            </div>

            <div v-if="settings.email_preprocessing.enabled"
              class="ml-7 space-y-3 pl-4 border-l-2 border-gray-200 dark:border-gray-700">
              <div class="flex items-start">
                <div class="flex items-center h-5">
                  <input id="preprocessing-subject" v-model="settings.email_preprocessing.include_subject"
                    type="checkbox"
                    class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
                </div>
                <div class="ml-3 text-sm">
                  <label for="preprocessing-subject" class="font-medium text-gray-700 dark:text-gray-300">
                    Include Email Subject
                  </label>
                  <p class="text-gray-500 dark:text-gray-400">
                    Use subject line as additional context for classification
                  </p>
                </div>
              </div>

              <div class="flex items-start">
                <div class="flex items-center h-5">
                  <input id="preprocessing-conversation"
                    v-model="settings.email_preprocessing.extract_last_conversation" type="checkbox"
                    class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
                </div>
                <div class="ml-3 text-sm">
                  <label for="preprocessing-conversation" class="font-medium text-gray-700 dark:text-gray-300">
                    Extract Last Conversation Only
                  </label>
                  <p class="text-gray-500 dark:text-gray-400">
                    Ignore email history, signatures, and boilerplate (LLM-based)
                  </p>
                </div>
              </div>

              <div class="flex items-start">
                <div class="flex items-center h-5">
                  <input id="preprocessing-pii" v-model="settings.email_preprocessing.detect_pii" type="checkbox"
                    class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
                </div>
                <div class="ml-3 text-sm">
                  <label for="preprocessing-pii" class="font-medium text-gray-700 dark:text-gray-300">
                    Detect Personal Information (PII)
                  </label>
                  <p class="text-gray-500 dark:text-gray-400">
                    Extract names, emails, phones, addresses for GDPR compliance (~€0.002/email)
                  </p>
                </div>
              </div>

              <!-- PII Detection Method Dropdown (shown when PII detection enabled) -->
              <div v-if="settings.email_preprocessing.detect_pii" class="ml-11 mt-3">
                <label for="pii-method" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {{ t('settings.processing.pii_detection_method') }}
                </label>
                <select id="pii-method" v-model="settings.email_preprocessing.pii_detection_method"
                  class="block w-full rounded-md border-gray-300 py-1.5 pl-3 pr-10 text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100">
                  <option value="llm">
                    {{ t('settings.processing.pii_method_llm') }}
                  </option>
                  <option value="azure_language">
                    {{ t('settings.processing.pii_method_azure') }}
                  </option>
                  <option value="both">
                    {{ t('settings.processing.pii_method_both') }}
                  </option>
                </select>
                <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  {{ t('settings.processing.pii_method_description') }}
                </p>
              </div>

              <!-- PII LLM Model Dropdown (shown when PII enabled + LLM or both method) -->
              <div
                v-if="settings.email_preprocessing.detect_pii && (settings.email_preprocessing.pii_detection_method === 'llm' || settings.email_preprocessing.pii_detection_method === 'both')"
                class="ml-11 mt-3">
                <label for="pii-llm-model" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {{ t('settings.processing.pii_llm_model') }}
                </label>
                <select id="pii-llm-model" v-model="settings.email_preprocessing.pii_llm_model"
                  class="block w-full rounded-md border-gray-300 py-1.5 pl-3 pr-10 text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100">
                  <option value="auto">
                    {{ t('settings.processing.pii_llm_model_auto') }}
                  </option>
                  <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">
                    {{ opt.label }}
                  </option>
                </select>
                <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  {{ t('settings.processing.pii_llm_model_description') }}
                </p>
              </div>
            </div>
          </div>
        </div>

        <!-- Section: CSV Export Settings -->
        <div class="rounded-lg border border-gray-200 dark:border-gray-700 p-5 bg-gray-50/50 dark:bg-gray-900/20 mt-6">
          <h4 class="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2 mb-2">
            <InformationCircleIcon class="h-5 w-5 text-blue-500" />
            CSV Export
          </h4>
          <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
            Configurer le contenu de l'export CSV et le traitement des emails non classifiés
          </p>

          <div class="space-y-4">
            <!-- Unclassified label -->
            <div>
              <label for="unclassified-label" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Libellé pour les emails non classifiés
              </label>
              <input id="unclassified-label" v-model="settings.csv_export.unclassified_label" type="text"
                class="block w-full max-w-xs rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600"
                placeholder="autre">
              <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Valeur affichée dans la colonne INTENTIONS quand aucune catégorie ne correspond (défaut: "autre")
              </p>
            </div>

            <!-- CSV columns toggles -->
            <div class="border-t border-gray-200 dark:border-gray-700 pt-4">
              <p class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
                Colonnes incluses dans l'export enrichi
              </p>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div class="flex items-center">
                  <input id="export-quality" v-model="settings.csv_export.show_quality" type="checkbox"
                    class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
                  <label for="export-quality" class="ml-2 text-sm text-gray-700 dark:text-gray-300">QUALITE</label>
                </div>
                <div class="flex items-center">
                  <input id="export-model" v-model="settings.csv_export.show_model" type="checkbox"
                    class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
                  <label for="export-model" class="ml-2 text-sm text-gray-700 dark:text-gray-300">MODELE</label>
                </div>
                <div class="flex items-center">
                  <input id="export-justification" v-model="settings.csv_export.show_justification" type="checkbox"
                    class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
                  <label for="export-justification"
                    class="ml-2 text-sm text-gray-700 dark:text-gray-300">JUSTIFICATION</label>
                </div>
                <div class="flex items-center">
                  <input id="export-visual-proofs" v-model="settings.csv_export.show_visual_proofs" type="checkbox"
                    class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
                  <label for="export-visual-proofs"
                    class="ml-2 text-sm text-gray-700 dark:text-gray-300">PREUVES_VISUELLES</label>
                </div>
                <div class="flex items-center">
                  <input id="export-time" v-model="settings.csv_export.show_time" type="checkbox"
                    class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
                  <label for="export-time" class="ml-2 text-sm text-gray-700 dark:text-gray-300">TEMPS_S</label>
                </div>
                <div class="flex items-center">
                  <input id="export-pii" v-model="settings.csv_export.show_pii" type="checkbox"
                    class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
                  <label for="export-pii" class="ml-2 text-sm text-gray-700 dark:text-gray-300">PII_DETECTE +
                    PII_TYPES</label>
                </div>
                <div class="flex items-center">
                  <input id="export-ocr-provider" v-model="settings.csv_export.show_ocr_provider" type="checkbox"
                    class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
                  <label for="export-ocr-provider"
                    class="ml-2 text-sm text-gray-700 dark:text-gray-300">SOURCE_OCR</label>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="mt-6 border-t border-gray-200 dark:border-gray-700 pt-6 flex items-center gap-4">
          <button type="button" :disabled="loading"
            class="rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600 disabled:opacity-50"
            @click="saveSettings">
            {{ loading ? t('settings.saving') : t('settings.save') }}
          </button>
          <transition enter-active-class="transition ease-out duration-200" enter-from-class="opacity-0 translate-y-1"
            enter-to-class="opacity-100 translate-y-0" leave-active-class="transition ease-in duration-150"
            leave-from-class="opacity-100 translate-y-0" leave-to-class="opacity-0 translate-y-1">
            <div v-if="saved" class="flex items-center text-green-600 dark:text-green-400 text-sm font-medium">
              <CheckCircleIcon class="h-5 w-5 mr-1" />
              {{ t('settings.saved') }}
            </div>
          </transition>
        </div>
      </div>
    </div>

    <!-- General Tab -->
    <div v-show="activeTab === 'general'">
      <GeneralTab v-model:settings="settings" :model-options="modelOptions" :loading="loading" :saved="saved" @save="saveSettings" />
    </div>

    <!-- Fine-tuning Tab -->
    <div v-show="activeTab === 'finetuning'">
      <FinetuningTab v-model:settings="settings" :loading="loading" />
    </div>

    <!-- Classification Categories Tab -->
    <div v-show="activeTab === 'classification'" class="bg-white dark:bg-gray-800 shadow sm:rounded-lg">
      <div class="px-4 py-5 sm:p-6">
        <!-- Warning Banner -->
        <div
          class="rounded-md bg-amber-50 dark:bg-amber-900/30 p-4 mb-6 border-l-4 border-amber-400 dark:border-amber-500">
          <div class="flex">
            <div class="flex-shrink-0">
              <ExclamationTriangleIcon class="h-5 w-5 text-amber-400 dark:text-amber-500" aria-hidden="true" />
            </div>
            <div class="ml-3">
              <h3 class="text-sm font-medium text-amber-800 dark:text-amber-200">
                {{ t('settings.categories.warning_title') }}
              </h3>
              <div class="mt-2 text-sm text-amber-700 dark:text-amber-300">
                <p>
                  {{ t('settings.categories.warning_text') }}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div class="flex justify-between items-center mb-6">
          <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
            {{ t('settings.categories.managed_title') }}
          </h3>
          <div class="flex items-center gap-4">
            <!-- Save Button -->
            <button type="button" :disabled="loading"
              class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              @click="saveSettings">
              <CheckCircleIcon v-if="!loading" class="-ml-0.5 mr-1.5 h-5 w-5" aria-hidden="true" />
              <ArrowPathIcon v-else class="-ml-0.5 mr-1.5 h-5 w-5 animate-spin" aria-hidden="true" />
              {{ loading ? t('settings.saving') : t('settings.categories.save_button') }}
            </button>
          </div>
        </div>

        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
          {{ t('settings.categories.current_categories') }}
        </p>

        <div class="mt-5">
          <div class="flow-root">
            <ul role="list" class="-my-5">
              <li v-for="(cat, idx) in settings.categories" :key="idx"
                class="py-4 border-b border-gray-200 dark:border-gray-700 last:border-0">
                <!-- Accordion Header -->
                <div
                  class="flex items-center justify-between cursor-pointer group hover:bg-gray-50 dark:hover:bg-gray-700/50 rounded-md p-2 -mx-2 transition-colors"
                  @click="toggleExpanded(idx)">
                  <div class="min-w-0 flex-1 flex items-center gap-3">
                    <button type="button" class="text-gray-400 group-hover:text-primary-500 transition-colors">
                      <component :is="expandedCategories.has(idx) ? ChevronUpIcon : ChevronDownIcon" class="h-5 w-5" />
                    </button>
                    <div>
                      <p class="text-sm font-bold text-gray-900 dark:text-white">
                        {{ cat.name }}
                      </p>
                      <p v-if="!expandedCategories.has(idx)"
                        class="text-xs text-gray-500 dark:text-gray-400 truncate max-w-md">
                        {{ cat.description }}
                      </p>
                    </div>
                  </div>
                  <div class="flex items-center gap-2">
                    <button type="button"
                      class="inline-flex rounded-md p-1.5 text-gray-400 hover:text-red-500 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                      title="Remove" @click.stop="removeCategory(idx)">
                      <TrashIcon class="h-5 w-5" />
                    </button>
                  </div>
                </div>

                <div v-if="expandedCategories.has(idx)" class="mt-3 pl-8 pr-2 pb-2">
                  <div
                    class="bg-gray-50 dark:bg-gray-700/30 p-4 rounded-md border border-gray-200 dark:border-gray-600">
                    <div class="grid grid-cols-1 gap-4">
                      <div class="grid grid-cols-2 gap-3">
                        <div>
                          <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">{{
                            t('settings.categories.form.name_label') }}</label>
                          <input v-model="cat.name" type="text"
                            class="block w-full rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600"
                            @change="updateCategory(idx, 'name', cat.name)">
                        </div>
                        <div>
                          <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">{{
                            t('settings.categories.form.slug_label') }}</label>
                          <input v-model="cat.slug" type="text" pattern="[a-z0-9_]+"
                            class="block w-full rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600 font-mono"
                            @change="updateCategory(idx, 'slug', cat.slug)">
                        </div>
                      </div>
                      <div>
                        <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                          {{ t('settings.categories.form.definition_label') }} - {{ cat.description?.length || 0 }}/2000
                        </label>
                        <textarea v-model="cat.description" rows="2" maxlength="2000"
                          :placeholder="t('settings.categories.form.definition_placeholder')"
                          class="block w-full rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600 font-mono text-xs"
                          @change="updateCategory(idx, 'description', cat.description)" />
                      </div>
                      <div>
                        <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                          {{ t('settings.categories.form.exclusions_label') }} - {{ cat.exclusions?.length || 0 }}/2000
                        </label>
                        <textarea v-model="cat.exclusions" rows="2" maxlength="2000"
                          :placeholder="t('settings.categories.form.exclusions_placeholder')"
                          class="block w-full rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600 font-mono text-xs"
                          @change="updateCategory(idx, 'exclusions', cat.exclusions)" />
                      </div>

                      <!-- AI Assessment Button + Progress -->
                      <div class="flex flex-col gap-2 pt-2 border-t border-gray-200 dark:border-gray-600">
                        <div class="flex justify-between items-center">
                          <button type="button" :disabled="assessingCategory === idx || !assessmentEnabled"
                            :title="!assessmentEnabled ? 'Assessment model not deployed in AI Foundry. Deploy the model selected in AI Assessment settings.' : ''"
                            class="inline-flex items-center rounded-md bg-indigo-600 px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                            @click="assessCategory(idx)">
                            <CpuChipIcon v-if="assessingCategory !== idx" class="-ml-0.5 mr-1.5 h-4 w-4"
                              aria-hidden="true" />
                            <ArrowPathIcon v-else class="-ml-0.5 mr-1.5 h-4 w-4 animate-spin" aria-hidden="true" />
                            {{ assessingCategory === idx ? t('settings.categories.assessment.analyzing') :
                              t('settings.categories.assessment.button', { model: assessmentModelLabel }) }}
                          </button>
                          <span class="text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1 italic">
                            <ExclamationTriangleIcon class="h-3 w-3" />
                            {{ t('settings.categories.form.local_changes_warning') }}
                          </span>
                        </div>
                        <!-- Progress bar (visible during assessment) -->
                        <div v-if="assessingCategory === idx" class="w-full">
                          <div class="flex justify-between items-center mb-1">
                            <span class="text-xs text-gray-500 dark:text-gray-400">
                              {{ t('settings.categories.assessment.progress') }}
                            </span>
                            <span class="text-xs font-mono text-red-500 dark:text-red-400">
                              {{ Math.round(categoryAssessments.get(idx)?.progress || 0) }}%
                            </span>
                          </div>
                          <div class="w-full bg-gray-200 rounded-full h-2 dark:bg-gray-700 overflow-hidden">
                            <div class="bg-red-500 h-2 rounded-full transition-all duration-300 ease-out"
                              :style="{ width: (categoryAssessments.get(idx)?.progress || 0) + '%' }" />
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- AI Assessment Results -->
                    <div v-if="categoryAssessments.get(idx) && !categoryAssessments.get(idx).loading"
                      class="mt-4 rounded-md border-2 transition-all" :class="[
                        categoryAssessments.get(idx).quality_score === 'Good' ? 'border-green-400 bg-green-50/30 dark:bg-green-900/10' : '',
                        categoryAssessments.get(idx).quality_score === 'Needs Improvement' ? 'border-amber-400 bg-amber-50/30 dark:bg-amber-900/10' : '',
                        categoryAssessments.get(idx).quality_score === 'Poor' ? 'border-red-400 bg-red-50/30 dark:bg-red-900/10' : '',
                        !['Good', 'Needs Improvement', 'Poor'].includes(categoryAssessments.get(idx).quality_score) ? 'border-blue-400 bg-blue-50/30 dark:bg-blue-900/10' : ''
                      ]">
                      <div class="p-4">
                        <div class="flex items-start gap-3">
                          <div class="flex-shrink-0">
                            <CheckCircleIcon v-if="categoryAssessments.get(idx).quality_score === 'Good'"
                              class="h-6 w-6 text-green-600 dark:text-green-400" />
                            <ExclamationTriangleIcon
                              v-else-if="categoryAssessments.get(idx).quality_score === 'Needs Improvement'"
                              class="h-6 w-6 text-amber-600 dark:text-amber-400" />
                            <ExclamationTriangleIcon v-else-if="categoryAssessments.get(idx).quality_score === 'Poor'"
                              class="h-6 w-6 text-red-600 dark:text-red-400" />
                            <InformationCircleIcon v-else class="h-6 w-6 text-blue-600 dark:text-blue-400" />
                          </div>
                          <div class="flex-1">
                            <h4 class="text-sm font-bold mb-1" :class="[
                              categoryAssessments.get(idx).quality_score === 'Good' ? 'text-green-800 dark:text-green-300' : '',
                              categoryAssessments.get(idx).quality_score === 'Needs Improvement' ? 'text-amber-800 dark:text-amber-300' : '',
                              categoryAssessments.get(idx).quality_score === 'Poor' ? 'text-red-800 dark:text-red-300' : '',
                              !['Good', 'Needs Improvement', 'Poor'].includes(categoryAssessments.get(idx).quality_score) ? 'text-blue-800 dark:text-blue-300' : ''
                            ]">
                              {{ t('settings.categories.assessment.title') }}: {{
                                categoryAssessments.get(idx).quality_score }}
                            </h4>
                            <div class="text-xs space-y-2" :class="[
                              categoryAssessments.get(idx).quality_score === 'Good' ? 'text-green-700 dark:text-green-200' : '',
                              categoryAssessments.get(idx).quality_score === 'Needs Improvement' ? 'text-amber-700 dark:text-amber-200' : '',
                              categoryAssessments.get(idx).quality_score === 'Poor' ? 'text-red-700 dark:text-red-200' : '',
                              !['Good', 'Needs Improvement', 'Poor'].includes(categoryAssessments.get(idx).quality_score) ? 'text-blue-700 dark:text-blue-200' : ''
                            ]">
                              <p class="whitespace-pre-wrap">
                                {{ categoryAssessments.get(idx).advice }}
                              </p>

                              <div v-if="categoryAssessments.get(idx).specific_suggestions?.length"
                                class="mt-3 pt-3 border-t" :class="[
                                  categoryAssessments.get(idx).quality_score === 'Good' ? 'border-green-300 dark:border-green-700' : '',
                                  categoryAssessments.get(idx).quality_score === 'Needs Improvement' ? 'border-amber-300 dark:border-amber-700' : '',
                                  categoryAssessments.get(idx).quality_score === 'Poor' ? 'border-red-300 dark:border-red-700' : '',
                                  !['Good', 'Needs Improvement', 'Poor'].includes(categoryAssessments.get(idx).quality_score) ? 'border-blue-300 dark:border-blue-700' : ''
                                ]">
                                <p class="font-semibold mb- 1">
                                  {{ t('settings.categories.assessment.suggestions') }}
                                </p>
                                <ul class="list-none space-y-2 ml-0">
                                  <li v-for="(suggestion, sidx) in categoryAssessments.get(idx).specific_suggestions"
                                    :key="sidx" class="flex items-start gap-2">
                                    <div class="flex-1 text-xs">
                                      <span class="inline-block align-top">{{ suggestion }}</span>
                                    </div>
                                    <button type="button"
                                      class="flex-shrink-0 inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-all"
                                      :class="isSuggestionApplied(idx, suggestion)
                                        ? 'bg-green-600 text-white cursor-default'
                                        : 'bg-purple-600 text-white hover:bg-purple-500 cursor-pointer'"
                                      :disabled="isSuggestionApplied(idx, suggestion)"
                                      @click="applySuggestion(idx, sidx)">
                                      <CheckCircleIcon v-if="isSuggestionApplied(idx, suggestion)"
                                        class="h-3.5 w-3.5" />
                                      {{ isSuggestionApplied(idx, suggestion)
                                        ? t('settings.categories.assessment.applied')
                                        : t('settings.categories.assessment.apply') }}
                                    </button>
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
              </li>

              <li v-if="!settings.categories?.length" class="py-8 text-center text-sm text-gray-500 italic">
                No categories defined.
              </li>
            </ul>
          </div>

          <!-- Add New Category (Collapsible) -->
          <div class="mt-8 border-t border-gray-200 dark:border-gray-700 pt-6">
            <button type="button"
              class="flex items-center gap-2 text-primary-600 hover:text-primary-700 font-medium text-sm w-full"
              @click="newCategoryExpanded = !newCategoryExpanded">
              <component :is="newCategoryExpanded ? ChevronUpIcon : PlusIcon" class="h-5 w-5" />
              {{ newCategoryExpanded ? t('settings.categories.form.cancel_adding') :
                t('settings.categories.form.add_new_category') }}
            </button>

            <div v-if="newCategoryExpanded"
              class="mt-4 bg-gray-50 dark:bg-gray-700/30 p-4 rounded-md border border-gray-200 dark:border-gray-700 transition-all">
              <div class="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-6">
                <div class="sm:col-span-3">
                  <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white mb-2">{{
                    t('settings.categories.form.name_label') }}</label>
                  <div class="mt-1">
                    <input v-model="newCategory.name" type="text"
                      class="block w-full rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600"
                      placeholder="e.g. Contract Cancellation">
                  </div>
                </div>
                <div class="sm:col-span-3">
                  <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white mb-2">{{
                    t('settings.categories.form.slug_label') }}</label>
                  <div class="mt-1">
                    <input v-model="newCategory.slug" type="text" pattern="[a-z0-9_]+"
                      class="block w-full rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600 font-mono"
                      placeholder="e.g. contract_cancellation">
                  </div>
                  <p class="mt-1 text-xs text-gray-500">
                    {{ t('settings.categories.form.slug_help') }}
                  </p>
                </div>
                <div class="sm:col-span-6">
                  <div class="flex justify-between">
                    <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white mb-2">{{
                      t('settings.categories.form.definition_label') }}</label>
                    <span class="text-xs text-gray-500">{{ newCategory.description?.length || 0 }}/2000</span>
                  </div>
                  <div class="mt-1">
                    <textarea v-model="newCategory.description" rows="2" maxlength="2000"
                      class="block w-full rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600 font-mono text-xs"
                      :placeholder="t('settings.categories.form.definition_placeholder')" />
                  </div>
                </div>
                <div class="sm:col-span-6">
                  <div class="flex justify-between">
                    <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white mb-2">{{
                      t('settings.categories.form.exclusions_label') }}</label>
                    <span class="text-xs text-gray-500">{{ newCategory.exclusions?.length || 0 }}/2000</span>
                  </div>
                  <div class="mt-1">
                    <textarea v-model="newCategory.exclusions" rows="2" maxlength="2000"
                      class="block w-full rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600 font-mono text-xs"
                      :placeholder="t('settings.categories.form.exclusions_placeholder')" />
                  </div>
                </div>
              </div>
              <div class="mt-4 flex justify-end gap-2">
                <button type="button"
                  class="inline-flex items-center rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
                  @click="addNewCategory">
                  <PlusIcon class="h-5 w-5 mr-1" />
                  {{ t('settings.categories.form.add_button') }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>



    <!-- Danger Zone Tab -->
    <div v-show="activeTab === 'danger'">
      <DangerZoneTab :settings="settings" :loading="loading" @save="saveSettings" />
    </div>

    <!-- Strategy Help Modal -->
    <div v-if="showStrategyHelp" class="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog"
      aria-modal="true">
      <div class="flex items-end justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
        <div class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" aria-hidden="true"
          @click="showStrategyHelp = false" />
        <span class="hidden sm:inline-block sm:align-middle sm:h-screen" aria-hidden="true">&#8203;</span>
        <div
          class="inline-block align-bottom bg-white dark:bg-gray-800 rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-2xl sm:w-full border border-gray-200 dark:border-gray-700">
          <div class="bg-white dark:bg-gray-800 px-4 pt-5 pb-4 sm:p-6 sm:pb-4">
            <h3 id="modal-title" class="text-lg leading-6 font-medium text-gray-900 dark:text-white mb-4">
              Processing Strategies Explained
            </h3>
            <div class="space-y-6 text-sm">
              <!-- Standard -->
              <div class="border-l-4 border-indigo-500 pl-4">
                <h4 class="font-bold text-gray-900 dark:text-white text-base">
                  Standard (Default)
                </h4>
                <p class="text-gray-500 dark:text-gray-400 mt-1">
                  Fast and optimized for standard text extraction. Uses zero-shot prompting optimized for cost.
                </p>
                <div
                  class="mt-2 bg-gray-50 dark:bg-gray-900 p-3 rounded text-gray-800 dark:text-gray-300 font-mono text-xs">
                  <span class="text-indigo-600 dark:text-indigo-400 font-bold">How it works:</span> Passes OCR text
                  directly to the model.<br>
                  <span class="text-indigo-600 dark:text-indigo-400 font-bold">Example:</span> A clearly typed PDF
                  claiming an "Address Change". The model identifies keywords and classifies instantly.
                </div>
              </div>

              <!-- Reasoning -->
              <div class="border-l-4 border-purple-500 pl-4">
                <h4 class="font-bold text-gray-900 dark:text-white text-base">
                  Reasoning (CoT)
                </h4>
                <p class="text-gray-500 dark:text-gray-400 mt-1">
                  Forces a "Chain-of-Thought" (Step-by-step) analysis. Essential for subtle intents or complex
                  narratives.
                </p>
                <div
                  class="mt-2 bg-gray-50 dark:bg-gray-900 p-3 rounded text-gray-800 dark:text-gray-300 font-mono text-xs">
                  <span class="text-purple-600 dark:text-purple-400 font-bold">How it works:</span> Injects system
                  instruction: <em>"Analyze context first, then deduce intents step-by-step."</em><br>
                  <span class="text-purple-600 dark:text-purple-400 font-bold">Example:</span> An email telling a story
                  about a storm without explicitly saying "claim". The model deduces "Bad Weather" -> "Damage" -> "Claim
                  Intent".
                </div>
              </div>

              <!-- Vision -->
              <div class="border-l-4 border-green-500 pl-4">
                <h4 class="font-bold text-gray-900 dark:text-white text-base">
                  Vision (Visual Analysis)
                </h4>
                <p class="text-gray-500 dark:text-gray-400 mt-1">
                  Integrates visual context (photos, diagrams, signatures) into the decision process using Mistral's
                  advanced BBox capabilities.<br>
                  <strong>⚠️ Limit:</strong> Image annotations are limited to <strong>8 pages</strong> per document.
                  For images beyond this limit, GPT-4o-mini provides fallback descriptions.<br>
                  <strong>Mechanism (3-Layer Analysis):</strong>
                </p>
                <div
                  class="mt-2 bg-gray-50 dark:bg-gray-900 p-3 rounded text-gray-800 dark:text-gray-300 font-mono text-xs">
                  <ul class="list-disc list-inside space-y-1">
                    <li>
                      <span class="text-green-600 dark:text-green-400 font-bold">1. Text:</span> Standard Markdown
                      extraction.
                    </li>
                    <li>
                      <span class="text-green-600 dark:text-green-400 font-bold">2. BBox Layout:</span> Spatial
                      normalization of elements (bounding boxes) to understand document structure.
                    </li>
                    <li>
                      <span class="text-green-600 dark:text-green-400 font-bold">3. Visual Enrichment:</span>
                      Generates descriptive "Alt-Text" for images/charts using the Vision model, allowing the LLM to
                      "read" non-text elements.
                    </li>
                  </ul>
                </div>
              </div>

              <!-- Broad Net Strategy -->
              <div class="border-l-4 border-amber-500 pl-4">
                <h4 class="font-bold text-gray-900 dark:text-white text-base">
                  "Broad Net" Entity Extraction
                </h4>
                <p class="text-gray-500 dark:text-gray-400 mt-1">
                  Applied automatically before Classification. We cast a "Broad Net" to extract structured facts (Names,
                  Dates, Amounts, IDs) first.
                </p>
                <div
                  class="mt-2 bg-gray-50 dark:bg-gray-900 p-3 rounded text-gray-800 dark:text-gray-300 font-mono text-xs">
                  <span class="text-amber-600 dark:text-amber-400 font-bold">Why?</span> Small Language Models (SLMs)
                  like Phi-4 perform better when facts are pre-extracted.<br>
                  <span class="text-amber-600 dark:text-amber-400 font-bold">How it aids capability:</span> By
                  presenting the model with <em class="text-gray-600 dark:text-gray-400">"Here are the facts
                    involved"</em> alongside the <em class="text-gray-600 dark:text-gray-400">"Category
                    Descriptions"</em>, we ensure the best possible understanding foundation. The model focuses on
                  <strong>matching intent</strong> rather than searching for data.
                </div>
              </div>
            </div>
          </div>
          <div class="bg-gray-50 dark:bg-gray-700 px-4 py-3 sm:px-6 sm:flex sm:flex-row-reverse">
            <button type="button"
              class="w-full inline-flex justify-center rounded-md border border-transparent shadow-sm px-4 py-2 bg-primary-600 text-base font-medium text-white hover:bg-primary-700 focus:outline-none sm:ml-3 sm:w-auto sm:text-sm"
              @click="showStrategyHelp = false">
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Model Advice Dialog -->
  <Teleport to="body">
    <div v-if="showModelAdvice" class="fixed inset-0 z-50 overflow-y-auto" @click.self="showModelAdvice = false">
      <div class="flex items-center justify-center min-h-screen p-4">
        <div class="fixed inset-0 bg-gray-900/75 transition-opacity" @click="showModelAdvice = false" />
        <div class="relative bg-white dark:bg-gray-800 rounded-xl shadow-2xl max-w-3xl w-full mx-auto overflow-hidden">
          <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <QuestionMarkCircleIcon class="h-5 w-5 text-purple-500" />
              {{ t('settings.agentic.advice_title') }}
            </h3>
            <button @click="showModelAdvice = false" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
              <span class="text-xl">&times;</span>
            </button>
          </div>
          <div class="px-6 py-5 max-h-[75vh] overflow-y-auto space-y-5">
            <!-- Orchestrator -->
            <div class="rounded-lg border-2 border-blue-200 dark:border-blue-800 p-4 bg-blue-50/50 dark:bg-blue-900/10">
              <h4 class="text-sm font-semibold text-blue-800 dark:text-blue-300 mb-2">🎯 {{
                t('settings.agentic.advice_orchestrator') }}</h4>
              <p class="text-xs text-gray-600 dark:text-gray-300 mb-2">{{ t('settings.agentic.advice_orchestrator_desc')
              }}</p>
              <div class="grid grid-cols-2 gap-2 text-[11px]">
                <div class="bg-white dark:bg-gray-900 rounded p-2 border border-blue-100 dark:border-blue-900">
                  <strong class="text-green-600">✓ gpt-4.1-nano</strong>
                  <p class="text-gray-500 mt-0.5">{{ t('settings.agentic.advice_orch_nano') }}</p>
                </div>
                <div class="bg-white dark:bg-gray-900 rounded p-2 border border-blue-100 dark:border-blue-900">
                  <strong class="text-blue-600">✓ model-router</strong>
                  <p class="text-gray-500 mt-0.5">{{ t('settings.agentic.advice_orch_router') }}</p>
                </div>
                <div class="bg-white dark:bg-gray-900 rounded p-2 border border-blue-100 dark:border-blue-900">
                  <strong class="text-gray-500">○ gpt-4.1-mini</strong>
                  <p class="text-gray-500 mt-0.5">{{ t('settings.agentic.advice_orch_mini') }}</p>
                </div>
                <div class="bg-white dark:bg-gray-900 rounded p-2 border border-blue-100 dark:border-blue-900">
                  <strong class="text-green-600">✓ gpt-5-nano</strong>
                  <p class="text-gray-500 mt-0.5">{{ t('settings.agentic.advice_orch_reasoning') }}</p>
                </div>
              </div>
            </div>

            <!-- Agent Tiers -->
            <div
              class="rounded-lg border-2 border-purple-200 dark:border-purple-800 p-4 bg-purple-50/50 dark:bg-purple-900/10">
              <h4 class="text-sm font-semibold text-purple-800 dark:text-purple-300 mb-2">🔍 {{
                t('settings.agentic.advice_agents') }}</h4>
              <p class="text-xs text-gray-600 dark:text-gray-300 mb-2">{{ t('settings.agentic.advice_agents_desc') }}
              </p>
              <div class="space-y-2 text-[11px]">
                <div
                  class="flex items-center gap-3 bg-white dark:bg-gray-900 rounded p-2 border border-green-200 dark:border-green-900">
                  <span
                    class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-green-500 text-white text-[10px] font-bold">1</span>
                  <div class="flex-1">
                    <strong class="text-green-700 dark:text-green-400">Tier 1 — gpt-4.1-nano</strong>
                    <p class="text-gray-500">{{ t('settings.agentic.advice_tier1') }}</p>
                  </div>
                </div>
                <div
                  class="flex items-center gap-3 bg-white dark:bg-gray-900 rounded p-2 border border-amber-200 dark:border-amber-900">
                  <span
                    class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-amber-500 text-white text-[10px] font-bold">2</span>
                  <div class="flex-1">
                    <strong class="text-amber-700 dark:text-amber-400">Tier 2 — gpt-4.1-mini</strong>
                    <p class="text-gray-500">{{ t('settings.agentic.advice_tier2') }}</p>
                  </div>
                </div>
                <div
                  class="flex items-center gap-3 bg-white dark:bg-gray-900 rounded p-2 border border-red-200 dark:border-red-900">
                  <span
                    class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-500 text-white text-[10px] font-bold">3</span>
                  <div class="flex-1">
                    <strong class="text-red-700 dark:text-red-400">Tier 3 — gpt-4.1</strong>
                    <p class="text-gray-500">{{ t('settings.agentic.advice_tier3') }}</p>
                  </div>
                </div>
              </div>
            </div>

            <!-- Red Team -->
            <div class="rounded-lg border-2 border-red-200 dark:border-red-800 p-4 bg-red-50/50 dark:bg-red-900/10">
              <h4 class="text-sm font-semibold text-red-800 dark:text-red-300 mb-2">🛡️ {{
                t('settings.agentic.advice_redteam') }}</h4>
              <p class="text-xs text-gray-600 dark:text-gray-300 mb-2">{{ t('settings.agentic.advice_redteam_desc') }}
              </p>
              <div class="text-[11px] bg-white dark:bg-gray-900 rounded p-2 border border-red-100 dark:border-red-900">
                <strong class="text-green-600">✓ gpt-4.1</strong>
                <span class="text-gray-500 ml-1">{{ t('settings.agentic.advice_redteam_model') }}</span>
              </div>
            </div>

            <!-- Key Insight -->
            <div class="rounded-lg bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 p-4">
              <h4 class="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-1">💡 {{
                t('settings.agentic.advice_insight_title') }}</h4>
              <p class="text-xs text-gray-600 dark:text-gray-300">{{ t('settings.agentic.advice_insight') }}</p>
            </div>
          </div>
          <div class="bg-gray-50 dark:bg-gray-700 px-6 py-3 flex justify-end">
            <button @click="showModelAdvice = false"
              class="inline-flex justify-center rounded-md border border-transparent shadow-sm px-4 py-2 bg-purple-600 text-sm font-medium text-white hover:bg-purple-700 focus:outline-none">
              {{ t('settings.agentic.advice_close') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
