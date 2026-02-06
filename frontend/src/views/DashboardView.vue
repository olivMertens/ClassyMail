<script setup>
/* eslint-disable vue/no-v-html */
import { ref, onMounted, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import MarkdownIt from 'markdown-it'
import {
  MagnifyingGlassIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CheckCircleIcon,
  ExclamationCircleIcon,
  ClockIcon,
  ArrowDownTrayIcon,
  ArrowPathIcon,
  ChatBubbleLeftRightIcon,
  XMarkIcon,
  EyeIcon,
  TableCellsIcon,
  Squares2X2Icon,
  TrashIcon,
  BarsArrowDownIcon,
  BarsArrowUpIcon,
  ShieldExclamationIcon
} from '@heroicons/vue/24/outline'
import DlqDetailModal from '@/components/DlqDetailModal.vue'
import { useDialog } from '@/composables/useDialog'

const { confirm, alert: showAlert } = useDialog()
const { t } = useI18n()

defineProps({
  active: {
    type: Boolean,
    default: true
  }
})

const emails = ref([])
const stats = ref({
  total: 0,
  review_required: 0,
  processed: 0,
  pending: 0,
  queue_depth: 0,
  finetune_ready: false,
  average_confidence: 0,
  finetune_min_required: 50
})
const filter = ref('all')
const search = ref('')
const confidenceFilter = ref('')
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref(null)
const reprocessingId = ref(null)
const dlq = ref({ count: 0, messages: [] })
const dlqError = ref(null)
const dlqDismissed = ref(false)
const diagnostics = ref(null)
const diagnosticsError = ref(null)
const currentTab = ref('dashboard')
const chatOpen = ref(false)
const dlqModalOpen = ref(false)
const selectedDlq = ref(null)
const chatQuery = ref('')
const chatLoading = ref(false)
const chatError = ref(null)
const chatMessages = ref([]) // Store conversation history: [{ role: 'user'|'assistant', content: string }]
const chatSources = ref([])
const chatSessionId = ref(localStorage.getItem('chatSessionId') || crypto.randomUUID())
watch(chatSessionId, (val) => localStorage.setItem('chatSessionId', val))
const md = new MarkdownIt({ linkify: true, breaks: false }) // breaks: false to avoid excessive <br>
const viewMode = ref('cards') // 'cards' or 'table'
const purging = ref(false)
const sortBy = ref('timestamp')
const sortOrder = ref('desc')

const pageSizeOptions = [20, 50, 100]

const allProcessed = computed(() => stats.value.total > 0 && stats.value.total === stats.value.processed)

const filters = computed(() => [
  { id: 'all', label: t('dashboard.filters.all'), color: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300' },
  { id: 'REVIEW_REQUIRED', label: t('dashboard.filters.review'), color: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300' },
  { id: 'PROCESSED', label: t('dashboard.filters.processed'), color: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300' },
  { id: 'ERROR', label: t('dashboard.filters.errors'), color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300' },
])

const reprocessEmail = async (email) => {
  if (await confirm('Are you sure you want to reprocess this email? It will be re-queued.')) {
    try {
      reprocessingId.value = email.id
      const res = await fetch(`/api/emails/${email.id}/reprocess`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to reprocess')
      // Optimistic update
      email.status = 'PENDING'
      await showAlert('Email re-queued successfully')
    } catch (e) {
      await showAlert(e.message)
    } finally {
      reprocessingId.value = null
    }
  }
}

const fetchEmails = async () => {
  loading.value = true
  error.value = null
  try {
    const params = new URLSearchParams()
    params.set('status', filter.value === 'all' ? 'all' : filter.value)
    params.set('page', page.value)
    params.set('page_size', pageSize.value)
    if (search.value) params.set('search', search.value)
    if (confidenceFilter.value) params.set('confidence_filter', confidenceFilter.value)
    params.set('sort_by', sortBy.value)
    params.set('order', sortOrder.value)

    const res = await fetch(`/api/emails?${params.toString()}`)
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Server Error: ${res.status}`)
    }
    const data = await res.json()

    emails.value = data.items || []
    // Update stats from API response - these are global counts, not filtered
    stats.value = {
      total: data.total || 0,
      review_required: data.review_required || 0,
      processed: data.processed || 0,
      pending: data.pending || 0,
      queue_depth: data.queue_depth || 0,
      finetune_ready: data.finetune_ready || false,
      average_confidence: data.average_confidence || 0,
      finetune_min_required: data.finetune_min_required || 50
    }

    // Log for debugging stats mismatch
    console.log('[Dashboard] Stats:', stats.value, '| Items:', emails.value.length)
  } catch (e) {
    console.error(e)
    error.value = e.message
  } finally {
    loading.value = false
  }
}

const fetchDeadletters = async () => {
  try {
    const res = await fetch('/api/admin/deadletter')
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Server Error: ${res.status}`)
    }
    dlq.value = await res.json()
    dlqError.value = null
  } catch (e) {
    console.error(e)
    dlqError.value = e.message
  }
}

const fetchDiagnostics = async () => {
  try {
    const res = await fetch('/api/admin/diagnostics')
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Server Error: ${res.status}`)
    }
    diagnostics.value = await res.json()
    diagnosticsError.value = null
  } catch (e) {
    console.error(e)
    diagnosticsError.value = e.message
  }
}

const openDlqDetails = (msg) => {
  selectedDlq.value = msg
  dlqModalOpen.value = true
}

const runChatSearch = async () => {
  chatLoading.value = true
  chatError.value = null
  try {
    const q = chatQuery.value.trim()
    if (!q) return

    // Add user message to conversation
    chatMessages.value.push({ role: 'user', content: q })

    // Clear input immediately after capturing query
    chatQuery.value = ''

    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: q }], session_id: chatSessionId.value })
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Server Error: ${res.status}`)
    }
    const data = await res.json()

    // Add assistant response to conversation
    chatMessages.value.push({ role: 'assistant', content: data.content })
    chatSources.value = data.sources || []
  } catch (e) {
    chatError.value = e.message
  } finally {
    chatLoading.value = false
  }
}

const useExample = (text) => {
  chatQuery.value = text
  runChatSearch()
}

const toggleSort = (column) => {
  if (sortBy.value === column) {
    sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortBy.value = column
    sortOrder.value = 'desc'
  }
  fetchEmails()
}

const purgeDlq = async () => {
  if (!await confirm("Are you sure you want to delete all messages in the Dead Letter Queue? This action cannot be undone.")) return

  purging.value = true
  try {
    const res = await fetch('/api/admin/purge-dlq', { method: 'POST' })
    if (!res.ok) throw new Error('Failed to purge DLQ')
    const data = await res.json()
    await showAlert(`Purged ${data.deleted_dlq} messages.`)
    await fetchDeadletters() // Refresh list
    if (dlq.value.count === 0) {
      currentTab.value = 'dashboard'
      dlqDismissed.value = false // Reset close state so it reappears if new errors come
    }
  } catch (e) {
    await showAlert(e.message)
  } finally {
    purging.value = false
  }
}

// Watchers
watch([filter, pageSize, confidenceFilter], () => {
  page.value = 1
  fetchEmails()
})

// Debounce search
let timeout
watch([search], () => {
  clearTimeout(timeout)
  timeout = setTimeout(() => {
    page.value = 1
    fetchEmails()
  }, 500)
})

onMounted(() => {
  fetchEmails()
  fetchDeadletters()
  fetchDiagnostics()
  // Poll every 20s as requested
  const pollEmails = setInterval(fetchEmails, 20000)
  const pollDlq = setInterval(fetchDeadletters, 20000)
  const pollDiag = setInterval(fetchDiagnostics, 60000)
  return () => {
    clearInterval(pollEmails)
    clearInterval(pollDlq)
    clearInterval(pollDiag)
  }
})

const totalPages = computed(() => Math.max(1, Math.ceil(stats.value.total / pageSize.value)))

const progressPercentage = computed(() => {
  if (!stats.value.total) return 0
  const processed = stats.value.processed + stats.value.review_required
  return Math.round((processed / stats.value.total) * 100)
})

const getScoreColor = (email) => {
  const intents = email.classification?.detected_intents || []
  if (!intents.length) return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
  const score = Math.max(...intents.map(i => i.confidence || 0))

  if (score >= 0.85) return 'bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-300'
  if (score >= 0.7) return 'bg-lime-100 text-lime-800 dark:bg-lime-900/50 dark:text-lime-300'
  if (score >= 0.5) return 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300'
  return 'bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-300'
}

const strategyBadge = (strategy) => {
  const map = {
    reasoning: { icon: '🧠', color: 'bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300 border-purple-200 dark:border-purple-700', key: 'reasoning_short' },
    vision: { icon: '👁', color: 'bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300 border-teal-200 dark:border-teal-700', key: 'vision_short' },
  }
  return map[strategy] || null // null = standard (no badge, it's the default)
}

const getScore = (email) => {
  const intents = email.classification?.detected_intents || []
  if (!intents.length) return 'N/A'
  return (Math.max(...intents.map(i => i.confidence || 0)) * 100).toFixed(0) + '%'
}

const formatDuration = (email) => {
  const ms = email?.processing_time_ms
  if (!ms) return null
  if (ms < 1000) return `${ms.toFixed(0)} ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)} s`
  const m = s / 60
  return `${m.toFixed(1)} min`
}

const formatMetric = (num) => {
  if (num === undefined || num === null) return '0'
  // Use compact notation for numbers >= 10,000 to handle large volumes (e.g., 10k, 9M)
  // Below 10,000, show full number with separators
  return new Intl.NumberFormat('en-US', {
    notation: num >= 10000 ? 'compact' : 'standard',
    maximumFractionDigits: 1
  }).format(num)
}

// Helper to get sorted intents by confidence (highest first)
const getSortedIntents = (email) => {
  const intents = email.classification?.detected_intents || []
  return [...intents].sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
}

const emit = defineEmits(['open-email'])
</script>

<template>
  <div class="space-y-6">
    <div
      v-if="allProcessed"
      class="flex items-center space-x-4 border-b border-gray-200 dark:border-gray-700 pb-2"
    >
      <button
        :class="['px-3 py-1 rounded-md text-sm font-medium', currentTab === 'dashboard' ? 'bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-100' : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300']"
        @click="currentTab = 'dashboard'"
      >
        {{ t('dashboard.tabs.dashboard') }}
      </button>
      <button
        v-if="dlq.count > 0"
        :class="['px-3 py-1 rounded-md text-sm font-medium flex items-center gap-1', currentTab === 'failures' ? 'bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-100' : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300']"
        @click="currentTab = 'failures'"
      >
        <ExclamationCircleIcon class="h-4 w-4" />
        {{ t('dashboard.tabs.failures', { count: dlq.count }) }}
      </button>
      <button
        :class="['px-3 py-1 rounded-md text-sm font-medium', currentTab === 'developer' ? 'bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-100' : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300']"
        @click="currentTab = 'developer'"
      >
        {{ t('dashboard.tabs.developer') }}
      </button>
    </div>
    <div
      v-if="dlq.count > 0 && !dlqDismissed && currentTab !== 'failures'"
      class="rounded-md bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 p-4 relative"
    >
      <button
        class="absolute top-2 right-2 text-red-400 hover:text-red-600 dark:text-red-300 dark:hover:text-red-100"
        :title="t('common.dismiss')"
        @click="dlqDismissed = true"
      >
        <XMarkIcon class="h-5 w-5" />
      </button>
      <div class="flex">
        <ExclamationCircleIcon class="h-5 w-5 text-red-400 mt-0.5" />
        <div class="ml-3">
          <h3 class="text-sm font-medium text-red-800 dark:text-red-200">
            {{ t('dashboard.dlq.title', { count: dlq.count }) }}
          </h3>
          <p class="mt-1 text-sm text-red-700 dark:text-red-200">
            {{ t('dashboard.dlq.subtitle') }}
            <button
              class="font-semibold underline ml-1 hover:text-red-900 dark:hover:text-red-100"
              @click="currentTab = 'failures'"
            >
              {{ t('dashboard.dlq.view_details') }}
            </button>
          </p>
        </div>
      </div>
    </div>
    <div
      v-else-if="dlqError"
      class="rounded-md bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 p-4"
    >
      <div class="flex">
        <ExclamationCircleIcon class="h-5 w-5 text-amber-400 mt-0.5" />
        <div class="ml-3">
          <h3 class="text-sm font-medium text-amber-800 dark:text-amber-200">
            {{ t('dashboard.dlq.unavailable') }}
          </h3>
          <p class="mt-2 text-sm text-amber-700 dark:text-amber-200">
            {{ dlqError }}
          </p>
        </div>
      </div>
    </div>
    <!-- Stats Cards -->
    <dl
      v-if="currentTab === 'dashboard'"
      class="mt-5 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4"
    >
      <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
        <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">
          {{ t('dashboard.stats.total') }}
        </dt>
        <dd
          class="mt-1 text-3xl font-semibold text-gray-900 dark:text-white"
          :title="stats.total.toLocaleString()"
        >
          {{ formatMetric(stats.total) }}
        </dd>
      </div>
      <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
        <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">
          {{ t('dashboard.stats.to_review') }}
        </dt>
        <dd
          class="mt-1 text-3xl font-semibold text-amber-600 dark:text-amber-400"
          :title="stats.review_required.toLocaleString()"
        >
          {{ formatMetric(stats.review_required) }}
        </dd>
      </div>
      <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
        <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">
          {{ t('dashboard.stats.processed') }}
        </dt>
        <dd
          class="mt-1 text-3xl font-semibold text-green-600 dark:text-green-400"
          :title="stats.processed.toLocaleString()"
        >
          {{ formatMetric(stats.processed) }}
        </dd>
      </div>
      <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
        <dt
          class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate"
          :title="t('dashboard.stats.quality_tooltip')"
        >
          {{ t('dashboard.stats.quality') }}
        </dt>
        <dd class="mt-1 text-3xl font-semibold text-indigo-600 dark:text-indigo-400">
          {{ (stats.average_confidence * 100).toFixed(1) }}%
        </dd>
      </div>
    </dl>
  </div>

  <!-- Progress Bar & Actions -->
  <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-4">
    <!-- Progress Bar (Only show if data exists) -->
    <div
      v-if="stats.total > 0"
      class="mb-4"
    >
      <div class="flex justify-between items-center mb-1">
        <div class="flex items-center gap-1">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">{{ t('dashboard.progress.title') }}</span>
          <span
            v-if="stats.queue_depth > 0 || stats.pending > 0"
            class="text-xs font-normal text-gray-500 dark:text-gray-400"
          >
            {{ t('dashboard.progress.pending', { processing: stats.pending, queued: stats.queue_depth }) }}
          </span>
        </div>
        <span class="text-sm font-medium text-primary-700 dark:text-primary-400">{{ progressPercentage }}%</span>
      </div>
      <div class="w-full bg-gray-200 rounded-full h-2.5 dark:bg-gray-700">
        <div
          class="bg-primary-600 h-2.5 rounded-full transition-all duration-500"
          :style="{ width: progressPercentage + '%' }"
        />
      </div>
    </div>
    <div
      v-else
      class="mb-4 text-sm text-gray-500 text-center italic"
    >
      {{ t('common.no_data') }}
    </div>
  </div>

  <!-- Filters & Search Toolbar -->
  <div class="flex flex-col gap-4 bg-white dark:bg-gray-800 p-4 shadow rounded-lg">
    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
      <!-- Tab-like Filters -->
      <div class="w-full sm:w-auto overflow-x-auto">
        <div class="flex p-1 bg-gray-100 dark:bg-gray-700 rounded-lg min-w-max">
          <button
            v-for="f in filters"
            :key="f.id"
            class="px-4 py-2 text-sm font-medium rounded-md transition-all whitespace-nowrap"
            :class="filter === f.id ? 'bg-white dark:bg-gray-600 text-gray-900 dark:text-white shadow' : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'"
            @click="filter = f.id"
          >
            {{ f.label }}
          </button>
        </div>
      </div>

      <!-- Search -->
      <div class="relative w-full sm:max-w-xs">
        <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
          <MagnifyingGlassIcon
            class="h-5 w-5 text-gray-400"
            aria-hidden="true"
          />
        </div>
        <input
          v-model="search"
          type="text"
          class="block w-full rounded-md border-0 py-2.5 pl-10 pr-3 text-gray-900 ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:ring-gray-600 dark:text-white dark:placeholder-gray-400"
          :placeholder="t('dashboard.search_placeholder')"
        >
      </div>
    </div>

    <!-- Secondary Filters Row -->
    <div class="flex flex-col sm:flex-row gap-4 items-center">
      <!-- Confidence Filter -->
      <div class="w-full sm:w-48">
        <select
          id="confidence-filter"
          v-model="confidenceFilter"
          class="block w-full rounded-md border-0 py-2 pl-3 pr-10 text-gray-900 ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:ring-gray-600 dark:text-white"
        >
          <option value="">
            {{ t('dashboard.confidence.any') }}
          </option>
          <option disabled>
            {{ t('dashboard.confidence.low_header') }}
          </option>
          <option value="lt_10">
            {{ t('dashboard.confidence.very_low') }}
          </option>
          <option value="lt_30">
            {{ t('dashboard.confidence.lt_30') }}
          </option>
          <option value="lt_50">
            {{ t('dashboard.confidence.lt_50') }}
          </option>
          <option value="lt_85">
            {{ t('dashboard.confidence.review_required') }}
          </option>
          <option disabled>
            {{ t('dashboard.confidence.high_header') }}
          </option>
          <option value="gt_85">
            {{ t('dashboard.confidence.high') }}
          </option>
          <option value="gt_90">
            {{ t('dashboard.confidence.very_high') }}
          </option>
          <option value="eq_100">
            {{ t('dashboard.confidence.perfect') }}
          </option>
          <option value="none">
            {{ t('dashboard.confidence.none') }}
          </option>
        </select>
      </div>

      <div class="flex-grow" />

      <!-- View Mode Toggle -->
      <div class="flex bg-gray-100 dark:bg-gray-700 p-1 rounded-lg shrink-0">
        <button
          type="button"
          :class="[
            'flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md transition-all',
            viewMode === 'cards'
              ? 'bg-white dark:bg-gray-600 text-primary-600 dark:text-primary-300 shadow-sm'
              : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
          ]"
          @click="viewMode = 'cards'"
        >
          <Squares2X2Icon class="h-4 w-4" />
          {{ t('dashboard.view_mode.cards') }}
        </button>
        <button
          type="button"
          :class="[
            'flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md transition-all',
            viewMode === 'table'
              ? 'bg-white dark:bg-gray-600 text-primary-600 dark:text-primary-300 shadow-sm'
              : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
          ]"
          @click="viewMode = 'table'"
        >
          <TableCellsIcon class="h-4 w-4" />
          {{ t('dashboard.view_mode.table') }}
        </button>
      </div>
    </div>
  </div>

  <!-- Grid -->
  <div
    v-if="loading && !emails.length"
    class="text-center py-12"
  >
    <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto" />
    <p class="mt-4 text-gray-500 dark:text-gray-400">
      {{ t('common.loading') }}
    </p>
  </div>

  <div
    v-else-if="error"
    class="rounded-md bg-gray-50 dark:bg-gray-800/50 p-6 border border-gray-200 dark:border-gray-700 flex flex-col items-center justify-center text-center"
  >
    <div class="flex h-12 w-12 items-center justify-center rounded-full bg-orange-100 dark:bg-orange-900/30 mb-4">
      <ExclamationCircleIcon
        class="h-6 w-6 text-orange-600 dark:text-orange-400"
        aria-hidden="true"
      />
    </div>
    <h3 class="text-lg font-medium text-gray-900 dark:text-white mb-2">
      {{ t('dashboard.waiting.title') }}
    </h3>
    <p class="text-sm text-gray-500 dark:text-gray-400 max-w-sm mb-4">
      {{ t('dashboard.waiting.subtitle') }}
    </p>
    <p
      class="text-xs text-gray-400 font-mono bg-white dark:bg-gray-900 px-3 py-2 rounded border border-gray-200 dark:border-gray-700"
    >
      {{ error }}
    </p>
    <button
      class="mt-6 inline-flex items-center rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
      @click="fetchEmails"
    >
      {{ t('common.retry') }}
    </button>
  </div>

  <div
    v-else-if="!emails.length"
    class="text-center py-12 border-2 border-dashed border-gray-300 dark:border-gray-700 rounded-lg"
  >
    <ArrowDownTrayIcon class="mx-auto h-12 w-12 text-gray-400" />
    <h3 class="mt-2 text-sm font-semibold text-gray-900 dark:text-white">
      {{ t('dashboard.no_emails_title') }}
    </h3>
    <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
      {{ t('dashboard.no_emails_subtitle') }}
    </p>
  </div>

  <!-- Cards View -->
  <div
    v-else-if="viewMode === 'cards'"
    class="grid gap-4 mt-8 grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-4"
  >
    <div
      v-for="email in emails"
      :key="email.id"
      :class="[
        'rounded-lg shadow-sm border hover:shadow-md transition-shadow flex flex-col h-full text-sm group cursor-pointer',
        email.test_mode
          ? 'bg-amber-50 dark:bg-amber-950/20 border-amber-300 dark:border-amber-700'
          : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700'
      ]"
      @click="emit('open-email', email)"
    >
      <div class="p-3 flex-1 flex flex-col gap-2">
        <!-- Header: Status + Actions -->
        <div class="flex justify-between items-start">
          <div class="flex items-center gap-2">
            <span
              v-if="email.status === 'ERROR'"
              class="text-red-500"
              :title="t('dashboard.status.error')"
            >
              <ExclamationCircleIcon class="h-4 w-4" />
            </span>
            <span
              v-else-if="email.status === 'PENDING' || email.status === 'uploaded' || email.status === 'PROCESSING'"
              class="text-blue-500 animate-pulse"
              :title="t('dashboard.status.processing')"
            >
              <ArrowPathIcon class="h-4 w-4 animate-spin" />
            </span>
            <span
              v-else-if="email.status === 'PROCESSED'"
              class="text-green-500"
              :title="t('dashboard.status.processed')"
            >
              <CheckCircleIcon class="h-4 w-4" />
            </span>
            <span
              v-else-if="email.status === 'REVIEW_REQUIRED'"
              class="text-amber-500"
              :title="t('dashboard.status.review')"
            >
              <ClockIcon class="h-4 w-4" />
            </span>

            <span
              v-if="email.classification?.detected_intents?.length"
              class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ring-1 ring-inset"
              :class="getScoreColor(email)"
              :title="`${getSortedIntents(email)[0]?.intent}: ${getScore(email)}`"
            >
              {{ getScore(email) }}
            </span>
          </div>

          <!-- Minimal Actions -->
          <div class="flex gap-2 opacity-100 transition-opacity">
            <span
              v-if="email.pii_detected"
              class="text-amber-500"
              :title="t('dashboard.pii.detected')"
            >
              <ShieldExclamationIcon class="h-5 w-5" />
            </span>
            <button
              :title="t('dashboard.actions.view')"
              class="text-gray-400 hover:text-primary-600"
              @click.stop="emit('open-email', email)"
            >
              <EyeIcon class="h-5 w-5" />
            </button>
            <button
              :title="t('dashboard.actions.reprocess')"
              :disabled="reprocessingId === email.id"
              class="text-gray-400 hover:text-green-600"
              @click.stop="reprocessEmail(email)"
            >
              <ArrowPathIcon
                class="h-5 w-5"
                :class="{ 'animate-spin': reprocessingId === email.id }"
              />
            </button>
          </div>
        </div>

        <!-- Content -->
        <div class="min-w-0">
          <h3
            class="font-medium text-gray-900 dark:text-white truncate text-sm leading-tight"
            :title="email.subject || (email.file_url ? decodeURIComponent(email.file_url.split('/').pop().split('?')[0]) : 'No Subject')"
          >
            {{ email.subject || (email.file_url ? decodeURIComponent(email.file_url.split('/').pop().split('?')[0]) :
              'No Subject') }}
          </h3>
          <p class="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
            {{ email.sender || 'Unknown Sender' }}
          </p>
        </div>

        <!-- Footer: ID & Category & Duration -->
        <div
          class="mt-auto pt-2 flex items-center justify-between gap-2 border-t border-gray-100 dark:border-gray-700/50"
        >
          <div class="text-[10px] text-gray-400 font-mono truncate max-w-[40%]">
            #{{ email.id.slice(0, 6) }}
          </div>
          <div
            v-if="getSortedIntents(email).length"
            class="flex-shrink-0 flex flex-wrap items-center gap-1 justify-end max-w-[60%]"
          >
            <span
              v-for="(intent, idx) in getSortedIntents(email).slice(0, 2)"
              :key="intent.intent"
              class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border"
              :class="idx === 0 ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 border-blue-100 dark:border-blue-800 font-medium' : 'bg-gray-50 text-gray-600 dark:bg-gray-800 dark:text-gray-400 border-gray-200 dark:border-gray-700'"
              :title="`${intent.intent}: ${Math.round((intent.confidence || 0) * 100)}%${intent.justification ? '\n' + intent.justification : ''}`"
            >
              <span class="truncate max-w-[80px]">{{ intent.intent }}</span>
              <span class="ml-0.5 font-semibold">{{ Math.round((intent.confidence || 0) * 100) }}%</span>
            </span>
            <span
              v-if="getSortedIntents(email).length > 2"
              class="inline-flex items-center px-1 py-0.5 rounded-full text-[9px] bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300 cursor-help font-medium"
              :title="'Additional intents:\n' + getSortedIntents(email).slice(2).map(i => `- ${i.intent}: ${Math.round((i.confidence || 0) * 100)}%`).join('\n')"
            >
              +{{ getSortedIntents(email).length - 2 }}
            </span>
          </div>
          <div
            v-else
            class="text-[10px] text-gray-400 italic max-w-[150px] truncate"
            :title="email.classification?.classification_reason || 'No category detected'"
          >
            {{ email.classification?.classification_reason || 'No category' }}
          </div>
          <div class="flex items-center gap-1.5">
            <span
              v-if="strategyBadge(email.processing_strategy)"
              class="inline-flex items-center px-1 py-0.5 rounded text-[9px] font-medium border"
              :class="strategyBadge(email.processing_strategy).color"
              :title="t('dashboard.strategy.' + (email.processing_strategy || 'standard'))"
            >
              {{ strategyBadge(email.processing_strategy).icon }} {{ t('dashboard.strategy.' +
                strategyBadge(email.processing_strategy).key) }}
            </span>
            <div
              v-if="formatDuration(email)"
              class="text-[10px] text-gray-500 dark:text-gray-400 inline-flex items-center gap-0.5"
              title="Processing time"
            >
              ⏱ {{ formatDuration(email) }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div
    v-if="currentTab === 'failures'"
    class="space-y-4 mt-4"
  >
    <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
      <div class="flex justify-between items-start mb-4">
        <div>
          <h3 class="text-lg font-medium text-gray-900 dark:text-white mb-2 flex items-center gap-2">
            <ExclamationCircleIcon class="h-6 w-6 text-red-500" />
            {{ t('dashboard.dlq.modal_title') }}
          </h3>
          <p class="text-sm text-gray-500 dark:text-gray-400">
            {{ t('dashboard.dlq.modal_desc') }}
          </p>
        </div>
        <div class="flex gap-2">
          <button
            class="flex items-center gap-2 px-3 py-2 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 border border-gray-300 dark:border-gray-600 rounded-md text-sm font-medium transition-colors"
            @click="currentTab = 'dashboard'"
          >
            <XMarkIcon class="h-4 w-4" />
            {{ t('common.close') }}
          </button>
          <button
            class="flex items-center gap-2 px-3 py-2 bg-red-600 hover:bg-red-700 text-white rounded-md text-sm font-medium transition-colors disabled:opacity-50"
            :disabled="purging"
            @click="purgeDlq"
          >
            <TrashIcon class="h-4 w-4" />
            {{ purging ? t('dashboard.dlq.purging') : t('dashboard.dlq.purge') }}
          </button>
        </div>
      </div>

      <div class="overflow-x-auto border rounded-md dark:border-gray-700">
        <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead class="bg-gray-50 dark:bg-gray-700">
            <tr>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
              >
                {{ t('dashboard.dlq.item_id') }}
              </th>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
              >
                {{ t('dashboard.dlq.reason') }}
              </th>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
              >
                {{ t('dashboard.dlq.description') }}
              </th>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
              >
                {{ t('dashboard.dlq.time') }}
              </th>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider"
              >
                {{ t('dashboard.dlq.actions') }}
              </th>
            </tr>
          </thead>
          <tbody class="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
            <tr
              v-for="msg in dlq.messages"
              :key="msg.message_id"
            >
              <td class="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-900 dark:text-white">
                {{ msg.blob_id || msg.message_id }}
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-red-600 dark:text-red-400">
                {{ msg.dead_letter_reason || 'Unknown' }}
              </td>
              <td class="px-6 py-4 text-sm text-gray-500 dark:text-gray-400">
                {{ msg.dead_letter_error_description || '—' }}
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                {{ msg.enqueued_time_utc || '—' }}
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm">
                <button
                  class="text-primary-600 dark:text-primary-400 hover:underline"
                  @click="openDlqDetails(msg)"
                >
                  {{ t('dashboard.dlq.view') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <div
    v-if="currentTab === 'developer'"
    class="space-y-4 mt-4"
  >
    <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-4">
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-medium text-gray-900 dark:text-gray-100">
          {{ t('dashboard.developer.title') }}
        </h3>
        <button
          class="inline-flex items-center px-2 py-1 text-xs font-medium rounded-md bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-100"
          @click="fetchDiagnostics"
        >
          {{ t('common.refresh') }}
        </button>
      </div>
      <div
        v-if="diagnosticsError"
        class="mt-2 text-sm text-red-600 dark:text-red-300"
      >
        {{ diagnosticsError }}
      </div>
      <table
        v-else-if="diagnostics"
        class="mt-2 min-w-full text-sm"
      >
        <tbody>
          <tr
            v-for="(v, k) in diagnostics.env"
            :key="k"
            class="border-b border-gray-200 dark:border-gray-700"
          >
            <td class="py-1 font-mono text-gray-500 dark:text-gray-300">
              {{ k }}
            </td>
            <td class="py-1 text-gray-900 dark:text-gray-100">
              {{ v || '—' }}
            </td>
          </tr>
          <tr>
            <td class="py-1 font-mono text-gray-500 dark:text-gray-300">
              {{ t('dashboard.developer.readiness') }}
            </td>
            <td class="py-1">
              <span :class="diagnostics.ok ? 'text-green-600 dark:text-green-300' : 'text-red-600 dark:text-red-300'">{{
                diagnostics.ok ? t('dashboard.developer.status_ok') : t('dashboard.developer.status_not_ready')
              }}</span>
              <pre
                v-if="diagnostics.readiness && Object.keys(diagnostics.readiness).length"
                class="mt-1 bg-gray-100 dark:bg-gray-900 p-2 rounded text-xs text-gray-700 dark:text-gray-200"
              >{{ JSON.stringify(diagnostics.readiness, null, 2) }}</pre>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- Table View -->
  <div
    v-else-if="viewMode === 'table'"
    class="overflow-x-auto bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700"
  >
    <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
      <thead class="bg-gray-50 dark:bg-gray-900">
        <tr>
          <th
            class="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
          >
            {{ t('dashboard.table.subject_sender') }}
          </th>
          <th
            class="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
          >
            {{ t('dashboard.table.category') }}
          </th>
          <th
            class="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:text-gray-700 dark:hover:text-gray-200"
            @click="toggleSort('status')"
          >
            <div class="flex items-center gap-1">
              {{ t('dashboard.table.status') }}
              <span v-if="sortBy === 'status'">
                <BarsArrowDownIcon
                  v-if="sortOrder === 'desc'"
                  class="h-3 w-3"
                />
                <BarsArrowUpIcon
                  v-else
                  class="h-3 w-3"
                />
              </span>
            </div>
          </th>
          <th
            class="hidden lg:table-cell px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:text-gray-700 dark:hover:text-gray-200"
            @click="toggleSort('timestamp')"
          >
            <div class="flex items-center gap-1">
              {{ t('dashboard.table.arrival') }}
              <span v-if="sortBy === 'timestamp'">
                <BarsArrowDownIcon
                  v-if="sortOrder === 'desc'"
                  class="h-3 w-3"
                />
                <BarsArrowUpIcon
                  v-else
                  class="h-3 w-3"
                />
              </span>
            </div>
          </th>
          <th
            class="hidden lg:table-cell px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
          >
            {{ t('dashboard.table.processed') }}
          </th>
          <th
            class="hidden md:table-cell px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-pointer hover:text-gray-700 dark:hover:text-gray-200"
            @click="toggleSort('processing_time')"
          >
            <div class="flex items-center gap-1">
              {{ t('dashboard.table.duration') }}
              <span v-if="sortBy === 'processing_time'">
                <BarsArrowDownIcon
                  v-if="sortOrder === 'desc'"
                  class="h-3 w-3"
                />
                <BarsArrowUpIcon
                  v-else
                  class="h-3 w-3"
                />
              </span>
            </div>
          </th>
          <th
            class="px-3 sm:px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
          >
            {{ t('dashboard.table.actions') }}
          </th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-200 dark:divide-gray-700">
        <tr
          v-for="email in emails"
          :key="email.id"
          :class="[
            'hover:bg-gray-50 dark:hover:bg-gray-700',
            email.test_mode ? 'bg-amber-50 dark:bg-amber-950/20' : ''
          ]"
        >
          <td class="px-3 sm:px-6 py-4">
            <div class="flex items-center gap-2">
              <div
                v-if="email.pii_detected"
                class="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 rounded-full"
                :title="t('dashboard.pii.tooltip')"
              >
                <ShieldExclamationIcon class="h-3.5 w-3.5 mr-1" />
                {{ t('dashboard.pii.badge') }}
              </div>
              <div
                v-if="email.test_mode"
                class="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 rounded"
              >
                {{ t('dashboard.table.test_badge') }}
              </div>
              <div>
                <button
                  class="text-left"
                  @click="emit('open-email', email)"
                >
                  <div class="text-sm font-medium text-gray-900 dark:text-white hover:underline">
                    {{ email.subject || t('dashboard.table.no_subject') }}
                  </div>
                  <div class="text-sm text-gray-500 dark:text-gray-400 hover:underline">
                    {{ email.sender || t('dashboard.table.unknown_sender') }}
                  </div>
                </button>
              </div>
            </div>
          </td>
          <td class="px-6 py-4">
            <div
              v-if="getSortedIntents(email).length"
              class="flex flex-wrap gap-1"
            >
              <span
                v-for="(intent, idx) in getSortedIntents(email).slice(0, 2)"
                :key="idx"
                class="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300"
                :title="`${intent.intent}: ${Math.round(intent.confidence * 100)}%${intent.justification ? '\n' + t('dashboard.table.justification') + ': ' + intent.justification : ''}`"
              >
                {{ intent.intent }} ({{ Math.round(intent.confidence * 100) }}%)
              </span>
              <span
                v-if="getSortedIntents(email).length > 2"
                class="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 cursor-help"
                :title="t('dashboard.table.extra_categories') + ':\n' + getSortedIntents(email).slice(2).map(i => `${i.intent}: ${Math.round(i.confidence * 100)}%`).join('\n')"
              >
                +{{ getSortedIntents(email).length - 2 }}
              </span>
            </div>
            <span
              v-else
              class="text-sm text-gray-400 dark:text-gray-500"
            >
              {{ t('dashboard.table.none') }}
            </span>
          </td>
          <td class="px-3 sm:px-6 py-4 whitespace-nowrap">
            <span
              :class="[
                'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium',
                email.status === 'PROCESSED'
                  ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300'
                  : email.status === 'REVIEW_REQUIRED'
                    ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300'
                    : (email.status === 'PENDING' || email.status === 'uploaded' || email.status === 'PROCESSING')
                      ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300 animate-pulse'
                      : 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300'
              ]"
            >
              {{ email.status === 'REVIEW_REQUIRED' ? t('dashboard.table.status_review') : email.status === 'PROCESSED'
                ? t('dashboard.table.status_processed') :
                  (email.status === 'PENDING' || email.status === 'uploaded' || email.status === 'PROCESSING') ?
                    t('dashboard.table.status_processing') : t('dashboard.table.status_error') }}
            </span>
          </td>
          <td class="hidden lg:table-cell px-3 sm:px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
            {{ email.created_at ? new Date(email.created_at).toLocaleString() : '—' }}
          </td>
          <td class="hidden lg:table-cell px-3 sm:px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
            {{ email.updated_at ? new Date(email.updated_at).toLocaleString() : '—' }}
          </td>
          <td class="hidden md:table-cell px-3 sm:px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
            <div class="flex items-center gap-1.5">
              <span>{{ formatDuration(email) || '—' }}</span>
              <span
                v-if="strategyBadge(email.processing_strategy)"
                class="inline-flex items-center px-1 py-0.5 rounded text-[9px] font-medium border"
                :class="strategyBadge(email.processing_strategy).color"
                :title="t('dashboard.strategy.' + (email.processing_strategy || 'standard'))"
              >
                {{ strategyBadge(email.processing_strategy).icon }} {{ t('dashboard.strategy.' +
                  strategyBadge(email.processing_strategy).key) }}
              </span>
            </div>
          </td>
          <td class="px-3 sm:px-6 py-4 whitespace-nowrap text-right text-sm font-medium flex justify-end gap-3">
            <button
              class="inline-flex items-center gap-1 text-primary-600 dark:text-primary-400 hover:text-primary-900 dark:hover:text-primary-300"
              @click="emit('open-email', email)"
            >
              <EyeIcon class="h-4 w-4" />
              {{ t('dashboard.actions.view') }}
            </button>
            <button
              class="inline-flex items-center gap-1 text-green-600 dark:text-green-400 hover:text-green-700 dark:hover:text-green-300"
              :disabled="reprocessingId === email.id"
              @click="reprocessEmail(email)"
            >
              <ArrowPathIcon
                class="h-4 w-4"
                :class="{ 'animate-spin': reprocessingId === email.id }"
              />
              {{ t('dashboard.actions.reprocess') }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- Pagination -->
  <div class="flex items-center justify-between border-t border-gray-200 dark:border-gray-700 pt-4">
    <div class="flex items-center">
      <select
        v-model="pageSize"
        class="block w-full rounded-md border-0 py-1.5 pl-3 pr-10 text-gray-900 ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:ring-gray-700 dark:text-white"
      >
        <option
          v-for="opt in pageSizeOptions"
          :key="opt"
          :value="opt"
        >
          {{ t('dashboard.pagination.per_page', { n: opt }) }}
        </option>
      </select>
    </div>
    <div class="flex items-center gap-2">
      <button
        :disabled="page <= 1"
        class="p-2 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 text-gray-500 dark:text-gray-400"
        @click="page--"
      >
        <ChevronLeftIcon class="h-5 w-5" />
      </button>
      <span class="text-sm text-gray-700 dark:text-gray-300">
        {{ t('dashboard.pagination.page_of', { current: page, total: totalPages }) }}
      </span>
      <button
        :disabled="page >= totalPages"
        class="p-2 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 text-gray-500 dark:text-gray-400"
        @click="page++"
      >
        <ChevronRightIcon class="h-5 w-5" />
      </button>
    </div>
    <!-- Floating Chat Assistant -->
    <div class="fixed bottom-4 right-4 z-50 flex flex-col items-end pointer-events-none">
      <div
        v-if="chatOpen"
        class="mb-4 w-[32rem] bg-white dark:bg-gray-900 shadow-xl rounded-lg border border-gray-200 dark:border-gray-700 pointer-events-auto flex flex-col overflow-hidden"
        style="max-height: 85vh;"
      >
        <!-- Header -->
        <div class="bg-primary-600 px-4 py-3 flex justify-between items-center text-white">
          <div class="flex items-center gap-2">
            <ChatBubbleLeftRightIcon class="h-5 w-5" />
            <span class="font-medium text-sm">{{ t('dashboard.chat.title') }}</span>
          </div>
          <button
            class="text-primary-100 hover:text-white"
            @click="chatOpen = false"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
              class="w-5 h-5"
            >
              <path
                d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
              />
            </svg>
          </button>
        </div>

        <!-- Content -->
        <div class="p-4 flex-1 overflow-y-auto bg-gray-50 dark:bg-gray-800/50 min-h-[200px]">
          <div
            v-if="chatMessages.length === 0 && !chatLoading"
            class="space-y-4"
          >
            <div
              class="bg-blue-50 dark:bg-blue-900/20 p-3 rounded-lg border border-blue-100 dark:border-blue-800 text-xs text-blue-800 dark:text-blue-200"
            >
              <span class="font-bold block mb-1">{{ t('dashboard.chat.how_it_works') }}</span>
              {{ t('dashboard.chat.how_it_works_desc') }}
            </div>
            <div>
              <p class="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-2 uppercase tracking-wider">
                {{ t('dashboard.chat.try_asking') }}
              </p>
              <div class="grid gap-2">
                <button
                  v-for="ex in [t('dashboard.chat.example_invoices'), t('dashboard.chat.example_errors'), t('dashboard.chat.example_intents'), t('dashboard.chat.example_urgent')]"
                  :key="ex"
                  class="text-left text-xs bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 border border-gray-200 dark:border-gray-700 px-3 py-2 rounded-md text-gray-700 dark:text-gray-300 transition-colors shadow-sm"
                  @click="useExample(ex)"
                >
                  {{ ex }}
                </button>
              </div>
            </div>
          </div>

          <div
            v-if="chatLoading"
            class="flex justify-start mt-2"
          >
            <div
              class="bg-white dark:bg-gray-800 px-4 py-3 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm flex items-center gap-2"
            >
              <div class="animate-spin h-3 w-3 border-2 border-primary-600 border-t-transparent rounded-full" />
              <span class="text-xs text-gray-500">{{ t('dashboard.chat.searching') }}</span>
            </div>
          </div>

          <!-- Conversation history -->
          <div
            v-for="(msg, idx) in chatMessages"
            :key="idx"
            class="flex mt-3"
            :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <div
              class="px-4 py-2.5 rounded-lg border shadow-sm max-w-[85%]"
              :class="msg.role === 'user'
                ? 'bg-primary-600 text-white border-primary-600'
                : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700'
              "
            >
              <div
                v-if="msg.role === 'user'"
                class="text-sm leading-relaxed whitespace-pre-wrap"
              >
                {{ msg.content }}
              </div>
              <!-- eslint-disable-next-line vue/no-v-html -->
              <div
                v-else
                class="text-sm text-gray-800 dark:text-gray-200 leading-relaxed prose prose-sm dark:prose-invert max-w-none"
                v-html="md.render(msg.content || '')"
              />
              <!-- Show sources only for last assistant message -->
              <div
                v-if="msg.role === 'assistant' && idx === chatMessages.length - 1 && chatSources.length"
                class="mt-2 text-[10px] text-gray-500 dark:text-gray-400"
              >
                <div class="uppercase tracking-wider font-semibold">
                  {{ t('dashboard.chat.sources') }}
                </div>
                <ul class="list-disc ml-4">
                  <li
                    v-for="s in chatSources"
                    :key="(s.parent_id || '') + ':' + (s.chunk_index || 0)"
                  >
                    {{ s.subject || s.parent_id }} <span v-if="s.chunk_index !== undefined">({{
                      t('dashboard.chat.chunk') }} {{ s.chunk_index
                    }})</span>
                  </li>
                </ul>
              </div>
              <div
                v-if="msg.role === 'assistant'"
                class="mt-2 text-[10px] text-gray-400 border-t dark:border-gray-700 pt-1 flex items-center gap-1"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  class="w-3 h-3"
                >
                  <path
                    fill-rule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                    clip-rule="evenodd"
                  />
                </svg>
                {{ t('dashboard.chat.generated_by') }}
              </div>
            </div>
          </div>

          <div
            v-if="chatError"
            class="mt-2 text-xs text-red-600 bg-red-50 dark:bg-red-900/20 p-2 rounded border border-red-100 dark:border-red-800"
          >
            {{ t('dashboard.chat.error') }} {{ chatError }}
          </div>
        </div>

        <!-- Footer -->
        <div class="p-3 bg-white dark:bg-gray-900 border-t border-gray-200 dark:border-gray-700">
          <div class="relative">
            <textarea
              v-model="chatQuery"
              rows="1"
              class="block w-full rounded-md border-0 py-2.5 pr-10 pl-3 text-gray-900 ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:ring-gray-700 dark:text-white resize-none"
              :placeholder="t('dashboard.chat.placeholder')"
              @keydown.enter.exact.prevent="runChatSearch"
            />
            <button
              :disabled="!chatQuery.trim() || chatLoading"
              class="absolute bottom-1.5 right-1.5 p-1.5 rounded-md text-primary-600 hover:text-primary-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-100 dark:hover:bg-gray-700 transition"
              @click="runChatSearch"
            >
              <span class="sr-only">{{ t('dashboard.chat.send') }}</span>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                class="w-5 h-5"
              >
                <path
                  d="M3.105 2.289a.75.75 0 00-.826.95l1.414 4.925A1.5 1.5 0 005.135 9.25h6.115a.75.75 0 010 1.5H5.135a1.5 1.5 0 00-1.442 1.086l-1.414 4.926a.75.75 0 00.826.95 28.896 28.896 0 0015.293-7.154.75.75 0 000-1.115A28.897 28.897 0 003.105 2.289z"
                />
              </svg>
            </button>
          </div>
        </div>
      </div>

      <button
        class="pointer-events-auto shadow-lg rounded-full w-14 h-14 bg-primary-600 hover:bg-primary-500 text-white flex items-center justify-center transition-transform hover:scale-105 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-600"
        :class="{ 'rotate-90': chatOpen }"
        @click="chatOpen = !chatOpen"
      >
        <ChatBubbleLeftRightIcon
          v-if="!chatOpen"
          class="h-7 w-7"
        />
        <svg
          v-else
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          class="w-6 h-6"
        >
          <path
            d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
          />
        </svg>
      </button>
    </div>
  </div>

  <DlqDetailModal
    :show="dlqModalOpen"
    :message="selectedDlq"
    @close="dlqModalOpen = false"
  />

  <!-- Reprocess Modal with Strategy Selector -->
  <Teleport to="body">
    <div
      v-if="reprocessModalOpen"
      class="fixed inset-0 z-[60] flex items-center justify-center bg-black/40"
      @click.self="reprocessModalOpen = false"
    >
      <div class="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <!-- Header -->
        <div class="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h3 class="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <ArrowPathIcon class="h-5 w-5 text-primary-600" />
            {{ t('dashboard.reprocess.title') }}
          </h3>
          <p
            v-if="reprocessTarget?.processing_strategy"
            class="text-xs text-gray-500 dark:text-gray-400 mt-1"
          >
            {{ t('dashboard.reprocess.current') }} {{ t('dashboard.strategy.' + reprocessTarget.processing_strategy) }}
          </p>
        </div>

        <!-- Strategy Options -->
        <div class="px-6 py-4 space-y-3">
          <p class="text-sm font-medium text-gray-700 dark:text-gray-300">
            {{ t('dashboard.reprocess.select_strategy') }}
          </p>
          <label
            v-for="s in ['standard', 'reasoning', 'vision']"
            :key="s"
            class="flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all"
            :class="reprocessStrategy === s
              ? 'border-primary-500 bg-primary-50 text-gray-900 dark:bg-primary-900/30 dark:border-primary-400 dark:text-white'
              : 'border-gray-200 bg-white text-gray-900 dark:border-gray-700 dark:bg-gray-700/50 dark:text-white hover:border-gray-300 dark:hover:border-gray-600'"
          >
            <input
              v-model="reprocessStrategy"
              type="radio"
              :value="s"
              class="mt-0.5 accent-primary-600"
            >
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-sm font-medium">
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

          <!-- Vision warning -->
          <div
            v-if="reprocessStrategy === 'vision'"
            class="flex items-start gap-2 p-2 rounded-md bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-xs text-amber-800 dark:text-amber-200"
          >
            <ExclamationCircleIcon class="h-4 w-4 flex-shrink-0 mt-0.5" />
            <span>{{ t('dashboard.reprocess.warning_vision') }}</span>
          </div>
        </div>

        <!-- Footer -->
        <div class="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
          <button
            class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors"
            @click="reprocessModalOpen = false"
          >
            {{ t('dashboard.reprocess.cancel') }}
          </button>
          <button
            class="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 transition-colors flex items-center gap-2"
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
