<script setup>
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import mermaid from 'mermaid'
import { CodeBracketIcon, MapIcon, ServerIcon, ArrowsPointingOutIcon, ArrowsPointingInIcon } from '@heroicons/vue/24/outline'

const { t } = useI18n()

const currentTab = ref('architecture')
const isDark = ref(false)
const refDiagramFullscreen = ref(false)
const refDiagramSvg = ref('')
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

  // Render main architecture diagram
  const mainEl = document.querySelector('.mermaid')
  if (mainEl) {
    mainEl.removeAttribute('data-processed')
    mainEl.innerHTML = diagram.value
  }
  await mermaid.run({ nodes: document.querySelectorAll('.mermaid') })

  // Render reference diagram and capture SVG
  const refEl = document.querySelector('.mermaid-ref')
  if (refEl) {
    refEl.removeAttribute('data-processed')
    refEl.innerHTML = refDiagram.value
  }
  await mermaid.run({ nodes: document.querySelectorAll('.mermaid-ref') })
  await nextTick()
  const svg = document.querySelector('.mermaid-ref svg')
  if (svg) {
    refDiagramSvg.value = svg.outerHTML
  }
}

onMounted(() => {
  // Initial theme check
  isDark.value = document.documentElement.classList.contains('dark')

  // Watch for theme changes
  observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.attributeName === 'class') {
        const newDark = document.documentElement.classList.contains('dark')
        if (newDark !== isDark.value) {
          isDark.value = newDark
          if (currentTab.value === 'architecture') initMermaid()
        }
      }
    })
  })
  observer.observe(document.documentElement, { attributes: true })

  if (currentTab.value === 'architecture') {
    initMermaid()
  }
})

onUnmounted(() => {
  if (observer) observer.disconnect()
})

const redocUrl = computed(() => {
  return `/docs/redoc-custom?theme=${isDark.value ? 'dark' : 'light'}`
})

const switchTab = (tab) => {
  currentTab.value = tab
  if (tab === 'architecture') {
    // slight delay to let DOM render
    setTimeout(initMermaid, 100)
  }
}

// Architecture Diagram Definition
// Removing strict classDefs and semi-colons which can sometimes cause parsing issues in strict mode
const diagram = computed(() => `
flowchart TD
    classDef azure fill:#0072C6,stroke:#fff,stroke-width:2px,color:#fff
    classDef app fill:#50e6ff,stroke:#333,stroke-width:2px,color:#000
    classDef db fill:#59b4d9,stroke:#333,stroke-width:2px
    classDef ai fill:#ff9900,stroke:#333,stroke-width:2px,color:#000
    classDef fallback fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#000

    Client([${t('developer_docs.diagram.client')}]) -->|HTTPS| FE[${t('developer_docs.diagram.frontend')}]
    FE -->|API Calls| API[${t('developer_docs.diagram.backend')}]

    subgraph AzureContainerApps [${t('developer_docs.diagram.aca')}]
        API
        Worker[${t('developer_docs.diagram.worker')}]
    end

    API -->|${t('developer_docs.diagram.save_upload')}| Blob[${t('developer_docs.diagram.blob')}]
    API -->|${t('developer_docs.diagram.metadata')}| Cosmos[${t('developer_docs.diagram.cosmos')}]
    API -->|${t('developer_docs.diagram.queue_job')}| SB[${t('developer_docs.diagram.sb')}]

    SB -->|${t('developer_docs.diagram.trigger')}| Worker
    Worker -->|${t('developer_docs.diagram.read_file')}| Blob
    Worker -->|${t('developer_docs.diagram.ocr')}| Mistral[${t('developer_docs.diagram.mistral')}]
    Mistral -.->|${t('developer_docs.diagram.fallback')}| DI[${t('developer_docs.diagram.doc_intelligence')}]
    Worker -->|${t('developer_docs.diagram.classify')}| OPENAI[${t('developer_docs.diagram.openai')}]

    OPENAI -->|"Agentic"| Orch["Orchestrator"]
    Orch -->|"Fan-out"| ParAgents["Parallel Agents"]
    ParAgents -->|"Per-intent"| AISearch[("AI Search Indexes")]
    AISearch -->|"RAG"| ParAgents
    ParAgents -->|"Verdicts"| OPENAI

    subgraph AIFoundry [${t('developer_docs.diagram.ai_foundry')}]
        Mistral
        OPENAI
        DI
    end

    Mistral -->|Markdown| Worker
    DI -.->|Markdown| Worker
    OPENAI -->|JSON Intent| Worker
    Worker -->|${t('developer_docs.diagram.update')}| Cosmos

    class Blob,Cosmos,SB azure
    class FE,API,Worker app
    class Mistral,OPENAI ai
    class DI fallback
`)

