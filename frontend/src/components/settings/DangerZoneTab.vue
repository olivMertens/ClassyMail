<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useDialog } from '../../composables/useDialog'
import { trackException } from '../../services/telemetry'
import {
  ArrowPathIcon,
  CommandLineIcon,
  CpuChipIcon,
  ExclamationTriangleIcon,
  MagnifyingGlassIcon,
  TrashIcon
} from '@heroicons/vue/24/outline'

const props = defineProps({
  settings: { type: Object, required: true },
  loading: { type: Boolean, default: false }
})

const emit = defineEmits(['save'])

const { t } = useI18n()
const { confirm, alert: showAlert } = useDialog()

// ── Local state ─────────────────────────────────────────────────────
const resetConfirm1 = ref(false)
const resetConfirm2 = ref(false)
const resetting = ref(false)
const purgingDlq = ref(false)
const reprocessingAll = ref(false)
const reindexing = ref(false)
const connTestLoading = ref(false)
const connTestResults = ref(null)
const llmTestLoading = ref(false)
const llmTestResults = ref(null)
const acaValidationLoading = ref(false)
const acaValidationResults = ref(null)
const simulatingFlow = ref(false)
const useAoaiEnhancement = ref(false)

// ── Functions ───────────────────────────────────────────────────────

const performReset = async () => {
  if (!resetConfirm1.value || !resetConfirm2.value) return
  if (!await confirm('FINAL WARNING: This is irreversible. Proceed?')) return

  resetting.value = true
  try {
    const res = await fetch('/api/admin/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm_1: resetConfirm1.value, confirm_2: resetConfirm2.value })
    })
    if (res.ok) {
      const data = await res.json()
      await showAlert(`Reset Successful.\nDeleted Blobs: ${data.deleted_blobs}\nDeleted Records: ${data.deleted_records}\nPurged DLQ: ${data.deleted_dlq}`)
      window.location.reload()
    } else {
      showAlert('Reset Failed')
    }
  } catch (e) {
    trackException(e)
    showAlert(`Reset Error: ${e.message}`)
  } finally {
    resetting.value = false
  }
}

const performDlqPurge = async () => {
  if (!await confirm('Are you sure you want to purge the Service Bus Dead Letter Queue? This cannot be undone.')) return
  purgingDlq.value = true
  try {
    const res = await fetch('/api/admin/purge-dlq', { method: 'POST' })
    if (res.ok) {
      const data = await res.json()
      showAlert(`Purge Successful.\nDeleted Messages: ${data.deleted_dlq}`)
    } else {
      const err = await res.json()
      showAlert(`Purge Failed: ${err.detail || 'Unknown error'}`)
    }
  } catch (e) {
    trackException(e)
    showAlert(`Purge Error: ${e.message}`)
  } finally {
    purgingDlq.value = false
  }
}

const performReprocessAll = async () => {
  const model = props.settings?.ai_model || 'default'
  const strategy = props.settings?.processing_strategy || 'standard'
  const ok1 = await confirm(
    `This will save your current settings and reprocess ALL emails (PROCESSED + REVIEW_REQUIRED) with:\n\n• Model: ${model}\n• Strategy: ${strategy}\n\nExisting classifications will be overwritten.\nDead Letter Queue messages will also be replayed.\n\nDo you want to continue?`,
    'Reprocess All Emails'
  )
  if (!ok1) return
  const ok2 = await confirm('FINAL CONFIRMATION\n\nAll processed emails will be re-queued for classification. This cannot be undone.\n\nProceed?', 'Confirm Reprocess All')
  if (!ok2) return

  reprocessingAll.value = true
  try {
    emit('save')
    const res = await fetch('/api/admin/reprocess-all', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ processing_strategy: props.settings?.processing_strategy || null }),
    })
    if (res.ok) {
      const data = await res.json()
      await showAlert(`Reprocess All Complete\n\n• Emails enqueued: ${data.enqueued}\n• DLQ replayed: ${data.dlq_replayed}\n• Errors: ${data.errors?.length || 0}`)
    } else {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
      await showAlert(`Reprocess All Failed: ${err.detail || 'Unknown error'}`)
    }
  } catch (e) {
    trackException(e)
    await showAlert(`Reprocess All Error: ${e.message}`)
  } finally {
    reprocessingAll.value = false
  }
}

