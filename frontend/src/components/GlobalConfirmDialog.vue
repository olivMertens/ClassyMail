<template>
  <div
    v-if="isVisible"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50"
    role="dialog"
  >
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md p-6 m-4 dark:bg-gray-800 dark:text-white">
      <h3 class="text-lg font-bold mb-4">
        {{ options.title }}
      </h3>
      <p class="mb-6 text-gray-700 dark:text-gray-300">
        {{ options.message }}
      </p>

      <div
        v-if="options.isPrompt"
        class="mb-6"
      >
        <input
          v-model="options.promptValue"
          type="text"
          class="block w-full rounded-md border-0 py-2.5 px-3 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 bg-white dark:bg-gray-700 dark:text-white dark:ring-gray-600"
          @keyup.enter="handleConfirm"
        >
      </div>

      <div class="flex justify-end gap-3">
        <button
          v-if="!options.isAlert"
          class="px-4 py-2 text-sm font-semibold text-gray-900 bg-white rounded-md shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-white dark:ring-gray-600 dark:hover:bg-gray-600 transition"
          @click="handleCancel"
        >
          {{ options.cancelLabel }}
        </button>
        <button
          class="px-4 py-2 text-sm font-semibold text-white bg-primary-600 rounded-md shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600 transition"
          @click="handleConfirm"
        >
          {{ options.confirmLabel }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useDialog } from '../composables/useDialog'

const { isVisible, options, handleConfirm, handleCancel } = useDialog()
</script>
