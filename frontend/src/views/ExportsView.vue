<script setup>
import { ref, onMounted } from 'vue'
import {
  ArrowDownTrayIcon,
  QuestionMarkCircleIcon,
  TableCellsIcon,
  DocumentTextIcon
} from '@heroicons/vue/24/outline'

const stats = ref({
    total: 0,
    finetune_ready: false,
    finetune_min_required: 50
})
const loading = ref(false)
const error = ref(null)

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
        alert(e.message)
    }
}

const exportCsv = () => {
    downloadFile('/api/emails/export', 'emails.csv')
}

const exportJsonl = (split = 'all') => {
    downloadFile(`/api/emails/export-finetune-jsonl?anonymize=true&split=${split}`)
}

const fetchStats = async () => {
    loading.value = true
    try {
        // Use admin summary endpoint for lightweight stats
        let data = {}
        const res2 = await fetch('/api/admin/stats/summary')
        if (res2.ok) {
             data = await res2.json()
             // Map backend stats to frontend expectations
             stats.value = {
                total: data.total || 0,
                finetune_ready: (data.processed || 0) >= 50, // rough check, ideally backend provides this flag
                finetune_min_required: 50
             }
        } else {
             // Fallback to searching emails if admin endpoint fails or is different
             const resFull = await fetch('/api/emails?page_size=1')
             if (resFull.ok) {
                const d = await resFull.json()
                stats.value = {
                    total: d.total || 0,
                    finetune_ready: d.finetune_ready || false,
                    finetune_min_required: d.finetune_min_required || 50
                }
             }
        }
    } catch (e) {
        error.value = e.message
    } finally {
        loading.value = false
    }
}

onMounted(() => {
    fetchStats()
})
</script>

<template>
  <div class="w-full mx-auto space-y-6 px-4 sm:px-6 lg:px-8">
    <div>
      <h2 class="text-2xl font-bold leading-7 text-gray-900 dark:text-white sm:truncate sm:text-3xl sm:tracking-tight">
        Data Exports
      </h2>
      <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
        Export your processed data for reporting, analysis, or fine-tuning custom AI models.
      </p>
    </div>

    <div class="grid gap-6 grid-cols-1">
      <!-- Human Reporting -->
      <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
        <div class="px-4 py-5 sm:px-6 bg-gray-50 dark:bg-gray-700/50">
          <div class="flex items-center gap-3">
            <div class="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg text-blue-600 dark:text-blue-400">
              <TableCellsIcon class="h-6 w-6" />
            </div>
            <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white">
              Reporting Data
            </h3>
          </div>
        </div>
        <div class="px-4 py-5 sm:p-6 space-y-4">
          <p class="text-sm text-gray-500 dark:text-gray-300">
            Download all processed emails, including classification results, metadata, and validation status in CSV format.
            Ideal for Excel, PowerBI, or manual audit.
          </p>
          <div class="pt-2">
            <button
              class="inline-flex w-full justify-center items-center gap-x-2 rounded-md bg-white dark:bg-gray-700 px-3.5 py-2.5 text-sm font-semibold text-gray-900 dark:text-white shadow-sm ring-1 ring-inset ring-gray-300 dark:ring-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50"
              :disabled="stats.total === 0"
              @click="exportCsv"
            >
              <ArrowDownTrayIcon
                class="-ml-0.5 h-5 w-5 text-gray-400"
                aria-hidden="true"
              />
              Download CSV Report
            </button>
            <p
              v-if="stats.total === 0"
              class="mt-2 text-xs text-amber-500 text-center"
            >
              No data available to export.
            </p>
          </div>
        </div>
      </div>

      <!-- Machine Learning Info -->
      <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
        <div class="px-4 py-5 sm:px-6 bg-gray-50 dark:bg-gray-700/50">
          <div class="flex items-center gap-3">
            <div class="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg text-purple-600 dark:text-purple-400">
              <DocumentTextIcon class="h-6 w-6" />
            </div>
            <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white">
              Fine-Tuning Datasets
            </h3>
          </div>
        </div>
        <div class="px-4 py-5 sm:p-6 space-y-4">
          <p class="text-sm text-gray-500 dark:text-gray-300">
            Export anonymized data in JSONL format compatible with OpenAI/Azure OpenAI fine-tuning.
            Requires at least {{ stats.finetune_min_required }} processed items.
            <span class="block mt-1 text-xs text-gray-400">Auto-split: 80% Train, 20% Test.</span>
          </p>

          <div class="flex flex-col gap-2 pt-2">
            <div class="flex gap-2">
              <button
                class="flex-1 inline-flex justify-center items-center gap-x-1.5 rounded-md bg-purple-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-600 disabled:opacity-50 disabled:bg-gray-300 dark:disabled:bg-gray-700"
                :disabled="!stats.finetune_ready"
                @click="exportJsonl('train')"
              >
                <ArrowDownTrayIcon
                  class="h-4 w-4"
                  aria-hidden="true"
                />
                Train Set
              </button>
              <button
                class="flex-1 inline-flex justify-center items-center gap-x-1.5 rounded-md bg-purple-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-600 disabled:opacity-50 disabled:bg-gray-300 dark:disabled:bg-gray-700"
                :disabled="!stats.finetune_ready"
                @click="exportJsonl('test')"
              >
                <ArrowDownTrayIcon
                  class="h-4 w-4"
                  aria-hidden="true"
                />
                Test Set
              </button>
            </div>
            <button
              class="w-full inline-flex justify-center items-center gap-x-1.5 rounded-md bg-white dark:bg-gray-700 px-3 py-2 text-sm font-semibold text-gray-900 dark:text-white shadow-sm ring-1 ring-inset ring-gray-300 dark:ring-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50"
              :disabled="!stats.finetune_ready"
              @click="exportJsonl('all')"
            >
              <ArrowDownTrayIcon
                class="h-4 w-4 text-gray-400"
                aria-hidden="true"
              />
              Download Complete Dataset (JSONL)
            </button>
          </div>

          <div
            v-if="!stats.finetune_ready"
            class="rounded-md bg-amber-50 dark:bg-amber-900/30 p-3"
          >
            <div class="flex">
              <div class="flex-shrink-0">
                <QuestionMarkCircleIcon
                  class="h-5 w-5 text-amber-400"
                  aria-hidden="true"
                />
              </div>
              <div class="ml-3">
                <h3 class="text-sm font-medium text-amber-800 dark:text-amber-300">
                  Start Requirement
                </h3>
                <div class="mt-2 text-sm text-amber-700 dark:text-amber-200">
                  <p>You need {{ stats.finetune_min_required }} processed emails to enable dataset generation.</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