// Reference Architecture Diagram (detailed processing flow)
const refDiagram = computed(() => `
flowchart TD
    classDef user fill:#e2e8f0,stroke:#64748b,stroke-width:2px,color:#1e293b
    classDef frontend fill:#dbeafe,stroke:#3b82f6,stroke-width:2px,color:#1e40af
    classDef api fill:#bfdbfe,stroke:#2563eb,stroke-width:2px,color:#1e3a8a
    classDef storage fill:#0072C6,stroke:#fff,stroke-width:2px,color:#fff
    classDef ocr fill:#818cf8,stroke:#6366f1,stroke-width:2px,color:#fff
    classDef decision fill:#475569,stroke:#e2e8f0,stroke-width:2px,color:#fff
    classDef model_primary fill:#f97316,stroke:#ea580c,stroke-width:2px,color:#fff
    classDef model_fallback fill:#22c55e,stroke:#16a34a,stroke-width:2px,color:#fff
    classDef model_parallel fill:#a855f7,stroke:#7c3aed,stroke-width:2px,color:#fff
    classDef result fill:#059669,stroke:#047857,stroke-width:2px,color:#fff
    classDef queue fill:#10b981,stroke:#059669,stroke-width:2px,color:#fff
    classDef agentic fill:#c084fc,stroke:#a855f7,stroke-width:2px,color:#000

    User(["${t('developer_docs.ref_diagram.user')}"])
    SPA["${t('developer_docs.ref_diagram.spa')}"]
    API["${t('developer_docs.ref_diagram.api')}"]
    Blob[("${t('developer_docs.ref_diagram.blob')}")]
    SBQ["${t('developer_docs.ref_diagram.sbq')}"]
    Worker["${t('developer_docs.ref_diagram.worker')}"]
    MistralOCR["${t('developer_docs.ref_diagram.mistral_ocr')}"]
    TokenCheck{"${t('developer_docs.ref_diagram.token_check')}"}
    StratCheck{"${t('developer_docs.ref_diagram.strat_check')}"}
    Phi4["${t('developer_docs.ref_diagram.phi4')}"]
    GPTMini["${t('developer_docs.ref_diagram.gpt_mini')}"]
    Parallel["${t('developer_docs.ref_diagram.parallel')}"]
    Orch["${t('developer_docs.ref_diagram.orchestrator')}"]
    Agents["${t('developer_docs.ref_diagram.agents')}"]
    AISearch[("${t('developer_docs.ref_diagram.ai_search')}")]
    RedTeam["${t('developer_docs.ref_diagram.red_team')}"]
    Cosmos[("${t('developer_docs.ref_diagram.cosmos')}")]
    Result["${t('developer_docs.ref_diagram.result')}"]

    User -->|"Upload PDF"| SPA
    SPA -->|"API"| API
    API -->|"GET"| Blob
    API -->|"Event Grid"| SBQ
    SBQ -->|"Download"| Worker
    Worker -->|"OCR"| MistralOCR
    MistralOCR -->|"Markdown"| API
    API -->|"Estimate tokens"| TokenCheck

    TokenCheck -->|"YES - Under 8K"| Phi4
    TokenCheck -->|"NO - Over 8K"| GPTMini

    API --> StratCheck
    StratCheck -->|"Standard"| Parallel
    StratCheck -->|"Agentic"| Orch

    Orch -->|"Fan-out"| Agents
    Agents -->|"Per-intent"| AISearch
    AISearch -->|"RAG"| Agents
    Agents -->|"Verdicts"| RedTeam
    RedTeam --> Result

    Parallel --> Result
    Phi4 --> Result
    GPTMini --> Result
    Result -->|"JSON"| Cosmos
    Cosmos -->|"Classification"| API

    class User user
    class SPA frontend
    class API api
    class Blob,Cosmos storage
    class SBQ queue
    class Worker api
    class MistralOCR ocr
    class TokenCheck,StratCheck decision
    class Phi4 model_primary
    class GPTMini model_fallback
    class Parallel model_parallel
    class Orch,Agents,RedTeam agentic
    class AISearch storage
    class Result result
`)
</script>

