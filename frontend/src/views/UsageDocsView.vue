<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { BookOpenIcon, CpuChipIcon, ShieldCheckIcon, EyeIcon, ArrowPathIcon, ChartBarIcon, ArrowsPointingOutIcon, ArrowsPointingInIcon, AdjustmentsHorizontalIcon } from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import mermaid from 'mermaid'

const { t } = useI18n()
const isDark = ref(false)
const diagramFullscreen = ref(false)
const diagramSvgHtml = ref('')
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
  const element = document.querySelector('.mermaid-graph')
  if (element) {
    element.removeAttribute('data-processed')
    element.innerHTML = diagram
  }
  await mermaid.run({
    nodes: document.querySelectorAll('.mermaid-graph')
  })
  // Capture rendered SVG for fullscreen reuse
  await nextTick()
  const svg = document.querySelector('.mermaid-graph svg')
  if (svg) {
    diagramSvgHtml.value = svg.outerHTML
  }
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
flowchart LR
    Upload["Upload PDF"] --> Blob["Blob Storage"]
    Blob -->|Event Grid| SBQ["Service Bus Queue"]
    SBQ --> Worker["Worker"]

    subgraph OCR ["OCR - Content Extraction"]
        direction TB
        Mistral["Mistral OCR"] -.->|Fallback| DI["Doc Intelligence"]
        Mistral --> MD["Markdown + Images"]
        DI --> MD
    end

    Worker --> OCR
    MD --> PII{"PII Detection?"}
    PII -->|LLM / Azure / Hybrid| Anonymize["Flag Sensitive Data"]
    Anonymize --> Classify{"Token Budget?"}

    Classify -->|Under 8K| Phi4["Phi-4 - Primary"]
    Classify -->|Over 8K| GPT["GPT-4o-mini - Fallback"]
    Classify -->|Agentic| Orch["Orchestrator"]

    Orch -->|"Top 5-6 intents"| Agents["Parallel Agents"]
    Agents -->|"Per-intent"| AISearch["AI Search RAG"]
    AISearch -->|"Positive + Negative examples"| Agents
    Agents -->|"Low confidence"| RedTeam["Red Team"]
    Agents -->|"High confidence"| Result
    RedTeam --> Result

    Phi4 --> Result["Classification Result"]
    GPT --> Result
    Result -->|Confidence over 85%| Auto["Auto Processed"]
    Result -->|Confidence under 85%| Review["Human Review"]
    Auto --> Cosmos["Cosmos DB"]
    Review --> Cosmos

    style Upload fill:#2563eb,stroke:#1e40af,color:#fff
    style Blob fill:#f59e0b,stroke:#d97706,color:#000
    style SBQ fill:#10b981,stroke:#059669,color:#fff
    style Worker fill:#0891b2,stroke:#0e7490,color:#fff
    style Mistral fill:#f97316,stroke:#ea580c,color:#000
    style DI fill:#ea580c,stroke:#c2410c,color:#fff
    style MD fill:#64748b,stroke:#475569,color:#fff
    style PII fill:#ec4899,stroke:#db2777,color:#fff
    style Anonymize fill:#f472b6,stroke:#ec4899,color:#000
    style Classify fill:#64748b,stroke:#475569,color:#fff
    style Phi4 fill:#818cf8,stroke:#6366f1,color:#000
    style GPT fill:#a78bfa,stroke:#7c3aed,color:#000
    style Result fill:#6366f1,stroke:#4f46e5,color:#fff
    style Auto fill:#34d399,stroke:#10b981,color:#000
    style Review fill:#eab308,stroke:#ca8a04,color:#000
    style Cosmos fill:#059669,stroke:#047857,color:#fff
    style Orch fill:#a855f7,stroke:#9333ea,color:#fff
    style Agents fill:#c084fc,stroke:#a855f7,color:#000
    style AISearch fill:#e9d5ff,stroke:#a855f7,color:#000
    style RedTeam fill:#f43f5e,stroke:#e11d48,color:#fff
