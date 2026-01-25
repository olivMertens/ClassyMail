<script setup>
import { ref, watch, onMounted } from 'vue'
import { XMarkIcon, ArrowPathIcon } from '@heroicons/vue/24/outline'
import MarkdownIt from 'markdown-it'

const props = defineProps(['emailId', 'isOpen'])
const emit = defineEmits(['close', 'updated'])

const md = new MarkdownIt({ html: true, linkify: true, breaks: true })

const email = ref(null)
const loading = ref(false)
const reprocessing = ref(false)
const intentsJson = ref('[]')

const loadEmail = async () => {
    if (!props.emailId) return
    loading.value = true
    try {
        const res = await fetch(`/api/emails/${props.emailId}`)
        if (res.ok) {
            email.value = await res.json()
            intentsJson.value = JSON.stringify(email.value.classification?.detected_intents || [], null, 2)
        }
    } catch (e) {
        console.error(e)
    } finally {
        loading.value = false
    }
}

const reprocess = async () => {
    if (!email.value) return
    reprocessing.value = true
    try {
        const res = await fetch(`/api/emails/${email.value.id}/reprocess`, { method: 'POST' })
        if (res.ok) {
            alert('Reprocessing started')
            emit('close')
        } else {
            alert('Error reprocessing')
        }
    } catch (e) {
        alert('Error reprocessing')
    } finally {
        reprocessing.value = false
    }
}

const saveIntents = async () => {
    if (!email.value) return
    try {
        let intents = JSON.parse(intentsJson.value)
        const payload = { intents }
        const res = await fetch(`/api/emails/${email.value.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        if (res.ok) {
            emit('updated')
            emit('close')
        }
    } catch (e) {
        alert('Invalid JSON')
    }
}

watch(() => props.isOpen, (newVal) => {
    if (newVal) {
        loadEmail()
    } else {
        email.value = null
    }
})

const renderMarkdown = (text) => md.render(text || '')
</script>

<template>
  <div
    v-if="isOpen"
    class="relative z-50"
    aria-labelledby="modal-title"
    role="dialog"
    aria-modal="true"
  >
    <div class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" />

    <div class="fixed inset-0 z-10 w-screen overflow-y-auto">
      <div class="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
        <div class="relative transform overflow-hidden rounded-lg bg-white dark:bg-gray-900 text-left shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-6xl h-[90vh] flex flex-col">
          <!-- Header -->
          <div class="bg-gray-50 dark:bg-gray-800 px-4 py-3 sm:px-6 flex justify-between items-center border-b border-gray-200 dark:border-gray-700">
            <h3
              id="modal-title"
              class="text-base font-semibold leading-6 text-gray-900 dark:text-white truncate max-w-lg"
            >
              {{ email?.subject || 'Loading...' }}
            </h3>
            <div class="flex gap-2">
              <button
                :disabled="reprocessing"
                class="text-amber-600 hover:text-amber-500 dark:text-amber-400 font-medium text-sm flex items-center gap-1"
                @click="reprocess"
              >
                <ArrowPathIcon
                  class="h-4 w-4"
                  :class="{'animate-spin': reprocessing}"
                />
                Reprocess
              </button>
              <button
                type="button"
                class="rounded-md bg-white dark:bg-gray-800 text-gray-400 hover:text-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
                @click="$emit('close')"
              >
                <span class="sr-only">Close</span>
                <XMarkIcon
                  class="h-6 w-6"
                  aria-hidden="true"
                />
              </button>
            </div>
          </div>

          <!-- Content -->
          <div class="flex-1 flex flex-col md:flex-row overflow-hidden">
            <!-- Left: PDF -->
            <div class="md:w-1/2 h-1/2 md:h-full border-b md:border-b-0 md:border-r border-gray-200 dark:border-gray-700 bg-gray-100 dark:bg-gray-800 flex flex-col">
              <iframe
                v-if="email?.file_url_sas || email?.file_url"
                :src="email?.file_url_sas || email?.file_url"
                class="w-full h-full"
                title="PDF Preview"
              />
              <div
                v-else
                class="flex-1 flex items-center justify-center text-gray-500"
              >
                {{ loading ? 'Loading PDF...' : 'No PDF URL available' }}
              </div>
            </div>

            <!-- Right: Data -->
            <div class="md:w-1/2 h-1/2 md:h-full overflow-y-auto p-6 bg-white dark:bg-gray-900">
              <div
                v-if="loading && !email"
                class="space-y-4"
              >
                <div class="animate-pulse bg-gray-200 dark:bg-gray-700 h-8 rounded w-3/4" />
                <div class="animate-pulse bg-gray-200 dark:bg-gray-700 h-32 rounded" />
              </div>

              <div
                v-else-if="email"
                class="space-y-6"
              >
                <!-- Error Box -->
                <div
                  v-if="email.error"
                  class="rounded-md bg-red-50 dark:bg-red-900/20 p-4 border border-red-200 dark:border-red-800"
                >
                  <div class="flex">
                    <div class="ml-3">
                      <h3 class="text-sm font-medium text-red-800 dark:text-red-300">
                        Processing Error
                      </h3>
                      <div class="mt-2 text-sm text-red-700 dark:text-red-200">
                        <p>{{ email.error }}</p>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Markdown Content -->
                <div class="prose dark:prose-invert max-w-none text-sm">
                  <div v-html="renderMarkdown(email.markdown)" />
                </div>

                <!-- Usage info -->
                <div
                  v-if="email.usage"
                  class="bg-gray-50 dark:bg-gray-800 p-3 rounded-md text-xs text-gray-500 dark:text-gray-400"
                >
                  <div class="grid grid-cols-2 gap-2">
                    <div>Phi-4: ${{ (email.usage.phi4_cost_usd || 0).toFixed(6) }}</div>
                    <div>Mistral: ${{ (email.usage.mistral?.cost_usd || 0).toFixed(6) }}</div>
                  </div>
                </div>

                <!-- Form -->
                <div class="border-t border-gray-200 dark:border-gray-700 pt-6">
                  <h4 class="text-sm font-medium text-gray-900 dark:text-white mb-2">
                    Validated Intents (JSON)
                  </h4>
                  <textarea
                    v-model="intentsJson"
                    rows="8"
                    class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-700 font-mono"
                  />
                        
                  <div class="mt-4 flex justify-end">
                    <button
                      class="rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
                      @click="saveIntents"
                    >
                      Validate & Save
                    </button>
                  </div>
                </div>
                    
                <!-- Logs -->
                <div
                  v-if="email.processing_log?.length"
                  class="border-t border-gray-200 dark:border-gray-700 pt-6"
                >
                  <details>
                    <summary class="text-xs text-gray-500 cursor-pointer hover:text-gray-700 dark:hover:text-gray-300">
                      Processing Logs
                    </summary>
                    <div class="mt-2 space-y-1">
                      <div
                        v-for="(log, idx) in email.processing_log"
                        :key="idx"
                        class="text-xs text-gray-400 font-mono flex gap-2"
                      >
                        <span class="opacity-50 text-[10px]">{{ (log.ts || '').slice(11, 19) }}</span>
                        <span class="text-gray-600 dark:text-gray-400">{{ log.stage }}</span>
                        <span class="truncate">{{ log.detail }}</span>
                      </div>
                    </div>
                  </details>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
