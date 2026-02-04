<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { BookOpenIcon, CpuChipIcon, ShieldCheckIcon, EyeIcon } from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import mermaid from 'mermaid'

const { t } = useI18n()
const isDark = ref(false)
let observer = null

const initMermaid = async () => {
  const darkMode = document.documentElement.classList.contains('dark')
  mermaid.initialize({
    startOnLoad: false,
    theme: darkMode ? 'dark' : 'default',
    securityLevel: 'loose',
    flowchart: { curve: 'basis' }
  })
  await nextTick()
  // Reset any previous SVG
  const element = document.querySelector('.mermaid-graph')
  if (element) {
    element.removeAttribute('data-processed')
    element.innerHTML = diagram
  }
  await mermaid.run({
    nodes: document.querySelectorAll('.mermaid-graph')
  })
}

onMounted(() => {
  isDark.value = document.documentElement.classList.contains('dark')

  // Watch themes
  observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.attributeName === 'class') {
        const newDark = document.documentElement.classList.contains('dark')
        if (newDark !== isDark.value) {
          isDark.value = newDark
          initMermaid()
        }
      }
    })
  })
  observer.observe(document.documentElement, { attributes: true })

  initMermaid()
})

onUnmounted(() => {
  if (observer) observer.disconnect()
})

const diagram = `
graph LR
    Input[Email Input] --> OCR

    subgraph Analysis [OCR & Content Extraction]
        direction TB
        OCR --> Text[Text Layer]
        OCR --> Img[Image Layer]
        Img -->|Image-to-Text| Desc["[Image: Dented Bumper]"]
        Text --> Markdown
        Desc --> Markdown
    end

    Markdown --> PII[PII Check]
    PII --> Classify[AI Classification]

    Classify -->|Confidence > 85%| Auto[Auto Process]
    Classify -->|Confidence < 85%| Review[Human Review]

    style Img fill:#ff9,stroke:#333,color:#000
    style Desc fill:#f9f,stroke:#333,color:#000
`

</script>

