# Cost Estimates

## What The UI Calculates

`GET /api/costs/summary` accepts `emails_per_month` (default 10000),
`pricing_source=fixed|retail` and `region`. The implementation is
[#classymail/api/routers/costs.py](../classymail/api/routers/costs.py);
[#frontend/src/views/CostsView.vue](../frontend/src/views/CostsView.vue) displays it.

The endpoint sums stored classification/LLM, Mistral OCR and Document Intelligence cost
fields, divides by the count of records carrying usage costs, and projects that average
over the requested monthly volume. With no usage-bearing records, the variable average
is zero; it is not evidence that model calls will be free.

These are application estimates derived from recorded usage and configured rates,
not invoiced Azure charges. Do not assume that every optional call, failed attempt,
embedding, chat turn, preprocessing or PII service charge is included in those sums.
Inspect [repository aggregations](../classymail/services/repository.py) when reconciling.

## Fixed And Retail Modes

Fixed mode adds configurable monthly estimates:

| Variable | Default USD/month |
| --- | --- |
| `COST_FIXED_SERVICE_BUS_USD_MONTH` | 9 |
| `COST_FIXED_STORAGE_USD_MONTH` | 5 |
| `COST_FIXED_CONTAINER_APPS_USD_MONTH` | 20 |
| `COST_FIXED_APP_INSIGHTS_USD_MONTH` | 0 |
| `COST_FIXED_COSMOS_USD_MONTH` | 0 |

The default fixed total is 34 USD, an input assumption rather than a quoted subscription
price. Zero-cost defaults do not imply that those resources have no charge.

Retail mode queries Azure Retail Prices and estimates compute, Service Bus operations
and telemetry ingestion using modeled usage assumptions. Other components retain fixed
estimates; missing prices or request failures can fall back to fixed values. Retail
prices are not negotiated contract prices and usage assumptions are not live meter data.
See [azure_retail_prices.py](../classymail/services/azure_retail_prices.py).

## Rates And Evaluation

Configured token/page prices live in [config.py](../classymail/core/config.py),
[costing.py](../classymail/services/costing.py), and saved `cost_overrides` settings.
Check units and currency: environment token rates use per-1000 units while catalog
prices may use per-million tokens. Deployment choice, region and pricing updates affect
the estimate; no accuracy or cost ranking follows from the model alias alone.

Reprocessing makes new calls and can incur charges; stored per-record totals need not
represent cumulative billed spend. For budgeting, compare the app estimate to Azure
Cost Management and include retrieval/search, monitoring, storage and other omitted
services. Benchmark latency, quality and cost on your own representative dataset rather
than relying on unsourced per-model accuracy scores or fixed strategy multipliers.

Regression coverage is in [test_costs_analysis.py](../tests/test_costs_analysis.py):

```powershell
uv run pytest tests/test_costs_analysis.py
```