`

</script>

<template>
  <div class="w-full mx-auto space-y-8">
    <div class="md:flex md:items-center md:justify-between">
      <div class="min-w-0 flex-1">
        <h2
          class="text-2xl font-bold leading-7 text-gray-900 dark:text-white sm:truncate sm:text-3xl sm:tracking-tight">
          {{ t('guide.title') }}
        </h2>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          {{ t('guide.subtitle') }}
        </p>
      </div>
    </div>

    <!-- Feature Highlights -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div
        class="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4 text-center">
        <CpuChipIcon class="h-8 w-8 text-blue-600 dark:text-blue-400 mx-auto" />
        <p class="mt-2 text-sm font-semibold text-gray-900 dark:text-white">
          {{ t('guide.highlights.ai_models') }}
        </p>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          {{ t('guide.highlights.ai_models_desc') }}
        </p>
      </div>
      <div
        class="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4 text-center">
        <ShieldCheckIcon class="h-8 w-8 text-green-600 dark:text-green-400 mx-auto" />
        <p class="mt-2 text-sm font-semibold text-gray-900 dark:text-white">
          {{ t('guide.highlights.pii') }}
        </p>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          {{ t('guide.highlights.pii_desc') }}
        </p>
      </div>
      <div
        class="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4 text-center">
        <EyeIcon class="h-8 w-8 text-amber-600 dark:text-amber-400 mx-auto" />
        <p class="mt-2 text-sm font-semibold text-gray-900 dark:text-white">
          {{ t('guide.highlights.vision') }}
        </p>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          {{ t('guide.highlights.vision_desc') }}
        </p>
      </div>
      <div
        class="bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800 rounded-lg p-4 text-center">
        <ChartBarIcon class="h-8 w-8 text-purple-600 dark:text-purple-400 mx-auto" />
        <p class="mt-2 text-sm font-semibold text-gray-900 dark:text-white">
          {{ t('guide.highlights.exports') }}
        </p>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          {{ t('guide.highlights.exports_desc') }}
        </p>
      </div>
    </div>

    <!-- Process Flow Diagram -->
    <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg overflow-hidden p-6">
      <div class="flex items-center justify-between mb-2">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
          {{ t('guide.flow_title') }}
        </h3>
        <button @click="diagramFullscreen = true"
          class="inline-flex items-center gap-1.5 text-xs text-gray-500 hover:text-primary-600 dark:text-gray-400 dark:hover:text-primary-400 transition-colors border border-gray-200 dark:border-gray-700 rounded-md px-2.5 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-700">
          <ArrowsPointingOutIcon class="h-4 w-4" />
          Fullscreen
        </button>
      </div>
      <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
        {{ t('guide.flow_desc') }}
      </p>

      <!-- Fullscreen overlay — uses pre-rendered SVG -->
      <Teleport to="body">
        <div v-if="diagramFullscreen" class="fixed inset-0 z-50 bg-gray-950/95 flex flex-col"
          @keydown.escape="diagramFullscreen = false">
          <div class="flex items-center justify-between px-6 py-3 border-b border-gray-700 bg-gray-900">
            <h3 class="text-white font-semibold text-sm">{{ t('guide.flow_title') }}</h3>
            <button @click="diagramFullscreen = false"
              class="text-gray-400 hover:text-white transition-colors flex items-center gap-1.5 text-sm border border-gray-600 rounded-md px-3 py-1.5 hover:bg-gray-800">
              <ArrowsPointingInIcon class="h-4 w-4" />
              Close
            </button>
          </div>
          <div class="flex-1 overflow-auto p-8 flex items-center justify-center">
            <!-- eslint-disable vue/no-v-html -->
            <div v-if="diagramSvgHtml" class="fullscreen-diagram" v-html="diagramSvgHtml" />
            <!-- eslint-enable vue/no-v-html -->
            <p v-else class="text-gray-400 text-sm">Diagram not available. Close and try again.</p>
          </div>
        </div>
      </Teleport>

      <div
        class="flex justify-center bg-gray-50 dark:bg-gray-900 p-4 rounded-lg border border-gray-200 dark:border-gray-700 overflow-x-auto cursor-pointer"
        @dblclick="diagramFullscreen = true" title="Double-click to enlarge">
        <div class="mermaid-graph w-full flex justify-center">
          {{ diagram }}
        </div>
      </div>
      <div class="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div class="flex items-center gap-2">
          <span class="inline-block w-3 h-3 rounded" style="background:#2563eb" />
          <span class="text-gray-600 dark:text-gray-300">{{ t('guide.legend.upload') }}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="inline-block w-3 h-3 rounded" style="background:#f97316" />
          <span class="text-gray-600 dark:text-gray-300">{{ t('guide.legend.ocr') }}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="inline-block w-3 h-3 rounded" style="background:#818cf8" />
          <span class="text-gray-600 dark:text-gray-300">{{ t('guide.legend.classification') }}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="inline-block w-3 h-3 rounded" style="background:#059669" />
          <span class="text-gray-600 dark:text-gray-300">{{ t('guide.legend.storage') }}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="inline-block w-3 h-3 rounded" style="background:#a855f7" />
          <span class="text-gray-600 dark:text-gray-300">{{ t('guide.legend.agentic') }}</span>
        </div>
      </div>
    </div>

    <!-- Overview / How to Use -->
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
                <li>{{ t('guide.usage.step1_li4') }}</li>
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
                <li>{{ t('guide.usage.step2_li4') }}</li>
              </ul>
            </div>
            <div>
              <h4 class="font-medium text-gray-900 dark:text-white">
                {{ t('guide.usage.step3_title') }}
              </h4>
              <p class="text-gray-600 dark:text-gray-300">
                {{ t('guide.usage.step3_desc') }}
              </p>
              <ul class="list-disc list-inside space-y-1 text-gray-600 dark:text-gray-300">
                <li>{{ t('guide.usage.step3_li1') }}</li>
                <li>{{ t('guide.usage.step3_li2') }}</li>
              </ul>

              <h4 class="font-medium mt-4 text-gray-900 dark:text-white">
                {{ t('guide.usage.step4_title') }}
              </h4>
              <p class="text-gray-600 dark:text-gray-300">
                {{ t('guide.usage.step4_desc') }}
              </p>
              <ul class="list-disc list-inside space-y-1 text-gray-600 dark:text-gray-300">
                <li>{{ t('guide.usage.step4_li1') }}</li>
                <li>{{ t('guide.usage.step4_li2') }}</li>
                <li>{{ t('guide.usage.step4_li3') }}</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Processing Strategies -->
    <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg overflow-hidden">
      <div class="px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white flex items-center gap-2">
          <ArrowPathIcon class="h-5 w-5 text-cyan-500" />
          {{ t('guide.strategies.title') }}
        </h3>
        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
          {{ t('guide.strategies.desc') }}
        </p>
        <div class="mt-4 grid grid-cols-1 md:grid-cols-4 gap-4">

          <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
            <div class="flex items-center gap-2 mb-2">
              <span class="inline-block w-2.5 h-2.5 rounded-full bg-blue-500" />
              <h5 class="font-medium text-sm text-gray-900 dark:text-white">
                {{ t('guide.strategies.standard_title') }}
              </h5>
            </div>
            <p class="text-xs text-gray-600 dark:text-gray-300">
              {{ t('guide.strategies.standard_desc') }}
            </p>
          </div>
          <div
            class="border border-indigo-200 dark:border-indigo-700 rounded-lg p-4 bg-indigo-50/50 dark:bg-indigo-900/10">
            <div class="flex items-center gap-2 mb-2">
              <span class="inline-block w-2.5 h-2.5 rounded-full bg-indigo-500" />
              <h5 class="font-medium text-sm text-gray-900 dark:text-white">
                {{ t('guide.strategies.reasoning_title') }}
              </h5>
            </div>
            <p class="text-xs text-gray-600 dark:text-gray-300">
              {{ t('guide.strategies.reasoning_desc') }}
            </p>
          </div>
          <div class="border border-amber-200 dark:border-amber-700 rounded-lg p-4 bg-amber-50/50 dark:bg-amber-900/10">
            <div class="flex items-center gap-2 mb-2">
              <span class="inline-block w-2.5 h-2.5 rounded-full bg-amber-500" />
              <h5 class="font-medium text-sm text-gray-900 dark:text-white">
                {{ t('guide.strategies.vision_title') }}
              </h5>
            </div>
            <p class="text-xs text-gray-600 dark:text-gray-300">
              {{ t('guide.strategies.vision_desc') }}
            </p>
          </div>
          <div
            class="border border-purple-200 dark:border-purple-700 rounded-lg p-4 bg-purple-50/50 dark:bg-purple-900/10">
            <div class="flex items-center gap-2 mb-2">
              <span class="inline-block w-2.5 h-2.5 rounded-full bg-purple-500" />
              <h5 class="font-medium text-sm text-gray-900 dark:text-white">
                {{ t('guide.strategies.agentic_title') }}
              </h5>
            </div>
            <p class="text-xs text-gray-600 dark:text-gray-300">
              {{ t('guide.strategies.agentic_desc') }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- Agentic Tier System -->
    <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg overflow-hidden">
      <div class="px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white flex items-center gap-2">
          <AdjustmentsHorizontalIcon class="h-5 w-5 text-purple-500" />
          Agentic Pipeline — How Tiers Work
        </h3>
        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
          In Agentic mode, the orchestrator assigns a rough confidence to each candidate intent. That confidence
          determines which model tier the specialized agent uses — optimizing cost for easy cases and accuracy for hard
          ones.
        </p>

        <div class="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
          <div
            class="rounded-lg border-2 border-green-200 dark:border-green-800 p-4 bg-green-50/50 dark:bg-green-900/10">
            <div class="flex items-center gap-2 mb-2">
              <span
                class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-green-500 text-white text-xs font-bold">1</span>
              <h5 class="font-medium text-sm text-gray-900 dark:text-white">Tier 1 — Simple</h5>
            </div>
            <p class="text-xs text-gray-600 dark:text-gray-300 mb-1"><strong>Trigger:</strong> Orchestrator confidence
              &gt; 80%</p>
            <p class="text-xs text-gray-600 dark:text-gray-300 mb-2"><strong>Default model:</strong> gpt-4.1-nano</p>
            <p class="text-xs text-gray-500 dark:text-gray-400">
              The document clearly matches — keywords are obvious, tone is unambiguous. The cheapest model is
              sufficient. The agent may still call its AI Search tool to verify.
            </p>
          </div>

          <div
            class="rounded-lg border-2 border-amber-200 dark:border-amber-800 p-4 bg-amber-50/50 dark:bg-amber-900/10">
            <div class="flex items-center gap-2 mb-2">
              <span
                class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-amber-500 text-white text-xs font-bold">2</span>
              <h5 class="font-medium text-sm text-gray-900 dark:text-white">Tier 2 — Ambiguous</h5>
            </div>
            <p class="text-xs text-gray-600 dark:text-gray-300 mb-1"><strong>Trigger:</strong> Orchestrator confidence
              50–80%</p>
            <p class="text-xs text-gray-600 dark:text-gray-300 mb-2"><strong>Default model:</strong> gpt-4.1-mini</p>
            <p class="text-xs text-gray-500 dark:text-gray-400">
              The document has subtle signals — could match multiple intents. A more capable model resolves ambiguity.
              RAG provides context from similar previously classified documents.
            </p>
          </div>

          <div class="rounded-lg border-2 border-red-200 dark:border-red-800 p-4 bg-red-50/50 dark:bg-red-900/10">
            <div class="flex items-center gap-2 mb-2">
              <span
                class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-red-500 text-white text-xs font-bold">3</span>
              <h5 class="font-medium text-sm text-gray-900 dark:text-white">Tier 3 — Critical</h5>
            </div>
            <p class="text-xs text-gray-600 dark:text-gray-300 mb-1"><strong>Trigger:</strong> Orchestrator confidence
              &lt; 50%</p>
            <p class="text-xs text-gray-600 dark:text-gray-300 mb-2"><strong>Default model:</strong> gpt-4.1</p>
            <p class="text-xs text-gray-500 dark:text-gray-400">
              The document is complex or the intent is unclear. The most robust model is used for maximum accuracy. Red
              Team quality gate is more likely to trigger.
            </p>
          </div>
        </div>

        <div
          class="mt-6 rounded-lg bg-purple-50 dark:bg-purple-900/10 border border-purple-200 dark:border-purple-800 p-4">
          <h4 class="text-sm font-semibold text-purple-800 dark:text-purple-300 mb-2">Tips for Better Performance</h4>
          <ul class="text-xs text-gray-600 dark:text-gray-300 space-y-1.5">
            <li>• <strong>Category definitions matter most</strong> — clear, specific definitions with concrete keywords
              help the orchestrator route with higher confidence (Tier 1 more often = cheaper).</li>
            <li>• <strong>Exclusions reduce false positives</strong> — defining what an intent is NOT prevents agents
              from matching similar-but-wrong documents.</li>
            <li>• <strong>Enable AI Search indexes</strong> — the RAG tool gives each agent reference examples (positive
              + negative), significantly improving accuracy.</li>
            <li>• <strong>Human corrections feed back</strong> — when you correct a classification in the UI, it becomes
              a negative example in the AI Search index.</li>
            <li>• <strong>Red Team threshold tuning</strong> — start with 0.7, lower to 0.5 for strict reviews, raise to
              0.85 for lenient.</li>
            <li>• <strong>Model selection per tier</strong> — use nano for Tier 1, keep robust models only for Tier 3.
            </li>
            <li>• <strong>Retrieval mode</strong> — "semantic" for best quality, "hybrid" for balanced, "vector" for
              fastest.</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- AI Capabilities + Exports -->
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
          <li class="flex items-start">
            <span class="font-bold mr-2">•</span>
            <span>{{ t('guide.ai.li4') }}</span>
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
            class="group bg-gray-50 dark:bg-gray-700/30 rounded-lg border border-gray-200 dark:border-gray-700 open:ring-1 open:ring-teal-500/50">
            <summary
              class="cursor-pointer flex items-center justify-between p-4 font-medium text-sm text-gray-900 dark:text-white select-none">
              <span class="flex items-center gap-2">
                <span class="p-1 rounded bg-teal-100 text-teal-700 dark:bg-teal-900 dark:text-teal-300">CSV</span>
                {{ t('guide.exports.csv_title') }}
              </span>
              <span class="ml-6 flex items-center">
                <svg class="h-5 w-5 transform transition-transform group-open:rotate-180 text-gray-400"
                  viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd"
                    d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                    clip-rule="evenodd" />
                </svg>
              </span>
            </summary>
            <div class="px-4 pb-4 pt-0">
              <p
                class="text-xs text-gray-600 dark:text-gray-300 mb-2 border-t border-gray-200 dark:border-gray-700 pt-2">
                {{ t('guide.exports.csv_desc') }}
              </p>
              <ul class="list-disc list-inside text-xs text-gray-500 dark:text-gray-400 space-y-1">
                <li>{{ t('guide.exports.csv_streaming') }}</li>
                <li>{{ t('guide.exports.csv_columns') }}</li>
              </ul>
            </div>
          </details>

          <details
            class="group bg-teal-50/50 dark:bg-teal-900/10 rounded-lg border border-teal-100 dark:border-teal-800 open:ring-1 open:ring-teal-500/50">
            <summary
              class="cursor-pointer flex items-center justify-between p-4 font-medium text-sm text-gray-900 dark:text-white select-none">
              <span class="flex items-center gap-2">
                <span
                  class="p-1 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300">JSONL</span>
                {{ t('guide.exports.jsonl_title') }}
              </span>
              <span class="ml-6 flex items-center">
                <svg class="h-5 w-5 transform transition-transform group-open:rotate-180 text-gray-400"
                  viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd"
                    d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                    clip-rule="evenodd" />
                </svg>
              </span>
            </summary>
            <div class="px-4 pb-4 pt-0">
              <p
                class="text-xs text-gray-600 dark:text-gray-300 mb-2 border-t border-teal-200 dark:border-teal-800 pt-2">
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

      <!-- Privacy & PII -->
      <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white flex items-center gap-2">
          <ShieldCheckIcon class="h-5 w-5 text-green-500" />
          {{ t('guide.privacy.title') }}
        </h3>
        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
          {{ t('guide.privacy.desc') }}
        </p>

        <!-- Detection sub-section -->
        <div
          class="mt-4 border border-green-200 dark:border-green-800 rounded-lg p-4 bg-green-50/50 dark:bg-green-900/10">
          <h4 class="font-medium text-sm text-gray-900 dark:text-white flex items-center gap-1.5">
            <span class="inline-block w-2 h-2 rounded-full bg-green-500" />
            {{ t('guide.privacy.detection_title') }}
          </h4>
          <p class="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
            {{ t('guide.privacy.detection_desc') }}
          </p>
          <ul class="mt-2 space-y-1.5 text-sm text-gray-600 dark:text-gray-300">
            <li class="flex items-start">
              <span class="font-bold mr-2">•</span>
              <span>{{ t('guide.privacy.detection_li1') }}</span>
            </li>
            <li class="flex items-start">
              <span class="font-bold mr-2">•</span>
              <span>{{ t('guide.privacy.detection_li2') }}</span>
            </li>
            <li class="flex items-start">
              <span class="font-bold mr-2">•</span>
              <span>{{ t('guide.privacy.detection_li3') }}</span>
            </li>
            <li class="flex items-start">
              <span class="font-bold mr-2">•</span>
              <span>{{ t('guide.privacy.detection_li4') }}</span>
            </li>
          </ul>
          <p class="mt-2 text-xs text-gray-500 dark:text-gray-400 italic">
            {{ t('guide.privacy.detection_categories') }}
          </p>
        </div>

        <!-- Anonymization sub-section -->
        <div
          class="mt-3 border border-indigo-200 dark:border-indigo-800 rounded-lg p-4 bg-indigo-50/50 dark:bg-indigo-900/10">
          <h4 class="font-medium text-sm text-gray-900 dark:text-white flex items-center gap-1.5">
            <span class="inline-block w-2 h-2 rounded-full bg-indigo-500" />
            {{ t('guide.privacy.anonymization_title') }}
          </h4>
          <p class="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
            {{ t('guide.privacy.anonymization_desc') }}
          </p>
          <ul class="mt-2 space-y-1.5 text-sm text-gray-600 dark:text-gray-300">
            <li class="flex items-start">
              <span class="font-bold mr-2">•</span>
              <span>{{ t('guide.privacy.anonymization_li1') }}</span>
            </li>
            <li class="flex items-start">
              <span class="font-bold mr-2">•</span>
              <span>{{ t('guide.privacy.anonymization_li2') }}</span>
            </li>
            <li class="flex items-start">
              <span class="font-bold mr-2">•</span>
              <span>{{ t('guide.privacy.anonymization_li3') }}</span>
            </li>
          </ul>
        </div>

        <!-- Settings hint -->
        <p class="mt-3 text-xs text-primary-600 dark:text-primary-400 font-medium">
          {{ t('guide.privacy.settings_hint') }}
        </p>
      </div>

      <!-- Smart Vision -->
      <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white flex items-center gap-2">
          <EyeIcon class="h-5 w-5 text-amber-500" />
          {{ t('guide.vision.title') }}
        </h3>
        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
          {{ t('guide.vision.desc') }}
        </p>
        <div class="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
            <h5 class="font-medium text-sm text-gray-900 dark:text-white">
              {{ t('guide.vision.standard_title') }}
            </h5>
            <p class="text-xs text-gray-600 dark:text-gray-300 mt-1">
              {{ t('guide.vision.standard_desc') }}
            </p>
          </div>
          <div class="border border-amber-200 dark:border-amber-700 rounded-lg p-4 bg-amber-50 dark:bg-amber-900/20">
            <h5 class="font-medium text-sm text-gray-900 dark:text-white">
              {{ t('guide.vision.vision_title') }}
            </h5>
            <p class="text-xs text-gray-600 dark:text-gray-300 mt-1">
              {{ t('guide.vision.vision_desc') }}
            </p>
          </div>
        </div>
        <div class="mt-4 border border-cyan-200 dark:border-cyan-800 rounded-lg p-4 bg-cyan-50/50 dark:bg-cyan-900/10">
          <h5 class="font-medium text-sm text-gray-900 dark:text-white">
            {{ t('guide.vision.fallback_title') }}
          </h5>
          <p class="text-xs text-gray-600 dark:text-gray-300 mt-1">
            {{ t('guide.vision.fallback_desc') }}
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

<style>
/* Fullscreen diagram SVG scaling (unscoped - targets teleported content) */
.fullscreen-diagram svg {
  max-width: 95vw;
  max-height: 80vh;
  width: auto;
  height: auto;
}
</style>
