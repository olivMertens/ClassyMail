<script setup>
import { ref, onMounted, defineAsyncComponent, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import DashboardLayout from './components/DashboardLayout.vue'
import DashboardView from './views/DashboardView.vue'
import EmailDetailModal from './components/EmailDetailModal.vue'
import GlobalConfirmDialog from './components/GlobalConfirmDialog.vue'

// Lazy-loaded views – only fetched when navigated to
const UploadView = defineAsyncComponent(() => import('./views/UploadView.vue'))
const CostsView = defineAsyncComponent(() => import('./views/CostsView.vue'))
const SettingsView = defineAsyncComponent(() => import('./views/SettingsView.vue'))
const DeveloperDocsView = defineAsyncComponent(() => import('./views/DeveloperDocsView.vue'))
const UsageDocsView = defineAsyncComponent(() => import('./views/UsageDocsView.vue'))
const ExportsView = defineAsyncComponent(() => import('./views/ExportsView.vue'))

const { locale } = useI18n()

const currentView = ref('dashboard')
const selectedEmailId = ref(null)
const isModalOpen = ref(false)
const dashboardRef = ref(null)

const openEmail = (email) => {
  selectedEmailId.value = email.id
  isModalOpen.value = true
}

const handleAskAi = (email) => {
  isModalOpen.value = false
  currentView.value = 'dashboard'
  nextTick(() => {
    dashboardRef.value?.askAboutEmail(email)
  })
}

onMounted(() => {
  // Restore Theme
  const savedTheme = localStorage.getItem('ClassyMail-theme')
  if (savedTheme) {
    document.documentElement.setAttribute('data-theme', savedTheme)
  }

  // Restore Dark Mode
  const savedDark = localStorage.getItem('ClassyMail-dark')
  if (savedDark === 'true') {
    document.documentElement.classList.add('dark')
  } else if (savedDark === 'false') {
    document.documentElement.classList.remove('dark')
  }

  // Restore Locale
  const savedLocale = localStorage.getItem('ClassyMail-locale')
  if (savedLocale) {
    locale.value = savedLocale
  }
})
</script>

<template>
  <DashboardLayout :current-view="currentView" @change-view="view => currentView = view">
    <DashboardView v-if="currentView === 'dashboard'" ref="dashboardRef" @open-email="openEmail" />
    <UploadView v-else-if="currentView === 'upload'" />
    <CostsView v-else-if="currentView === 'costs'" />
    <SettingsView v-else-if="currentView === 'settings'" />
    <DeveloperDocsView v-else-if="currentView === 'developer'" />
    <UsageDocsView v-else-if="currentView === 'docs'" />
    <ExportsView v-else-if="currentView === 'exports'" />

    <EmailDetailModal :email-id="selectedEmailId" :is-open="isModalOpen" @close="isModalOpen = false"
      @updated="() => { }" @ask-ai="handleAskAi" />

    <GlobalConfirmDialog />
  </DashboardLayout>
</template>
