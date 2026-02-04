<script setup>
import { ref, computed, onMounted } from 'vue'
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
  ArrowDownTrayIcon
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
const isDark = ref(document.documentElement.classList.contains('dark'))
const uiConfig = ref({ show_info_modal: true, show_developer_tab: true, organization_name: 'ClassyMail', environment: 'development' })
const organizationName = computed(() => uiConfig.value.organization_name || 'ClassyMail')

const fetchUiConfig = async () => {
  try {
    const res = await fetch('/api/admin/ui-config')
    if (res.ok) {
      uiConfig.value = await res.json()
    }
  } catch (e) {
    console.error('Failed to fetch UI config', e)
  }
}

onMounted(() => {
  fetchUiConfig()
})

const toggleDarkMode = () => {
  isDark.value = !isDark.value
  if (isDark.value) {
    document.documentElement.classList.add('dark')
    localStorage.setItem('ClassyMail-dark', 'true')
  } else {
    document.documentElement.classList.remove('dark')
    localStorage.setItem('ClassyMail-dark', 'false')
  }
}

const navigation = computed(() => {
  const items = [
    { name: t('nav.dashboard'), id: 'dashboard', icon: HomeIcon },
    { name: t('nav.upload'), id: 'upload', icon: CloudArrowUpIcon },
    { name: 'Exports', id: 'exports', icon: ArrowDownTrayIcon },
    { name: t('nav.costs'), id: 'costs', icon: CurrencyDollarIcon },
    { name: 'Guide', id: 'docs', icon: BookOpenIcon },
    { name: t('nav.settings'), id: 'settings', icon: Cog6ToothIcon },
    { name: 'Developer', id: 'developer', icon: CodeBracketSquareIcon },
  ]
  if (!uiConfig.value.show_developer_tab) {
    return items.filter(i => i.id !== 'developer')
  }
  return items
})
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
          <span class="text-xl font-bold text-gray-900 dark:text-white">{{ organizationName }}</span>
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
      class="hidden md:fixed md:inset-y-0 md:flex md:flex-col shadow-lg z-30"
      :class="sidebarCollapsed ? 'md:w-20' : 'md:w-64'"
    >
      <div class="flex flex-col flex-1 min-h-0 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700">
        <div
          class="flex items-center h-16 flex-shrink-0 px-4 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700"
        >
          <span class="text-2xl mr-2">📧</span>
          <span
            v-if="!sidebarCollapsed"
            class="text-xl font-bold text-gray-900 dark:text-white"
          >{{ organizationName
          }}</span>
        </div>
        <div class="flex-1 flex flex-col overflow-y-auto">
          <nav
            class="flex-1 px-2 py-4 space-y-1"
            :class="sidebarCollapsed ? 'items-center' : ''"
          >
            <a
              v-for="item in navigation"
              :key="item.name"
              href="#"
              class="group flex items-center px-2 py-2 text-sm font-medium rounded-md"
              :class="[currentView === item.id ? 'bg-primary-50 text-primary-600 dark:bg-gray-700 dark:text-white' : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white']"
              @click.prevent="emit('change-view', item.id)"
            >
              <component
                :is="item.icon"
                class="h-5 w-5 flex-shrink-0"
                :class="[currentView === item.id ? 'text-primary-600 dark:text-white' : 'text-gray-400 group-hover:text-gray-500 dark:text-gray-400 dark:group-hover:text-gray-300', sidebarCollapsed ? '' : 'mr-3']"
                aria-hidden="true"
              />
              <span v-if="!sidebarCollapsed">{{ item.name }}</span>
            </a>
          </nav>
        </div>
        <!-- User/Footer area -->
        <div class="flex-shrink-0 flex border-t border-gray-200 dark:border-gray-700 p-4">
          <div class="flex items-center w-full">
            <div class="ml-3">
              <p
                v-if="!sidebarCollapsed"
                class="text-xs font-medium text-gray-500 dark:text-gray-400"
              >
                {{ organizationName }}
              </p>
              <p
                v-if="!sidebarCollapsed"
                class="text-xs font-medium text-gray-400 dark:text-gray-500"
              >
                Février 2026
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Content Area -->
    <div
      class="flex flex-col flex-1 h-screen overflow-hidden"
      :class="sidebarCollapsed ? 'md:pl-20' : 'md:pl-64'"
    >
      <!-- Top bar -->
      <div
        class="sticky top-0 z-10 flex-shrink-0 flex h-16 bg-white dark:bg-gray-800 shadow dark:shadow-gray-900/20 md:hidden"
      >
        <button
          class="px-4 border-r border-gray-200 dark:border-gray-700 text-gray-500 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary-500 md:hidden"
          @click="sidebarOpen = true"
        >
          <Bars3Icon class="h-6 w-6" />
        </button>
        <div class="flex-1 px-4 flex justify-between items-center">
          <span class="font-bold text-gray-900 dark:text-white">{{ organizationName }}</span>
          <div class="flex items-center gap-2">
            <button
              v-if="uiConfig.show_info_modal"
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
      <header
        class="hidden md:flex items-center justify-between h-16 px-4 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 gap-2"
      >
        <button
          class="p-2 rounded-full text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700 transition-colors"
          title="Toggle sidebar"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
          <Bars3Icon class="h-6 w-6" />
        </button>
        <div class="flex items-center gap-2">
          <button
            v-if="uiConfig.show_info_modal"
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
        </div>
      </header>

      <!-- Main Content Scroller -->
      <main class="flex-1 overflow-y-auto p-4 md:p-4 scroll-smooth">
        <div class="mx-auto w-full">
          <slot />
        </div>
      </main>
    </div>
    <InfoModal
      :show="showInfoModal"
      :organization-name="organizationName"
      @close="showInfoModal = false"
      @navigate="(view) => { showInfoModal = false; emit('change-view', view) }"
    />
  </div>
</template>
