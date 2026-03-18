<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ExclamationCircleIcon } from '@heroicons/vue/24/outline'

const { t } = useI18n()
const costs = ref(null)
const loading = ref(false)
const error = ref(null)
const emailsPerMonth = ref(10000)
const pricingSource = ref('fixed')

const loadCosts = async () => {
  loading.value = true
  error.value = null
  try {
    const params = new URLSearchParams()
    params.set('emails_per_month', emailsPerMonth.value)
    params.set('pricing_source', pricingSource.value)
    params.set('region', 'swedencentral')

    const res = await fetch(`/api/costs/summary?${params.toString()}`)
    if (res.ok) {
      costs.value = await res.json()
    } else {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Server Error: ${res.status}`)
    }
  } catch (e) {
    console.error(e)
    error.value = e.message
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
        <h2
          class="text-2xl font-bold leading-7 text-gray-900 dark:text-white sm:truncate sm:text-3xl sm:tracking-tight">
          {{ t('costs.title') }}
        </h2>
      </div>
      <div class="mt-4 flex md:ml-4 md:mt-0">
        <button type="button"
          class="ml-3 inline-flex items-center rounded-md bg-primary-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
          @click="loadCosts">
          {{ t('costs.recalculate') }}
        </button>
      </div>
    </div>

    <!-- Inputs -->
    <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
      <div class="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div>
          <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">{{
            t('costs.emails_projection') }}</label>
          <div class="mt-2">
            <input v-model.number="emailsPerMonth" type="number"
              class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600">
          </div>
        </div>
        <div>
          <label class="block text-sm font-medium leading-6 text-gray-900 dark:text-white">{{ t('costs.pricing_source')
          }}</label>
          <div class="mt-2">
            <select v-model="pricingSource"
              class="block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-primary-600 sm:text-sm sm:leading-6 dark:bg-gray-700 dark:text-white dark:ring-gray-600">
              <option value="fixed">
                {{ t('costs.pricing_options.fixed') }}
              </option>
              <option value="retail">
                {{ t('costs.pricing_options.retail') }}
              </option>
            </select>
          </div>
        </div>
      </div>
    </div>

    <!-- Pricing Assumptions Warning -->
    <div class="rounded-md bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-4">
      <div class="flex">
        <div class="flex-shrink-0">
          <ExclamationCircleIcon class="h-5 w-5 text-amber-400" aria-hidden="true" />
        </div>
        <div class="ml-3 flex-1">
          <h3 class="text-sm font-semibold text-amber-800 dark:text-amber-300">
            {{ t('costs.pricing_assumptions.title') }}
          </h3>
          <div class="mt-2 text-sm text-amber-700 dark:text-amber-200 space-y-1">
            <p>{{ t('costs.pricing_assumptions.model_pricing') }}</p>
            <p>{{ t('costs.pricing_assumptions.reprocessing') }}</p>
            <p class="mt-2 text-xs italic">
              💡 {{ t('costs.pricing_assumptions.env_override') }}
            </p>
            <p class="mt-2 text-xs">
              <a href="https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/"
                target="_blank" rel="noopener" class="text-primary-600 dark:text-primary-400 hover:underline">📎
                Microsoft Azure OpenAI Pricing</a>
              · <a href="https://azure.microsoft.com/en-us/pricing/details/cognitive-services/document-intelligence/"
                target="_blank" rel="noopener" class="text-primary-600 dark:text-primary-400 hover:underline">📎 Mistral
                / Doc Intelligence Pricing</a>
            </p>
          </div>
        </div>
      </div>
    </div>

    <div v-if="loading && !costs" class="text-center py-12">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto" />
    </div>

    <div v-else-if="error"
      class="rounded-md bg-gray-50 dark:bg-gray-800/50 p-8 border border-gray-200 dark:border-gray-700 text-center">
      <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800 mb-4">
        <ExclamationCircleIcon class="h-6 w-6 text-gray-400" aria-hidden="true" />
      </div>
      <h3 class="text-base font-semibold text-gray-900 dark:text-white">
        Start Processing to see Costs
      </h3>
      <p class="mt-2 text-sm text-gray-500 dark:text-gray-400 max-w-sm mx-auto">
        No cost data is available yet because the database is empty or unreachable. Upload your first document to
        initialize specific cost tracking.
      </p>
      <p class="mt-4 text-xs text-gray-400 font-mono bg-gray-100 dark:bg-gray-900 p-2 rounded inline-block">
        Debug: {{ error }}
      </p>
    </div>

    <div v-else-if="costs" class="space-y-6">
      <!-- Stats -->
      <div class="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
          <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">
            {{ t('costs.emails_usage') }}
          </dt>
          <dd class="mt-1 text-3xl font-semibold text-gray-900 dark:text-white">
            {{ costs.counts?.emails_with_usage ?? costs.counts?.processed ?? 0 }}
          </dd>
          <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
            {{ t('costs.proc_vs_usage', {
              processed: costs.counts?.processed ?? 0, priced:
                costs.counts?.emails_with_usage ?? 0
            }) }}
          </p>
        </div>
        <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6">
          <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">
            {{ t('costs.avg_cost') }}
          </dt>
          <dd class="mt-1 text-3xl font-semibold text-gray-900 dark:text-white">
            ${{ (costs.avg_usd_per_email?.ai_total ?? 0).toFixed(4) }}
          </dd>
        </div>
      </div>
      <p class="text-xs text-gray-500 dark:text-gray-400 mt-2">
        {{ t('costs.counts_hint') }}
      </p>

      <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <!-- Actual Spend -->
        <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
          <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white mb-4">
            {{ t('costs.actual_spend') }}
          </h3>
          <dl class="divide-y divide-gray-200 dark:divide-gray-700">
            <div class="px-0 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
              <dt class="text-sm font-medium text-gray-500 dark:text-gray-400">
                LLM (Classification)
              </dt>
              <dd class="mt-1 text-sm text-gray-900 dark:text-white sm:col-span-2 sm:mt-0">
                ${{ (costs.actual_usd?.llm ?? costs.actual_usd?.phi4 ?? 0).toFixed(4) }}
              </dd>
            </div>
            <div class="px-0 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
              <dt class="text-sm font-medium text-gray-500 dark:text-gray-400">
                Mistral OCR
              </dt>
              <dd class="mt-1 text-sm text-gray-900 dark:text-white sm:col-span-2 sm:mt-0">
                ${{ (costs.actual_usd?.mistral_ocr ?? 0).toFixed(4) }}
              </dd>
            </div>
            <div
              class="px-0 py-3 sm:grid sm:grid-cols-3 sm:gap-4 font-bold bg-gray-50 dark:bg-gray-700/50 rounded-md px-2">
              <dt class="text-sm text-gray-900 dark:text-white">
                {{ t('costs.total_ai') }}
              </dt>
              <dd class="mt-1 text-sm text-gray-900 dark:text-white sm:col-span-2 sm:mt-0">
                ${{ (costs.actual_usd?.ai_total ?? 0).toFixed(4) }}
              </dd>
            </div>
          </dl>
        </div>

        <!-- Model Cost Comparison -->
        <div v-if="costs.model_cost_comparison && costs.model_cost_comparison.length"
          class="bg-white dark:bg-gray-800 shadow rounded-lg p-6 lg:col-span-2">
          <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white mb-2">
            {{ t('costs.model_comparison_title') || 'Model Cost Comparison' }}
          </h3>
          <p class="text-xs text-gray-500 dark:text-gray-400 mb-2">
            {{ t('costs.model_comparison_desc') || 'Projected LLM cost if all emails were reprocessed with each model, based on actual token usage.' }}
          </p>

          <!-- Token hypothesis from actual data -->
          <div v-if="costs.token_hypothesis"
            class="text-[11px] text-blue-700 dark:text-blue-300 bg-blue-50/60 dark:bg-blue-900/20 rounded p-2 mb-3 space-y-1 border border-blue-200/50 dark:border-blue-800/30">
            <p class="font-semibold">
              📊 Token hypothesis (from {{ costs.token_hypothesis.emails_sampled }} processed emails):
            </p>
            <p>
              Avg input: <strong>{{ costs.token_hypothesis.avg_input_tokens_per_email?.toLocaleString() }}</strong>
              tokens/email
              · Avg output: <strong>{{ costs.token_hypothesis.avg_output_tokens_per_email?.toLocaleString() }}</strong>
              tokens/email
            </p>
            <p class="italic">
              {{ costs.token_hypothesis.description }}
            </p>
          </div>

          <!-- 10K projection grid -->
          <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-3">
            <div v-for="mc in costs.model_cost_comparison" :key="mc.key"
              class="relative rounded-lg border p-3 text-center" :class="mc.projected_10k_usd === Math.min(...costs.model_cost_comparison.map(m => m.projected_10k_usd))
                ? 'border-green-300 dark:border-green-700 bg-green-50 dark:bg-green-900/20'
                : 'border-gray-200 dark:border-gray-700'">
              <div class="text-xs font-medium text-gray-600 dark:text-gray-300 truncate">
                {{ mc.model }}
              </div>
              <div class="mt-1 text-lg font-bold text-gray-900 dark:text-white">
                ${{ mc.projected_10k_usd?.toFixed(0) ?? mc.projected_usd?.toFixed(4) }}
              </div>
              <div class="text-[10px] text-gray-400">
                /10K emails
              </div>
              <div
                v-if="mc.projected_10k_usd === Math.min(...costs.model_cost_comparison.map(m => m.projected_10k_usd))"
                class="mt-1 text-[10px] font-semibold text-green-700 dark:text-green-400">
                {{ t('costs.cheapest') || 'Cheapest' }}
              </div>
            </div>
          </div>

          <!-- Actual spend for current batch -->
          <p v-if="costs.llm_tokens" class="text-[11px] text-gray-400 dark:text-gray-500 mt-3">
            Actual total tokens ({{ costs.counts?.emails_with_usage ?? 0 }} emails):
            {{ (costs.llm_tokens.prompt_tokens ?? 0).toLocaleString() }} input +
            {{ (costs.llm_tokens.completion_tokens ?? 0).toLocaleString() }} output
          </p>

          <!-- Mistral OCR baseline -->
          <div
            class="mt-3 text-[11px] text-purple-700 dark:text-purple-300 bg-purple-50/60 dark:bg-purple-900/20 rounded p-2 border border-purple-200/50 dark:border-purple-800/30">
            <p class="font-semibold">+ Mistral OCR (mandatory for all models):</p>
            <p>${{ (costs.avg_usd_per_email?.mistral_ocr ?? 0).toFixed(4) }}/email · ${{
              ((costs.avg_usd_per_email?.mistral_ocr ?? 0) * 10000).toFixed(0) }}/10K emails</p>
            <p class="italic mt-0.5">OCR is required before any LLM classification. Add this baseline to each model's
              cost above.</p>
          </div>

          <!-- Cost multiplier warning -->
          <div
            class="mt-3 text-[11px] text-amber-700 dark:text-amber-300 bg-amber-50/60 dark:bg-amber-900/20 rounded p-2 space-y-1 border border-amber-200/50 dark:border-amber-800/30">
            <p class="font-semibold">
              ⚠️ Classification-only estimate. Costs increase with:
            </p>
            <ul class="list-disc pl-4 space-y-0.5">
              <li><strong>Entity extraction:</strong> ~×1.3</li>
              <li><strong>PII detection (LLM):</strong> ~×1.5</li>
              <li><strong>All features:</strong> ~×3–4 total</li>
              <li><strong>Reprocessing:</strong> multiplies by number of passes</li>
            </ul>
          </div>
        </div>

        <!-- Projected Spend -->
        <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
          <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white mb-4 flex justify-between">
            <span>{{ t('costs.monthly_projection') }}</span>
            <span class="text-xs font-normal text-gray-500">{{ costs.pricing?.source || pricingSource }}</span>
          </h3>

          <div class="mb-3 space-y-1 text-xs text-gray-500 dark:text-gray-400">
            <div>
              {{ t('costs.projection_emails', { n: costs.projection_monthly_usd?.emails_per_month ?? emailsPerMonth })
              }}
            </div>
            <div>
              {{ t('costs.projection_ai_formula', {
                avg: (costs.avg_usd_per_email?.ai_total ?? 0).toFixed(4),
                n: costs.projection_monthly_usd?.emails_per_month ?? emailsPerMonth,
              }) }}
            </div>
            <div v-if="(costs.counts?.emails_with_usage ?? 0) === 0" class="text-amber-700 dark:text-amber-400">
              {{ t('costs.projection_ai_no_data') }}
            </div>
          </div>

          <dl class="divide-y divide-gray-200 dark:divide-gray-700">
            <div class="px-0 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
              <dt class="text-sm font-medium text-gray-500 dark:text-gray-400">
                {{ t('costs.ai_variable') }}
              </dt>
              <dd class="mt-1 text-sm text-gray-900 dark:text-white sm:col-span-2 sm:mt-0">
                ${{ (costs.projection_monthly_usd?.ai_variable ?? 0).toFixed(2) }}
              </dd>
            </div>
            <div class="px-0 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
              <dt class="text-sm font-medium text-gray-500 dark:text-gray-400">
                {{ t('costs.infra_fixed') }}
              </dt>
              <dd class="mt-1 text-sm text-gray-900 dark:text-white sm:col-span-2 sm:mt-0">
                ${{ (costs.projection_monthly_usd?.fixed ?? 0).toFixed(2) }}
              </dd>
            </div>
            <div
              class="px-0 py-3 sm:grid sm:grid-cols-3 sm:gap-4 font-bold bg-gray-50 dark:bg-gray-700/50 rounded-md px-2">
              <dt class="text-sm text-gray-900 dark:text-white">
                {{ t('costs.total_estimated') }}
              </dt>
              <dd class="mt-1 text-sm text-gray-900 dark:text-white sm:col-span-2 sm:mt-0">
                ${{ (costs.projection_monthly_usd?.total ?? 0).toFixed(2) }}
              </dd>
            </div>
          </dl>
        </div>
      </div>

      <!-- Logic Breakdown (Retail only) -->
      <div v-if="costs.pricing?.retail" class="bg-white dark:bg-gray-800 shadow rounded-lg p-6 space-y-4">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white">
          {{ t('costs.logic_title') }}
        </h3>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm">
          <!-- Unit Prices -->
          <div>
            <h4 class="font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ t('costs.logic_unit_prices', { region: costs.pricing.region }) }}
            </h4>
            <ul class="list-disc pl-5 space-y-1 text-gray-600 dark:text-gray-400">
              <li v-if="costs.pricing.retail.aca?.vcpu_seconds?.unit_price">
                {{ t('costs.item_vcpu') }}: ${{ costs.pricing.retail.aca.vcpu_seconds.unit_price.toPrecision(4) }} / s
              </li>
              <li v-if="costs.pricing.retail.aca?.gib_seconds?.unit_price">
                {{ t('costs.item_gib') }}: ${{ costs.pricing.retail.aca.gib_seconds.unit_price.toPrecision(4) }} / s
              </li>
              <li v-if="costs.pricing.retail.service_bus?.operations?.unit_price">
                {{ t('costs.item_ops') }}: ${{ (costs.pricing.retail.service_bus.operations.unit_price *
                  1000).toPrecision(4) }} / 1k ops
              </li>
            </ul>
          </div>

          <!-- Assumptions -->
          <div>
            <h4 class="font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ t('costs.logic_assumptions') }}
            </h4>
            <ul v-if="costs.pricing.retail.assumptions"
              class="list-disc pl-5 space-y-1 text-gray-600 dark:text-gray-400">
              <li>
                {{ t('costs.logic_aca_worker') }}:
                {{ costs.pricing.retail.assumptions.aca_worker_seconds_per_email }}s/email
                ({{ costs.pricing.retail.assumptions.aca_worker_vcpu }} vCPU, {{
                  costs.pricing.retail.assumptions.aca_worker_gib }} GiB)
              </li>
              <li>
                {{ t('costs.logic_aca_api') }}:
                {{ costs.pricing.retail.assumptions.aca_api_min_replicas }} Rep.,
                {{ costs.pricing.retail.assumptions.aca_api_idle_hours_per_month }}h {{ t('costs.val_idle') }}
              </li>
            </ul>
          </div>
        </div>

        <!-- Formulas -->
        <div v-if="costs.pricing.retail.assumptions"
          class="bg-gray-50 dark:bg-gray-700/50 p-3 rounded text-xs font-mono text-gray-600 dark:text-gray-300 overflow-x-auto">
          <div>
            <strong>Worker:</strong> (Emails/Mo * {{ costs.pricing.retail.assumptions.aca_worker_seconds_per_email
            }}s) * ({{ costs.pricing.retail.assumptions.aca_worker_vcpu }} * vCPU_Price + {{
              costs.pricing.retail.assumptions.aca_worker_gib }} * GiB_Price)
          </div>
          <div class="mt-1">
            <strong>API:</strong> ({{ costs.pricing.retail.assumptions.aca_api_min_replicas }} Rep. * {{
              costs.pricing.retail.assumptions.aca_api_idle_hours_per_month }}h * 3600s) * (0.5 * vCPU_Price + 1.0 *
            GiB_Price)
          </div>
        </div>
      </div>

      <!-- Static Reference Rates (Moved from Info) -->
      <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
        <h3 class="text-base font-semibold leading-6 text-gray-900 dark:text-white mb-4">
          {{ t('costs.ref_title') }} <span class="text-xs font-normal text-gray-500">({{ t('costs.ref_subtitle')
          }})</span>
        </h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm">
          <div>
            <h4 class="font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ t('info.est_email') }}
            </h4>
            <ul class="list-disc pl-5 space-y-1 text-gray-600 dark:text-gray-400">
              <li>{{ t('info.email_items.ocr') }}</li>
              <li>{{ t('info.email_items.classification') }}</li>
              <li>{{ t('info.email_items.infra') }}</li>
            </ul>
          </div>
          <div>
            <h4 class="font-medium text-gray-700 dark:text-gray-300 mb-2">
              {{ t('info.est_monthly') }}
            </h4>
            <ul class="list-disc pl-5 space-y-1 text-gray-600 dark:text-gray-400">
              <li>{{ t('info.infra_items.service_bus') }}</li>
              <li>{{ t('info.infra_items.cosmos') }}</li>
              <li>{{ t('info.infra_items.storage') }}</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
