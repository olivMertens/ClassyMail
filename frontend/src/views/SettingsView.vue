<script setup>
import { ref, onMounted } from 'vue'
import {
    CheckCircleIcon,
    MoonIcon,
    SunIcon,
    PlusIcon,
    TrashIcon,
    PencilSquareIcon,
    ExclamationTriangleIcon,
    SwatchIcon,
    CpuChipIcon,
    AdjustmentsHorizontalIcon,
    QueueListIcon,
    BanknotesIcon,
    ArrowPathIcon,
    QuestionMarkCircleIcon,
    ChevronDownIcon,
    ChevronUpIcon,
    XMarkIcon
} from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'

const { t, locale } = useI18n()

// Tabs
const activeTab = ref('classification')
const showStrategyHelp = ref(false)

// Config Data
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

// Reset State
const resetConfirm1 = ref(false)
const resetConfirm2 = ref(false)
const resetting = ref(false)

// --- Category Management & Sanitization ---

const expandedCategories = ref(new Set())
const newCategory = ref({ name: '', description: '' })
const newCategoryExpanded = ref(false)

const sanitizeInput = (str, type) => {
    if (!str) return ''
    let cleaned = str
    cleaned = cleaned.replace(/"""/g, '"').replace(/'''/g, "'")
    cleaned = cleaned.trim()

    if (type === 'name') {
        cleaned = cleaned.replace(/[\r\n]+/g, ' ')
        if (cleaned.length > 50) cleaned = cleaned.substring(0, 50)
    } else {
        if (cleaned.length > 2000) cleaned = cleaned.substring(0, 2000)
    }
    return cleaned
}

const toggleExpanded = (index) => {
    if (expandedCategories.value.has(index)) {
        expandedCategories.value.delete(index)
    } else {
        expandedCategories.value.add(index)
    }
}

const updateCategory = (index, field, value) => {
    const cleanValue = sanitizeInput(value, field)
    settings.value.categories[index][field] = cleanValue
}

const addNewCategory = () => {
    const name = sanitizeInput(newCategory.value.name, 'name')
    const desc = sanitizeInput(newCategory.value.description, 'description')

    if (name && desc) {
        if (!settings.value.categories) settings.value.categories = []
        settings.value.categories.push({ name, description: desc })
        newCategory.value = { name: '', description: '' }
        newCategoryExpanded.value = false
        saveSettings()
    }
}

const removeCategory = (index) => {
    if (confirm('Are you sure you want to remove this category?')) {
        settings.value.categories.splice(index, 1)
        expandedCategories.value.delete(index)
        saveSettings()
    }
}

// --- API Calls ---

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
    if (!confirm('FINAL WARNING: This is irreversible. Proceed?')) return

    resetting.value = true
    try {
        const res = await fetch('/api/admin/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                confirm_1: resetConfirm1.value,
                confirm_2: resetConfirm2.value
            })
        })
        if (res.ok) {
            const data = await res.json()
            alert(`Reset Successful.\nDeleted Blobs: ${data.deleted_blobs}`)
            window.location.reload()
        } else {
            alert('Reset Failed')
        }
    } catch (e) {
        alert(`Reset Error: ${e.message}`)
    } finally {
        resetting.value = false
    }
}

// --- Appearance & Init ---

const isDark = ref(false)
const currentTheme = ref('blue')
const currentLocale = ref('en')

const themes = [
    { id: 'blue', name: 'Blue', class: 'bg-blue-600' },
    { id: 'green', name: 'Green', class: 'bg-emerald-600' },
    { id: 'indigo', name: 'Indigo', class: 'bg-indigo-600' },
    { id: 'orange', name: 'Orange', class: 'bg-orange-600' }
]

const toggleDarkMode = () => {
    isDark.value = !isDark.value
    document.documentElement.classList.toggle('dark', isDark.value)
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

    const savedDark = localStorage.getItem('classimail-dark')
    isDark.value = savedDark === 'true'
    if (isDark.value) document.documentElement.classList.add('dark')

    const savedTheme = localStorage.getItem('classimail-theme')
    if (savedTheme) setTheme(savedTheme)

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
    <div class="border-b border-gray-200 dark:border-gray-700 overflow-x-auto overflow-y-hidden">
      <nav
        class="-mb-px flex space-x-8"
        aria-label="Tabs"
      >
        <button
          :class="[activeTab === 'classification' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'classification'"
        >
          <QueueListIcon class="h-4 w-4" />
          Categories
        </button>
        <button
          :class="[activeTab === 'design' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'design'"
        >
          <SwatchIcon class="h-4 w-4" />
          {{ t('settings.appearance') }}
        </button>
        <button
          :class="[activeTab === 'processing' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'processing'"
        >
          <CpuChipIcon class="h-4 w-4" />
          Processing Strategy
        </button>
        <button
          :class="[activeTab === 'finetuning' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'finetuning'"
        >
          <AdjustmentsHorizontalIcon class="h-4 w-4" />
          Fine-tuning
        </button>
        <button
          :class="[activeTab === 'general' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400', 'whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium flex items-center gap-2']"
          @click="activeTab = 'general'"
        >
          <BanknotesIcon class="h-4 w-4" />
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

    <!-- Design / Appearance Tab -->
    <div
      v-show="activeTab === 'design'"
      class="bg-white dark:bg-gray-800 shadow sm:rounded-lg"
    >
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

    <!-- Processing Strategy Tab -->
    <div
      v-show="activeTab === 'processing'"
      class="bg-white dark:bg-gray-800 shadow sm:rounded-lg"
    >
      <div class="px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white flex items-center gap-2">
          Processing Strategy
          <button
            class="text-gray-400 hover:text-primary-500 transition-colors"
            title="How these strategies work"
            @click="showStrategyHelp = true"
          >
            <QuestionMarkCircleIcon class="h-5 w-5" />
          </button>
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
          </div>
        </div>
      </div>
    </div>

    <!-- Fine-tuning Tab -->
    <div
      v-show="activeTab === 'finetuning'"
      class="bg-white dark:bg-gray-800 shadow sm:rounded-lg"
    >
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

    <!-- General & Costs Tab -->
    <div
      v-show="activeTab === 'general'"
      class="bg-white dark:bg-gray-800 shadow sm:rounded-lg"
    >
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

        <div class="flex justify-between items-center">
          <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
            Managed Categories
          </h3>
          <button
            type="button"
            class="text-sm text-primary-600 hover:text-primary-500"
            @click="saveSettings"
          >
            Save Changes to System
          </button>
        </div>

        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
          Current active categories extracted by the LLM.
        </p>

        <div class="mt-5">
          <div class="flow-root">
            <ul
              role="list"
              class="-my-5"
            >
              <li
                v-for="(cat, idx) in settings.categories"
                :key="idx"
                class="py-4 border-b border-gray-200 dark:border-gray-700 last:border-0"
              >
                <!-- Accordion Header -->
                <div
                  class="flex items-center justify-between cursor-pointer group hover:bg-gray-50 dark:hover:bg-gray-700/50 rounded-md p-2 -mx-2 transition-colors"
                  @click="toggleExpanded(idx)"
                >
                  <div class="min-w-0 flex-1 flex items-center gap-3">
                    <button
                      type="button"
                      class="text-gray-400 group-hover:text-primary-500 transition-colors"
                    >
                      <component
                        :is="expandedCategories.has(idx) ? ChevronUpIcon : ChevronDownIcon"
                        class="h-5 w-5"
                      />
                    </button>
                    <div>
                      <p class="text-sm font-bold text-gray-900 dark:text-white">
                        {{ cat.name }}
                      </p>
                      <p
                        v-if="!expandedCategories.has(idx)"
                        class="text-xs text-gray-500 dark:text-gray-400 truncate max-w-md"
                      >
                        {{ cat.description }}
                      </p>
                    </div>
                  </div>
                  <div class="flex items-center gap-2">
                    <button
                      type="button"
                      class="inline-flex rounded-md p-1.5 text-gray-400 hover:text-red-500 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                      title="Remove"
                      @click.stop="removeCategory(idx)"
                    >
                      <TrashIcon class="h-5 w-5" />
                    </button>
                  </div>
                </div>

                <!-- Accordion Body (Edit Form) -->
                <div
                  v-if="expandedCategories.has(idx)"
                  class="mt-3 pl-8 pr-2 pb-2"
                >
                  <div class="bg-gray-50 dark:bg-gray-700/30 p-4 rounded-md border border-gray-200 dark:border-gray-600">
                    <div class="grid grid-cols-1 gap-4">
                      <div>
                        <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Name</label>
                        <input
                          v-model="cat.name"
                          type="text"
                          class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600"
                          @change="updateCategory(idx, 'name', cat.name)"
                        >
                      </div>
                      <div>
                        <label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                          Description (Context for LLM) - {{ cat.description?.length || 0 }}/2000
                        </label>
                        <textarea
                          v-model="cat.description"
                          rows="3"
                          maxlength="2000"
                          class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600 font-mono text-xs"
                          @change="updateCategory(idx, 'description', cat.description)"
                        />
                      </div>
                      <div class="flex justify-end pt-2">
                        <span class="text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1 italic">
                          <ExclamationTriangleIcon class="h-3 w-3" />
                          Changes are applied locally. Click "Save Changes to System" above to commit.
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </li>

              <li
                v-if="!settings.categories?.length"
                class="py-8 text-center text-sm text-gray-500 italic"
              >
                No categories defined.
              </li>
            </ul>
          </div>

          <!-- Add New Category (Collapsible) -->
          <div class="mt-8 border-t border-gray-200 dark:border-gray-700 pt-6">
            <button
              type="button"
              class="flex items-center gap-2 text-primary-600 hover:text-primary-700 font-medium text-sm w-full"
              @click="newCategoryExpanded = !newCategoryExpanded"
            >
              <component
                :is="newCategoryExpanded ? ChevronUpIcon : PlusIcon"
                class="h-5 w-5"
              />
              {{ newCategoryExpanded ? 'Cancel Adding Category' : 'Add New Category' }}
            </button>

            <div
              v-if="newCategoryExpanded"
              class="mt-4 bg-gray-50 dark:bg-gray-700/30 p-4 rounded-md border border-gray-200 dark:border-gray-700 transition-all"
            >
              <div class="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-6">
                <div class="sm:col-span-2">
                  <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">Name</label>
                  <div class="mt-1">
                    <input
                      v-model="newCategory.name"
                      type="text"
                      class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600"
                      placeholder="e.g. Contract Cancellation"
                    >
                  </div>
                </div>
                <div class="sm:col-span-4">
                  <div class="flex justify-between">
                    <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">Description (LLM Context)</label>
                    <span class="text-xs text-gray-500">{{ newCategory.description?.length || 0 }}/2000</span>
                  </div>
                  <div class="mt-1">
                    <textarea
                      v-model="newCategory.description"
                      rows="3"
                      maxlength="2000"
                      class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-800 dark:text-white dark:ring-gray-600 font-mono text-xs"
                      placeholder="Describe the criteria for this category..."
                    />
                  </div>
                </div>
              </div>
              <div class="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  class="inline-flex items-center rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
                  @click="addNewCategory"
                >
                  <PlusIcon class="h-5 w-5 mr-1" />
                  Add Category
                </button>
              </div>
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
            <li><strong>Preserve</strong> application settings (Categories, Costs, etc).</li>
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

    <!-- Strategy Help Modal -->
    <div
      v-if="showStrategyHelp"
      class="fixed inset-0 z-50 overflow-y-auto"
      aria-labelledby="modal-title"
      role="dialog"
      aria-modal="true"
    >
      <div class="flex items-end justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
        <div
          class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
          aria-hidden="true"
          @click="showStrategyHelp = false"
        />
        <span
          class="hidden sm:inline-block sm:align-middle sm:h-screen"
          aria-hidden="true"
        >&#8203;</span>
        <div class="inline-block align-bottom bg-white dark:bg-gray-800 rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-2xl sm:w-full border border-gray-200 dark:border-gray-700">
          <div class="bg-white dark:bg-gray-800 px-4 pt-5 pb-4 sm:p-6 sm:pb-4">
            <h3
              id="modal-title"
              class="text-lg leading-6 font-medium text-gray-900 dark:text-white mb-4"
            >
              Processing Strategies Explained
            </h3>
            <div class="space-y-6 text-sm">
              <!-- Standard -->
              <div class="border-l-4 border-indigo-500 pl-4">
                <h4 class="font-bold text-gray-900 dark:text-white text-base">
                  Standard (Default)
                </h4>
                <p class="text-gray-500 dark:text-gray-400 mt-1">
                  Fast and optimized for standard text extraction. Uses zero-shot prompting optimized for cost.
                </p>
                <div class="mt-2 bg-gray-50 dark:bg-gray-900 p-3 rounded text-gray-800 dark:text-gray-300 font-mono text-xs">
                  <span class="text-indigo-600 dark:text-indigo-400 font-bold">How it works:</span> Passes OCR text directly to the model.<br>
                  <span class="text-indigo-600 dark:text-indigo-400 font-bold">Example:</span> A clearly typed PDF claiming an "Address Change". The model identifies keywords and classifies instantly.
                </div>
              </div>

              <!-- Reasoning -->
              <div class="border-l-4 border-purple-500 pl-4">
                <h4 class="font-bold text-gray-900 dark:text-white text-base">
                  Reasoning (CoT)
                </h4>
                <p class="text-gray-500 dark:text-gray-400 mt-1">
                  Forces a "Chain-of-Thought" (Step-by-step) analysis. Essential for subtle intents or complex narratives.
                </p>
                <div class="mt-2 bg-gray-50 dark:bg-gray-900 p-3 rounded text-gray-800 dark:text-gray-300 font-mono text-xs">
                  <span class="text-purple-600 dark:text-purple-400 font-bold">How it works:</span> Injects system instruction: <em>"Analyze context first, then deduce intents step-by-step."</em><br>
                  <span class="text-purple-600 dark:text-purple-400 font-bold">Example:</span> An email telling a story about a storm without explicitly saying "claim". The model deduces "Bad Weather" -> "Damage" -> "Claim Intent".
                </div>
              </div>

              <!-- Vision -->
              <div class="border-l-4 border-green-500 pl-4">
                <h4 class="font-bold text-gray-900 dark:text-white text-base">
                  Vision (Visual Analysis)
                </h4>
                <p class="text-gray-500 dark:text-gray-400 mt-1">
                  Integrates visual context from OCR (photos, diagrams, signatures) into the decision process.
                </p>
                <div class="mt-2 bg-gray-50 dark:bg-gray-900 p-3 rounded text-gray-800 dark:text-gray-300 font-mono text-xs">
                  <span class="text-green-600 dark:text-green-400 font-bold">How it works:</span> Mistral OCR describes images (e.g. "photo of water leak"). The prompt explicitly asks to consider these visual descriptions.<br>
                  <span class="text-green-600 dark:text-green-400 font-bold">Example:</span> An email body says "See attached". The PDF contains a photo of a crashed car. The model uses "car crash photo" to classify as "Vehicle Accident".
                </div>
              </div>
            </div>
          </div>
          <div class="bg-gray-50 dark:bg-gray-700 px-4 py-3 sm:px-6 sm:flex sm:flex-row-reverse">
            <button
              type="button"
              class="w-full inline-flex justify-center rounded-md border border-transparent shadow-sm px-4 py-2 bg-primary-600 text-base font-medium text-white hover:bg-primary-700 focus:outline-none sm:ml-3 sm:w-auto sm:text-sm"
              @click="showStrategyHelp = false"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
