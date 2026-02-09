from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Query, HTTPException

from classymail.services.azure_clients import Clients, get_clients
from classymail.services.azure_retail_prices import get_retail_unit_prices
from classymail.services.costing import MODEL_PRICING
from classymail.services.repository import (
    count_by_status,
    sum_mistral_cost_usd,
    sum_phi4_cost_usd,
    sum_llm_tokens,
    count_items_with_any_usage_cost,
)


router = APIRouter(prefix="/api", tags=["costs"])


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


@router.get("/costs/summary")
async def costs_summary(
    emails_per_month: int = Query(10_000, ge=0),
    pricing_source: str = Query("fixed", pattern="^(fixed|retail)$"),
    region: str = Query("swedencentral"),
    clients: Clients = Depends(get_clients),
) -> dict[str, Any]:
    try:
        processed_count = await count_by_status("PROCESSED", clients=clients)
        review_count = await count_by_status("REVIEW_REQUIRED", clients=clients)
        error_count = await count_by_status("ERROR", clients=clients)

        phi4_usd = await sum_phi4_cost_usd(clients=clients)
        mistral_usd = await sum_mistral_cost_usd(clients=clients)
        llm_tokens = await sum_llm_tokens(clients=clients)

        emails_with_usage = await count_items_with_any_usage_cost(clients=clients)
    except Exception as e:
        # If database is unreachable or empty (init issue), return 503 so UI knows.
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable: {str(e)}. Ensure Cosmos DB is provisioned and identity has permissions.",
        )

    ai_total_usd = (phi4_usd or 0.0) + (mistral_usd or 0.0)

    avg_ai_usd_per_email = (ai_total_usd / emails_with_usage) if emails_with_usage else 0.0
    projected_ai_usd = avg_ai_usd_per_email * float(emails_per_month)

    # Fixed monthly estimates: keep them configurable because pricing varies by region and configuration.
    fixed_service_bus = _env_float("COST_FIXED_SERVICE_BUS_USD_MONTH", 9.0)
    fixed_storage = _env_float("COST_FIXED_STORAGE_USD_MONTH", 5.0)
    fixed_container_apps = _env_float("COST_FIXED_CONTAINER_APPS_USD_MONTH", 20.0)
    fixed_app_insights = _env_float("COST_FIXED_APP_INSIGHTS_USD_MONTH", 0.0)
    fixed_cosmos = _env_float("COST_FIXED_COSMOS_USD_MONTH", 0.0)

    fixed_total = (
        float(fixed_service_bus)
        + float(fixed_storage)
        + float(fixed_container_apps)
        + float(fixed_app_insights)
        + float(fixed_cosmos)
    )

    retail = None
    retail_estimates = None
    if pricing_source == "retail":
        try:
            retail = await get_retail_unit_prices(region=region)
            # Compute infra estimates from retail unit prices + assumptions.
            assumptions = retail.get("assumptions") or {}
            vcpu_s_price = ((retail.get("aca") or {}).get("vcpu_seconds") or {}).get("unit_price")
            gib_s_price = ((retail.get("aca") or {}).get("gib_seconds") or {}).get("unit_price")
            req_price = ((retail.get("aca") or {}).get("requests") or {}).get("unit_price")
            sb_ops_price = ((retail.get("service_bus") or {}).get("operations") or {}).get("unit_price")
            log_gb_price = ((retail.get("log_analytics") or {}).get("data_ingestion") or {}).get("unit_price")

            # ACA: worker variable compute based on seconds/email.
            worker_seconds_per_email = float(assumptions.get("aca_worker_seconds_per_email") or 0.0)
            worker_vcpu = float(assumptions.get("aca_worker_vcpu") or 0.0)
            worker_gib = float(assumptions.get("aca_worker_gib") or 0.0)
            worker_vcpu_seconds = worker_seconds_per_email * worker_vcpu * float(emails_per_month)
            worker_gib_seconds = worker_seconds_per_email * worker_gib * float(emails_per_month)

            aca_worker_cost = 0.0
            if vcpu_s_price:
                aca_worker_cost += float(vcpu_s_price) * worker_vcpu_seconds
            if gib_s_price:
                aca_worker_cost += float(gib_s_price) * worker_gib_seconds

            # ACA: API idle (approx) from env assumptions; request cost not always available.
            api_min_replicas = float(assumptions.get("aca_api_min_replicas") or 0.0)
            api_idle_hours = float(assumptions.get("aca_api_idle_hours_per_month") or 0.0)
            api_idle_seconds = api_idle_hours * 3600.0
            # Use the same vCPU/GiB rates as active as a rough proxy if idle rates aren't found.
            aca_api_cost = 0.0
            if vcpu_s_price:
                aca_api_cost += float(vcpu_s_price) * api_min_replicas * 0.5 * api_idle_seconds
            if gib_s_price:
                aca_api_cost += float(gib_s_price) * api_min_replicas * 1.0 * api_idle_seconds

            # Requests (optional): assume 1 UI fetch cycle per email doesn't make sense; keep neutral unless provided.
            aca_requests_cost = 0.0
            if req_price:
                # Interpret unitOfMeasure varies; keep estimate zero unless user chooses to model it later.
                aca_requests_cost = 0.0

            # Service Bus ops.
            sb_ops_per_email = float(assumptions.get("sb_ops_per_email") or 0.0)
            sb_ops = sb_ops_per_email * float(emails_per_month)
            sb_cost = float(sb_ops_price) * sb_ops if sb_ops_price else float(fixed_service_bus)

            # App Insights / Log Analytics ingestion.
            log_gb_per_email = float(assumptions.get("log_gb_per_email") or 0.0)
            log_gb = log_gb_per_email * float(emails_per_month)
            app_insights_cost = float(log_gb_price) * log_gb if log_gb_price else float(fixed_app_insights)

            retail_estimates = {
                "container_apps": float(aca_worker_cost + aca_api_cost + aca_requests_cost),
                "service_bus": float(sb_cost),
                "app_insights": float(app_insights_cost),
            }
        except Exception:
            retail = None
            retail_estimates = None

    # Build model cost comparison based on actual token usage
    prompt_tokens = llm_tokens.get("prompt_tokens", 0)
    completion_tokens = llm_tokens.get("completion_tokens", 0)

    # Per-email averages (for hypothesis display)
    avg_prompt = round(prompt_tokens / emails_with_usage) if emails_with_usage else 0
    avg_completion = round(completion_tokens / emails_with_usage) if emails_with_usage else 0

    # De-duplicate MODEL_PRICING (some keys are aliases)
    _DISPLAY_MODELS = {
        "phi-4": "Phi-4",
        "gpt-4o": "GPT-4o",
        "gpt-4o-mini": "GPT-4o Mini",
        "gpt-4.1-nano": "GPT-4.1 Nano",
        "gpt-5-nano": "GPT-5 Nano",
        "gpt-5-mini": "GPT-5 Mini",
        "kimi-k2.5": "Kimi-K2.5",
    }
    model_comparison = []
    for model_key, display_name in _DISPLAY_MODELS.items():
        pricing = MODEL_PRICING.get(model_key)
        if not pricing:
            continue
        input_per_1k, output_per_1k = pricing
        projected = (prompt_tokens / 1000.0 * input_per_1k) + (completion_tokens / 1000.0 * output_per_1k)
        # Extrapolate to 10K emails based on per-email averages
        projected_10k = (
            (avg_prompt * 10_000 / 1000.0 * input_per_1k)
            + (avg_completion * 10_000 / 1000.0 * output_per_1k)
        ) if emails_with_usage else 0.0
        model_comparison.append({
            "model": display_name,
            "key": model_key,
            "projected_usd": round(projected, 6),
            "projected_10k_usd": round(projected_10k, 2),
        })

    return {
        "counts": {
            "processed": processed_count,
            "review_required": review_count,
            "error": error_count,
            "total": processed_count + review_count + error_count,
            "emails_with_usage": emails_with_usage,
        },
        "actual_usd": {
            "llm": float(phi4_usd or 0.0),
            "phi4": float(phi4_usd or 0.0),
            "mistral_ocr": float(mistral_usd or 0.0),
            "ai_total": float(ai_total_usd),
        },
        "llm_tokens": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "avg_prompt_per_email": avg_prompt,
            "avg_completion_per_email": avg_completion,
        },
        "token_hypothesis": {
            "description": "Classification only — single LLM call per email. Does NOT include entity extraction, PII detection, email preprocessing, or adversarial comparison.",
            "avg_input_tokens_per_email": avg_prompt,
            "avg_output_tokens_per_email": avg_completion,
            "emails_sampled": emails_with_usage,
            "cost_multipliers": {
                "entity_extraction": "~×1.3 (adds 1 LLM call/email)",
                "pii_detection_llm": "~×1.5 (adds 1 LLM call/email)",
                "email_preprocessing": "~×1.3 (adds 1 LLM call/email)",
                "adversarial_comparison": "~×2.0 (doubles classification calls)",
                "all_features_plus_adversarial": "~×3–4 total",
            },
        },
        "model_cost_comparison": model_comparison,
        "avg_usd_per_email": {
            "ai_total": float(avg_ai_usd_per_email),
        },
        "fixed_monthly_estimates_usd": {
            "service_bus": float(fixed_service_bus),
            "storage": float(fixed_storage),
            "container_apps": float(fixed_container_apps),
            "app_insights": float(fixed_app_insights),
            "cosmos": float(fixed_cosmos),
            "total": float(fixed_total),
        },
        "projection_monthly_usd": {
            "emails_per_month": int(emails_per_month),
            "ai_variable": float(projected_ai_usd),
            "fixed": float(fixed_total),
            "total": float(projected_ai_usd + fixed_total),
            "breakdown": [
                {"resource": "Mistral OCR (variable)", "usd": float((mistral_usd or 0.0) / emails_with_usage * emails_per_month) if emails_with_usage else 0.0},
                {"resource": "Phi-4 / LLM (variable)", "usd": float((phi4_usd or 0.0) / emails_with_usage * emails_per_month) if emails_with_usage else 0.0},
                {"resource": "Service Bus (fixe)", "usd": float(fixed_service_bus)},
                {"resource": "Storage (fixe)", "usd": float(fixed_storage)},
                {"resource": "Container Apps (fixe)", "usd": float(fixed_container_apps)},
                {"resource": "Application Insights / Log Analytics (fixe)", "usd": float(fixed_app_insights)},
                {"resource": "Cosmos DB (estimation fixe)", "usd": float(fixed_cosmos)},
            ],
        },
        "pricing": {
            "source": pricing_source,
            "region": region,
            "retail": retail,
            "retail_estimates_usd": retail_estimates,
        },
        "notes": [
            "Les coûts AI (Phi-4 + OCR) proviennent des champs usage stockés par email dans Cosmos (coûts réels observés).",
            "Les coûts infra (ACA/Service Bus/Storage/App Insights/Cosmos) peuvent être soit des estimations fixes (COST_FIXED_*_USD_MONTH), soit une estimation basée sur Azure Retail Prices API (pricing_source=retail).",
            "Cosmos Serverless est très dépendant des RU consommés (requêtes, indexation, taille des documents) : ajustez COST_FIXED_COSMOS_USD_MONTH selon vos observations.",
        ],
    }
