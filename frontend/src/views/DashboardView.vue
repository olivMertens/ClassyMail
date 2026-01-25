<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { 
  MagnifyingGlassIcon, 
  ChevronLeftIcon, 
  ChevronRightIcon,
  CheckCircleIcon,
  ExclamationCircleIcon,
  ClockIcon
} from '@heroicons/vue/24/outline'

const props = defineProps(['active'])

const emails = ref([])
const stats = ref({ total: 0, review_required: 0, processed: 0 })
const filter = ref('all')
const search = ref('')
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const pageSizeOptions = [20, 50, 100, 250]

const filters = [
  { id: 'all', label: 'All', color: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300' },
  { id: 'REVIEW_REQUIRED', label: 'To Review', color: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300' },
  { id: 'PROCESSED', label: 'Processed', color: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300' },
  { id: 'ERROR', label: 'Errors', color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300' },
]

const fetchEmails = async () => {
    loading.value = true
    try {
        const params = new URLSearchParams()
        params.set('status', filter.value === 'all' ? 'all' : filter.value)
        params.set('page', page.value)
        params.set('page_size', pageSize.value)
        if (search.value) params.set('search', search.value)
        
        const res = await fetch(`/api/emails?${params.toString()}`)
        if (!res.ok) throw new Error('Failed to fetch')
        const data = await res.json()
        
        emails.value = data.items || []
        stats.value = {
            total: data.total || 0,
            review_required: data.review_required || 0,
            processed: data.processed || ((data.total||0) - (data.review_required||0))
        }
    } catch (e) {
        console.error(e)
    } finally {
        loading.value = false
    }
}

// Watchers
watch([filter, pageSize], () => {
    page.value = 1
    fetchEmails()
})

// Debounce search
let timeout
watch(search, () => {
    clearTimeout(timeout)
    timeout = setTimeout(() => {
        page.value = 1
        fetchEmails()
    }, 300)
})

onMounted(() => {
    fetchEmails()
    // Poll every 15s
    const poll = setInterval(fetchEmails, 15000)
    return () => clearInterval(poll)
})

const totalPages = computed(() => Math.max(1, Math.ceil(stats.value.total / pageSize.value)))

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
    <div class="grid grid-cols-1 gap-5 sm:grid-cols-3">
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
    </div>

    <!-- Toolbar -->
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
            <span
              class="inline-flex items-center rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset"
              :class="getScoreColor(email)"
            >
              Score {{ getScore(email) }}
            </span>
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
             
          <div class="text-xs text-gray-400 dark:text-gray-500 mb-2">
            {{ formatDate(email.created_at) }}
          </div>

          <div
            v-if="email.error"
            class="mt-2 text-xs text-red-600 dark:text-red-400 line-clamp-2"
          >
            {{ email.error }}
          </div>
        </div>
          
        <div class="bg-gray-50 dark:bg-gray-700/50 px-5 py-3 border-t border-gray-200 dark:border-gray-700 flex justify-between items-center rounded-b-lg">
          <button
            class="text-sm font-medium text-primary-600 hover:text-primary-500 dark:text-primary-400"
            @click="emit('open-email', email)"
          >
            Open Details
          </button>
          <!-- Reprocess button could go here -->
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
  </div>
</template>
