<script setup>
import { ref } from 'vue'
import { 
  HomeIcon, 
  CloudArrowUpIcon, 
  CurrencyDollarIcon, 
  Cog6ToothIcon,
  Bars3Icon,
  XMarkIcon,
  MoonIcon,
  SunIcon
} from '@heroicons/vue/24/outline'

const props = defineProps(['currentView'])
const emit = defineEmits(['change-view'])

const sidebarOpen = ref(false)
const isDark = ref(document.documentElement.classList.contains('dark'))

const toggleDarkMode = () => {
  isDark.value = !isDark.value
  if (isDark.value) {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}

const navigation = [
  { name: 'Dashboard', id: 'dashboard', icon: HomeIcon },
  { name: 'Upload', id: 'upload', icon: CloudArrowUpIcon },
  { name: 'Costs', id: 'costs', icon: CurrencyDollarIcon },
  { name: 'Settings', id: 'settings', icon: Cog6ToothIcon },
]
</script>

<template>
  <div class="h-full min-h-screen bg-gray-50 dark:bg-gray-900">
    <!-- Mobile sidebar backdrop -->
    <div v-if="sidebarOpen" class="fixed inset-0 z-40 bg-gray-600 bg-opacity-75 md:hidden" @click="sidebarOpen = false"></div>

    <!-- Mobile sidebar -->
    <div v-if="sidebarOpen" class="fixed inset-y-0 left-0 z-50 w-72 bg-white dark:bg-gray-800 shadow-xl md:hidden flex flex-col">
       <div class="flex items-center justify-between px-4 py-5 border-b border-gray-200 dark:border-gray-700">
          <div class="flex items-center gap-2">
            <span class="text-2xl">📧</span>
            <span class="text-xl font-bold text-gray-900 dark:text-white">ClassiMail</span>
          </div>
          <button @click="sidebarOpen = false" class="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
             <XMarkIcon class="h-6 w-6" />
          </button>
       </div>
       <nav class="flex-1 px-2 py-4 space-y-1">
          <a v-for="item in navigation" :key="item.name" href="#" 
             @click.prevent="emit('change-view', item.id); sidebarOpen = false"
             :class="[currentView === item.id ? 'bg-primary-50 text-primary-600 dark:bg-gray-700 dark:text-white' : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white', 'group flex items-center px-2 py-2 text-base font-medium rounded-md']">
             <component :is="item.icon" :class="[currentView === item.id ? 'text-primary-600 dark:text-gray-300' : 'text-gray-400 group-hover:text-gray-500 dark:text-gray-400 dark:group-hover:text-gray-300', 'mr-4 h-6 w-6 flex-shrink-0']" aria-hidden="true" />
             {{ item.name }}
          </a>
       </nav>
    </div>

    <!-- Desktop sidebar -->
    <div class="hidden md:fixed md:inset-y-0 md:flex md:w-64 md:flex-col shadow-lg z-30">
      <div class="flex flex-col flex-1 min-h-0 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700">
        <div class="flex items-center h-16 flex-shrink-0 px-4 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
             <span class="text-2xl mr-2">📧</span>
             <span class="text-xl font-bold text-gray-900 dark:text-white">ClassiMail</span>
        </div>
        <div class="flex-1 flex flex-col overflow-y-auto">
          <nav class="flex-1 px-2 py-4 space-y-1">
            <a v-for="item in navigation" :key="item.name" href="#" 
               @click.prevent="emit('change-view', item.id)"
               class="group flex items-center px-2 py-2 text-sm font-medium rounded-md"
               :class="[currentView === item.id ? 'bg-primary-50 text-primary-600 dark:bg-gray-700 dark:text-white' : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white']">
               <component :is="item.icon" 
                 class="mr-3 h-5 w-5 flex-shrink-0" 
                 :class="[currentView === item.id ? 'text-primary-600 dark:text-white' : 'text-gray-400 group-hover:text-gray-500 dark:text-gray-400 dark:group-hover:text-gray-300']" aria-hidden="true" />
               {{ item.name }}
            </a>
          </nav>
        </div>
        <!-- User/Footer area -->
        <div class="flex-shrink-0 flex border-t border-gray-200 dark:border-gray-700 p-4">
             <div class="flex items-center w-full">
                <div class="ml-3">
                   <p class="text-xs font-medium text-gray-500 dark:text-gray-400">Microsoft G2S POC</p>
                   <p class="text-xs font-medium text-gray-400 dark:text-gray-500">Mars 2026</p>
                </div>
             </div>
        </div>
      </div>
    </div>

    <!-- Content Area -->
    <div class="flex flex-col md:pl-64 flex-1 h-screen overflow-hidden">
        <!-- Top bar -->
        <div class="sticky top-0 z-10 flex-shrink-0 flex h-16 bg-white dark:bg-gray-800 shadow dark:shadow-gray-900/20 md:hidden">
            <button @click="sidebarOpen = true" class="px-4 border-r border-gray-200 dark:border-gray-700 text-gray-500 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary-500 md:hidden">
               <Bars3Icon class="h-6 w-6" />
            </button>
            <div class="flex-1 px-4 flex justify-between items-center">
                 <span class="font-bold text-gray-900 dark:text-white">ClassiMail</span>
                 <button @click="toggleDarkMode" class="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
                    <SunIcon v-if="isDark" class="h-6 w-6" />
                    <MoonIcon v-else class="h-6 w-6" />
                 </button>
            </div>
        </div>
        
        <!-- Desktop Top Bar extensions (like Dark Mode toggle which is usually in sidebar or header) -->
        <div class="hidden md:flex justify-end p-4 bg-gray-50 dark:bg-gray-900 absolute top-0 right-0 z-20">
             <button @click="toggleDarkMode" class="p-2 rounded-full text-gray-500 hover:bg-gray-200 dark:text-gray-400 dark:hover:bg-gray-700 transition-colors">
                <SunIcon v-if="isDark" class="h-6 w-6" />
                <MoonIcon v-else class="h-6 w-6" />
             </button>
        </div>

        <!-- Main Content Scroller -->
        <main class="flex-1 overflow-y-auto p-4 md:p-8 pt-16 md:pt-8 scroll-smooth">
             <div class="max-w-7xl mx-auto">
                 <slot></slot>
             </div>
        </main>
    </div>
  </div>
</template>
