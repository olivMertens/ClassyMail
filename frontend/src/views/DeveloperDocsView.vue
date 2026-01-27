<script setup>
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import mermaid from 'mermaid'
import {
  CodeBracketIcon,
  MapIcon,
  ServerIcon,
  CommandLineIcon,
  PlayIcon,
  CheckCircleIcon,
  XCircleIcon,
  ArrowPathIcon
} from '@heroicons/vue/24/outline'

const currentTab = ref('architecture')
const isDark = ref(false)
let observer = null

// Debug State
const debugResults = ref(null)
const debugLoading = ref(false)
const writeTestResults = ref(null)
const writeTestLoading = ref(false)

const runDeepHealthCheck = async () => {
  debugLoading.value = true
  debugResults.value = null
  try {
    const res = await fetch('/api/readyz/deep')
    if (res.ok) {
      debugResults.value = { status: 'ready', failures: {} }
    } else {
      const data = await res.json()
      debugResults.value = {
        status: 'not_ready',
        failures: data.detail?.failures || { error: 'Unknown State' }
      }
    }
  } catch (e) {
    debugResults.value = { status: 'error', failures: { network: e.message } }
  } finally {
    debugLoading.value = false
  }
}

const runWriteTests = async () => {
    writeTestLoading.value = true
    writeTestResults.value = null
    try {
        const res = await fetch('/api/admin/debug/connectivity', { method: 'POST' })
        if (res.ok) {
            writeTestResults.value = await res.json()
        } else {
            const err = await res.json()
            writeTestResults.value = { error: err.detail || 'Request failed' }
        }
    } catch(e) {
        writeTestResults.value = { error: e.message }
    } finally {
        writeTestLoading.value = false
    }
}

const initMermaid = async () => {
    const darkMode = document.documentElement.classList.contains('dark')
    mermaid.initialize({
        startOnLoad: false,
        theme: darkMode ? 'dark' : 'default',
        securityLevel: 'loose'
    })
    await nextTick()
    await mermaid.run({
        nodes: document.querySelectorAll('.mermaid')
    })
}

