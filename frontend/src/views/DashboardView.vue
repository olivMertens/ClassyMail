<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import {
  MagnifyingGlassIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CheckCircleIcon,
  ExclamationCircleIcon,
  ClockIcon,
  ArrowDownTrayIcon,
  QuestionMarkCircleIcon,
  ArrowPathIcon,
  ChatBubbleLeftRightIcon,
  XMarkIcon,
  EyeIcon,
  TableCellsIcon,
  Squares2X2Icon
} from '@heroicons/vue/24/outline'

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
    finetune_ready: false,
    average_confidence: 0,
    finetune_min_required: 50
})
const filter = ref('all')
const search = ref('')
const categoryFilter = ref('')
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
const chatQuery = ref('')
const chatLoading = ref(false)
const chatError = ref(null)
const chatResponse = ref(null)
const viewMode = ref('cards') // 'cards' or 'table'

const pageSizeOptions = [20, 50, 100]

const allProcessed = computed(() => stats.value.total > 0 && stats.value.total === stats.value.processed)

const filters = [
  { id: 'all', label: 'All', color: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300' },
  { id: 'REVIEW_REQUIRED', label: 'To Review', color: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300' },
  { id: 'PROCESSED', label: 'Processed', color: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300' },
  { id: 'ERROR', label: 'Errors', color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300' },
]

const downloadFile = async (url, filename) => {
    try {
        const res = await fetch(url)
        if (!res.ok) {
            const err = await res.json().catch(() => ({}))
            throw new Error(err.detail?.message || err.detail || `Server Error: ${res.status}`)
        }
        const blob = await res.blob()
        const downloadUrl = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = downloadUrl

        // Try to get filename from content-disposition if not provided
        if (!filename) {
            const disposition = res.headers.get('Content-Disposition')
            if (disposition && disposition.indexOf('attachment') !== -1) {
                const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(disposition)
                if (matches != null && matches[1]) {
                    filename = matches[1].replace(/['"]/g, '')
                }
            }
        }

        a.download = filename || 'download'
        document.body.appendChild(a)
        a.click()
        a.remove()
        window.URL.revokeObjectURL(downloadUrl)
    } catch (e) {
        console.error(e)
        alert(e.message) // Simple alert for error feedback
    }
}

const exportCsv = () => {
    downloadFile('/api/emails/export', 'emails.csv')
}

const exportJsonl = (split = 'all') => {
    downloadFile(`/api/emails/export-finetune-jsonl?anonymize=true&split=${split}`)
}

const reprocessEmail = async (email) => {
    if (confirm('Are you sure you want to reprocess this email? It will be re-queued.')) {
        try {
            reprocessingId.value = email.id
            const res = await fetch(`/api/emails/${email.id}/reprocess`, { method: 'POST' })
            if (!res.ok) throw new Error('Failed to reprocess')
            // Optimistic update
            email.status = 'PENDING'
            alert('Email re-queued successfully')
        } catch (e) {
            alert(e.message)
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
        if (categoryFilter.value) params.set('category', categoryFilter.value)
        if (confidenceFilter.value) params.set('confidence_filter', confidenceFilter.value)

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

const runChatSearch = async () => {
    chatLoading.value = true
    chatError.value = null
    chatResponse.value = null
    try {
        const q = chatQuery.value.trim()
        if (!q) return
        const res = await fetch('/api/chat', {
             method: 'POST',
             headers: { 'Content-Type': 'application/json' },
             body: JSON.stringify({ messages: [{ role: 'user', content: q }] })
        })
        if (!res.ok) {
            const err = await res.json().catch(() => ({}))
            throw new Error(err.detail || `Server Error: ${res.status}`)
        }
        const data = await res.json()
        chatResponse.value = data.content
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

// Watchers
watch([filter, pageSize, categoryFilter, confidenceFilter], () => {
    page.value = 1
    fetchEmails()
})

// Debounce search
let timeout
watch([search, categoryFilter], () => {
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
    // Poll every 30s
    const pollEmails = setInterval(fetchEmails, 30000)
    const pollDlq = setInterval(fetchDeadletters, 30000)
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
    return Math.round((stats.value.processed / stats.value.total) * 100)
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

const getScore = (email) => {
    const intents = email.classification?.detected_intents || []
    if (!intents.length) return 'N/A'
    return Math.max(...intents.map(i => i.confidence || 0)).toFixed(2)
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
        :class="['px-3 py-1 rounded-md text-sm font-medium', currentTab==='dashboard' ? 'bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-100' : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300']"
        @click="currentTab='dashboard'"
      >
        Dashboard
      </button>
      <button
        v-if="dlq.count > 0"
        :class="['px-3 py-1 rounded-md text-sm font-medium flex items-center gap-1', currentTab==='failures' ? 'bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-100' : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300']"
        @click="currentTab='failures'"
      >
        <ExclamationCircleIcon class="h-4 w-4" />
        Failures ({{ dlq.count }})
      </button>
      <button
        :class="['px-3 py-1 rounded-md text-sm font-medium', currentTab==='developer' ? 'bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-100' : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300']"
        @click="currentTab='developer'"
      >
        Developer
      </button>
    </div>
    <div
      v-if="dlq.count > 0 && !dlqDismissed && currentTab !== 'failures'"
      class="rounded-md bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 p-4 relative"
    >
      <button
        class="absolute top-2 right-2 text-red-400 hover:text-red-600 dark:text-red-300 dark:hover:text-red-100"
        title="Dismiss"
        @click="dlqDismissed = true"
      >
        <XMarkIcon class="h-5 w-5" />
      </button>
      <div class="flex">
        <ExclamationCircleIcon class="h-5 w-5 text-red-400 mt-0.5" />
        <div class="ml-3">
          <h3 class="text-sm font-medium text-red-800 dark:text-red-200">
            Dead-letter queue has {{ dlq.count }} message(s)
          </h3>
          <p class="mt-1 text-sm text-red-700 dark:text-red-200">
            Processing failed for some items.
            <button
              class="font-semibold underline ml-1 hover:text-red-900 dark:hover:text-red-100"
              @click="currentTab='failures'"
            >
              View Details
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
            Dead-letter status unavailable
          </h3>
          <p class="mt-2 text-sm text-amber-700 dark:text-amber-200">
            {{ dlqError }}
          </p>
        </div>
      </div>
    </div>
    <!-- Stats Cards -->
    <dl
      v-if="currentTab==='dashboard'"
      class="mt-5 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4"
    >
      <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
        <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">
          Total Emails
        </dt>
        <dd class="mt-1 text-3xl font-semibold text-gray-900 dark:text-white">
          {{ stats.total }}
        </dd>
      </div>
      <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
        <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">
          To Review
        </dt>
        <dd class="mt-1 text-3xl font-semibold text-amber-600 dark:text-amber-400">
          {{ stats.review_required }}
        </dd>
      </div>
      <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
        <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">
          Processed
        </dt>
        <dd class="mt-1 text-3xl font-semibold text-green-600 dark:text-green-400">
          {{ stats.processed }}
        </dd>
      </div>
      <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
        <dt
          class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate"
          title="Average confidence of processed emails"
        >
          Avg. Quality
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
      <div class="flex justify-between mb-1">
        <span class="text-sm font-medium text-primary-700 dark:text-primary-400">Pipeline Progress</span>
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
      No data available yet.
    </div>

    <!-- Actions Row -->
    <div class="flex flex-col sm:flex-row justify-between items-end gap-4 mt-2 border-t pt-4 dark:border-gray-700">
      <p class="text-xs text-gray-500 dark:text-gray-400">
        {{ stats.processed }} of {{ stats.total }} emails processed.
        <span
          v-if="stats.total > 0 && progressPercentage < 100"
          class="ml-2 animate-pulse text-primary-600"
        >Processing... (Auto-refresh 15s)</span>
        <span
          v-else-if="stats.total > 0"
          class="ml-2 text-green-600"
        >Complete</span>
      </p>

      <div class="flex flex-wrap gap-2 items-center">
        <!-- Export CSV -->
        <div class="relative flex items-center group">
          <button
            class="inline-flex items-center gap-x-1.5 rounded-md bg-white dark:bg-gray-800 px-3 py-2 text-sm font-semibold text-gray-900 dark:text-gray-300 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="stats.total === 0"
            @click="exportCsv"
          >
            <ArrowDownTrayIcon
              class="-ml-0.5 h-5 w-5 text-gray-400"
              aria-hidden="true"
            />
            Export CSV
          </button>
          <QuestionMarkCircleIcon
            v-if="stats.total === 0"
            class="ml-1 h-5 w-5 text-gray-300 cursor-help"
            title="Disabled: No emails available to export."
          />
        </div>

        <!-- JSONL Buttons -->
        <div class="relative flex items-center gap-2 border-l pl-2 ml-2 dark:border-gray-700">
          <button
            class="inline-flex items-center gap-x-1.5 rounded-md bg-white dark:bg-gray-800 px-3 py-2 text-sm font-semibold text-gray-900 dark:text-gray-300 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="!stats.finetune_ready"
            @click="exportJsonl('train')"
          >
            <ArrowDownTrayIcon
              class="-ml-0.5 h-5 w-5 text-gray-400"
              aria-hidden="true"
            />
            JSONL (Train)
          </button>
          <button
            class="inline-flex items-center gap-x-1.5 rounded-md bg-white dark:bg-gray-800 px-3 py-2 text-sm font-semibold text-gray-900 dark:text-gray-300 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="!stats.finetune_ready"
            @click="exportJsonl('test')"
          >
            <ArrowDownTrayIcon
              class="-ml-0.5 h-5 w-5 text-gray-400"
              aria-hidden="true"
            />
            JSONL (Test)
          </button>

          <div class="relative flex items-center">
            <button
              class="inline-flex items-center gap-x-1.5 rounded-md bg-white dark:bg-gray-800 px-3 py-2 text-sm font-semibold text-gray-900 dark:text-gray-300 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="!stats.finetune_ready"
              @click="exportJsonl('all')"
            >
              <ArrowDownTrayIcon
                class="-ml-0.5 h-5 w-5 text-gray-400"
                aria-hidden="true"
              />
              JSONL (All)
            </button>
            <div class="ml-2 relative group">
              <QuestionMarkCircleIcon
                class="h-5 w-5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 cursor-help"
                :class="{'text-amber-500': !stats.finetune_ready}"
              />
              <!-- Tooltip on Hover -->
              <div
                class="absolute bottom-full right-0 mb-2 w-72 bg-white dark:bg-gray-800 p-3 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 z-50 text-xs hidden group-hover:block"
              >
                <div
                  v-if="!stats.finetune_ready"
                  class="mb-2 pb-2 border-b border-gray-100 dark:border-gray-700 text-amber-600 dark:text-amber-400 font-bold"
                >
                  Action Disabled:
                  <span class="font-normal text-gray-600 dark:text-gray-300 block mt-1">
                    You need at least {{ stats.finetune_min_required }} reviewed emails to generate a fine-tuning dataset.
                  </span>
                </div>
                <span class="font-semibold text-gray-900 dark:text-white block mb-2">Fine-tuning Best Practices:</span>
                <ul class="list-disc list-inside space-y-1 text-gray-600 dark:text-gray-300">
                  <li>Aim for at least {{ stats.finetune_min_required }} reviewed examples per category for stability.</li>
                  <li>Ensure examples are diverse and correctly labeled (validation is key).</li>
                  <li>For Phi-4 or GPT-4o-mini, quality > quantity. "Garbage in, garbage out".</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="flex flex-col sm:flex-row justify-between gap-4">
    <!-- Tabs -->
    <div class="flex space-x-2 overflow-x-auto pb-2 sm:pb-0">
      <button
        v-for="f in filters"
        :key="f.id"
        class="px-3 py-2 rounded-md text-sm font-medium whitespace-nowrap transition-colors"
        :class="filter === f.id ? 'ring-2 ring-primary-500 ring-offset-2 dark:ring-offset-gray-900 ' + f.color : 'bg-white text-gray-700 hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 shadow-sm'"
        @click="filter = f.id"
      >
        {{ f.label }}
      </button>
    </div>
    <!-- Search -->
    <div class="relative rounded-md shadow-sm max-w-xs w-full">
      <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
        <MagnifyingGlassIcon
          class="h-5 w-5 text-gray-400"
          aria-hidden="true"
        />
      </div>
      <input
        v-model="search"
        type="text"
        class="block w-full rounded-md border-0 py-1.5 pl-10 text-gray-900 ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:ring-gray-700 dark:text-white dark:placeholder-gray-500"
        placeholder="Search emails..."
      >
    </div>
  </div>

  <!-- Filters Row 2 -->
  <div class="flex flex-col sm:flex-row gap-4">
    <div class="flex-1">
      <label
        for="category-filter"
        class="sr-only"
      >Category</label>
      <input
        id="category-filter"
        v-model="categoryFilter"
        type="text"
        placeholder="Filter by Category Name..."
        class="block w-full rounded-md border-0 py-1.5 pl-3 text-gray-900 ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:ring-gray-700 dark:text-white dark:placeholder-gray-500"
      >
    </div>
    <div class="w-full sm:w-48">
      <label
        for="confidence-filter"
        class="sr-only"
      >Confidence</label>
      <select
        id="confidence-filter"
        v-model="confidenceFilter"
        class="block w-full rounded-md border-0 py-1.5 pl-3 pr-10 text-gray-900 ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:ring-gray-700 dark:text-white"
      >
        <option value="">
          Any Confidence
        </option>
        <option value="lt_10">
          &lt; 10% (Very Low)
        </option>
        <option value="lt_30">
          &lt; 30%
        </option>
        <option value="lt_50">
          &lt; 50%
        </option>
        <option value="lt_90">
          &lt; 90%
        </option>
        <option value="eq_100">
          100% (High)
        </option>
      </select>
    </div>
    <!-- View Mode Toggle -->
    <div class="flex bg-gray-100 dark:bg-gray-700 p-1 rounded-lg">
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
        Cards
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
        Table
      </button>
    </div>
  </div>

  <!-- Grid -->
  <div
    v-if="loading && !emails.length"
    class="text-center py-12"
  >
    <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto" />
    <p class="mt-4 text-gray-500 dark:text-gray-400">
      Loading emails...
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
      Waiting for Data
    </h3>
    <p class="text-sm text-gray-500 dark:text-gray-400 max-w-sm mb-4">
      The dashboard cannot retrieve emails. This usually means the database is initializing or empty.
    </p>
    <p class="text-xs text-gray-400 font-mono bg-white dark:bg-gray-900 px-3 py-2 rounded border border-gray-200 dark:border-gray-700">
      {{ error }}
    </p>
    <button
      class="mt-6 inline-flex items-center rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
      @click="fetchEmails"
    >
      Retry Connection
    </button>
  </div>

  <div
    v-else-if="!emails.length"
    class="text-center py-12 border-2 border-dashed border-gray-300 dark:border-gray-700 rounded-lg"
  >
    <ArrowDownTrayIcon class="mx-auto h-12 w-12 text-gray-400" />
    <h3 class="mt-2 text-sm font-semibold text-gray-900 dark:text-white">
      No emails found
    </h3>
    <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
      Upload PDF documents to start the classification pipeline (ensure Cloud Storage is connected).
    </p>
  </div>

  <!-- Cards View -->
  <div
    v-else-if="viewMode === 'cards'"
    class="grid gap-6 sm:grid-cols-2 lg:grid-cols-3"
  >
    <div
      v-for="email in emails"
      :key="email.id"
      :class="[
        'rounded-lg shadow-sm border hover:shadow-md transition-shadow flex flex-col h-full',
        email.test_mode
          ? 'bg-amber-50 dark:bg-amber-950/20 border-amber-300 dark:border-amber-700'
          : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700'
      ]"
    >
      <div class="p-5 flex-1">
        <!-- Test Mode Badge -->
        <div
          v-if="email.test_mode"
          class="mb-2"
        >
          <span class="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 rounded">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
              class="w-3 h-3"
            >
              <path
                fill-rule="evenodd"
                d="M8.5 3.528v4.644c0 .729-.29 1.428-.805 1.944l-1.217 1.216a8.75 8.75 0 013.55.621l.502.201a7.25 7.25 0 004.178.365l-2.403-2.403a2.75 2.75 0 01-.805-1.944V3.528a40.205 40.205 0 00-3 0zm4.5.084l.19.015a.75.75 0 10.12-1.495 41.364 41.364 0 00-6.62 0 .75.75 0 00.12 1.495L7 3.612v4.56c0 .331-.132.649-.366.883L2.6 13.09c-1.496 1.496-.817 4.15 1.403 4.475C5.961 17.852 7.963 18 10 18s4.039-.148 5.997-.436c2.22-.325 2.9-2.979 1.403-4.475l-4.034-4.034A1.25 1.25 0 0113 9.172V3.612z"
                clip-rule="evenodd"
              />
            </svg>
            TEST E2E
          </span>
          <span
            v-if="email.expected_category"
            class="ml-2 text-xs text-amber-700 dark:text-amber-400"
          >
            Expected: {{ email.expected_category }}
          </span>
        </div>
        <div class="flex justify-between items-start mb-2">
          <div class="flex flex-col gap-1">
            <span
              class="inline-flex items-center rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset w-fit"
              :class="getScoreColor(email)"
            >
              Score {{ getScore(email) }}
            </span>
            <span
              v-if="email.processing_time_ms"
              class="text-xs text-gray-400"
            >
              {{ Math.round(email.processing_time_ms) }}ms
            </span>
          </div>
          <span
            v-if="email.status === 'ERROR'"
            class="text-red-500"
            title="Error"
          >
            <ExclamationCircleIcon class="h-5 w-5" />
          </span>
          <span
            v-else-if="email.status === 'PROCESSED'"
            class="text-green-500"
            title="Processed"
          >
            <CheckCircleIcon class="h-5 w-5" />
          </span>
          <span
            v-else-if="email.status === 'REVIEW_REQUIRED'"
            class="text-amber-500"
            title="Review Required"
          >
            <ClockIcon class="h-5 w-5" />
          </span>
        </div>

        <h3
          class="text-lg font-medium text-gray-900 dark:text-white truncate mb-1"
          :title="email.subject"
        >
          {{ email.subject || 'No Subject' }}
        </h3>
        <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
          {{ email.sender || 'Unknown Sender' }}
        </p>

        <div class="mt-2 space-y-1">
          <div
            v-if="!(email.classification?.detected_intents || []).length"
            class="text-xs text-gray-400 dark:text-gray-500 italic"
          >
            Aucune catégorie détectée
          </div>
          <div
            v-for="intent in email.classification?.detected_intents || []"
            :key="intent.intent"
            class="flex justify-between text-xs"
          >
            <span
              class="text-gray-600 dark:text-gray-300 truncate pr-2"
              :title="intent.intent"
            >{{ intent.intent }}</span>
            <span class="font-mono text-gray-500 dark:text-gray-400">{{ (intent.confidence * 100).toFixed(0) }}%</span>
          </div>
        </div>
      </div>

      <div class="bg-gray-50 dark:bg-gray-700/50 px-5 py-3 border-t border-gray-200 dark:border-gray-700 flex justify-between items-center rounded-b-lg">
        <button
          class="text-sm font-medium text-primary-600 hover:text-primary-500 dark:text-primary-400"
          @click="emit('open-email', email)"
        >
          Open Details
        </button>
        <button
          class="text-xs font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 flex items-center gap-1"
          :disabled="reprocessingId === email.id"
          @click="reprocessEmail(email)"
        >
          <ArrowPathIcon
            class="h-4 w-4"
            :class="{'animate-spin': reprocessingId === email.id}"
          />
          Reprocess
        </button>
      </div>
    </div>
  </div>

  <div
    v-if="currentTab==='failures'"
    class="space-y-4 mt-4"
  >
    <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
      <h3 class="text-lg font-medium text-gray-900 dark:text-white mb-2 flex items-center gap-2">
        <ExclamationCircleIcon class="h-6 w-6 text-red-500" />
        Dead Letter Queue (Failures)
      </h3>
      <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
        These items failed processing and were moved to the Dead Letter Queue in Azure Service Bus.
        You can purge them by resetting the environment in Settings.
      </p>

      <div class="overflow-x-auto border rounded-md dark:border-gray-700">
        <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead class="bg-gray-50 dark:bg-gray-700">
            <tr>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Item ID / ID
              </th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Reason
              </th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Description
              </th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                Time
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
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <div
    v-if="currentTab==='developer'"
    class="space-y-4 mt-4"
  >
    <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-4">
      <div class="flex items-center justify-between">
        <h3 class="text-lg font-medium text-gray-900 dark:text-gray-100">
          Environment
        </h3>
        <button
          class="inline-flex items-center px-2 py-1 text-xs font-medium rounded-md bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-100"
          @click="fetchDiagnostics"
        >
          <ArrowPathIcon class="h-4 w-4 mr-1" /> Refresh
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
              readiness
            </td>
            <td class="py-1">
              <span :class="diagnostics.ok ? 'text-green-600 dark:text-green-300' : 'text-red-600 dark:text-red-300'">{{ diagnostics.ok ? 'OK' : 'NOT READY' }}</span>
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
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
            Subject / Sender
          </th>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
            Category
          </th>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
            Status
          </th>
          <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
            Date
          </th>
          <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
            Actions
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
          <td class="px-6 py-4 whitespace-nowrap">
            <div class="flex items-center gap-2">
              <div
                v-if="email.test_mode"
                class="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 rounded"
              >
                TEST
              </div>
              <div>
                <div class="text-sm font-medium text-gray-900 dark:text-white">
                  {{ email.subject || 'No Subject' }}
                </div>
                <div class="text-sm text-gray-500 dark:text-gray-400">
                  {{ email.sender || 'Unknown Sender' }}
                </div>
              </div>
            </div>
          </td>
          <td class="px-6 py-4">
            <div
              v-if="email.classification?.detected_intents?.length"
              class="flex flex-wrap gap-1"
            >
              <span
                v-for="(intent, idx) in email.classification.detected_intents.slice(0, 2)"
                :key="idx"
                class="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300"
              >
                {{ intent.intent }} ({{ Math.round(intent.confidence * 100) }}%)
              </span>
              <span
                v-if="email.classification.detected_intents.length > 2"
                class="text-xs text-gray-500 dark:text-gray-400"
              >
                +{{ email.classification.detected_intents.length - 2 }} more
              </span>
            </div>
            <span
              v-else
              class="text-sm text-gray-400 dark:text-gray-500"
            >
              None
            </span>
          </td>
          <td class="px-6 py-4 whitespace-nowrap">
            <span
              :class="[
                'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium',
                email.status === 'PROCESSED'
                  ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300'
                  : email.status === 'REVIEW_REQUIRED'
                    ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300'
                    : 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300'
              ]"
            >
              {{ email.status === 'REVIEW_REQUIRED' ? 'To Review' : email.status === 'PROCESSED' ? 'Processed' : 'Error' }}
            </span>
          </td>
          <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
            {{ email.updated_at ? new Date(email.updated_at).toLocaleString() : '—' }}
          </td>
          <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
            <button
              class="inline-flex items-center gap-1 text-primary-600 dark:text-primary-400 hover:text-primary-900 dark:hover:text-primary-300"
              @click="emit('open-email', email)"
            >
              <EyeIcon class="h-4 w-4" />
              View
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
          {{ opt }} / page
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
        Page <span class="font-medium">{{ page }}</span> of <span class="font-medium">{{ totalPages }}</span>
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
            <span class="font-medium text-sm">AI Assistant</span>
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
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>
        </div>

        <!-- Content -->
        <div class="p-4 flex-1 overflow-y-auto bg-gray-50 dark:bg-gray-800/50 min-h-[200px]">
          <div
            v-if="!chatResponse && !chatLoading"
            class="space-y-4"
          >
            <div class="bg-blue-50 dark:bg-blue-900/20 p-3 rounded-lg border border-blue-100 dark:border-blue-800 text-xs text-blue-800 dark:text-blue-200">
              <span class="font-bold block mb-1">How it works:</span>
              I can search the email database using tools (search, latest errors, stats, top intents). Ask me about processed emails.
            </div>
            <div>
              <p class="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-2 uppercase tracking-wider">
                Try Asking:
              </p>
              <div class="grid gap-2">
                <button
                  v-for="ex in ['Find emails about invoices', 'Show latest errors', 'What are the top intents?', 'Search text containing Urgent']"
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
            <div class="bg-white dark:bg-gray-800 px-4 py-3 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm flex items-center gap-2">
              <div class="animate-spin h-3 w-3 border-2 border-primary-600 border-t-transparent rounded-full" />
              <span class="text-xs text-gray-500">Searching database...</span>
            </div>
          </div>

          <div
            v-if="chatResponse"
            class="flex justify-start mt-2"
          >
            <div class="bg-white dark:bg-gray-800 px-4 py-3 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm max-w-[90%]">
              <div class="text-sm text-gray-800 dark:text-gray-200 whitespace-pre-wrap leading-relaxed">
                {{ chatResponse }}
              </div>
              <div class="mt-2 text-[10px] text-gray-400 border-t dark:border-gray-700 pt-1 flex items-center gap-1">
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
                Generated by Azure AI
              </div>
            </div>
          </div>

          <div
            v-if="chatError"
            class="mt-2 text-xs text-red-600 bg-red-50 dark:bg-red-900/20 p-2 rounded border border-red-100 dark:border-red-800"
          >
            Error: {{ chatError }}
          </div>
        </div>

        <!-- Footer -->
        <div class="p-3 bg-white dark:bg-gray-900 border-t border-gray-200 dark:border-gray-700">
          <div class="relative">
            <textarea
              v-model="chatQuery"
              rows="1"
              class="block w-full rounded-md border-0 py-2 pr-10 pl-3 text-gray-900 ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:ring-gray-700 dark:text-white resize-none"
              placeholder="Type your message..."
              @keydown.enter.exact.prevent="runChatSearch"
            />
            <button
              :disabled="!chatQuery.trim() || chatLoading"
              class="absolute bottom-1.5 right-1.5 p-1.5 rounded-md text-primary-600 hover:text-primary-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-100 dark:hover:bg-gray-700 transition"
              @click="runChatSearch"
            >
              <span class="sr-only">Send</span>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                class="w-5 h-5"
              >
                <path d="M3.105 2.289a.75.75 0 00-.826.95l1.414 4.925A1.5 1.5 0 005.135 9.25h6.115a.75.75 0 010 1.5H5.135a1.5 1.5 0 00-1.442 1.086l-1.414 4.926a.75.75 0 00.826.95 28.896 28.896 0 0015.293-7.154.75.75 0 000-1.115A28.897 28.897 0 003.105 2.289z" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      <button
        class="pointer-events-auto shadow-lg rounded-full w-14 h-14 bg-primary-600 hover:bg-primary-500 text-white flex items-center justify-center transition-transform hover:scale-105 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-600"
        :class="{'rotate-90': chatOpen}"
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
          <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
        </svg>
      </button>
    </div>
  </div>
</template>
