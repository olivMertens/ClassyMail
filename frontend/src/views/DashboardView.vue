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
  ArrowPathIcon
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
const showFinetuneHelp = ref(false)
const filter = ref('all')
const search = ref('')
const categoryFilter = ref('')
const confidenceFilter = ref('')
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref(null)
const reprocessingId = ref(null)

const pageSizeOptions = [20, 50, 100]

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
        stats.value = {
            total: data.total || 0,
            review_required: data.review_required || 0,
            processed: data.processed || ((data.total||0) - (data.review_required||0)),
            finetune_ready: data.finetune_ready || false,
            average_confidence: data.average_confidence || 0,
            finetune_min_required: data.finetune_min_required || 50
        }
    } catch (e) {
        console.error(e)
        error.value = e.message
    } finally {
        loading.value = false
    }
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
    // Poll every 30s
    const poll = setInterval(fetchEmails, 30000)
    return () => clearInterval(poll)
})

const totalPages = computed(() => Math.max(1, Math.ceil(stats.value.total / pageSize.value)))

const progressPercentage = computed(() => {
    if (!stats.value.total) return 0
    return Math.round((stats.value.processed / stats.value.total) * 100)
})

const formatDate = (dateString) => {
    if (!dateString) return ''
    return new Date(dateString).toLocaleString()
}

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
    <!-- Stats Cards -->
    <dl class="mt-5 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
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
  <!-- Fine-tuning Advice -->
  <div class="bg-blue-50 dark:bg-blue-900/20 p-3 rounded-md border border-blue-100 dark:border-blue-800 text-xs text-blue-800 dark:text-blue-200 flex flex-col gap-1">
    <span class="font-semibold">Fine-tuning Best Practices:</span>
    <ul class="list-disc list-inside ml-1">
      <li>Aim for at least {{ stats.finetune_min_required }} reviewed examples per category for stability.</li>
      <li>Ensure examples are diverse and correctly labeled (validation is key).</li>
      <li>For Phi-4 or GPT-4o-mini, quality > quantity. "Garbage in, garbage out".</li>
    </ul>
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

  <div
    v-else
    class="grid gap-6 sm:grid-cols-2 lg:grid-cols-3"
  >
    <div
      v-for="email in emails"
      :key="email.id"
      class="bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 hover:shadow-md transition-shadow flex flex-col h-full"
    >
      <div class="p-5 flex-1">
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
  </div>
</template>