onMounted(() => {
    // Initial theme check
    isDark.value = document.documentElement.classList.contains('dark')

    // Watch for theme changes
    observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.attributeName === 'class') {
                isDark.value = document.documentElement.classList.contains('dark')
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
      <nav
        class="-mb-px flex space-x-8"
        aria-label="Tabs"
      >
        <button
          :class="[currentTab === 'architecture' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300', 'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium']"
          @click="switchTab('architecture')"
        >
          <MapIcon
            class="-ml-0.5 mr-2 h-5 w-5"
            aria-hidden="true"
          />
          Architecture
        </button>
        <button
          :class="[currentTab === 'api' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300', 'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium']"
          @click="switchTab('api')"
        >
          <ServerIcon
            class="-ml-0.5 mr-2 h-5 w-5"
            aria-hidden="true"
          />
          API Reference (Redoc)
        </button>
        <button
          :class="[currentTab === 'repo' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300', 'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium']"
          @click="switchTab('repo')"
        >
          <CodeBracketIcon
            class="-ml-0.5 mr-2 h-5 w-5"
            aria-hidden="true"
          />
          Repository
        </button>
        <button
          :class="[currentTab === 'debug' ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300', 'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium']"
          @click="switchTab('debug')"
        >
          <CommandLineIcon
            class="-ml-0.5 mr-2 h-5 w-5"
            aria-hidden="true"
          />
          Debug & Health
        </button>
      </nav>
    </div>

    <!-- Content -->
    <div class="py-4">
      <!-- Debug Tab -->
      <div
        v-if="currentTab === 'debug'"
        class="space-y-8"
      >
        <!-- Read/Connect Check -->
        <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg p-6">
          <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white">
              Service Connection Status
            </h3>
            <button
              class="inline-flex items-center gap-x-1.5 rounded-md bg-white dark:bg-gray-700 px-3 py-2 text-sm font-semibold text-gray-900 dark:text-white shadow-sm ring-1 ring-inset ring-gray-300 dark:ring-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600"
              @click="runDeepHealthCheck"
            >
              <ArrowPathIcon
                class="-ml-0.5 h-5 w-5"
                :class="{ 'animate-spin': debugLoading }"
                aria-hidden="true"
              />
              {{ debugLoading ? 'Checking...' : 'Check Connectivity' }}
            </button>
          </div>

          <div
            v-if="debugResults"
            class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2"
          >
            <!-- Items -->
            <div
              v-for="service in ['credential', 'servicebus', 'storage', 'cosmos']"
              :key="service"
              class="relative flex items-center space-x-3 rounded-lg border border-gray-300 dark:border-gray-700 px-6 py-5 shadow-sm focus-within:ring-2 focus-within:ring-primary-500 focus-within:ring-offset-2 hover:border-gray-400 dark:hover:border-gray-500"
            >
              <div class="flex-shrink-0">
                <CheckCircleIcon
                  v-if="!debugResults.failures[service]"
                  class="h-8 w-8 text-green-500"
                />
                <XCircleIcon
                  v-else
                  class="h-8 w-8 text-red-500"
                />
              </div>
              <div class="min-w-0 flex-1">
                <span
                  class="absolute inset-0"
                  aria-hidden="true"
                />
                <p class="text-sm font-medium text-gray-900 dark:text-white capitalize">
                  {{ service }} Connection
                </p>
                <p class="truncate text-sm text-gray-500 dark:text-gray-400">
                  {{ debugResults.failures[service] ? `Error: ${debugResults.failures[service]}` : 'Connected & Authenticated' }}
                </p>
              </div>
            </div>
          </div>
          <div
            v-else
            class="text-sm text-gray-500 italic"
          >
            Click 'Check Connectivity' to probe all Azure services.
          </div>
        </div>

        <!-- Write/Upload Active Check -->
        <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg p-6 border-t-4 border-indigo-500">
          <div class="flex justify-between items-center mb-4">
            <div>
              <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white">
                Active Write/Upload Tests
              </h3>
              <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
                This attempts real data operations: Uploading a dummy file to Blob Storage and creating a dummy item in Cosmos DB, then deleting them.
              </p>
            </div>
            <button
              class="inline-flex items-center gap-x-1.5 rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:opacity-50"
              :disabled="writeTestLoading"
              @click="runWriteTests"
            >
              <PlayIcon
                class="-ml-0.5 h-5 w-5"
                aria-hidden="true"
              />
              {{ writeTestLoading ? 'Testing...' : 'Run Write Tests' }}
            </button>
          </div>

          <div
            v-if="writeTestResults"
            class="mt-4 space-y-4"
          >
            <div
              v-if="writeTestResults.error"
              class="p-4 bg-red-50 text-red-700 rounded-md"
            >
              Global Error: {{ writeTestResults.error }}
            </div>
            <div
              v-else
              class="grid grid-cols-1 gap-4 sm:grid-cols-3"
            >
              <!-- Storage Result -->
              <div
                class="p-4 rounded-md border"
                :class="writeTestResults.storage_upload === 'ok' ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'"
              >
                <span
                  class="block text-sm font-bold"
                  :class="writeTestResults.storage_upload === 'ok' ? 'text-green-800' : 'text-red-800'"
                >
                  Blob Storage Upload
                </span>
                <span
                  class="text-sm"
                  :class="writeTestResults.storage_upload === 'ok' ? 'text-green-700' : 'text-red-700'"
                >
                  {{ writeTestResults.storage_upload === 'ok' ? 'Success (Write+Delete)' : writeTestResults.storage_upload }}
                </span>
              </div>
              <!-- Cosmos Result -->
              <div
                class="p-4 rounded-md border"
                :class="writeTestResults.cosmos_write === 'ok' ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'"
              >
                <span
                  class="block text-sm font-bold"
                  :class="writeTestResults.cosmos_write === 'ok' ? 'text-green-800' : 'text-red-800'"
                >
                  Cosmos DB Write
                </span>
                <span
                  class="text-sm"
                  :class="writeTestResults.cosmos_write === 'ok' ? 'text-green-700' : 'text-red-700'"
                >
                  {{ writeTestResults.cosmos_write === 'ok' ? 'Success (Create+Delete)' : writeTestResults.cosmos_write }}
                </span>
              </div>
              <!-- SB Connect Result -->
              <div
                class="p-4 rounded-md border"
                :class="writeTestResults.servicebus_connect === 'ok' ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'"
              >
                <span
                  class="block text-sm font-bold"
                  :class="writeTestResults.servicebus_connect === 'ok' ? 'text-green-800' : 'text-red-800'"
                >
                  Service Bus Link
                </span>
                <span
                  class="text-sm"
                  :class="writeTestResults.servicebus_connect === 'ok' ? 'text-green-700' : 'text-red-700'"
                >
                  {{ writeTestResults.servicebus_connect === 'ok' ? 'Success (Link Open)' : writeTestResults.servicebus_connect }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Architecture Tab -->
      <div
        v-if="currentTab === 'architecture'"
        class="space-y-8"
      >
        <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg p-6">
          <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white mb-4">
            System Architecture
          </h3>
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
          <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white mb-4">
            Security & Access Roles (RBAC)
          </h3>
          <p class="text-sm text-gray-500 dark:text-gray-400 mb-4">
            The application executes with a User Assigned Identity that requires the following Azure RBAC roles.
            Connection strings are NOT used for core data services.
          </p>
          <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-300 dark:divide-gray-700">
              <thead class="bg-gray-50 dark:bg-gray-700">
                <tr>
                  <th
                    scope="col"
                    class="py-3.5 pl-4 pr-3 text-left text-sm font-semibold text-gray-900 dark:text-white sm:pl-6"
                  >
                    Resource
                  </th>
                  <th
                    scope="col"
                    class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900 dark:text-white"
                  >
                    Role Name
                  </th>
                  <th
                    scope="col"
                    class="px-3 py-3.5 text-left text-sm font-semibold text-gray-900 dark:text-white"
                  >
                    Scope / Purpose
                  </th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-200 dark:divide-gray-700 bg-white dark:bg-gray-800">
                <tr>
                  <td class="whitespace-nowrap py-4 pl-4 pr-3 text-sm font-medium text-gray-900 dark:text-white sm:pl-6">
                    Storage Account
                  </td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 dark:text-gray-300 font-mono">
                    Storage Blob Data Contributor
                  </td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 dark:text-gray-300">
                    Read inputs (PDFs) & write logs
                  </td>
                </tr>
                <tr>
                  <td class="whitespace-nowrap py-4 pl-4 pr-3 text-sm font-medium text-gray-900 dark:text-white sm:pl-6">
                    Service Bus
                  </td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 dark:text-gray-300 font-mono">
                    Azure Service Bus Data Receiver
                  </td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 dark:text-gray-300">
                    Worker message consumption
                  </td>
                </tr>
                <tr>
                  <td class="whitespace-nowrap py-4 pl-4 pr-3 text-sm font-medium text-gray-900 dark:text-white sm:pl-6">
                    Service Bus
                  </td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 dark:text-gray-300 font-mono">
                    Azure Service Bus Data Sender
                  </td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 dark:text-gray-300">
                    API trigger & Dead-letter re-queue
                  </td>
                </tr>
                <tr>
                  <td class="whitespace-nowrap py-4 pl-4 pr-3 text-sm font-medium text-gray-900 dark:text-white sm:pl-6">
                    Cosmos DB
                  </td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 dark:text-gray-300 font-mono">
                    Cosmos DB Built-in Data Contributor
                  </td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 dark:text-gray-300">
                    Read/Write JSON metadata (No Keys)
                  </td>
                </tr>
                <tr>
                  <td class="whitespace-nowrap py-4 pl-4 pr-3 text-sm font-medium text-gray-900 dark:text-white sm:pl-6">
                    AI Foundry
                  </td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 dark:text-gray-300 font-mono">
                    Cognitive Services User
                  </td>
                  <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 dark:text-gray-300">
                    Invoke Phi-4 & Mistral Models
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- API Tab -->
      <div
        v-if="currentTab === 'api'"
        class="bg-white shadow sm:rounded-lg overflow-hidden h-[800px] relative"
      >
        <div class="absolute top-2 right-2 z-10">
          <a
            :href="redocUrl"
            target="_blank"
            class="inline-flex items-center rounded-md bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50"
          >
            Open in New Tab &nearr;
          </a>
        </div>
        <!-- Using standard /redoc endpoint -->
        <iframe
          :src="redocUrl"
          class="w-full h-full border-0"
        />
      </div>

      <!-- Repo Tab -->
      <div
        v-if="currentTab === 'repo'"
        class="bg-white dark:bg-gray-800 shadow sm:rounded-lg p-6"
      >
        <h3 class="text-lg font-medium leading-6 text-gray-900 dark:text-white mb-4">
          Source Code
        </h3>
        <div class="space-y-4">
          <p class="text-gray-600 dark:text-gray-300">
            The source code for this Proof of Concept is hosted on GitHub.
          </p>
          <a
            href="https://github.com/olmertens/ClassificationG2S"
            target="_blank"
            class="inline-flex items-center gap-x-2 rounded-md bg-gray-900 px-3.5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-gray-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
          >
            <svg
              class="h-5 w-5 fill-current"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                fill-rule="evenodd"
                d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
                clip-rule="evenodd"
              />
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
