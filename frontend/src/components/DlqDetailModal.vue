<script setup>
import { XMarkIcon } from '@heroicons/vue/24/outline'
import { trackException } from '../services/telemetry'

defineProps({
  show: { type: Boolean, default: false },
  message: { type: Object, default: null }
})
const emit = defineEmits(['close', 'reprocess'])

const formatTime = (t) => {
  if (!t) return '—'
  try {
    return new Date(t).toLocaleString()
  } catch (e) {
    console.error('Date formatting error:', e)
    trackException(e)
    return t
  }
}

const statusColor = (s) => {
  if (!s) return 'text-gray-400'
  const lc = s.toLowerCase()
  if (lc === 'error') return 'text-red-500 dark:text-red-400'
  if (lc === 'processing') return 'text-blue-500 dark:text-blue-400'
  if (lc === 'processed') return 'text-green-500 dark:text-green-400'
  return 'text-gray-500 dark:text-gray-400'
}

const stageIcon = (stage) => {
  const icons = { download: '📥', ocr: '🔍', classification: '🧠', pii: '🔒', worker: '⚙️', simulation: '🧪' }
  return icons[stage] || '📋'
}
</script>

<template>
  <div
    v-if="show && message"
    class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900 bg-opacity-75 p-4 backdrop-blur-sm"
    @click.self="emit('close')"
  >
    <div
      class="relative w-full max-w-3xl bg-white dark:bg-gray-900 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 overflow-hidden transform transition-all"
    >
      <div class="px-5 py-4 flex items-center justify-between border-b border-gray-200 dark:border-gray-700">
        <h3 class="text-lg font-semibold text-gray-900 dark:text-white">
          Dead Letter Details
        </h3>
        <button
          class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
          @click="emit('close')"
        >
          <XMarkIcon class="h-6 w-6" />
        </button>
      </div>

      <div class="p-5 space-y-4 text-sm text-gray-800 dark:text-gray-200 max-h-[70vh] overflow-y-auto">
        <!-- Identity -->
        <div class="grid grid-cols-2 gap-4">
          <div>
            <div class="text-gray-500 text-xs uppercase">
              Blob ID
            </div>
            <div class="font-mono break-all">
              {{ message.blob_id || '—' }}
            </div>
          </div>
          <div>
            <div class="text-gray-500 text-xs uppercase">
              Message ID
            </div>
            <div class="font-mono break-all">
              {{ message.message_id || '—' }}
            </div>
          </div>
          <div>
            <div class="text-gray-500 text-xs uppercase">
              Reason
            </div>
            <div class="text-red-600 dark:text-red-300">
              {{ message.dead_letter_reason || '—' }}
            </div>
          </div>
          <div>
            <div class="text-gray-500 text-xs uppercase">
              Enqueued
            </div>
            <div>{{ formatTime(message.enqueued_time_utc) }}</div>
          </div>
        </div>

        <!-- Service Bus Metadata -->
        <div>
          <div class="text-gray-500 text-xs uppercase mb-1">
            Service Bus Metadata
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-3 gap-3 bg-gray-50 dark:bg-gray-800 p-3 rounded border border-gray-200 dark:border-gray-700 text-xs">
            <div>
              <span class="text-gray-400">Delivery Count</span>
              <div
                class="font-mono font-semibold"
                :class="message.delivery_count > 3 ? 'text-red-500' : 'text-gray-700 dark:text-gray-300'"
              >
                {{ message.delivery_count ?? '—' }}
              </div>
            </div>
            <div>
              <span class="text-gray-400">Sequence #</span>
              <div class="font-mono text-gray-700 dark:text-gray-300">
                {{ message.sequence_number ?? '—' }}
              </div>
            </div>
            <div v-if="message.dead_letter_source">
              <span class="text-gray-400">DLQ Source</span>
              <div class="font-mono text-gray-700 dark:text-gray-300">
                {{ message.dead_letter_source }}
              </div>
            </div>
            <div v-if="message.content_type">
              <span class="text-gray-400">Content Type</span>
              <div class="font-mono text-gray-700 dark:text-gray-300">
                {{ message.content_type }}
              </div>
            </div>
            <div v-if="message.subject">
              <span class="text-gray-400">Subject</span>
              <div class="font-mono text-gray-700 dark:text-gray-300">
                {{ message.subject }}
              </div>
            </div>
            <div v-if="message.correlation_id">
              <span class="text-gray-400">Correlation ID</span>
              <div class="font-mono break-all text-gray-700 dark:text-gray-300">
                {{ message.correlation_id }}
              </div>
            </div>
          </div>
        </div>

        <!-- Application Properties (custom headers) -->
        <div v-if="message.application_properties && Object.keys(message.application_properties).length">
          <div class="text-gray-500 text-xs uppercase mb-1">
            Application Properties (Headers)
          </div>
          <div class="bg-gray-50 dark:bg-gray-800 p-3 rounded border border-gray-200 dark:border-gray-700">
            <div
              v-for="(val, key) in message.application_properties"
              :key="key"
              class="flex justify-between text-xs py-0.5 border-b border-gray-100 dark:border-gray-700 last:border-b-0"
            >
              <span class="text-gray-500 font-mono">{{ key }}</span>
              <span class="text-gray-700 dark:text-gray-300 font-mono break-all ml-2">{{ val }}</span>
            </div>
          </div>
        </div>

        <!-- Cosmos DB Status (if worker saved error before DLQ) -->
        <div v-if="message.cosmos_status || message.cosmos_error || message.cosmos_error_stage">
          <div class="text-gray-500 text-xs uppercase mb-1">
            Worker Error Record (Cosmos DB)
          </div>
          <div class="bg-gray-50 dark:bg-gray-800 p-3 rounded border border-gray-200 dark:border-gray-700 text-xs space-y-1">
            <div class="flex gap-4">
              <div>
                <span class="text-gray-400">Status:</span>
                <span
                  class="ml-1 font-semibold"
                  :class="statusColor(message.cosmos_status)"
                >{{ message.cosmos_status || '—' }}</span>
              </div>
              <div v-if="message.cosmos_error_stage">
                <span class="text-gray-400">Failed Stage:</span>
                <span class="ml-1 font-mono text-orange-500 dark:text-orange-400">{{ message.cosmos_error_stage }}</span>
              </div>
            </div>
            <div
              v-if="message.cosmos_error"
              class="mt-1"
            >
              <span class="text-gray-400">Error:</span>
              <pre class="whitespace-pre-wrap text-red-600 dark:text-red-300 mt-0.5 font-mono">{{ message.cosmos_error }}</pre>
            </div>
          </div>
        </div>

        <!-- Error description -->
        <div>
          <div class="text-gray-500 text-xs uppercase mb-1">
            Dead Letter Description
          </div>
          <pre
            class="whitespace-pre-wrap bg-gray-50 dark:bg-gray-800 p-3 rounded border border-gray-200 dark:border-gray-700 text-xs font-mono max-h-60 overflow-auto"
          >{{ message.dead_letter_error_description || '—' }}</pre>
        </div>

        <!-- Processing Log -->
        <div v-if="message.processing_log?.length">
          <div class="text-gray-500 text-xs uppercase mb-1">
            Processing Log ({{ message.processing_log.length }} entries)
          </div>
          <div class="space-y-1.5 text-xs font-mono">
            <div
              v-for="(entry, idx) in message.processing_log"
              :key="idx"
              class="bg-gray-50 dark:bg-gray-800 p-2 rounded border border-gray-200 dark:border-gray-700"
              :class="entry.event === 'error' || entry.event === 'mistral_failed' ? 'border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/20' : ''"
            >
              <div class="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                <span>{{ stageIcon(entry.stage) }}</span>
                <span class="font-semibold text-gray-800 dark:text-gray-200">{{ entry.stage || '—' }}</span>
                <span class="text-gray-400">·</span>
                <span :class="entry.event === 'error' ? 'text-red-500' : entry.event === 'ok' || entry.event === 'fallback_ok' ? 'text-green-500' : ''">
                  {{ entry.event || '—' }}
                </span>
                <span class="ml-auto text-gray-400 text-[10px]">{{ formatTime(entry.ts) }}</span>
              </div>
              <div
                v-if="entry.detail || entry.details"
                class="mt-1 text-gray-600 dark:text-gray-400 break-all"
              >
                {{ entry.detail || entry.details }}
              </div>
            </div>
          </div>
        </div>
        <div
          v-else
          class="text-xs text-gray-400 italic"
        >
          No processing log available — the worker may not have reached the pipeline stage before failing.
        </div>

        <!-- Body Preview -->
        <div v-if="message.body_preview">
          <div class="text-gray-500 text-xs uppercase mb-1">
            Message Body Preview
          </div>
          <pre
            class="whitespace-pre-wrap bg-gray-50 dark:bg-gray-800 p-3 rounded border border-gray-200 dark:border-gray-700 text-xs font-mono max-h-40 overflow-auto text-gray-600 dark:text-gray-400"
          >{{ message.body_preview }}</pre>
        </div>
      </div>

      <div class="px-5 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 flex justify-end gap-3">
        <button
          v-if="message?.blob_id"
          class="inline-flex items-center px-4 py-2 text-sm font-medium rounded-md bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-200 border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
          @click="$emit('reprocess', message)"
        >
          Reprocess
        </button>
        <button
          class="inline-flex items-center px-4 py-2 text-sm font-medium rounded-md bg-primary-600 text-white hover:bg-primary-500 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
          @click="emit('close')"
        >
          Close
        </button>
      </div>
    </div>
  </div>
</template>
