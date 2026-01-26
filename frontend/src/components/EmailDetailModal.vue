<script setup>
import { ref, watch, computed } from 'vue'
import { XMarkIcon, ArrowPathIcon, CheckIcon, TrashIcon, ClockIcon } from '@heroicons/vue/24/outline'
import MarkdownIt from 'markdown-it'

const props = defineProps({
  emailId: {
    type: String,
    default: null
  },
  isOpen: {
    type: Boolean,
    default: false
  }
})
const emit = defineEmits(['close', 'updated'])

const md = new MarkdownIt({ html: true, linkify: true, breaks: true })

const email = ref(null)
const loading = ref(false)
const reprocessing = ref(false)
const intentsJson = ref('[]')
const availableCategories = ref([])
const correctionReason = ref('')
const activeTab = ref('review') // review | history

// New Multi-select state
const selectedCategoryNames = ref([])
const customCategories = ref([])

const loadSettings = async () => {
    try {
        const res = await fetch('/api/settings')
        if (res.ok) {
            const data = await res.json()
            availableCategories.value = data.categories || []
        }
    } catch (e) { console.error(e) }
}

const loadEmail = async () => {
    if (!props.emailId) return
    loading.value = true
    correctionReason.value = ''
    selectedCategoryNames.value = []
    customCategories.value = []
    
    try {
        const res = await fetch(`/api/emails/${props.emailId}`)
        if (res.ok) {
            email.value = await res.json()
            intentsJson.value = JSON.stringify(email.value.classification?.detected_intents || [], null, 2)
            correctionReason.value = email.value.correction_reason || ''
            
            // Populate selection from current intent
            const currentIntents = email.value.classification?.detected_intents || []
            currentIntents.forEach(i => {
                const name = i.intent
                if (availableCategories.value.find(c => c.name === name)) {
                    if (!selectedCategoryNames.value.includes(name)) {
                        selectedCategoryNames.value.push(name)
                    }
                } else {
                    // It's a custom or old category
                    if (!customCategories.value.includes(name)) {
                        customCategories.value.push(name)
                        if (!selectedCategoryNames.value.includes(name)) {
                            selectedCategoryNames.value.push(name)
                        }
                    }
                }
            })
        }
    } catch (e) {
        console.error(e)
    } finally {
        loading.value = false
    }
}

const toggleCategory = (name) => {
    if (selectedCategoryNames.value.includes(name)) {
        selectedCategoryNames.value = selectedCategoryNames.value.filter(n => n !== name)
    } else {
        selectedCategoryNames.value.push(name)
    }
}