const performReindex = async () => {
  const ok = await confirm('This will rebuild the vector search index for ALL emails.\n\n• All existing chunks will be deleted\n• New embeddings will be generated for every email\n• This may take several minutes and use API quota\n\nProceed?', 'Rebuild Vector Index')
  if (!ok) return
  reindexing.value = true
  try {
    const res = await fetch('/api/admin/reindex-embeddings', { method: 'POST' })
    if (res.ok) {
      const data = await res.json()
      await showAlert(`Vector Index Rebuilt\n\n• Emails reindexed: ${data.emails_reindexed}\n• Old chunks deleted: ${data.chunks_deleted}\n• New chunks created: ${data.chunks_created}\n• Errors: ${data.errors?.length || 0}`)
    } else {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
      await showAlert(`Reindex Failed: ${err.detail || 'Unknown error'}`)
    }
  } catch (e) {
    trackException(e)
    await showAlert(`Reindex Error: ${e.message}`)
  } finally {
    reindexing.value = false
  }
}

const runConnectivityTest = async () => {
  connTestLoading.value = true
  connTestResults.value = null
  try {
    const res = await fetch('/api/admin/debug/connectivity', { method: 'POST' })
    if (res.ok) {
      connTestResults.value = await res.json()
      showAlert('Connectivity Test Complete. See results.')
    } else {
      const err = await res.json()
      showAlert(`Connectivity Test Failed: ${err.detail || 'Request failed'}`)
    }
  } catch (e) {
    trackException(e)
    showAlert(`Connectivity Error: ${e.message}`)
  } finally {
    connTestLoading.value = false
  }
}

const runLLMTests = async () => {
  llmTestLoading.value = true
  llmTestResults.value = null
  try {
    const chatModel = props.settings?.chat_model || 'gpt-5.2-chat'
    const responses = await Promise.all([
      fetch('/api/admin/test-phi4'),
      fetch('/api/admin/test-mistral-ocr'),
      fetch('/api/admin/test-gpt'),
      fetch('/api/admin/test-language-service'),
      fetch(`/api/admin/test-gpt?model=${encodeURIComponent(chatModel)}`)
    ])
    const [phi4Data, mistralData, gptData, languageData, chatData] = await Promise.all(responses.map(r => r.json()))
    llmTestResults.value = { phi4: phi4Data, mistral: mistralData, gpt: gptData, language: languageData, chat: chatData }
  } catch (e) {
    trackException(e)
    showAlert(`LLM Test Error: ${e.message}`)
  } finally {
    llmTestLoading.value = false
  }
}

const validateACAConfig = async () => {
  acaValidationLoading.value = true
  acaValidationResults.value = null
  try {
    const res = await fetch('/api/admin/validate-aca-env')
    if (res.ok) {
      acaValidationResults.value = await res.json()
      if (acaValidationResults.value.all_required_present) {
        showAlert('✓ ACA Configuration Valid: All required variables are present')
      } else {
        const missing = acaValidationResults.value.missing_required || []
        showAlert(`⚠ ACA Configuration Issue: Missing ${missing.length} required variable(s): ${missing.join(', ')}`)
      }
    } else {
      const err = await res.json()
      showAlert(`ACA Validation Failed: ${err.detail || 'Request failed'}`)
    }
  } catch (e) {
    trackException(e)
    showAlert(`ACA Validation Error: ${e.message}`)
  } finally {
    acaValidationLoading.value = false
  }
}

