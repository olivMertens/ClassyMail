<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  HomeIcon,
  CloudArrowUpIcon,
  CurrencyDollarIcon,
  Cog6ToothIcon,
  Bars3Icon,
  XMarkIcon,
  MoonIcon,
  SunIcon,
  InformationCircleIcon,
  CodeBracketSquareIcon,
  BookOpenIcon,
  TableCellsIcon,
  CheckCircleIcon,
  ArrowPathIcon
} from '@heroicons/vue/24/outline'
import InfoModal from './InfoModal.vue'

defineProps({
  currentView: {
    type: String,
    required: true
  }
})
const emit = defineEmits(['change-view'])
const { t } = useI18n()

const sidebarOpen = ref(false)
const sidebarCollapsed = ref(false)
const showInfoModal = ref(false)
const showConnectionModal = ref(false)
const isDark = ref(document.documentElement.classList.contains('dark'))
const connectionStatus = ref(null)
const checkingConnection = ref(false)

const toggleDarkMode = () => {
  isDark.value = !isDark.value
  if (isDark.value) {
    document.documentElement.classList.add('dark')
    localStorage.setItem('classimail-dark', 'true')
  } else {
    document.documentElement.classList.remove('dark')
    localStorage.setItem('classimail-dark', 'false')
  }
}

const checkConnectivity = async () => {
  checkingConnection.value = true
  try {
    const response = await fetch('/api/health/readyz')
    const data = await response.json()
    connectionStatus.value = data
  } catch (error) {
    connectionStatus.value = { error: error.message }
  } finally {
    checkingConnection.value = false
  }
}

const navigation = computed(() => [
  { name: t('nav.dashboard'), id: 'dashboard', icon: HomeIcon },
  { name: t('nav.upload'), id: 'upload', icon: CloudArrowUpIcon },
  { name: t('nav.costs'), id: 'costs', icon: CurrencyDollarIcon },
  { name: 'Data Exports', id: 'exports', icon: TableCellsIcon }, // Added new menu item
  { name: t('nav.guide'), id: 'docs', icon: BookOpenIcon },
  { name: t('nav.settings'), id: 'settings', icon: Cog6ToothIcon },
  { name: t('nav.developer'), id: 'developer', icon: CodeBracketSquareIcon },
])
</script>