<template>
  <div class="w-full mx-auto space-y-8">
    <div class="md:flex md:items-center md:justify-between">
      <div class="min-w-0 flex-1">
        <h2
          class="text-2xl font-bold leading-7 text-gray-900 dark:text-white sm:truncate sm:text-3xl sm:tracking-tight"
        >
          {{ t('guide.title') }}
        </h2>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          {{ t('guide.subtitle') }}
        </p>
      </div>
    </div>

    <!-- Process Flow Diagram -->
    <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg overflow-hidden p-6">
      <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white mb-4">
        {{ t('guide.flow_title') }}
      </h3>
      <div
        class="flex justify-center bg-gray-50 dark:bg-gray-900 p-4 rounded border border-gray-200 dark:border-gray-700 overflow-x-auto"
      >
        <div class="mermaid-graph w-full flex justify-center">
          {{ diagram }}
        </div>
      </div>
    </div>

    <!-- Overview -->
    <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg overflow-hidden">
      <div class="px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white flex items-center gap-2">
          <BookOpenIcon class="h-5 w-5 text-primary-600" />
          {{ t('guide.usage.title') }}
        </h3>
        <div class="mt-4 prose dark:prose-invert text-sm max-w-none">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div>
              <h4 class="font-medium text-gray-900 dark:text-white">
                {{ t('guide.usage.step1_title') }}
              </h4>
              <p class="text-gray-600 dark:text-gray-300">
                {{ t('guide.usage.step1_desc') }}
              </p>
              <ul class="list-disc list-inside space-y-1 text-gray-600 dark:text-gray-300">
                <li>{{ t('guide.usage.step1_li1') }}</li>
                <li>{{ t('guide.usage.step1_li2') }}</li>
                <li>{{ t('guide.usage.step1_li3') }}</li>
              </ul>

              <h4 class="font-medium mt-4 text-gray-900 dark:text-white">
                {{ t('guide.usage.step2_title') }}
              </h4>
              <p class="text-gray-600 dark:text-gray-300">
                {{ t('guide.usage.step2_desc') }}
              </p>
              <ul class="list-disc list-inside space-y-1 text-gray-600 dark:text-gray-300">
                <li>{{ t('guide.usage.step2_li1') }}</li>
                <li>{{ t('guide.usage.step2_li2') }}</li>
                <li>{{ t('guide.usage.step2_li3') }}</li>
              </ul>
            </div>
            <div>
              <h4 class="font-medium text-gray-900 dark:text-white">
                {{ t('guide.usage.step3_title') }}
              </h4>
              <p class="text-gray-600 dark:text-gray-300">
                {{ t('guide.usage.step3_desc') }}
              </p>

              <h4 class="font-medium mt-4 text-gray-900 dark:text-white">
                {{ t('guide.usage.step4_title') }}
              </h4>
              <p class="text-gray-600 dark:text-gray-300">
                {{ t('guide.usage.step4_desc') }}
              </p>
              <ul class="list-disc list-inside space-y-1 text-gray-600 dark:text-gray-300">
                <li>{{ t('guide.usage.step4_li1') }}</li>
                <li>{{ t('guide.usage.step4_li2') }}</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- AI Capabilities -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white flex items-center gap-2">
          <CpuChipIcon class="h-5 w-5 text-indigo-500" />
          {{ t('guide.ai.title') }}
        </h3>
        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
          {{ t('guide.ai.desc') }}
        </p>
        <ul class="mt-3 space-y-2 text-sm text-gray-600 dark:text-gray-300">
          <li class="flex items-start">
            <span class="font-bold mr-2">•</span>
            <span>{{ t('guide.ai.li1') }}</span>
          </li>
          <li class="flex items-start">
            <span class="font-bold mr-2">•</span>
            <span>{{ t('guide.ai.li2') }}</span>
          </li>
          <li class="flex items-start">
            <span class="font-bold mr-2">•</span>
            <span>{{ t('guide.ai.li3') }}</span>
          </li>
        </ul>
      </div>

      <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white flex items-center gap-2">
          <BookOpenIcon class="h-5 w-5 text-teal-500" />
          {{ t('guide.exports.title') }}
        </h3>
        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
          {{ t('guide.exports.desc') }}
        </p>
        <div class="mt-4 space-y-4">
          <details
            class="group bg-gray-50 dark:bg-gray-700/30 rounded-lg border border-gray-200 dark:border-gray-700 open:ring-1 open:ring-teal-500/50"
          >
            <summary
              class="cursor-pointer flex items-center justify-between p-4 font-medium text-sm text-gray-900 dark:text-white select-none"
            >
              <span class="flex items-center gap-2">
                <span class="p-1 rounded bg-teal-100 text-teal-700 dark:bg-teal-900 dark:text-teal-300">CSV</span>
                {{ t('guide.exports.csv_title') }}
              </span>
              <span class="ml-6 flex items-center">
                <svg
                  class="h-5 w-5 transform transition-transform group-open:rotate-180 text-gray-400"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                >
                  <path
                    fill-rule="evenodd"
                    d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                    clip-rule="evenodd"
                  />
                </svg>
              </span>
            </summary>
            <div class="px-4 pb-4 pt-0">
              <p
                class="text-xs text-gray-600 dark:text-gray-300 mb-2 border-t border-gray-200 dark:border-gray-700 pt-2"
              >
                {{ t('guide.exports.csv_desc') }}
              </p>
              <ul class="list-disc list-inside text-xs text-gray-500 dark:text-gray-400 space-y-1">
                <li>{{ t('guide.exports.csv_streaming') }}</li>
                <li>{{ t('guide.exports.csv_columns') }}</li>
              </ul>
            </div>
          </details>

          <details
            class="group bg-teal-50/50 dark:bg-teal-900/10 rounded-lg border border-teal-100 dark:border-teal-800 open:ring-1 open:ring-teal-500/50"
          >
            <summary
              class="cursor-pointer flex items-center justify-between p-4 font-medium text-sm text-gray-900 dark:text-white select-none"
            >
              <span class="flex items-center gap-2">
                <span
                  class="p-1 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300"
                >JSONL</span>
                {{ t('guide.exports.jsonl_title') }}
              </span>
              <span class="ml-6 flex items-center">
                <svg
                  class="h-5 w-5 transform transition-transform group-open:rotate-180 text-gray-400"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                >
                  <path
                    fill-rule="evenodd"
                    d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                    clip-rule="evenodd"
                  />
                </svg>
              </span>
            </summary>
            <div class="px-4 pb-4 pt-0">
              <p
                class="text-xs text-gray-600 dark:text-gray-300 mb-2 border-t border-teal-200 dark:border-teal-800 pt-2"
              >
                {{ t('guide.exports.jsonl_desc') }}
              </p>
              <div class="bg-gray-900 text-gray-200 p-3 rounded text-xs font-mono overflow-x-auto whitespace-pre">
                {{ `{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "{\\"intents\\":
                [...] }"}]}` }}
              </div>
            </div>
          </details>
        </div>
      </div>

      <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white flex items-center gap-2">
          <ShieldCheckIcon class="h-5 w-5 text-green-500" />
          {{ t('guide.privacy.title') }}
        </h3>
        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
          {{ t('guide.privacy.desc') }}
        </p>
        <ul class="mt-3 space-y-2 text-sm text-gray-600 dark:text-gray-300">
          <li class="flex items-start">
            <span class="font-bold mr-2">•</span>
            <span>{{ t('guide.privacy.li1') }}</span>
          </li>
          <li class="flex items-start">
            <span class="font-bold mr-2">•</span>
            <span>{{ t('guide.privacy.li2') }}</span>
          </li>
        </ul>
      </div>
    </div>

    <!-- Features -->
    <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg px-4 py-5 sm:p-6">
      <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white flex items-center gap-2">
        <EyeIcon class="h-5 w-5 text-amber-500" />
        {{ t('guide.vision.title') }}
      </h3>
      <p class="mt-2 text-sm text-gray-500 dark:text-gray-400 max-w-3xl">
        {{ t('guide.vision.desc') }}
      </p>
      <div class="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div class="border border-gray-200 dark:border-gray-700 rounded p-3">
          <h5 class="font-medium text-sm text-gray-900 dark:text-white">
            {{ t('guide.vision.standard_title') }}
          </h5>
          <p class="text-xs text-gray-500 mt-1">
            {{ t('guide.vision.standard_desc') }}
          </p>
        </div>
        <div class="border border-gray-200 dark:border-gray-700 rounded p-3 bg-amber-50 dark:bg-amber-900/10">
          <h5 class="font-medium text-sm text-gray-900 dark:text-white">
            {{ t('guide.vision.vision_title') }}
          </h5>
          <p class="text-xs text-gray-500 mt-1">
            {{ t('guide.vision.vision_desc') }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mermaid-graph {
  min-width: 300px;
}
</style>
