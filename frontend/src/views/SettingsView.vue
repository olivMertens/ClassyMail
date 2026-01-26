<script setup>
import { ref, onMounted } from 'vue'
import { CheckCircleIcon, MoonIcon, SunIcon, PlusIcon, TrashIcon, PencilSquareIcon, ExclamationTriangleIcon, QuestionMarkCircleIcon } from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'

const { t, locale } = useI18n()

const activeTab = ref('classification') // classification | general | danger

const settings = ref({
    processing_strategy: 'standard',
    phi4_input_per_1k: null,
    phi4_output_per_1k: null,
    mistral_per_1k_pages: null,
    finetune_min_examples: 50,
    categories: []
})
const loading = ref(false)
const saved = ref(false)

// Category Form
const newCategory = ref({ name: '', description: '' })
const editingIndex = ref(null)
const editingCategory = ref({ name: '', description: '' })
const isEditing = ref(false)

// Appearance state
const isDark = ref(false)
const currentTheme = ref('blue')
const currentLocale = ref('en')

const themes = [
    { id: 'blue', name: 'Blue', class: 'bg-blue-600' },
    { id: 'green', name: 'Green', class: 'bg-emerald-600' },
    { id: 'indigo', name: 'Indigo', class: 'bg-indigo-600' },
    { id: 'orange', name: 'Orange', class: 'bg-orange-600' }
]

const resetConfirm1 = ref(false)
const resetConfirm2 = ref(false)
const resetting = ref(false)

const loadSettings = async () => {
    loading.value = true
    try {
        const res = await fetch('/api/settings')
        if (res.ok) {
            settings.value = await res.json()
        }
    } catch (e) {
        console.error(e)
    } finally {
        loading.value = false
    }
}

const saveSettings = async () => {
    loading.value = true
    saved.value = false
    try {
        const payload = {
            processing_strategy: settings.value.processing_strategy,
            phi4_input_per_1k: settings.value.phi4_input_per_1k ? Number(settings.value.phi4_input_per_1k) : undefined,
            phi4_output_per_1k: settings.value.phi4_output_per_1k ? Number(settings.value.phi4_output_per_1k) : undefined,
            mistral_per_1k_pages: settings.value.mistral_per_1k_pages ? Number(settings.value.mistral_per_1k_pages) : undefined,
            finetune_min_examples: settings.value.finetune_min_examples ? Number(settings.value.finetune_min_examples) : 50,
            categories: settings.value.categories
        }

        await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        localStorage.setItem('classimail-settings', JSON.stringify(payload))
        saved.value = true
        setTimeout(() => saved.value = false, 3000)
    } catch (e) {
        alert('Failed to save settings')
    } finally {
        loading.value = false
    }
}

const performReset = async () => {
    if (!resetConfirm1.value || !resetConfirm2.value) return
    resetting.value = true
    try {
        const res = await fetch('/api/admin/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm_1: true, confirm_2: true })
        })
        const data = await res.json()
        if (res.ok) {
            alert(`Environment Reset Successful.\nDeleted Blobs: ${data.deleted_blobs}\nDeleted DB Records: ${data.deleted_records}`)
            resetConfirm1.value = false
            resetConfirm2.value = false
        } else {
            alert(`Reset Failed: ${data.detail || JSON.stringify(data.errors)}`)
        }
    } catch (e) {
        alert('Error connecting to server')
    } finally {
        resetting.value = false
    }
}

const addCategory = () => {
    if (newCategory.value.name) {
        if (!settings.value.categories) settings.value.categories = []
        settings.value.categories.push({ ...newCategory.value })
        newCategory.value = { name: '', description: '' }
        saveSettings()
    }
}

const removeCategory = (index) => {
    if (confirm('Are you sure you want to remove this category?')) {
        settings.value.categories.splice(index, 1)
        saveSettings()
    }
}

const startEdit = (index) => {
    editingIndex.value = index
    editingCategory.value = { ...settings.value.categories[index] }
    isEditing.value = true
}

const saveEdit = () => {
    if (editingIndex.value !== null && editingCategory.value.name) {
        settings.value.categories[editingIndex.value] = { ...editingCategory.value }
        isEditing.value = false
        editingIndex.value = null
        editingCategory.value = { name: '', description: '' }
        saveSettings()
    }
}

const cancelEdit = () => {
    isEditing.value = false
    editingIndex.value = null
    editingCategory.value = { name: '', description: '' }
}

