<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowDownTrayIcon,
  QuestionMarkCircleIcon,
  TableCellsIcon,
  DocumentTextIcon
} from '@heroicons/vue/24/outline'
import { useDialog } from '../composables/useDialog'

const { t } = useI18n()
const { confirm: confirmDialog, alert: showAlert } = useDialog()

const stats = ref({
  total: 0,
  finetune_ready: false,
  finetune_min_required: 50,
  finetune_reviewed_ready: 0
})
const loading = ref(false)
const generating = ref(false) // Added generating state
const error = ref(null)

const exportFormat = ref('enriched')
const statusFilter = ref('all')
const exporting = ref(false)

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
    showAlert(e.message)
  }
}

const exportCsv = async () => {
  exporting.value = true
  try {
    const params = new URLSearchParams({
      status: statusFilter.value,
      format: exportFormat.value
    })
    await downloadFile(`/api/emails/export/csv?${params.toString()}`)
  } finally {
    exporting.value = false
  }
}

const exportJsonl = (split = 'all') => {
  downloadFile(`/api/emails/export-finetune-jsonl?anonymize=true&split=${split}`)
}

const generateSyntheticData = async () => {
  const ok = await confirmDialog(
    t('exports.finetune.generate_confirm',
      { fallback: 'This will use GPT-5.2 to generate synthetic emails based on your existing data to help you reach the minimum requirement. Continue?' })
  )
  if (!ok) return

  generating.value = true
  try {
    // Calculate how many we need based on reviewed-ready items vs minimum required
    const needed = Math.max(stats.value.finetune_min_required - stats.value.finetune_reviewed_ready, 5)

    const res = await fetch('/api/admin/generate-synthetic', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_count: needed })
    })

    if (res.ok) {
      const data = await res.json()
      await showAlert(data.message)
      fetchStats() // refresh
    } else {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
      await showAlert(t('exports.finetune.generate_error', { error: err.detail || 'Unknown error' }))
    }
  } catch (e) {
    await showAlert(t('exports.finetune.generate_error', { error: e.message }))
  } finally {
    generating.value = false
  }
}

