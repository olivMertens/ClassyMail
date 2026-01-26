<script setup>
import { ref, onMounted, nextTick } from 'vue'
import mermaid from 'mermaid'
import { LinkIcon, CodeBracketIcon, MapIcon, BookOpenIcon, ServerIcon } from '@heroicons/vue/24/outline'

const currentTab = ref('architecture')

const initMermaid = async () => {
    mermaid.initialize({
        startOnLoad: false,
        theme: document.documentElement.classList.contains('dark') ? 'dark' : 'default',
        securityLevel: 'loose'
    })
    await nextTick()
    await mermaid.run({
        nodes: document.querySelectorAll('.mermaid')
    })
}

onMounted(() => {
    if (currentTab.value === 'architecture') {
        initMermaid()
    }
})

const switchTab = (tab) => {
    currentTab.value = tab
    if (tab === 'architecture') {
        // slight delay to let DOM render
        setTimeout(initMermaid, 100)
    }
}

// Architecture Diagram Definition
const diagram = `
graph TD
    classDef azure fill:#0072C6,stroke:#fff,stroke-width:2px,color:#fff;
    classDef app fill:#50e6ff,stroke:#333,stroke-width:2px;
    classDef db fill:#59b4d9,stroke:#333,stroke-width:2px;
    classDef ai fill:#ff9900,stroke:#333,stroke-width:2px;

    Client([Client Browser]) -->|HTTPS| FE[Vue Frontend]
    FE -->|API Calls| API[FastAPI Backend]

    subgraph Azure Container Apps
        API
        Worker[Background Worker]
    end

    API -->|Save Upload| Blob[Azure Blob Storage]
    API -->|Metadata| Cosmos[Cosmos DB]
    API -->|Queue Job| SB[Service Bus]

    SB -->|Trigger| Worker
    Worker -->|Read File| Blob
    Worker -->|OCR| Mistral[Mistral AI OCR]
    Worker -->|Classify| OPENAI[Azure OpenAI Phi-4]

    Mistral -->|Markdown| Worker
    OPENAI -->|JSON Intent| Worker
    Worker -->|Update| Cosmos

    class Blob,Cosmos,SB azure;
    class FE,API,Worker app;
    class Mistral,OPENAI ai;
`
</script>

<template>
  <div class="max-w-6xl mx-auto space-y-6">
    <div class="md:flex md:items-center md:justify-between">
      <div class="min-w-0 flex-1">
        <h2 class="text-2xl font-bold leading-7 text-gray-900 dark:text-white sm:truncate sm:text-3xl sm:tracking-tight">
          Developer Documentation
        </h2>
      </div>
    </div>

    <!-- Tabs -->
    <div class="border-b border-gray-200 dark:border-gray-700">
        <nav class="-mb-px flex space-x-8" aria-label="Tabs">
            <button
                @click="switchTab('architecture')"
                :class="[currentTab === 'architecture' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300', 'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium']"
            >
                <MapIcon class="-ml-0.5 mr-2 h-5 w-5" aria-hidden="true" />
                Architecture
            </button>
            <button
                @click="switchTab('api')"
                :class="[currentTab === 'api' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300', 'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium']"
            >
                <ServerIcon class="-ml-0.5 mr-2 h-5 w-5" aria-hidden="true" />
                API Reference (Redoc)
            </button>
            <button
                @click="switchTab('repo')"
                :class="[currentTab === 'repo' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300', 'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium']"
            >
                <CodeBracketIcon class="-ml-0.5 mr-2 h-5 w-5" aria-hidden="true" />
                Repository
            </button>
        </nav>
    </div>

    <!-- Content -->
    <div class="py-4">
        <!-- Architecture Tab -->
        <div v-if="currentTab === 'architecture'" class="space-y-8">
            <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg p-6">
                <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white mb-4">System Architecture</h3>
                <p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
                    The ClassiMail system leverages Azure Container Apps, Azure AI Services, and Cosmos DB to provide a scalable email classification pipeline.
                </p>

                <div class="flex justify-center bg-white dark:bg-gray-900 p-4 rounded border border-gray-200 dark:border-gray-700 overflow-x-auto">
                    <div class="mermaid">
                        {{ diagram }}
                    </div>
                </div>
            </div>

            <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg p-6">
                 <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white mb-4">Reference Architecture</h3>
                 <div class="border-2 border-dashed border-gray-300 dark:border-gray-700 rounded-lg p-12 text-center">
                    <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                        <path vector-effect="non-scaling-stroke" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    <h3 class="mt-2 text-sm font-semibold text-gray-900 dark:text-white">Future Architecture Diagram</h3>
                    <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">Placeholder for PNG image export.</p>
                 </div>
            </div>
        </div>

        <!-- API Tab -->
        <div v-if="currentTab === 'api'" class="bg-white shadow sm:rounded-lg overflow-hidden h-[800px]">
             <!-- Using standard /redoc endpoint -->
             <iframe src="/redoc" class="w-full h-full border-0"></iframe>
        </div>

        <!-- Repo Tab -->
        <div v-if="currentTab === 'repo'" class="bg-white dark:bg-gray-800 shadow sm:rounded-lg p-6">
            <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white mb-4">Source Code</h3>
            <div class="space-y-4">
                <p class="text-gray-600 dark:text-gray-300">
                    The source code for this Proof of Concept is hosted on GitHub.
                </p>
                <a
                    href="https://github.com/olmertens/ClassificationG2S"
                    target="_blank"
                    class="inline-flex items-center gap-x-2 rounded-md bg-gray-900 px-3.5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-gray-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
                >
                    <svg class="h-5 w-5 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                         <path fill-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clip-rule="evenodd" />
                    </svg>
                    View on GitHub
                </a>
            </div>
        </div>
    </div>
  </div>
</template>

<style>
.mermaid {
    width: 100%;
    display: flex;
    justify-content: center;
}
</style>