const toggleDarkMode = () => {
    isDark.value = !isDark.value
    if (isDark.value) {
        document.documentElement.classList.add('dark')
    } else {
        document.documentElement.classList.remove('dark')
    }
    localStorage.setItem('classimail-dark', isDark.value)
}

const setTheme = (id) => {
    currentTheme.value = id
    document.documentElement.setAttribute('data-theme', id)
    localStorage.setItem('classimail-theme', id)
}

const setLocale = (l) => {
    currentLocale.value = l
    locale.value = l
    localStorage.setItem('classimail-locale', l)
}

onMounted(() => {
    loadSettings()

    // Load persisted appearance config
    const savedDark = localStorage.getItem('classimail-dark')
    isDark.value = savedDark === 'true'
    if (isDark.value) document.documentElement.classList.add('dark')

    const savedTheme = localStorage.getItem('classimail-theme')
    if (savedTheme) {
        setTheme(savedTheme)
    }

    const savedLocale = localStorage.getItem('classimail-locale')
    if (savedLocale) {
        currentLocale.value = savedLocale
        locale.value = savedLocale
    }
})
</script>

<template>
  <div class="w-full space-y-6">
    <div class="md:flex md:items-center md:justify-between">
      <div class="min-w-0 flex-1">
        <h2 class="text-2xl font-bold leading-7 text-gray-900 dark:text-white sm:truncate sm:text-3xl sm:tracking-tight">
          {{ t('settings.title') }}
        </h2>
      </div>
    </div>

    <!-- Tabs -->
    <div class="border-b border-gray-200 dark:border-gray-700">
      <nav
        class="-mb-px flex space-x-8"
        aria-label="Tabs"
      >
        <button
          :class="[activeTab === 'classification' ? 'border-amber-500 text-amber-600 dark:text-amber-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'classification'"
        >
          Classification Categories
          <ExclamationTriangleIcon class="h-4 w-4 text-amber-500" />
        </button>
        <button
          :class="[activeTab === 'general' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium']"
          @click="activeTab = 'general'"
        >
          General & Costs
        </button>
        <button
          :class="[activeTab === 'danger' ? 'border-red-500 text-red-600 dark:text-red-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'danger'"
        >
          Danger Zone
          <ExclamationTriangleIcon class="h-4 w-4 text-red-500" />
        </button>
      </nav>
    </div>

    <!-- Classification Categories Tab (Moved First) -->
    <div
      v-show="activeTab === 'classification'"
      class="bg-white dark:bg-gray-800 shadow sm:rounded-lg"
    >
      <!-- Appearance Settings -->
      <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg">
        <div class="px-4 py-5 sm:p-6">
          <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
            {{ t('settings.appearance') }}
          </h3>

          <div class="mt-6 space-y-6">
            <!-- Language -->
            <div>
              <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">{{ t('settings.language') }}</label>
              <div class="mt-2 flex items-center space-x-4">
                <button
                  class="px-3 py-1.5 text-sm font-medium rounded-md transition-colors"
                  :class="currentLocale === 'en' ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'"
                  @click="setLocale('en')"
                >
                  English
                </button>
                <button
                  class="px-3 py-1.5 text-sm font-medium rounded-md transition-colors"
                  :class="currentLocale === 'fr' ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'"
                  @click="setLocale('fr')"
                >
                  Français
                </button>
              </div>
            </div>

            <!-- Dark Mode -->
            <div class="flex items-center justify-between">
              <span class="flex-grow flex flex-col">
                <span class="text-sm font-medium text-gray-900 dark:text-white">{{ t('settings.dark_mode') }}</span>
              </span>
              <button
                type="button"
                class="relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary-600 focus:ring-offset-2"
                :class="isDark ? 'bg-primary-600' : 'bg-gray-200'"
                @click="toggleDarkMode"
              >
                <span
                  class="pointer-events-none relative inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
                  :class="isDark ? 'translate-x-5' : 'translate-x-0'"
                >
                  <span
                    class="absolute inset-0 flex h-full w-full items-center justify-center transition-opacity"
                    :class="isDark ? 'opacity-0 duration-100 ease-out' : 'opacity-100 duration-200 ease-in'"
                  >
                    <SunIcon class="h-3 w-3 text-gray-400" />
                  </span>
                  <span
                    class="absolute inset-0 flex h-full w-full items-center justify-center transition-opacity"
                    :class="isDark ? 'opacity-100 duration-200 ease-in' : 'opacity-0 duration-100 ease-out'"
                  >
                    <MoonIcon class="h-3 w-3 text-primary-600" />
                  </span>
                </span>
              </button>
            </div>

            <!-- Theme -->
            <div>
              <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">{{ t('settings.theme') }}</label>
              <div class="mt-2 flex items-center space-x-3">
                <button
                  v-for="theme in themes"
                  :key="theme.id"
                  class="relative h-8 w-8 rounded-full focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-gray-800"
                  :class="[theme.class, currentTheme === theme.id ? 'ring-2 ring-primary-500 ring-offset-2' : '']"
                  :title="theme.name"
                  @click="setTheme(theme.id)"
                >
                  <CheckCircleIcon
                    v-if="currentTheme === theme.id"
                    class="absolute inset-0 m-auto h-5 w-5 text-white"
                  />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Fine-tuning Settings -->
      <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg">
        <div class="px-4 py-5 sm:p-6">
          <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
            Fine-tuning Configuration
          </h3>
          <div class="mt-2 max-w-xl text-sm text-gray-500 dark:text-gray-400">
            <p>Configure parameters for Fine-tuning dataset generation.</p>
          </div>

          <div class="mt-4">
            <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">Minimum Samples Required</label>
            <div class="mt-2">
              <input
                v-model="settings.finetune_min_examples"
                type="number"
                min="5"
                step="1"
                class="block w-full max-w-xs rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600"
              >
              <p class="mt-1 text-xs text-gray-500">
                Minimum number of reviewed examples required to enable JSONL export. Lowering this allows testing with smaller datasets.
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- Processing Strategy -->
      <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg">
        <div class="px-4 py-5 sm:p-6">
          <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
            Processing Strategy
          </h3>
          <div class="mt-2 max-w-xl text-sm text-gray-500 dark:text-gray-400">
            <p>Select the AI processing pipeline strategy.</p>
          </div>
          <div class="mt-4 space-y-4">
            <div class="flex items-center">
              <input
                id="strategy-standard"
                v-model="settings.processing_strategy"
                name="processing_strategy"
                type="radio"
                value="standard"
                class="h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600"
              >
              <label
                for="strategy-standard"
                class="ml-3 block text-sm font-medium leading-6 text-gray-900 dark:text-white"
              >
                Standard (Text/OCR Optimized - Default)
              </label>
              <div class="ml-2 text-xs text-gray-500 max-w-lg">
                Fast and cost-effective. Uses optimized prompting for standard text extraction and classification. Best for typed documents and clear emails.
              </div>
            </div>
            <div class="flex items-center">
              <input
                id="strategy-reasoning"
                v-model="settings.processing_strategy"
                name="processing_strategy"
                type="radio"
                value="reasoning"
                class="h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600"
              >
              <label
                for="strategy-reasoning"
                class="ml-3 block text-sm font-medium leading-6 text-gray-900 dark:text-white"
              >
                Reasoning (Deep Reasoning / CoT)
              </label>
              <div class="ml-2 text-xs text-gray-500 max-w-lg">
                Forces a "Chain-of-Thought" (Step-by-step) approach. Instructs the model to analyze context and deduce intents logically before classifying. essential for subtle or complex cases.
              </div>
            </div>
            <div class="flex items-center">
              <input
                id="strategy-vision"
                v-model="settings.processing_strategy"
                name="processing_strategy"
                type="radio"
                value="vision"
                class="h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-600 dark:bg-gray-700 dark:border-gray-600"
              >
              <label
                for="strategy-vision"
                class="ml-3 block text-sm font-medium leading-6 text-gray-900 dark:text-white"
              >
                Vision (Vision/Image Analysis - Experimental)
              </label>
              <div class="ml-2 text-xs text-gray-500 max-w-lg">
                Integrates visual analysis. Explicitly considers descriptions of non-text elements (photos, diagrams) detected by OCR. Crucial for claims relying on visual evidence (e.g., damage photos).
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Costs Settings -->
      <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg">
        <div class="px-4 py-5 sm:p-6">
          <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
            {{ t('settings.costs_title') }}
          </h3>
          <div class="mt-2 max-w-xl text-sm text-gray-500 dark:text-gray-400">
            <p>{{ t('settings.costs_desc') }}</p>
          </div>

          <form
            class="mt-5 space-y-6"
            @submit.prevent="saveSettings"
          >
            <div>
              <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">Phi-4 Input Cost (€ / 1K tokens)</label>
              <div class="mt-2">
                <input
                  v-model="settings.phi4_input_per_1k"
                  type="number"
                  step="0.000001"
                  class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600"
                >
              </div>
            </div>

            <div>
              <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">Phi-4 Output Cost (€ / 1K tokens)</label>
              <div class="mt-2">
                <input
                  v-model="settings.phi4_output_per_1k"
                  type="number"
                  step="0.000001"
                  class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600"
                >
              </div>
            </div>

            <div>
              <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">Mistral OCR Cost (€ / 1K pages)</label>
              <div class="mt-2">
                <input
                  v-model="settings.mistral_per_1k_pages"
                  type="number"
                  step="0.001"
                  class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600"
                >
              </div>
            </div>

            <div class="flex items-center gap-4">
              <button
                type="submit"
                :disabled="loading"
                class="rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600 disabled:opacity-50"
              >
                {{ loading ? t('settings.saving') : t('settings.save') }}
              </button>
              <transition
                enter-active-class="transition ease-out duration-200"
                enter-from-class="opacity-0 translate-y-1"
                enter-to-class="opacity-100 translate-y-0"
                leave-active-class="transition ease-in duration-150"
                leave-from-class="opacity-100 translate-y-0"
                leave-to-class="opacity-0 translate-y-1"
              >
                <div
                  v-if="saved"
                  class="flex items-center text-green-600 dark:text-green-400 text-sm font-medium"
                >
                  <CheckCircleIcon class="h-5 w-5 mr-1" />
                  {{ t('settings.saved') }}
                </div>
              </transition>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- Classification Categories Tab -->
    <div
      v-show="activeTab === 'classification'"
      class="bg-white dark:bg-gray-800 shadow sm:rounded-lg"
    >
      <div class="px-4 py-5 sm:p-6">
        <!-- Warning Banner -->
        <div class="rounded-md bg-amber-50 dark:bg-amber-900/30 p-4 mb-6 border-l-4 border-amber-400 dark:border-amber-500">
          <div class="flex">
            <div class="flex-shrink-0">
              <ExclamationTriangleIcon
                class="h-5 w-5 text-amber-400 dark:text-amber-500"
                aria-hidden="true"
              />
            </div>
            <div class="ml-3">
              <h3 class="text-sm font-medium text-amber-800 dark:text-amber-200">
                Critical Configuration
              </h3>
              <div class="mt-2 text-sm text-amber-700 dark:text-amber-300">
                <p>
                  Modifying categories drastically changes how the AI classifies incoming emails.
                  Changes propagate to the System Prompt immediately.
                  Descriptions are key for the LLM context.
                </p>
              </div>
            </div>
          </div>
        </div>

        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
          Managed Categories
        </h3>
        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
          Current active categories extracted by the LLM.
        </p>

        <div class="mt-5">
          <div class="flow-root">
            <ul
              role="list"
              class="-my-5 divide-y divide-gray-200 dark:divide-gray-700"
            >
              <li
                v-for="(cat, idx) in settings.categories"
                :key="idx"
                class="py-4"
              >
                <div class="flex items-start justify-between">
                  <div class="min-w-0 flex-1 mr-4">
                    <p class="text-sm font-bold text-gray-900 dark:text-white">
                      {{ cat.name }}
                    </p>
                    <p class="mt-1 text-sm text-gray-500 dark:text-gray-400 whitespace-pre-wrap">
                      {{ cat.description }}
                    </p>
                  </div>
                  <div class="flex items-center gap-2">
                    <button
                      type="button"
                      class="inline-flex rounded-md bg-white dark:bg-gray-800 px-2.5 py-1.5 text-sm font-semibold text-gray-900 dark:text-white shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
                      title="Edit"
                      @click="startEdit(idx)"
                    >
                      <PencilSquareIcon class="h-5 w-5 text-gray-400 hover:text-primary-500" />
                    </button>
                    <button
                      type="button"
                      class="inline-flex rounded-md bg-white dark:bg-gray-800 px-2.5 py-1.5 text-sm font-semibold text-gray-900 dark:text-white shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
                      title="Remove"
                      @click="removeCategory(idx)"
                    >
                      <TrashIcon class="h-5 w-5 text-gray-400 hover:text-red-500" />
                    </button>
                  </div>
                </div>
              </li>
              <li
                v-if="!settings.categories?.length"
                class="py-8 text-center text-sm text-gray-500 italic"
              >
                No categories defined. Add one below.
              </li>
            </ul>
          </div>

          <!-- Add/Edit Form -->
          <div class="mt-8 bg-gray-50 dark:bg-gray-700/30 p-4 rounded-md border border-gray-200 dark:border-gray-700">
            <h4 class="text-sm font-medium text-gray-900 dark:text-white mb-3">
              {{ isEditing ? 'Edit Category' : 'Add New Category' }}
            </h4>
            <div class="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-6">
              <div class="sm:col-span-2">
                <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">Name</label>
                <div class="mt-1">
                  <input
                    v-model="(isEditing ? editingCategory : newCategory).name"
                    type="text"
                    class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600"
                    placeholder="e.g. Contract Cancellation"
                  >
                </div>
              </div>
              <div class="sm:col-span-4">
                <div class="flex justify-between">
                  <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">Description (LLM Context)</label>
                  <span class="text-xs text-gray-500">{{ (isEditing ? editingCategory : newCategory).description?.length || 0 }}/2000</span>
                </div>
                <div class="mt-1">
                  <textarea
                    v-model="(isEditing ? editingCategory : newCategory).description"
                    rows="3"
                    maxlength="2000"
                    class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600"
                    placeholder="Describe the criteria for this category..."
                  />
                </div>
              </div>
            </div>
            <div class="mt-4 flex justify-end gap-2">
              <button
                v-if="isEditing"
                type="button"
                class="inline-flex items-center rounded-md bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50"
                @click="cancelEdit"
              >
                Cancel
              </button>
              <button
                type="button"
                class="inline-flex items-center rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
                @click="isEditing ? saveEdit() : addCategory()"
              >
                <component
                  :is="isEditing ? PencilSquareIcon : PlusIcon"
                  class="h-5 w-5 mr-1"
                  aria-hidden="true"
                />
                {{ isEditing ? 'Update Category' : 'Add Category' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Danger Zone Tab -->
    <div
      v-show="activeTab === 'danger'"
      class="bg-white dark:bg-gray-800 shadow sm:rounded-lg border border-red-200 dark:border-red-900"
    >
      <div class="px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-red-600 dark:text-red-400 flex items-center gap-2">
          <ExclamationTriangleIcon class="h-5 w-5" />
          Atomic Zone - Environment Reset
        </h3>
        <div class="mt-2 max-w-xl text-sm text-gray-500 dark:text-gray-400">
          <p>
            Proceed with extreme caution. This action will permanently delete all data in the current environment.
          </p>
        </div>

        <div class="mt-5 bg-red-50 dark:bg-red-900/20 p-4 rounded-md">
          <h4 class="text-sm font-medium text-red-800 dark:text-red-300">
            This action will:
          </h4>
          <ul class="list-disc list-inside mt-2 text-sm text-red-700 dark:text-red-200">
            <li>Delete ALL emails and classification records from Database.</li>
            <li>Delete ALL files (PDFs) from the Input Storage Container.</li>
            <li>Reset the dashboard state completely.</li>
          </ul>
        </div>

        <div class="mt-6 space-y-4">
          <div class="flex items-start">
            <div class="flex h-6 items-center">
              <input
                id="confirm_1"
                v-model="resetConfirm1"
                type="checkbox"
                class="h-4 w-4 rounded border-gray-300 text-red-600 focus:ring-red-600 dark:bg-gray-700 dark:border-gray-600"
              >
            </div>
            <div class="ml-3 text-sm leading-6">
              <label
                for="confirm_1"
                class="font-medium text-gray-900 dark:text-white"
              >I understand this deletes all data permanently.</label>
            </div>
          </div>
          <div class="flex items-start">
            <div class="flex h-6 items-center">
              <input
                id="confirm_2"
                v-model="resetConfirm2"
                type="checkbox"
                class="h-4 w-4 rounded border-gray-300 text-red-600 focus:ring-red-600 dark:bg-gray-700 dark:border-gray-600"
              >
            </div>
            <div class="ml-3 text-sm leading-6">
              <label
                for="confirm_2"
                class="font-medium text-gray-900 dark:text-white"
              >I confirm I want to reset the environment.</label>
            </div>
          </div>

          <button
            type="button"
            class="mt-4 inline-flex items-center rounded-md bg-red-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-red-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-600 disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="!resetConfirm1 || !resetConfirm2 || resetting"
            @click="performReset"
          >
            <TrashIcon
              v-if="!resetting"
              class="-ml-0.5 mr-1.5 h-5 w-5"
              aria-hidden="true"
            />
            <ArrowPathIcon
              v-else
              class="-ml-0.5 mr-1.5 h-5 w-5 animate-spin"
              aria-hidden="true"
            />
            {{ resetting ? 'Nuking Environment...' : 'NUKE EVERYTHING' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