const fetchStats = async () => {
  loading.value = true
  try {
    // Use /api/emails/stats which returns proper finetune fields
    const res = await fetch('/api/emails/stats')
    if (res.ok) {
      const data = await res.json()
      stats.value = {
        total: data.total || 0,
        finetune_ready: data.finetune_ready || false,
        finetune_min_required: data.finetune_min_required || 50,
        finetune_reviewed_ready: data.finetune_reviewed_ready || 0
      }
    } else {
      // Fallback to email list endpoint
      const resFull = await fetch('/api/emails?page_size=1')
      if (resFull.ok) {
        const d = await resFull.json()
        stats.value = {
          total: d.total || 0,
          finetune_ready: d.finetune_ready || false,
          finetune_min_required: d.finetune_min_required || 50,
          finetune_reviewed_ready: d.finetune_reviewed_ready || 0
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
        {{ t('exports.title') }}
      </h2>
      <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
        {{ t('exports.subtitle') }}
      </p>
    </div>

    <div class="grid gap-6 grid-cols-1">
      <!-- Human Reporting -->
      <div
        class="bg-white dark:bg-gray-800 shadow sm:rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700"
      >
        <div class="px-4 py-5 sm:px-6 bg-gray-50 dark:bg-gray-700/50">
          <div class="flex items-center gap-3">
            <div class="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg text-blue-600 dark:text-blue-400">
              <TableCellsIcon class="h-6 w-6" />
            </div>
            <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white">
              {{ t('exports.reporting.title') }}
            </h3>
          </div>
        </div>
        <div class="px-4 py-5 sm:p-6 space-y-4">
          <p class="text-sm text-gray-500 dark:text-gray-300">
            {{ t('exports.reporting.desc') }}
          </p>
          <div class="pt-2 space-y-3">
            <div class="flex flex-col sm:flex-row gap-3">
              <div class="flex-1">
                <label
                  class="sr-only"
                  for="export-format"
                >{{ t('exports.reporting.format_label') }}</label>
                <select
                  id="export-format"
                  v-model="exportFormat"
                  class="block w-full rounded-md border-0 py-2 pl-3 pr-10 text-gray-900 ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:ring-gray-600 dark:text-white"
                >
                  <option value="minimal">
                    {{ t('exports.reporting.format_minimal') }}
                  </option>
                  <option value="enriched">
                    {{ t('exports.reporting.format_enriched') }}
                  </option>
                </select>
              </div>
              <div class="flex-1">
                <label
                  class="sr-only"
                  for="export-status"
                >{{ t('exports.reporting.status_label') }}</label>
                <select
                  id="export-status"
                  v-model="statusFilter"
                  class="block w-full rounded-md border-0 py-2 pl-3 pr-10 text-gray-900 ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:ring-gray-600 dark:text-white"
                >
                  <option value="all">
                    {{ t('exports.reporting.status_all') }}
                  </option>
                  <option value="REVIEW_REQUIRED">
                    {{ t('exports.reporting.status_review') }}
                  </option>
                  <option value="PROCESSED">
                    {{ t('exports.reporting.status_processed') }}
                  </option>
                  <option value="ERROR">
                    {{ t('exports.reporting.status_error') }}
                  </option>
                </select>
              </div>
              <button
                type="button"
                class="inline-flex w-full sm:w-auto justify-center items-center gap-x-2 rounded-md bg-white dark:bg-gray-700 px-3.5 py-2.5 text-sm font-semibold text-gray-900 dark:text-white shadow-sm ring-1 ring-inset ring-gray-300 dark:ring-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50"
                :disabled="stats.total === 0 || exporting"
                @click="exportCsv"
              >
                <ArrowDownTrayIcon
                  class="-ml-0.5 h-5 w-5 text-gray-400"
                  aria-hidden="true"
                />
                {{ exporting ? t('exports.reporting.button_loading') : t('exports.reporting.button') }}
              </button>
            </div>
            <p
              v-if="stats.total === 0"
              class="mt-2 text-xs text-amber-500 text-center"
            >
              {{ t('exports.reporting.empty') }}
            </p>
          </div>
        </div>
      </div>

      <!-- Machine Learning Info -->
      <div
        class="bg-white dark:bg-gray-800 shadow sm:rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700"
      >
        <div class="px-4 py-5 sm:px-6 bg-gray-50 dark:bg-gray-700/50">
          <div class="flex items-center gap-3">
            <div class="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg text-purple-600 dark:text-purple-400">
              <DocumentTextIcon class="h-6 w-6" />
            </div>
            <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white">
              {{ t('exports.finetune.title') }}
            </h3>
          </div>
        </div>
        <div class="px-4 py-5 sm:p-6 space-y-4">
          <p class="text-sm text-gray-500 dark:text-gray-300">
            {{ t('exports.finetune.desc', { n: stats.finetune_min_required }) }}
            <span class="block mt-1 text-xs text-gray-400">{{ t('exports.finetune.split_hint') }}</span>
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
                {{ t('exports.finetune.train') }}
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
                {{ t('exports.finetune.test') }}
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
              {{ t('exports.finetune.all') }}
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
                  {{ t('exports.finetune.requirement_title') }}
                </h3>
                <div class="mt-2 text-sm text-amber-700 dark:text-amber-200">
                  <p>{{ t('exports.finetune.requirement_desc', { n: stats.finetune_min_required }) }}</p>
                </div>
                <!-- Generator Button -->
                <div class="mt-3">
                  <button
                    type="button"
                    class="rounded-md bg-amber-100 dark:bg-amber-800 px-2 py-1.5 text-sm font-medium text-amber-800 dark:text-amber-100 hover:bg-amber-200 dark:hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2 dark:focus:ring-offset-gray-900 disabled:opacity-50"
                    :disabled="generating"
                    @click="generateSyntheticData"
                  >
                    <span v-if="!generating">{{ t('exports.finetune.generate') }}</span>
                    <span v-else>{{ t('exports.finetune.generating') }}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
