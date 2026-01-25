<script setup>
import { ref, onMounted } from 'vue'

const costs = ref(null)
const loading = ref(false)
const emailsPerMonth = ref(10000)
const pricingSource = ref('fixed')

const loadCosts = async () => {
    loading.value = true
    try {
        const params = new URLSearchParams()
        params.set('emails_per_month', emailsPerMonth.value)
        params.set('pricing_source', pricingSource.value)
        params.set('region', 'swedencentral')
        
        const res = await fetch(`/api/costs/summary?${params.toString()}`)
        if (res.ok) {
            costs.value = await res.json()
        }
    } catch (e) {
        console.error(e)
    } finally {
        loading.value = false
    }
}

onMounted(() => {
    loadCosts()
})
</script>

<template>
  <div class="space-y-6">
    <div class="md:flex md:items-center md:justify-between">
      <div class="min-w-0 flex-1">
        <h2 class="text-2xl font-bold leading-7 text-gray-900 dark:text-white sm:truncate sm:text-3xl sm:tracking-tight">Costs Analysis</h2>
      </div>
      <div class="mt-4 flex md:ml-4 md:mt-0">
        <button type="button" @click="loadCosts" class="ml-3 inline-flex items-center rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600">
             Recalculate
        </button>
      </div>
    </div>

    <!-- Inputs -->
    <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
        <div class="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <div>
                <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">Emails / Month Projection</label>
                <div class="mt-2">
                    <input type="number" v-model.number="emailsPerMonth" class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600" />
                </div>
            </div>
            <div>
                <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">Pricing Source</label>
                <div class="mt-2">
                    <select v-model="pricingSource" class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600">
                        <option value="fixed">Fixed Estimate (POC)</option>
                        <option value="retail">Azure Retail Prices API</option>
                    </select>
                </div>
            </div>
        </div>
    </div>

    <div v-if="loading && !costs" class="text-center py-12">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto"></div>
    </div>

    <div v-else-if="costs" class="space-y-6">
        <!-- Stats -->
        <div class="grid grid-cols-1 gap-5 sm:grid-cols-3">
            <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
                <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">Processed Emails</dt>
                <dd class="mt-1 text-3xl font-semibold text-gray-900 dark:text-white">{{ costs.counts?.processed ?? 0 }}</dd>
            </div>
            <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
                <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">Emails with Usage Data</dt>
                <dd class="mt-1 text-3xl font-semibold text-gray-900 dark:text-white">{{ costs.counts?.emails_with_usage ?? 0 }}</dd>
            </div>
            <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
                <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">Avg AI Cost / Email</dt>
                <dd class="mt-1 text-3xl font-semibold text-gray-900 dark:text-white">${{ (costs.avg_usd_per_email?.ai_total ?? 0).toFixed(4) }}</dd>
            </div>
        </div>

        <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <!-- Actual Spend -->
            <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
                <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white mb-4">Actual AI Spend (Repo History)</h3>
                <dl class="divide-y divide-gray-200 dark:divide-gray-700">
                    <div class="px-0 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
                        <dt class="text-sm font-medium text-gray-500 dark:text-gray-400">Phi-4</dt>
                        <dd class="mt-1 text-sm text-gray-900 dark:text-white sm:col-span-2 sm:mt-0">${{ (costs.actual_usd?.phi4 ?? 0).toFixed(4) }}</dd>
                    </div>
                    <div class="px-0 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
                        <dt class="text-sm font-medium text-gray-500 dark:text-gray-400">Mistral OCR</dt>
                        <dd class="mt-1 text-sm text-gray-900 dark:text-white sm:col-span-2 sm:mt-0">${{ (costs.actual_usd?.mistral_ocr ?? 0).toFixed(4) }}</dd>
                    </div>
                    <div class="px-0 py-3 sm:grid sm:grid-cols-3 sm:gap-4 font-bold bg-gray-50 dark:bg-gray-700/50 rounded-md px-2">
                        <dt class="text-sm text-gray-900 dark:text-white">Total AI</dt>
                        <dd class="mt-1 text-sm text-gray-900 dark:text-white sm:col-span-2 sm:mt-0">${{ (costs.actual_usd?.ai_total ?? 0).toFixed(4) }}</dd>
                    </div>
                </dl>
            </div>

            <!-- Projected Spend -->
            <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
                <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white mb-4 flex justify-between">
                    <span>Monthly Projection</span>
                    <span class="text-xs font-normal text-gray-500">{{ costs.pricing?.source || pricingSource }}</span>
                </h3>
                <dl class="divide-y divide-gray-200 dark:divide-gray-700">
                    <div class="px-0 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
                        <dt class="text-sm font-medium text-gray-500 dark:text-gray-400">AI (Variable)</dt>
                        <dd class="mt-1 text-sm text-gray-900 dark:text-white sm:col-span-2 sm:mt-0">${{ (costs.projection_monthly_usd?.ai_variable ?? 0).toFixed(2) }}</dd>
                    </div>
                    <div class="px-0 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
                        <dt class="text-sm font-medium text-gray-500 dark:text-gray-400">Infrastructure (Fixed Est.)</dt>
                        <dd class="mt-1 text-sm text-gray-900 dark:text-white sm:col-span-2 sm:mt-0">${{ (costs.projection_monthly_usd?.fixed ?? 0).toFixed(2) }}</dd>
                    </div>
                    <div class="px-0 py-3 sm:grid sm:grid-cols-3 sm:gap-4 font-bold bg-gray-50 dark:bg-gray-700/50 rounded-md px-2">
                        <dt class="text-sm text-gray-900 dark:text-white">Total Estimated</dt>
                        <dd class="mt-1 text-sm text-gray-900 dark:text-white sm:col-span-2 sm:mt-0">${{ (costs.projection_monthly_usd?.total ?? 0).toFixed(2) }}</dd>
                    </div>
                </dl>
            </div>
        </div>
        
        <!-- Breakdown -->
         <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
            <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white mb-4">Cost Breakdown Details</h3>
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-300 dark:divide-gray-700">
                    <thead>
                        <tr>
                            <th scope="col" class="py-3.5 pl-4 pr-3 text-left text-sm font-semibold text-gray-900 dark:text-white sm:pl-0">Resource</th>
                            <th scope="col" class="px-3 py-3.5 text-right text-sm font-semibold text-gray-900 dark:text-white">Est. Cost (USD/Month)</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-200 dark:divide-gray-700">
                        <tr v-for="(row, idx) in (costs.projection_monthly_usd?.breakdown || [])" :key="idx">
                            <td class="whitespace-nowrap py-4 pl-4 pr-3 text-sm font-medium text-gray-900 dark:text-white sm:pl-0">{{ row.resource }}</td>
                            <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500 dark:text-gray-400 text-right">${{ (row.usd ?? 0).toFixed(2) }}</td>
                        </tr>
                    </tbody>
                </table>
            </div>
             <p v-if="costs.notes?.length" class="mt-4 text-xs text-gray-500">{{ costs.notes.join(' ') }}</p>
         </div>
    </div>
  </div>
</template>
