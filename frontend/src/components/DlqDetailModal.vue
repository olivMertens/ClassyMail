<script setup>
import { XMarkIcon } from '@heroicons/vue/24/outline'
import { trackException } from '../services/telemetry'

defineProps({
  show: { type: Boolean, default: false },
  message: { type: Object, default: null }
})
const emit = defineEmits(['close'])

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

        <div>
          <div class="text-gray-500 text-xs uppercase mb-1">
            Description
          </div>
          <pre
            class="whitespace-pre-wrap bg-gray-50 dark:bg-gray-800 p-3 rounded border border-gray-200 dark:border-gray-700 text-xs font-mono max-h-60 overflow-auto"
          >{{ message.dead_letter_error_description || '—' }}</pre>
        </div>

        <div v-if="message.processing_log?.length">
          <div class="text-gray-500 text-xs uppercase mb-1">
            Processing Log
          </div>
          <div class="space-y-2 text-xs font-mono">
            <div
              v-for="(entry, idx) in message.processing_log"
              :key="idx"
              class="bg-gray-50 dark:bg-gray-800 p-2 rounded border border-gray-200 dark:border-gray-700"
            >
              <div>Status: {{ entry.status_code }} | Attempt: {{ entry.attempt }}</div>
              <div>Headers: {{ entry.headers }}</div>
              <div class="mt-1">
                {{ entry.text_snippet }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="px-5 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 flex justify-end">
        <button
          class="inline-flex items-center px-4 py-2 text-sm font-medium rounded-md bg-primary-600 text-white hover:bg-primary-500"
          @click="emit('close')"
        >
          Close
        </button>
      </div>
    </div>
  </div>
</template>
