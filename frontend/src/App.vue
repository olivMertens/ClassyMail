<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DashboardLayout from './components/DashboardLayout.vue'
import DashboardView from './views/DashboardView.vue'
import UploadView from './views/UploadView.vue'
import CostsView from './views/CostsView.vue'
import SettingsView from './views/SettingsView.vue'
import DeveloperDocsView from './views/DeveloperDocsView.vue'
import UsageDocsView from './views/UsageDocsView.vue'
import ExportsView from './views/ExportsView.vue'
import EmailDetailModal from './components/EmailDetailModal.vue'
import GlobalConfirmDialog from './components/GlobalConfirmDialog.vue'

const { locale } = useI18n()

const currentView = ref('dashboard')
const selectedEmailId = ref(null)
const isModalOpen = ref(false)

const openEmail = (email) => {
  selectedEmailId.value = email.id
  isModalOpen.value = true
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
  <DashboardLayout
    :current-view="currentView"
    @change-view="view => currentView = view"
  >
    <DashboardView
      v-if="currentView === 'dashboard'"
      @open-email="openEmail"
    />
    <UploadView v-else-if="currentView === 'upload'" />
    <CostsView v-else-if="currentView === 'costs'" />
    <SettingsView v-else-if="currentView === 'settings'" />
    <DeveloperDocsView v-else-if="currentView === 'developer'" />
    <UsageDocsView v-else-if="currentView === 'docs'" />
    <ExportsView v-else-if="currentView === 'exports'" />

    <EmailDetailModal
      :email-id="selectedEmailId"
      :is-open="isModalOpen"
      @close="isModalOpen = false"
      @updated="() => { } /* Optional: refetch dashboard */"
    />

    <GlobalConfirmDialog />
  </DashboardLayout>
</template>
