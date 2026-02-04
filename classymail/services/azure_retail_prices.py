from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx


AZURE_RETAIL_PRICES_API = "https://prices.azure.com/api/retail/prices"


@dataclass(frozen=True)
class RetailPrice:
    service_name: str
    product_name: str
    sku_name: str
    meter_name: str
    arm_region_name: str
    unit_price: float
    unit_of_measure: str
    currency_code: str


class AzureRetailPricesClient:
    def __init__(self, *, timeout_s: float = 20.0) -> None:
        self._timeout = timeout_s
        self._cache: dict[str, tuple[float, Any]] = {}

    def _cache_get(self, key: str, *, ttl_s: float) -> Any | None:
        hit = self._cache.get(key)
        if not hit:
            return None
        ts, value = hit
        if (time.time() - ts) > ttl_s:
            return None
        return value

    def _cache_set(self, key: str, value: Any) -> None:
        self._cache[key] = (time.time(), value)

    async def _get_json(self, url: str) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    async def find_lowest_unit_price(
        self,
        *,
        service_name: str,
        arm_region_name: str,
        meter_name_contains: str,
        currency_code: str = "USD",
        ttl_s: float = 6 * 3600,
        max_pages: int = 10,
    ) -> Optional[RetailPrice]:
        # Note: Retail Prices API is public and can change shape/labels.
        # We do best-effort matching and return the cheapest unit price for the meter.
        cache_key = f"min:{service_name}:{arm_region_name}:{meter_name_contains}:{currency_code}"
        cached = self._cache_get(cache_key, ttl_s=ttl_s)
        if cached is not None:
            return cached

        filter_expr = (
            f"serviceName eq '{service_name}' and armRegionName eq '{arm_region_name}' "
            f"and contains(meterName,'{meter_name_contains}') and currencyCode eq '{currency_code}'"
        )
        url = f"{AZURE_RETAIL_PRICES_API}?$filter={httpx.QueryParams({'$filter': filter_expr})['$filter']}"

        best: RetailPrice | None = None
        pages = 0
        while url and pages < max_pages:
            pages += 1
            data = await self._get_json(url)
            items = data.get("Items") or []
            for it in items:
                try:
                    unit_price = float(it.get("unitPrice") or 0.0)
                except Exception:
                    continue
                if unit_price <= 0:
                    continue
                rp = RetailPrice(
                    service_name=str(it.get("serviceName") or ""),
                    product_name=str(it.get("productName") or ""),
                    sku_name=str(it.get("skuName") or ""),
                    meter_name=str(it.get("meterName") or ""),
                    arm_region_name=str(it.get("armRegionName") or ""),
                    unit_price=unit_price,
                    unit_of_measure=str(it.get("unitOfMeasure") or ""),
                    currency_code=str(it.get("currencyCode") or ""),
                )
                if best is None or rp.unit_price < best.unit_price:
                    best = rp

            url = data.get("NextPageLink")

        self._cache_set(cache_key, best)
        return best


def _env_float(name: str, default: float) -> float:
    import os

    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def _env_str(name: str, default: str) -> str:
    import os

    raw = os.getenv(name)
    return str(raw).strip() if raw is not None and str(raw).strip() else default


async def get_retail_unit_prices(*, region: str) -> dict[str, Any]:
    client = AzureRetailPricesClient()

    # Best-effort: meter labels may differ by region/offer. We keep fallbacks.
    aca_vcpu = await client.find_lowest_unit_price(
        service_name="Container Apps",
        arm_region_name=region,
        meter_name_contains="vCPU",
    )
    aca_mem = await client.find_lowest_unit_price(
        service_name="Container Apps",
        arm_region_name=region,
        meter_name_contains="GiB",
    )
    aca_req = await client.find_lowest_unit_price(
        service_name="Container Apps",
        arm_region_name=region,
        meter_name_contains="Requests",
    )

    sb_ops = await client.find_lowest_unit_price(
        service_name="Service Bus",
        arm_region_name=region,
        meter_name_contains="Operations",
    )

    log_ingest = await client.find_lowest_unit_price(
        service_name="Log Analytics",
        arm_region_name=region,
        meter_name_contains="Data Ingestion",
    )

    return {
        "region": region,
        "aca": {
            "vcpu_seconds": aca_vcpu.__dict__ if aca_vcpu else None,
            "gib_seconds": aca_mem.__dict__ if aca_mem else None,
            "requests": aca_req.__dict__ if aca_req else None,
        },
        "service_bus": {
            "operations": sb_ops.__dict__ if sb_ops else None,
        },
        "log_analytics": {
            "data_ingestion": log_ingest.__dict__ if log_ingest else None,
        },
        "assumptions": {
            "region": region,
            "aca_worker_seconds_per_email": _env_float("COST_ACA_WORKER_SECONDS_PER_EMAIL", 8.0),
            "aca_worker_vcpu": _env_float("COST_ACA_WORKER_VCPU", 0.5),
            "aca_worker_gib": _env_float("COST_ACA_WORKER_GIB", 1.0),
            "aca_api_min_replicas": _env_float("COST_ACA_API_MIN_REPLICAS", 1.0),
            "aca_api_idle_hours_per_month": _env_float("COST_ACA_API_IDLE_HOURS_PER_MONTH", 720.0),
            "sb_ops_per_email": _env_float("COST_SB_OPS_PER_EMAIL", 2.0),
            "log_gb_per_email": _env_float("COST_LOG_GB_PER_EMAIL", 0.0005),
            "currency": _env_str("COST_CURRENCY", "USD"),
        },
    }