<template>
  <div class="max-w-6xl mx-auto space-y-6">
    <div class="md:flex md:items-center md:justify-between">
      <div class="min-w-0 flex-1">
        <h2
          class="text-2xl font-bold leading-7 text-gray-900 dark:text-white sm:truncate sm:text-3xl sm:tracking-tight">
          {{ t('developer_docs.title') }}
        </h2>
      </div>
    </div>

    <!-- Tabs -->
    <div class="border-b border-gray-200 dark:border-gray-700">
      <nav class="-mb-px flex space-x-8" aria-label="Tabs">
        <button
          :class="[currentTab === 'architecture' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300', 'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium']"
          @click="switchTab('architecture')">
          <MapIcon class="-ml-0.5 mr-2 h-5 w-5" aria-hidden="true" />
          {{ t('developer_docs.tabs.architecture') }}
        </button>
        <button
          :class="[currentTab === 'api' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300', 'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium']"
          @click="switchTab('api')">
          <ServerIcon class="-ml-0.5 mr-2 h-5 w-5" aria-hidden="true" />
          {{ t('developer_docs.tabs.api') }}
        </button>
        <button
          :class="[currentTab === 'repo' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300', 'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium']"
          @click="switchTab('repo')">
          <CodeBracketIcon class="-ml-0.5 mr-2 h-5 w-5" aria-hidden="true" />
          {{ t('developer_docs.tabs.repo') }}
        </button>
      </nav>
    </div>

    <!-- Content -->
    <div class="py-4">
      <!-- Architecture Tab -->
      <div v-if="currentTab === 'architecture'" class="space-y-8">
        <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg p-6">
          <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white mb-4">
            {{ t('developer_docs.architecture.title') }}
          </h3>
          <!-- eslint-disable vue/no-v-html -->
          <p class="text-sm text-gray-500 dark:text-gray-400 mb-6"
            v-html="t('developer_docs.architecture.desc_html')" />
          <!-- eslint-enable vue/no-v-html -->

          <div
            class="flex justify-center bg-white dark:bg-gray-900 p-4 rounded border border-gray-200 dark:border-gray-700 overflow-x-auto">
            <div class="mermaid">
              {{ diagram }}
            </div>
          </div>
        </div>

        <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg p-6">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white">
              {{ t('developer_docs.architecture.ref_title') }}
            </h3>
            <button @click="refDiagramFullscreen = true"
              class="inline-flex items-center gap-1.5 text-xs text-gray-500 hover:text-primary-600 dark:text-gray-400 dark:hover:text-primary-400 transition-colors border border-gray-200 dark:border-gray-700 rounded-md px-2.5 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-700">
              <ArrowsPointingOutIcon class="h-4 w-4" />
              Fullscreen
            </button>
          </div>

          <!-- Fullscreen overlay -->
          <Teleport to="body">
            <div v-if="refDiagramFullscreen" class="fixed inset-0 z-50 bg-gray-950/95 flex flex-col"
              @keydown.escape="refDiagramFullscreen = false">
              <div class="flex items-center justify-between px-6 py-3 border-b border-gray-700 bg-gray-900">
                <h3 class="text-white font-semibold text-sm">{{ t('developer_docs.architecture.ref_title') }}</h3>
                <button @click="refDiagramFullscreen = false"
                  class="text-gray-400 hover:text-white transition-colors flex items-center gap-1.5 text-sm border border-gray-600 rounded-md px-3 py-1.5 hover:bg-gray-800">
                  <ArrowsPointingInIcon class="h-4 w-4" />
                  Close
                </button>
              </div>
              <div class="flex-1 overflow-auto p-8 flex items-center justify-center">
                <!-- eslint-disable vue/no-v-html -->
                <div v-if="refDiagramSvg" class="fullscreen-ref-diagram" v-html="refDiagramSvg" />
                <!-- eslint-enable vue/no-v-html -->
                <p v-else class="text-gray-400 text-sm">Diagram not available. Close and try again.</p>
              </div>
            </div>
          </Teleport>

          <div
            class="flex justify-center bg-white dark:bg-gray-900 p-4 rounded border border-gray-200 dark:border-gray-700 overflow-x-auto cursor-pointer"
            @dblclick="refDiagramFullscreen = true" title="Double-click to enlarge">
            <div class="mermaid-ref w-full flex justify-center">
              {{ refDiagram }}
            </div>
          </div>
        </div>
      </div>

      <!-- API Tab -->
      <div v-if="currentTab === 'api'" class="bg-white shadow sm:rounded-lg overflow-hidden h-[800px] relative">
        <div class="absolute top-2 right-2 z-10">
          <a :href="redocUrl" target="_blank"
            class="inline-flex items-center rounded-md bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50">
            {{ t('developer_docs.api.open_new_tab') }}
          </a>
        </div>
        <!-- Using standard /redoc endpoint -->
        <iframe :src="redocUrl" class="w-full h-full border-0" />
      </div>

      <!-- Repo Tab -->
      <div v-if="currentTab === 'repo'" class="bg-white dark:bg-gray-800 shadow sm:rounded-lg p-6">
        <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white mb-4">
          {{ t('developer_docs.repo.title') }}
        </h3>
        <div class="space-y-4">
          <p class="text-gray-600 dark:text-gray-300">
            {{ t('developer_docs.repo.desc') }}
          </p>
          <a href="https://github.com/olmertens/ClassyMail" target="_blank"
            class="inline-flex items-center gap-x-2 rounded-md bg-gray-900 px-3.5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-gray-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900">
            <svg class="h-5 w-5 fill-current" viewBox="0 0 24 24" aria-hidden="true">
              <path fill-rule="evenodd"
                d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
                clip-rule="evenodd" />
            </svg>
            {{ t('developer_docs.repo.cta') }}
          </a>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
.mermaid,
.mermaid-ref {
  width: 100%;
  display: flex;
  justify-content: center;
}

.fullscreen-ref-diagram svg {
  max-width: 95vw;
  max-height: 80vh;
  width: auto;
  height: auto;
}
</style>
