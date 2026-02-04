<script setup>
import { useI18n } from 'vue-i18n'
import { XMarkIcon } from '@heroicons/vue/24/outline'

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  },
  organizationName: {
    type: String,
    default: 'ClassiMail'
  }
})
const emit = defineEmits(['close', 'navigate'])
const { t } = useI18n()
</script>

<template>
  <div
    v-if="show"
    class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900 bg-opacity-75 p-4 sm:p-0"
  >
    <div
      class="relative transform overflow-hidden rounded-lg bg-white text-left shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg dark:bg-gray-800 border border-gray-200 dark:border-gray-700"
    >
      <div class="bg-white dark:bg-gray-800 px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
        <div class="sm:flex sm:items-start">
          <div class="mt-3 text-center sm:ml-4 sm:mt-0 sm:text-left w-full">
            <div class="flex justify-between items-start">
              <h3
                id="modal-title"
                class="text-xl font-semibold leading-6 text-gray-900 dark:text-white"
              >
                {{ t('info.poc_header', { org: props.organizationName, date: t('info.date') }) }}
              </h3>
              <button
                class="text-gray-400 hover:text-gray-500 dark:hover:text-gray-200"
                @click="emit('close')"
              >
                <XMarkIcon class="h-6 w-6" />
              </button>
            </div>

            <div class="mt-4 text-sm text-gray-600 dark:text-gray-300">
              <p class="font-medium text-lg">
                {{ t('info.subtitle') }}
              </p>
              <p class="mt-2 text-primary-600 dark:text-primary-400 italic">
                {{ t('info.tagline') }}
              </p>
              <p class="mt-2">
                <strong>{{ t('info.contact') }}:</strong> Olivier Mertens<br>
                <a
                  href="mailto:olmertens@microsoft.com"
                  class="text-primary-600 dark:text-primary-400 hover:underline"
                >olmertens@microsoft.com</a>
              </p>

              <div class="mt-5 space-y-2">
                <div
                  class="font-semibold text-gray-900 dark:text-white border-b border-gray-200 dark:border-gray-700 pb-1 mb-2"
                >
                  {{ t('info.target_title') }}
                </div>
                <p class="text-gray-600 dark:text-gray-300">
                  {{ t('info.target_desc') }}
                </p>

                <div
                  class="font-semibold text-gray-900 dark:text-white border-b border-gray-200 dark:border-gray-700 pb-1 mb-2 mt-4"
                >
                  {{ t('info.resources_title') }}
                </div>
                <ul class="list-disc list-inside space-y-1 ml-1 text-gray-600 dark:text-gray-300">
                  <li>{{ t('info.infra_items.service_bus') }}</li>
                  <li>{{ t('info.infra_items.cosmos') }}</li>
                  <li>{{ t('info.infra_items.storage') }}</li>
                  <li>{{ t('info.infra_items.ai_foundry') }}</li>
                  <li>{{ t('info.infra_items.container_apps') }}</li>
                </ul>

                <div
                  class="font-semibold text-gray-900 dark:text-white border-b border-gray-200 dark:border-gray-700 pb-1 mb-2 mt-4"
                >
                  {{ t('info.features.title') }}
                </div>
                <ul class="list-disc list-inside space-y-1 ml-1 text-gray-600 dark:text-gray-300">
                  <li>{{ t('info.features.adversarial') }}</li>
                  <li>{{ t('info.features.dark_mode') }}</li>
                  <li>{{ t('info.features.retail_prices') }}</li>
                </ul>

                <div class="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                  <p class="text-sm text-gray-500 dark:text-gray-400">
                    {{ t('info.guide_prompt') }}
                    <a
                      href="#"
                      class="text-primary-600 dark:text-primary-400 hover:underline font-medium"
                      @click.prevent="emit('navigate', 'docs')"
                    >
                      {{ t('info.guide_link') }}
                    </a>
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="bg-gray-50 dark:bg-gray-700 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
        <button
          type="button"
          class="inline-flex w-full justify-center rounded-md bg-sky-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-sky-500 sm:ml-3 sm:w-auto"
          @click="emit('close')"
        >
          {{ t('info.close') }}
        </button>
      </div>
    </div>
  </div>
</template>
