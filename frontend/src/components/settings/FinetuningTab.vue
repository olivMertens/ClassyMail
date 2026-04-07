<script setup>
import { useI18n } from 'vue-i18n'
import { InformationCircleIcon } from '@heroicons/vue/24/outline'

const props = defineProps({
  settings: { type: Object, required: true },
  loading: { type: Boolean, default: false }
})

const { t } = useI18n()
</script>

<template>
  <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg">
    <div class="px-4 py-5 sm:p-6">
      <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
        {{ t('settings.finetuning.title') }}
      </h3>
      <div class="mt-2 max-w-xl text-sm text-gray-500 dark:text-gray-400">
        <p>{{ t('settings.finetuning.desc') }}</p>
      </div>

      <!-- Info Box -->
      <div class="mt-4 rounded-md bg-blue-50 dark:bg-blue-900/20 p-4 border border-blue-200 dark:border-blue-800">
        <div class="flex">
          <div class="flex-shrink-0">
            <InformationCircleIcon class="h-5 w-5 text-blue-400" aria-hidden="true" />
          </div>
          <div class="ml-3 flex-1 md:flex md:justify-between">
            <div class="text-sm text-blue-700 dark:text-blue-300">
              <h4 class="font-bold">{{ t('settings.finetuning.info_title') }}</h4>
              <p class="mt-1">{{ t('settings.finetuning.info_desc') }}</p>
            </div>
          </div>
        </div>
        <div class="mt-3 ml-8">
          <a href="https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/fine-tuning?view=foundry-classic&tabs=oai-sdk%2Cazure-openai&pivots=programming-language-python"
            target="_blank"
            class="text-sm font-medium text-blue-700 dark:text-blue-300 hover:text-blue-600 hover:underline flex items-center gap-1">
            {{ t('settings.finetuning.learn_more') }}
            <span aria-hidden="true"> &rarr;</span>
          </a>
        </div>
      </div>

      <div class="mt-6">
        <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">
          {{ t('settings.finetuning.min_samples') }}
        </label>
        <div class="mt-2">
          <input v-model="settings.finetune_min_examples" type="number" min="5" step="1"
            class="block w-full max-w-xs rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600">
          <p class="mt-1 text-xs text-gray-500">{{ t('settings.finetuning.min_samples_help') }}</p>
        </div>
      </div>
    </div>
  </div>
</template>
