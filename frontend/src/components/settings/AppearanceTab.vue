<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircleIcon, MoonIcon, SunIcon } from '@heroicons/vue/24/outline'

const { t, locale } = useI18n()

const isDark = ref(false)
const currentTheme = ref('blue')
const currentLocale = ref('en')

const themes = [
  { id: 'blue', name: 'Blue', class: 'bg-blue-600' },
  { id: 'green', name: 'Green', class: 'bg-emerald-600' },
  { id: 'indigo', name: 'Indigo', class: 'bg-indigo-600' },
  { id: 'slate', name: 'Slate', class: 'bg-slate-600' },
  { id: 'orange', name: 'Orange', class: 'bg-orange-600' },
  { id: 'red', name: 'Red', class: 'bg-red-600' }
]

const toggleDarkMode = () => {
  isDark.value = !isDark.value
  document.documentElement.classList.toggle('dark', isDark.value)
  localStorage.setItem('ClassyMail-dark', isDark.value)
}

const setTheme = (id) => {
  currentTheme.value = id
  document.documentElement.setAttribute('data-theme', id)
  localStorage.setItem('ClassyMail-theme', id)
}

const setLocale = (l) => {
  currentLocale.value = l
  locale.value = l
  localStorage.setItem('ClassyMail-locale', l)
}

// Restore from localStorage
const savedDark = localStorage.getItem('ClassyMail-dark')
isDark.value = savedDark === 'true'
if (isDark.value) document.documentElement.classList.add('dark')

const savedTheme = localStorage.getItem('ClassyMail-theme')
if (savedTheme) setTheme(savedTheme)

const savedLocale = localStorage.getItem('ClassyMail-locale')
if (savedLocale) {
  currentLocale.value = savedLocale
  locale.value = savedLocale
}
</script>

<template>
  <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg">
    <div class="px-4 py-5 sm:p-6">
      <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
        {{ t('settings.appearance') }}
      </h3>

      <div class="mt-6 space-y-6">
        <!-- Language -->
        <div>
          <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">{{ t('settings.language') }}</label>
          <div class="mt-2 flex flex-wrap items-center gap-2">
            <button v-for="lang in [{ code: 'en', label: 'English' }, { code: 'fr', label: 'Français' }, { code: 'es', label: 'Español' }, { code: 'de', label: 'Deutsch' }, { code: 'it', label: 'Italiano' }]"
              :key="lang.code"
              class="px-3 py-1.5 text-sm font-medium rounded-md transition-colors"
              :class="currentLocale === lang.code ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'"
              @click="setLocale(lang.code)">
              {{ lang.label }}
            </button>
          </div>
        </div>

        <!-- Dark Mode -->
        <div class="flex items-center justify-between">
          <span class="flex-grow flex flex-col">
            <span class="text-sm font-medium text-gray-900 dark:text-white">{{ t('settings.dark_mode') }}</span>
          </span>
          <button type="button"
            class="relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary-600 focus:ring-offset-2"
            :class="isDark ? 'bg-primary-600' : 'bg-gray-200'" @click="toggleDarkMode">
            <span class="pointer-events-none relative inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
              :class="isDark ? 'translate-x-5' : 'translate-x-0'">
              <span class="absolute inset-0 flex h-full w-full items-center justify-center transition-opacity"
                :class="isDark ? 'opacity-0 duration-100 ease-out' : 'opacity-100 duration-200 ease-in'">
                <SunIcon class="h-3 w-3 text-gray-400" />
              </span>
              <span class="absolute inset-0 flex h-full w-full items-center justify-center transition-opacity"
                :class="isDark ? 'opacity-100 duration-200 ease-in' : 'opacity-0 duration-100 ease-out'">
                <MoonIcon class="h-3 w-3 text-primary-600" />
              </span>
            </span>
          </button>
        </div>

        <!-- Theme -->
        <div>
          <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">{{ t('settings.theme') }}</label>
          <div class="mt-2 flex items-center space-x-3">
            <button v-for="theme in themes" :key="theme.id"
              class="relative h-8 w-8 rounded-full focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-gray-800"
              :class="[theme.class, currentTheme === theme.id ? 'ring-2 ring-primary-500 ring-offset-2' : '']"
              :title="theme.name" @click="setTheme(theme.id)">
              <CheckCircleIcon v-if="currentTheme === theme.id" class="absolute inset-0 m-auto h-5 w-5 text-white" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