<template>
  <div class="h-full min-h-screen bg-gray-50 dark:bg-gray-900">
    <!-- Mobile sidebar backdrop -->
    <div
      v-if="sidebarOpen"
      class="fixed inset-0 z-40 bg-gray-600 bg-opacity-75 md:hidden"
      @click="sidebarOpen = false"
    />

    <!-- Mobile sidebar -->
    <div
      v-if="sidebarOpen"
      class="fixed inset-y-0 left-0 z-50 w-72 bg-white dark:bg-gray-800 shadow-xl md:hidden flex flex-col"
    >
      <div class="flex items-center justify-between px-4 py-5 border-b border-gray-200 dark:border-gray-700">
        <div class="flex items-center gap-2">
          <span class="text-2xl">📧</span>
          <span class="text-xl font-bold text-gray-900 dark:text-white">ClassiMail</span>
        </div>
        <button
          class="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          @click="sidebarOpen = false"
        >
          <XMarkIcon class="h-6 w-6" />
        </button>
      </div>
      <nav class="flex-1 px-2 py-4 space-y-1">
        <a
          v-for="item in navigation"
          :key="item.name"
          href="#"
          :class="[currentView === item.id ? 'bg-primary-50 text-primary-600 dark:bg-gray-700 dark:text-white' : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white', 'group flex items-center px-2 py-2 text-base font-medium rounded-md']"
          @click.prevent="emit('change-view', item.id); sidebarOpen = false"
        >
          <component
            :is="item.icon"
            :class="[currentView === item.id ? 'text-primary-600 dark:text-gray-300' : 'text-gray-400 group-hover:text-gray-500 dark:text-gray-400 dark:group-hover:text-gray-300', 'mr-4 h-6 w-6 flex-shrink-0']"
            aria-hidden="true"
          />
          {{ item.name }}
        </a>
      </nav>
    </div>

    <!-- Desktop sidebar -->
    <div
      class="hidden md:fixed md:inset-y-0 md:flex md:flex-col shadow-lg z-30 transition-all duration-300"
      :class="sidebarCollapsed ? 'md:w-16' : 'md:w-64'"
    >
      <div class="flex flex-col flex-1 min-h-0 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700">
        <div class="flex items-center h-16 flex-shrink-0 px-4 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 justify-between">
          <div
            v-if="!sidebarCollapsed"
            class="flex items-center"
          >
            <span class="text-2xl mr-2">📧</span>
            <span class="text-xl font-bold text-gray-900 dark:text-white">ClassiMail</span>
          </div>
          <span
            v-else
            class="text-2xl mx-auto"
          >📧</span>
          <button
            class="p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
            :class="sidebarCollapsed ? 'mx-auto' : ''"
            @click="sidebarCollapsed = !sidebarCollapsed"
          >
            <Bars3Icon
              v-if="sidebarCollapsed"
              class="h-6 w-6 text-gray-500 dark:text-gray-400"
            />
            <XMarkIcon
              v-else
              class="h-6 w-6 text-gray-500 dark:text-gray-400"
            />
          </button>
        </div>
        <div class="flex-1 flex flex-col overflow-y-auto">
          <nav class="flex-1 px-2 py-4 space-y-1">
            <a
              v-for="item in navigation"
              :key="item.name"
              href="#"
              class="group flex items-center px-2 py-2 text-sm font-medium rounded-md"
              :class="[
                currentView === item.id ? 'bg-primary-50 text-primary-600 dark:bg-gray-700 dark:text-white' : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white',
                sidebarCollapsed ? 'justify-center' : ''
              ]"
              :title="sidebarCollapsed ? item.name : ''"
              @click.prevent="emit('change-view', item.id)"
            >
              <component
                :is="item.icon"
                class="h-5 w-5 flex-shrink-0"
                :class="[
                  currentView === item.id ? 'text-primary-600 dark:text-white' : 'text-gray-400 group-hover:text-gray-500 dark:text-gray-400 dark:group-hover:text-gray-300',
                  sidebarCollapsed ? '' : 'mr-3'
                ]"
                aria-hidden="true"
              />
              <span v-if="!sidebarCollapsed">{{ item.name }}</span>
            </a>
          </nav>
        </div>
        <!-- User/Footer area -->
        <div
          class="flex-shrink-0 border-t border-gray-200 dark:border-gray-700 p-4 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          @click="showConnectionModal = true; checkConnectivity()"
        >
          <div
            v-if="!sidebarCollapsed"
            class="flex items-center w-full"
          >
            <div class="ml-3">
              <p class="text-xs font-medium text-gray-500 dark:text-gray-400">
                Microsoft G2S POC
              </p>
              <p class="text-xs font-medium text-gray-400 dark:text-gray-500">
                Février 2026
              </p>
            </div>
          </div>
          <div
            v-else
            class="flex justify-center"
          >
            <InformationCircleIcon class="h-5 w-5 text-gray-500 dark:text-gray-400" />
          </div>
        </div>
      </div>
    </div>

    <!-- Content Area -->
    <div
      class="flex flex-col flex-1 h-screen overflow-hidden transition-all duration-300"
      :class="sidebarCollapsed ? 'md:pl-16' : 'md:pl-64'"
    >
      <!-- Top bar -->
      <div class="sticky top-0 z-10 flex-shrink-0 flex h-16 bg-white dark:bg-gray-800 shadow dark:shadow-gray-900/20 md:hidden">
        <button
          class="px-4 border-r border-gray-200 dark:border-gray-700 text-gray-500 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary-500 md:hidden"
          @click="sidebarOpen = true"
        >
          <Bars3Icon class="h-6 w-6" />
        </button>
        <div class="flex-1 px-4 flex justify-between items-center">
          <span class="font-bold text-gray-900 dark:text-white">ClassiMail</span>
          <div class="flex items-center gap-2">
            <button
              class="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              @click="showInfoModal = true"
            >
              <InformationCircleIcon class="h-6 w-6" />
            </button>
            <button
              class="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              @click="toggleDarkMode"
            >
              <SunIcon
                v-if="isDark"
                class="h-6 w-6"
              />
              <MoonIcon
                v-else
                class="h-6 w-6"
              />
            </button>
          </div>
        </div>
      </div>

      <!-- Desktop Top Bar extensions -->
      <header class="hidden md:flex items-center justify-end h-16 px-8 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 gap-2">
        <button
          class="p-2 rounded-full text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700 transition-colors"
          title="Info"
          @click="showInfoModal = true"
        >
          <InformationCircleIcon class="h-6 w-6" />
        </button>
        <button
          class="p-2 rounded-full text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700 transition-colors"
          @click="toggleDarkMode"
        >
          <SunIcon
            v-if="isDark"
            class="h-6 w-6"
          />
          <MoonIcon
            v-else
            class="h-6 w-6"
          />
        </button>
      </header>

      <!-- Main Content Scroller -->
      <main class="flex-1 overflow-y-auto p-4 md:p-8 scroll-smooth">
        <div class="mx-auto w-full max-w-[1600px]">
          <slot />
        </div>
      </main>
    </div>
    <InfoModal
      :show="showInfoModal"
      @close="showInfoModal = false"
      @navigate="(view) => { showInfoModal = false; emit('change-view', view) }"
    />

    <!-- Connection Status Modal -->
    <div
      v-if="showConnectionModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900 bg-opacity-75 p-4"
    >
      <div class="relative transform overflow-hidden rounded-lg bg-white dark:bg-gray-800 text-left shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-2xl border border-gray-200 dark:border-gray-700">
        <div class="bg-white dark:bg-gray-800 px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <div class="flex justify-between items-center">
            <h3 class="text-xl font-semibold text-gray-900 dark:text-white">
              Service Connection Status
            </h3>
            <div class="flex gap-2 items-center">
              <button
                class="px-4 py-2 text-sm font-medium rounded-md border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
                :disabled="checkingConnection"
                @click="checkConnectivity"
              >
                <span class="flex items-center gap-2">
                  <ArrowPathIcon
                    class="h-4 w-4"
                    :class="{ 'animate-spin': checkingConnection }"
                  />
                  Check Connectivity
                </span>
              </button>
              <button
                class="text-gray-400 hover:text-gray-500 dark:hover:text-gray-200"
                @click="showConnectionModal = false"
              >
                <XMarkIcon class="h-6 w-6" />
              </button>
            </div>
          </div>
        </div>

        <div class="px-6 py-4 max-h-[70vh] overflow-y-auto">
          <div
            v-if="checkingConnection"
            class="text-center py-8 text-gray-500 dark:text-gray-400"
          >
            <ArrowPathIcon class="h-8 w-8 animate-spin mx-auto mb-2" />
            Checking connections...
          </div>

          <div
            v-else-if="connectionStatus"
            class="space-y-4"
          >
            <!-- Connection Status Grid -->
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div
                class="p-4 rounded-lg border"
                :class="connectionStatus.credential ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'"
              >
                <div class="flex items-center gap-3">
                  <div class="flex-shrink-0">
                    <CheckCircleIcon
                      v-if="connectionStatus.credential"
                      class="h-8 w-8 text-green-600 dark:text-green-400"
                    />
                    <XMarkIcon
                      v-else
                      class="h-8 w-8 text-red-600 dark:text-red-400"
                    />
                  </div>
                  <div>
                    <h4
                      class="text-sm font-semibold"
                      :class="connectionStatus.credential ? 'text-green-900 dark:text-green-100' : 'text-red-900 dark:text-red-100'"
                    >
                      Credential Connection
                    </h4>
                    <p
                      class="text-xs"
                      :class="connectionStatus.credential ? 'text-green-700 dark:text-green-300' : 'text-red-700 dark:text-red-300'"
                    >
                      {{ connectionStatus.credential ? 'Connected & Authenticated' : 'Error: ' + (connectionStatus.failures?.credential || 'Unknown') }}
                    </p>
                  </div>
                </div>
              </div>

              <div
                class="p-4 rounded-lg border"
                :class="connectionStatus.servicebus ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'"
              >
                <div class="flex items-center gap-3">
                  <div class="flex-shrink-0">
                    <CheckCircleIcon
                      v-if="connectionStatus.servicebus"
                      class="h-8 w-8 text-green-600 dark:text-green-400"
                    />
                    <XMarkIcon
                      v-else
                      class="h-8 w-8 text-red-600 dark:text-red-400"
                    />
                  </div>
                  <div>
                    <h4
                      class="text-sm font-semibold"
                      :class="connectionStatus.servicebus ? 'text-green-900 dark:text-green-100' : 'text-red-900 dark:text-red-100'"
                    >
                      Servicebus Connection
                    </h4>
                    <p
                      class="text-xs"
                      :class="connectionStatus.servicebus ? 'text-green-700 dark:text-green-300' : 'text-red-700 dark:text-red-300'"
                    >
                      {{ connectionStatus.servicebus ? 'Connected & Authenticated' : 'Error: ' + (connectionStatus.failures?.servicebus || 'Unknown') }}
                    </p>
                  </div>
                </div>
              </div>

              <div
                class="p-4 rounded-lg border"
                :class="connectionStatus.storage ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'"
              >
                <div class="flex items-center gap-3">
                  <div class="flex-shrink-0">
                    <CheckCircleIcon
                      v-if="connectionStatus.storage"
                      class="h-8 w-8 text-green-600 dark:text-green-400"
                    />
                    <XMarkIcon
                      v-else
                      class="h-8 w-8 text-red-600 dark:text-red-400"
                    />
                  </div>
                  <div>
                    <h4
                      class="text-sm font-semibold"
                      :class="connectionStatus.storage ? 'text-green-900 dark:text-green-100' : 'text-red-900 dark:text-red-100'"
                    >
                      Storage Connection
                    </h4>
                    <p
                      class="text-xs"
                      :class="connectionStatus.storage ? 'text-green-700 dark:text-green-300' : 'text-red-700 dark:text-red-300'"
                    >
                      {{ connectionStatus.storage ? 'Connected & Authenticated' : 'Error: ' + (connectionStatus.failures?.storage || 'Unknown') }}
                    </p>
                  </div>
                </div>
              </div>

              <div
                class="p-4 rounded-lg border"
                :class="connectionStatus.storage_public ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'"
              >
                <div class="flex items-center gap-3">
                  <div class="flex-shrink-0">
                    <CheckCircleIcon
                      v-if="connectionStatus.storage_public"
                      class="h-8 w-8 text-green-600 dark:text-green-400"
                    />
                    <XMarkIcon
                      v-else
                      class="h-8 w-8 text-red-600 dark:text-red-400"
                    />
                  </div>
                  <div>
                    <h4
                      class="text-sm font-semibold"
                      :class="connectionStatus.storage_public ? 'text-green-900 dark:text-green-100' : 'text-red-900 dark:text-red-100'"
                    >
                      Storage Public Connection
                    </h4>
                    <p
                      class="text-xs"
                      :class="connectionStatus.storage_public ? 'text-green-700 dark:text-green-300' : 'text-red-700 dark:text-red-300'"
                    >
                      {{ connectionStatus.storage_public ? 'Connected & Authenticated' : 'Error: ' + (connectionStatus.failures?.storage_public || 'Unknown') }}
                    </p>
                  </div>
                </div>
              </div>

              <div
                class="p-4 rounded-lg border"
                :class="connectionStatus.cosmos ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'"
              >
                <div class="flex items-center gap-3">
                  <div class="flex-shrink-0">
                    <CheckCircleIcon
                      v-if="connectionStatus.cosmos"
                      class="h-8 w-8 text-green-600 dark:text-green-400"
                    />
                    <XMarkIcon
                      v-else
                      class="h-8 w-8 text-red-600 dark:text-red-400"
                    />
                  </div>
                  <div>
                    <h4
                      class="text-sm font-semibold"
                      :class="connectionStatus.cosmos ? 'text-green-900 dark:text-green-100' : 'text-red-900 dark:text-red-100'"
                    >
                      Cosmos Connection
                    </h4>
                    <p
                      class="text-xs"
                      :class="connectionStatus.cosmos ? 'text-green-700 dark:text-green-300' : 'text-red-700 dark:text-red-300'"
                    >
                      {{ connectionStatus.cosmos ? 'Connected & Authenticated' : 'Error: ' + (connectionStatus.failures?.cosmos || 'Unknown') }}
                    </p>
                  </div>
                </div>
              </div>

              <div
                class="p-4 rounded-lg border"
                :class="connectionStatus.ai ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'"
              >
                <div class="flex items-center gap-3">
                  <div class="flex-shrink-0">
                    <CheckCircleIcon
                      v-if="connectionStatus.ai"
                      class="h-8 w-8 text-green-600 dark:text-green-400"
                    />
                    <XMarkIcon
                      v-else
                      class="h-8 w-8 text-red-600 dark:text-red-400"
                    />
                  </div>
                  <div>
                    <h4
                      class="text-sm font-semibold"
                      :class="connectionStatus.ai ? 'text-green-900 dark:text-green-100' : 'text-red-900 dark:text-red-100'"
                    >
                      Ai Connection
                    </h4>
                    <p
                      class="text-xs"
                      :class="connectionStatus.ai ? 'text-green-700 dark:text-green-300' : 'text-red-700 dark:text-red-300'"
                    >
                      {{ connectionStatus.ai ? 'Connected & Authenticated' : 'Error: ' + (connectionStatus.failures?.ai || 'Unknown') }}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div
            v-else
            class="text-center py-8 text-gray-500 dark:text-gray-400"
          >
            Click "Check Connectivity" to test connections
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