const addCustomCategory = () => {
    const name = prompt("Enter new category name:")
    if (name) {
        if (!customCategories.value.includes(name)) {
            customCategories.value.push(name)
        }
        if (!selectedCategoryNames.value.includes(name)) {
            selectedCategoryNames.value.push(name)
        }
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

const markAsInvalid = async () => {
     if (!confirm("Are you sure you want to mark this email as Invalid/Garbage?")) return;
     try {
        const payload = { status: 'INVALID', reason: correctionReason.value || 'Marked as invalid by user' }
        const res = await fetch(`/api/emails/${email.value.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        if (res.ok) {
            emit('updated')
            emit('close')
        }
     } catch (e) { alert("Error saving") }
}

const saveIntents = async () => {
    if (!email.value) return
    if (!correctionReason.value && email.value.classification?.needs_review) {
         if (!confirm("Confirm validation without providing a correction reason?")) return;
    }

    try {
        // Construct intents from selection
        // We assume 1.0 confidence for manual selection
        const newIntents = selectedCategoryNames.value.map(name => ({
            intent: name,
            confidence: 1.0,
            justification: "Manually selected by user"
        }))

        const payload = { intents: newIntents, reason: correctionReason.value }
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
        alert('Error Saving')
    }
}

watch(() => props.isOpen, (newVal) => {
    if (newVal) {
        loadSettings().then(loadEmail)
    } else {
        email.value = null
        activeTab.value = 'review'
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
            <div class="md:w-1/2 h-1/2 md:h-full overflow-y-auto bg-white dark:bg-gray-900 flex flex-col">
              
              <!-- Tabs -->
              <div class="border-b border-gray-200 dark:border-gray-700">
                <nav class="flex -mb-px" aria-label="Tabs">
                  <button
                    @click="activeTab = 'review'"
                    :class="[activeTab === 'review' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400', 'w-1/2 py-4 px-1 text-center border-b-2 font-medium text-sm']"
                  >
                    Review & Classify
                  </button>
                  <button
                    @click="activeTab = 'history'"
                    :class="[activeTab === 'history' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400', 'w-1/2 py-4 px-1 text-center border-b-2 font-medium text-sm']"
                  >
                    History
                  </button>
                </nav>
              </div>

              <!-- Tab Content -->
              <div class="p-6 flex-1">
                
                <div v-if="loading && !email" class="space-y-4">
                    <div class="animate-pulse bg-gray-200 dark:bg-gray-700 h-8 rounded w-3/4" />
                    <div class="animate-pulse bg-gray-200 dark:bg-gray-700 h-32 rounded" />
                </div>

                <!-- Review Tab -->
                <div v-else-if="activeTab === 'review' && email" class="space-y-6">
                    <!-- Error Box -->
                    <div v-if="email.error" class="rounded-md bg-red-50 dark:bg-red-900/20 p-4 border border-red-200 dark:border-red-800">
                        <p class="text-sm text-red-700 dark:text-red-200">{{ email.error }}</p>
                    </div>

                    <div class="prose dark:prose-invert max-w-none text-sm max-h-60 overflow-y-auto border border-gray-100 rounded p-2">
                        <div v-html="renderMarkdown(email.markdown)" />
                    </div>

                    <!-- Category Selection -->
                    <div>
                        <h4 class="text-sm font-medium text-gray-900 dark:text-white mb-3">Categories</h4>
                        <div class="flex flex-wrap gap-2 mb-3">
                            <button 
                                v-for="cat in availableCategories" 
                                :key="cat.name"
                                @click="toggleCategory(cat.name)"
                                :class="selectedCategoryNames.includes(cat.name) ? 'bg-primary-100 text-primary-800 ring-primary-500 dark:bg-primary-900 dark:text-primary-200' : 'bg-gray-100 text-gray-700 ring-gray-200 dark:bg-gray-800 dark:text-gray-300'"
                                class="inline-flex items-center rounded-md px-2.5 py-1.5 text-sm font-medium ring-1 ring-inset transition-colors"
                            >
                                <CheckIcon v-if="selectedCategoryNames.includes(cat.name)" class="w-4 h-4 mr-1.5" />
                                {{ cat.name }}
                            </button>
                            <button 
                                v-for="cat in customCategories" 
                                :key="cat"
                                @click="toggleCategory(cat)"
                                :class="selectedCategoryNames.includes(cat) ? 'bg-indigo-100 text-indigo-800 ring-indigo-500 dark:bg-indigo-900 dark:text-indigo-200' : 'bg-gray-100 text-gray-700 ring-gray-200 dark:bg-gray-800 dark:text-gray-300'"
                                class="inline-flex items-center rounded-md px-2.5 py-1.5 text-sm font-medium ring-1 ring-inset transition-colors"
                            >
                                <CheckIcon v-if="selectedCategoryNames.includes(cat)" class="w-4 h-4 mr-1.5" />
                                {{ cat }} (Manual)
                            </button>
                            <button @click="addCustomCategory" class="inline-flex items-center rounded-md px-2.5 py-1.5 text-sm font-medium bg-white text-gray-500 ring-1 ring-inset ring-gray-300 hover:bg-gray-50 border-dashed dark:bg-gray-800 dark:text-gray-400">
                                + Custom
                            </button>
                        </div>
                    </div>

                    <!-- Reason -->
                    <div>
                        <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">Correction Reason / Comment</label>
                        <textarea
                            v-model="correctionReason"
                            rows="2"
                            class="mt-2 block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-700"
                            placeholder="Why did you change the category? (Used for reinforcement learning)"
                        />
                    </div>

                    <!-- Actions -->
                    <div class="flex justify-between pt-4 border-t border-gray-200 dark:border-gray-700">
                        <button
                            @click="markAsInvalid"
                            class="text-red-600 hover:text-red-500 text-sm font-medium flex items-center"
                        >
                            <TrashIcon class="w-4 h-4 mr-1" />
                            Mark as Garbage/Invalid
                        </button>
                        <button
                            class="rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600 disabled:opacity-50"
                            :disabled="selectedCategoryNames.length === 0"
                            @click="saveIntents"
                        >
                            Validate & Save
                        </button>
                    </div>
                </div>

                <!-- History Tab -->
                <div v-else-if="activeTab === 'history' && email" class="space-y-6">
                    <h3 class="text-sm font-medium text-gray-900 dark:text-white">Classification History</h3>
                    <div class="flow-root">
                        <ul role="list" class="-mb-8">
                            <li v-for="(entry, idx) in (email.classification_history || []).slice().reverse()" :key="idx">
                                <div class="relative pb-8">
                                    <span v-if="idx !== email.classification_history.length - 1" class="absolute top-4 left-4 -ml-px h-full w-0.5 bg-gray-200 dark:bg-gray-700" aria-hidden="true" />
                                    <div class="relative flex space-x-3">
                                        <div>
                                            <span class="h-8 w-8 rounded-full bg-gray-100 flex items-center justify-center ring-8 ring-white dark:ring-gray-900 dark:bg-gray-800">
                                                <ClockIcon class="h-5 w-5 text-gray-500" aria-hidden="true" />
                                            </span>
                                        </div>
                                        <div class="flex min-w-0 flex-1 justify-between space-x-4 pt-1.5">
                                            <div>
                                                <p class="text-sm text-gray-500 dark:text-gray-400">
                                                    Updated by <span class="font-medium text-gray-900 dark:text-white">{{ entry.updated_by }}</span>
                                                </p>
                                                <div class="mt-2 text-sm text-gray-700 dark:text-gray-300">
                                                    <p v-if="entry.previous_intents?.length">
                                                        Previous Intents:
                                                        <span v-for="i in entry.previous_intents" :key="i.intent" class="inline-flex items-center rounded-md bg-gray-50 dark:bg-gray-700 px-2 py-1 text-xs font-medium text-gray-600 dark:text-gray-300 ring-1 ring-inset ring-gray-500/10 mr-1">
                                                            {{ i.intent }}
                                                        </span>
                                                    </p>
                                                    <p v-else class="italic text-gray-400">No previous intents</p>
                                                    
                                                    <div v-if="entry.correction_reason" class="mt-2 text-xs border-l-2 border-gray-300 pl-2">
                                                        <span class="font-semibold">Reason:</span> {{ entry.correction_reason }}
                                                    </div>
                                                    
                                                    <div v-if="entry.llm_feedback" class="mt-2 text-xs bg-blue-50 dark:bg-blue-900/30 p-2 rounded border border-blue-100 dark:border-blue-800 text-blue-800 dark:text-blue-200">
                                                        <span class="font-bold">🤖 LLM Insight:</span> {{ entry.llm_feedback }}
                                                    </div>
                                                </div>
                                            </div>
                                            <div class="whitespace-nowrap text-right text-sm text-gray-500">
                                                <time :datetime="entry.timestamp">{{ new Date(entry.timestamp).toLocaleDateString() }}</time>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </li>
                            <li v-if="!email.classification_history?.length">
                                <p class="text-sm text-gray-500 italic">No history available.</p>
                            </li>
                        </ul>
                    </div>
                </div>

              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
