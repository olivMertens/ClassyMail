from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Query

from classificationg2s.services.azure_clients import Clients, get_clients
from classificationg2s.services.repository import (
    count_by_status,
    sum_mistral_cost_usd,
    sum_phi4_cost_usd,
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
    clients: Clients = Depends(get_clients),
) -> dict[str, Any]:
    processed_count = await count_by_status("PROCESSED", clients=clients)
    review_count = await count_by_status("REVIEW_REQUIRED", clients=clients)
    error_count = await count_by_status("ERROR", clients=clients)

    phi4_usd = await sum_phi4_cost_usd(clients=clients)
    mistral_usd = await sum_mistral_cost_usd(clients=clients)

    emails_with_usage = await count_items_with_any_usage_cost(clients=clients)
    ai_total_usd = (phi4_usd or 0.0) + (mistral_usd or 0.0)

    avg_ai_usd_per_email = (ai_total_usd / emails_with_usage) if emails_with_usage else 0.0
    projected_ai_usd = avg_ai_usd_per_email * float(emails_per_month)

    # Fixed monthly estimates: keep them configurable because pricing varies by region and configuration.
    fixed_service_bus = _env_float("COST_FIXED_SERVICE_BUS_USD_MONTH", 9.0)
    fixed_storage = _env_float("COST_FIXED_STORAGE_USD_MONTH", 5.0)
    fixed_container_apps = _env_float("COST_FIXED_CONTAINER_APPS_USD_MONTH", 20.0)
    fixed_observability = _env_float("COST_FIXED_OBSERVABILITY_USD_MONTH", 0.0)
    fixed_cosmos = _env_float("COST_FIXED_COSMOS_USD_MONTH", 0.0)

    fixed_total = (
        float(fixed_service_bus)
        + float(fixed_storage)
        + float(fixed_container_apps)
        + float(fixed_observability)
        + float(fixed_cosmos)
    )

    return {
        "counts": {
            "processed": processed_count,
            "review_required": review_count,
            "error": error_count,
            "total": processed_count + review_count + error_count,
            "emails_with_usage": emails_with_usage,
        },
        "actual_usd": {
            "phi4": float(phi4_usd or 0.0),
            "mistral_ocr": float(mistral_usd or 0.0),
            "ai_total": float(ai_total_usd),
        },
        "avg_usd_per_email": {
            "ai_total": float(avg_ai_usd_per_email),
        },
        "fixed_monthly_estimates_usd": {
            "service_bus": float(fixed_service_bus),
            "storage": float(fixed_storage),
            "container_apps": float(fixed_container_apps),
            "observability": float(fixed_observability),
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
                {"resource": "Observabilité (fixe)", "usd": float(fixed_observability)},
                {"resource": "Cosmos DB (estimation fixe)", "usd": float(fixed_cosmos)},
            ],
        },
        "notes": [
            "Les coûts AI (Phi-4 + OCR) proviennent des champs usage stockés par email dans Cosmos (coûts réels observés).",
            "Les coûts infra (Service Bus/Storage/Container Apps/Observabilité/Cosmos) sont des estimations configurables via variables d’environnement COST_FIXED_*_USD_MONTH.",
            "Cosmos Serverless est très dépendant des RU consommés (requêtes, indexation, taille des documents) : ajustez COST_FIXED_COSMOS_USD_MONTH selon vos observations.",
        ],
    }
