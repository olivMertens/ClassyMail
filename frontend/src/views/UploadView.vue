<script setup>
import { ref } from 'vue'
import { CloudArrowUpIcon, DocumentIcon, XMarkIcon, CheckCircleIcon, ExclamationTriangleIcon } from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const dragActive = ref(false)
const uploading = ref(false)
const files = ref([])


const handleDragOver = (e) => {
    e.preventDefault()
    dragActive.value = true
}

const handleDragLeave = (e) => {
    e.preventDefault()
    dragActive.value = false
}

const handleDrop = (e) => {
    e.preventDefault()
    dragActive.value = false
    const droppedFiles = Array.from(e.dataTransfer.files)
    addFiles(droppedFiles)
}

const handleFileSelect = (e) => {
    const selectedFiles = Array.from(e.target.files)
    addFiles(selectedFiles)
}

const addFiles = (newFiles) => {
    // Filter by type (PDF) and size (max 10MB)
    const MAX_SIZE = 10 * 1024 * 1024 // 10MB

    const validFiles = newFiles
        .filter(f => f.type === 'application/pdf')
        .slice(0, 10 - files.value.length)

    validFiles.forEach(f => {
        if (files.value.length < 10) {
            const isTooLarge = f.size > MAX_SIZE
            files.value.push({
                file: f,
                id: Math.random().toString(36).substring(7),
                status: isTooLarge ? 'error' : 'pending',
                message: isTooLarge ? 'File exceeds 10MB limit' : ''
            })
        }
    })
}

const removeFile = (id) => {
    files.value = files.value.filter(f => f.id !== id)
}

const uploadFiles = async () => {
    if (!files.value.length) return

    uploading.value = true
    const pendingFiles = files.value.filter(f => f.status === 'pending' || f.status === 'error')

    const formData = new FormData()
    pendingFiles.forEach(f => {
        formData.append('files', f.file)
        f.status = 'uploading'
    })

    try {
        const res = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        })

        if (!res.ok) throw new Error('Upload failed')

        const data = await res.json()
        const results = data.results || []

        pendingFiles.forEach(f => {
            const result = results.find(r => r.name === f.file.name)
            if (result) {
                if (result.status === 'success') {
                    f.status = 'success'
                    f.message = 'Uploaded'
                } else {
                    f.status = 'error'
                    f.message = result.error
                }
            } else {
                f.status = 'error'
                f.message = 'Unknown error'
            }
        })

    } catch (e) {
        pendingFiles.forEach(f => {
            f.status = 'error'
            f.message = e.message
        })
    } finally {
        uploading.value = false
    }
}
</script>

<template>
  <div class="max-w-3xl mx-auto space-y-6">
    <div class="bg-white dark:bg-gray-800 shadow sm:rounded-lg">
      <div class="px-4 py-5 sm:p-6">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
          {{ t('upload.title') }}
        </h3>
        <div class="mt-2 max-w-xl text-sm text-gray-500 dark:text-gray-400">
          <p>{{ t('upload.subtitle') }}</p>
        </div>

        <div
          class="mt-5 flex justify-center rounded-lg border border-dashed border-gray-900/25 dark:border-gray-600 px-6 py-10 transition-colors"
          :class="[dragActive ? 'bg-primary-50 border-primary-500 dark:bg-gray-700' : 'bg-gray-50 dark:bg-gray-900']"
          @dragover="handleDragOver"
          @dragleave="handleDragLeave"
          @drop="handleDrop"
        >
          <div class="text-center">
            <CloudArrowUpIcon
              class="mx-auto h-12 w-12 text-gray-300"
              aria-hidden="true"
            />
            <div class="mt-4 flex text-sm leading-6 text-gray-600 dark:text-gray-400">
              <label
                for="file-upload"
                class="relative cursor-pointer rounded-md bg-white dark:bg-gray-800 font-semibold text-primary-600 focus-within:outline-none focus-within:ring-2 focus-within:ring-primary-600 focus-within:ring-offset-2 hover:text-primary-500 px-2"
              >
                <span>{{ t('upload.select') }}</span>
                <input
                  id="file-upload"
                  name="file-upload"
                  type="file"
                  class="sr-only"
                  multiple
                  accept=".pdf"
                  @change="handleFileSelect"
                >
              </label>
              <p class="pl-1">
                {{ t('upload.drop_text') }}
              </p>
            </div>
            <p class="text-xs leading-5 text-gray-600 dark:text-gray-400">
              {{ t('upload.limits') }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- File List -->
    <div
      v-if="files.length"
      class="bg-white dark:bg-gray-800 shadow sm:rounded-lg overflow-hidden"
    >
      <ul
        role="list"
        class="divide-y divide-gray-200 dark:divide-gray-700"
      >
        <li
          v-for="file in files"
          :key="file.id"
          class="px-4 py-4 sm:px-6 flex items-center justify-between"
        >
          <div class="flex items-center truncate">
            <DocumentIcon class="h-5 w-5 text-gray-400 flex-shrink-0" />
            <span
              class="ml-2 truncate text-sm font-medium text-gray-900 dark:text-gray-200"
              :title="file.file.name"
            >{{ file.file.name }}</span>
            <span class="ml-2 text-xs text-gray-500 dark:text-gray-400">{{ (file.file.size / 1024 / 1024).toFixed(2) }} MB</span>
          </div>
          <div class="flex items-center ml-4">
            <div
              v-if="file.status === 'uploading'"
              class="animate-spin rounded-full h-4 w-4 border-b-2 border-primary-600 mr-2"
            />
            <CheckCircleIcon
              v-else-if="file.status === 'success'"
              class="h-5 w-5 text-green-500 mr-2"
            />
            <ExclamationTriangleIcon
              v-else-if="file.status === 'error'"
              class="h-5 w-5 text-red-500 mr-2"
            />

            <span
              v-if="file.message"
              class="text-xs mr-3"
              :class="{'text-red-500': file.status === 'error', 'text-green-500': file.status === 'success'}"
            >
              {{ file.message }}
            </span>

            <button
              v-if="file.status !== 'uploading'"
              class="text-gray-400 hover:text-gray-500 dark:hover:text-gray-300"
              @click="removeFile(file.id)"
            >
              <XMarkIcon class="h-5 w-5" />
            </button>
          </div>
        </li>
      </ul>
      <div class="bg-gray-50 dark:bg-gray-700 px-4 py-3 sm:px-6 flex justify-end">
        <button
          type="button"
          :disabled="uploading || !files.some(f => f.status === 'pending' || f.status === 'error')"
          class="rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600 disabled:opacity-50 disabled:cursor-not-allowed"
          @click="uploadFiles"
        >
          {{ uploading ? t('upload.uploading') : t('upload.start') }}
        </button>
      </div>
    </div>
  </div>
</template>

