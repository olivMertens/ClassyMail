<script setup>
import { ref } from 'vue'
import DashboardLayout from './components/DashboardLayout.vue'
import DashboardView from './views/DashboardView.vue'
import UploadView from './views/UploadView.vue'
import CostsView from './views/CostsView.vue'
import SettingsView from './views/SettingsView.vue'
import EmailDetailModal from './components/EmailDetailModal.vue'

const currentView = ref('dashboard')
const selectedEmailId = ref(null)
const isModalOpen = ref(false)

const openEmail = (email) => {
    selectedEmailId.value = email.id
    isModalOpen.value = true
}
</script>

<template>
  <DashboardLayout :currentView="currentView" @change-view="view => currentView = view">
     <DashboardView v-if="currentView === 'dashboard'" @open-email="openEmail" />
     <UploadView v-else-if="currentView === 'upload'" />
     <CostsView v-else-if="currentView === 'costs'" />
     <SettingsView v-else-if="currentView === 'settings'" />
     
     <EmailDetailModal 
        :emailId="selectedEmailId" 
        :isOpen="isModalOpen" 
        @close="isModalOpen = false"
        @updated="() => {} /* Optional: refetch dashboard */"
     />
  </DashboardLayout>
</template>
