<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useDialog } from '../../composables/useDialog'
import { trackException } from '../../services/telemetry'
import {
  CheckCircleIcon,
  CpuChipIcon,
  ExclamationTriangleIcon
} from '@heroicons/vue/24/outline'

const props = defineProps({
  settings: { type: Object, required: true },
  modelOptions: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  saved: { type: Boolean, default: false }
})

const emit = defineEmits(['save'])

const { t } = useI18n()
</script>

<template>
  <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg">
    <div class="px-4 py-5 sm:p-6">
      <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
        {{ t('settings.general.title') }}
      </h3>
      <div class="mt-2 max-w-xl text-sm text-gray-500 dark:text-gray-400">
        <p>{{ t('settings.general.desc') }}</p>
      </div>

      <form class="mt-5 space-y-6" @submit.prevent="emit('save')">
        <!-- Assessment Model -->
        <div>
          <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white mb-2">
            <CpuChipIcon class="inline h-4 w-4 -mt-0.5 mr-1 text-blue-500" />
            {{ t('settings.general.assessment_model') }}
          </label>
          <div class="mt-1">
            <select v-model="settings.ai_assessment_model"
              class="block w-full max-w-xs rounded-md border-0 py-2 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600">
              <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t('settings.general.assessment_model_help') }}</p>
        </div>

        <!-- Data Generation Model -->
        <div>
          <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white mb-2">
            <CpuChipIcon class="inline h-4 w-4 -mt-0.5 mr-1 text-purple-500" />
            {{ t('settings.general.generation_model') }}
          </label>
          <div class="mt-1">
            <select v-model="settings.data_generation_model"
              class="block w-full max-w-xs rounded-md border-0 py-2 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600">
              <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t('settings.general.generation_model_help') }}</p>
        </div>

        <!-- Reasoning Effort -->
        <div v-if="settings.data_generation_model?.includes('gpt-5') || settings.ai_assessment_model?.includes('gpt-5') || settings.data_generation_model === 'model-router' || settings.ai_assessment_model === 'model-router'">
          <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white mb-2">
            {{ t('settings.general.reasoning_effort') }}
          </label>
          <div class="mt-1">
            <select v-model="settings.generation_reasoning_effort"
              class="block w-full max-w-xs rounded-md border-0 py-2 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600">
              <option value="none">{{ t('settings.general.effort_none') }}</option>
              <option value="low">{{ t('settings.general.effort_low') }}</option>
              <option value="medium">{{ t('settings.general.effort_medium') }}</option>
              <option value="high">{{ t('settings.general.effort_high') }}</option>
            </select>
          </div>
          <div class="mt-2 flex items-start gap-2 text-amber-600 dark:text-amber-400 text-xs">
            <ExclamationTriangleIcon class="h-4 w-4 flex-shrink-0 mt-0.5" />
            <span>{{ t('settings.general.reasoning_warning') }}</span>
          </div>
        </div>

        <div class="flex items-center gap-4">
          <button type="submit" :disabled="loading"
            class="rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600 disabled:opacity-50">
            {{ loading ? t('settings.saving') : t('settings.save') }}
          </button>
          <transition enter-active-class="transition ease-out duration-200" enter-from-class="opacity-0 translate-y-1"
            enter-to-class="opacity-100 translate-y-0" leave-active-class="transition ease-in duration-150"
            leave-from-class="opacity-100 translate-y-0" leave-to-class="opacity-0 translate-y-1">
            <div v-if="saved" class="flex items-center text-green-600 dark:text-green-400 text-sm font-medium">
              <CheckCircleIcon class="h-5 w-5 mr-1" />
              {{ t('settings.saved') }}
            </div>
          </transition>
        </div>
      </form>
    </div>
  </div>
</template>