const performSimulateFlow = async () => {
  simulatingFlow.value = true
  try {
    const res = await fetch('/api/admin/debug/simulate-flow', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ use_aoai: useAoaiEnhancement.value })
    })
    if (res.ok) {
      const data = await res.json()
      const aoaiNote = useAoaiEnhancement.value ? ' (with AOAI enhancement)' : ' (template-based)'
      showAlert(`✓ E2E Simulation Complete${aoaiNote}\n\nBlob ID: ${data.item_id}\n\nYou can track this email in the Dashboard.`)
    } else {
      const err = await res.json()
      showAlert(`Simulation Failed: ${err.detail || 'Unknown error'}`)
    }
  } catch (e) {
    trackException(e)
    showAlert(`Simulation Error: ${e.message}`)
  } finally {
    simulatingFlow.value = false
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- Section 1: Maintenance & Diagnostics -->
    <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg border border-blue-200 dark:border-blue-900">
      <div class="px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-blue-600 dark:text-blue-400 flex items-center gap-2">
          <CommandLineIcon class="h-5 w-5" />
          {{ t('settings.danger.maintenance_title') }}
        </h3>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t('settings.danger.maintenance_desc') }}</p>

        <div class="mt-5">
          <h4 class="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-2">{{ t('settings.danger.diagnostics_title') }}</h4>
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t('settings.danger.diagnostics_desc') }}</p>
          <div class="mt-3 flex flex-wrap gap-2">
            <button type="button" class="inline-flex items-center rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50" :disabled="llmTestLoading" @click="runLLMTests">
              <ArrowPathIcon v-if="llmTestLoading" class="-ml-0.5 mr-1.5 h-4 w-4 animate-spin" />
              Test LLM Models
            </button>
            <button type="button" class="inline-flex items-center rounded-md bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-white dark:ring-gray-600 dark:hover:bg-gray-600 disabled:opacity-50" :disabled="connTestLoading" @click="runConnectivityTest">
              <ArrowPathIcon v-if="connTestLoading" class="-ml-0.5 mr-1.5 h-4 w-4 animate-spin" />
              Test Service Connectivity
            </button>
          </div>
          <div class="mt-3 flex items-center gap-4">
            <div class="flex items-center">
              <input id="use-aoai" v-model="useAoaiEnhancement" type="checkbox" class="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600">
              <label for="use-aoai" class="ml-2 block text-xs text-gray-700 dark:text-gray-300">Enhance with AOAI</label>
            </div>
            <button type="button" class="inline-flex items-center rounded-md bg-white px-3 py-2 text-sm font-semibold text-indigo-600 shadow-sm ring-1 ring-inset ring-indigo-300 hover:bg-indigo-50 dark:bg-gray-800 dark:text-indigo-400 dark:ring-indigo-900 dark:hover:bg-indigo-900/20 disabled:opacity-50" :disabled="simulatingFlow" @click="performSimulateFlow">
              <CpuChipIcon v-if="!simulatingFlow" class="-ml-0.5 mr-1.5 h-4 w-4" />
              <ArrowPathIcon v-else class="-ml-0.5 mr-1.5 h-4 w-4 animate-spin" />
              {{ simulatingFlow ? 'Simulating...' : 'Simulate E2E Flow' }}
            </button>
          </div>
          <div v-if="connTestResults" class="mt-3 p-3 bg-gray-50 dark:bg-gray-900 rounded text-xs font-mono overflow-auto max-h-40">
            <pre>{{ JSON.stringify(connTestResults, null, 2) }}</pre>
          </div>
          <div v-if="llmTestResults" class="mt-3 p-3 bg-gray-50 dark:bg-gray-900 rounded text-xs font-mono overflow-auto max-h-40">
            <pre>{{ JSON.stringify(llmTestResults, null, 2) }}</pre>
          </div>
        </div>

        <!-- ACA Validation -->
        <div class="mt-6 border-t border-gray-100 dark:border-gray-700 pt-5">
          <h4 class="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-2">{{ t('settings.danger.aca_title') }}</h4>
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t('settings.danger.aca_desc') }}</p>
          <div class="mt-3">
            <button type="button" class="inline-flex items-center rounded-md bg-gray-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-gray-500 disabled:opacity-50" :disabled="acaValidationLoading" @click="validateACAConfig">
              <ArrowPathIcon v-if="acaValidationLoading" class="-ml-0.5 mr-1.5 h-4 w-4 animate-spin" />
              Validate ACA Configuration
            </button>
          </div>
          <div v-if="acaValidationResults" class="mt-4 bg-gray-50 dark:bg-gray-900 rounded-lg p-4">
            <div class="mb-3 pb-3 border-b border-gray-200 dark:border-gray-700">
              <p class="text-sm font-medium text-gray-900 dark:text-gray-100">
                Status:
                <span :class="acaValidationResults.all_required_present ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'">
                  {{ acaValidationResults.all_required_present ? '✓ All Required Variables Present' : '✗ Missing Required Variables' }}
                </span>
              </p>
              <p class="text-xs text-gray-600 dark:text-gray-400 mt-1">
                Required: {{ acaValidationResults.summary?.required_present || 0 }}/{{ acaValidationResults.summary?.required_count || 0 }} •
                Optional: {{ acaValidationResults.summary?.optional_present || 0 }}/{{ acaValidationResults.summary?.optional_count || 0 }}
              </p>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <h5 class="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">Required Variables</h5>
                <div class="space-y-1">
                  <div v-for="item in acaValidationResults.required" :key="item.name" class="flex items-center text-xs font-mono">
                    <span :class="item.present ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'" class="w-4">{{ item.present ? '✓' : '✗' }}</span>
                    <span class="text-gray-700 dark:text-gray-300 flex-1">{{ item.name }}</span>
                    <span v-if="item.present" class="text-gray-500 text-xs truncate max-w-[150px]">{{ item.value }}</span>
                    <span v-else class="text-red-500 text-xs">NOT SET</span>
                  </div>
                </div>
              </div>
              <div>
                <h5 class="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">Optional Variables</h5>
                <div class="space-y-1">
                  <div v-for="item in acaValidationResults.optional" :key="item.name" class="flex items-center text-xs font-mono">
                    <span :class="item.present ? 'text-yellow-600 dark:text-yellow-400' : 'text-gray-400 dark:text-gray-600'" class="w-4">○</span>
                    <span class="text-gray-700 dark:text-gray-300 flex-1">{{ item.name }}</span>
                    <span v-if="item.present" class="text-gray-500 text-xs truncate max-w-[150px]">{{ item.value }}</span>
                    <span v-else class="text-gray-500 text-xs">not configured</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Section 2: Bulk Operations -->
    <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg border border-amber-200 dark:border-amber-900">
      <div class="px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-amber-600 dark:text-amber-400 flex items-center gap-2">
          <ArrowPathIcon class="h-5 w-5" />
          {{ t('settings.danger.bulk_title') }}
        </h3>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t('settings.danger.bulk_desc') }}</p>
        <div class="mt-5 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="p-4 rounded-lg bg-amber-50 dark:bg-amber-900/10 border border-amber-100 dark:border-amber-900/30">
            <h4 class="text-sm font-medium text-amber-700 dark:text-amber-400 flex items-center gap-2">
              <ArrowPathIcon class="h-4 w-4" />
              {{ t('settings.danger.reprocess_title') }}
            </h4>
            <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t('settings.danger.reprocess_desc') }}</p>
            <button type="button" :disabled="reprocessingAll" class="mt-3 inline-flex items-center gap-2 rounded-md bg-amber-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-amber-500 disabled:opacity-50" @click="performReprocessAll">
              <ArrowPathIcon class="h-4 w-4" :class="{ 'animate-spin': reprocessingAll }" />
              {{ reprocessingAll ? 'Reprocessing...' : 'Reprocess All Emails' }}
            </button>
          </div>
          <div class="p-4 rounded-lg bg-purple-50 dark:bg-purple-900/10 border border-purple-100 dark:border-purple-900/30">
            <h4 class="text-sm font-medium text-purple-700 dark:text-purple-400 flex items-center gap-2">
              <MagnifyingGlassIcon class="h-4 w-4" />
              {{ t('settings.danger.reindex_title') }}
            </h4>
            <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t('settings.danger.reindex_desc') }}</p>
            <button type="button" :disabled="reindexing" class="mt-3 inline-flex items-center gap-2 rounded-md bg-purple-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-purple-500 disabled:opacity-50" @click="performReindex">
              <ArrowPathIcon class="h-4 w-4" :class="{ 'animate-spin': reindexing }" />
              {{ reindexing ? t('settings.danger.reindex_running') : t('settings.danger.reindex_button') }}
            </button>
          </div>
        </div>
        <div class="mt-5 border-t border-gray-200 dark:border-gray-700 pt-5">
          <h4 class="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-2">
            <ExclamationTriangleIcon class="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
            {{ t('settings.danger.dlq_title') }}
          </h4>
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t('settings.danger.dlq_desc') }}</p>
          <div class="mt-3 flex gap-2">
            <a href="/api/admin/deadletter" target="_blank" class="inline-flex items-center rounded-md bg-yellow-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-yellow-500">{{ t('settings.danger.view_dlq') }}</a>
            <button type="button" class="inline-flex items-center rounded-md bg-white px-3 py-2 text-sm font-semibold text-yellow-600 shadow-sm ring-1 ring-inset ring-yellow-300 hover:bg-yellow-50 dark:bg-gray-800 dark:text-yellow-400 dark:ring-yellow-900 dark:hover:bg-yellow-900/20 disabled:opacity-50" :disabled="purgingDlq" @click="performDlqPurge">
              <TrashIcon v-if="!purgingDlq" class="-ml-0.5 mr-1.5 h-4 w-4" />
              <ArrowPathIcon v-else class="-ml-0.5 mr-1.5 h-4 w-4 animate-spin" />
              {{ purgingDlq ? 'Purging DLQ...' : t('settings.danger.purge_dlq') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Section 3: Destructive Operations -->
    <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg border-2 border-red-300 dark:border-red-900">
      <div class="px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-red-600 dark:text-red-400 flex items-center gap-2">
          <ExclamationTriangleIcon class="h-5 w-5" />
          {{ t('settings.danger.destructive_title') }}
        </h3>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t('settings.danger.destructive_desc') }}</p>
        <div class="mt-5 bg-red-50 dark:bg-red-900/20 p-4 rounded-md">
          <h4 class="text-sm font-medium text-red-800 dark:text-red-300 flex items-center gap-2">
            <ExclamationTriangleIcon class="h-4 w-4" />
            {{ t('settings.danger.reset_title') }}
          </h4>
          <p class="mt-1 text-xs text-gray-600 dark:text-gray-400">{{ t('settings.danger.reset_desc') }}</p>
          <h5 class="mt-3 text-xs font-semibold text-red-700 dark:text-red-300">{{ t('settings.danger.reset_warning_title') }}</h5>
          <ul class="list-disc list-inside mt-1 text-xs text-red-700 dark:text-red-200 space-y-0.5">
            <li>Delete ALL emails and classification records from Database.</li>
            <li>Delete ALL files (PDFs) from Input Storage Container.</li>
            <li><strong>Purge</strong> the Service Bus Dead-letter Queue.</li>
            <li>Reset the dashboard state completely.</li>
            <li><strong>Preserve</strong> application settings (Categories, Costs, etc).</li>
          </ul>
          <div class="mt-4 space-y-3">
            <div class="flex items-start">
              <input id="confirm_1" v-model="resetConfirm1" type="checkbox" class="mt-1 h-4 w-4 rounded border-gray-300 text-red-600 focus:ring-red-600 dark:bg-gray-700 dark:border-gray-600">
              <label for="confirm_1" class="ml-2 text-sm font-medium text-gray-900 dark:text-white">I understand this deletes all data permanently.</label>
            </div>
            <div class="flex items-start">
              <input id="confirm_2" v-model="resetConfirm2" type="checkbox" class="mt-1 h-4 w-4 rounded border-gray-300 text-red-600 focus:ring-red-600 dark:bg-gray-700 dark:border-gray-600">
              <label for="confirm_2" class="ml-2 text-sm font-medium text-gray-900 dark:text-white">I confirm I want to reset the environment.</label>
            </div>
            <button type="button" class="inline-flex items-center rounded-md bg-red-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed" :disabled="!resetConfirm1 || !resetConfirm2 || resetting" @click="performReset">
              <TrashIcon v-if="!resetting" class="-ml-0.5 mr-1.5 h-5 w-5" />
              <ArrowPathIcon v-else class="-ml-0.5 mr-1.5 h-5 w-5 animate-spin" />
              {{ resetting ? 'Nuking Environment...' : 'NUKE EVERYTHING' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
