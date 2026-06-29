"""Admin diagnostics — UI config, version, diagnostics, env validation, metrics."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from classymail.core import config
from classymail.core.monitoring import get_queue_metrics, get_system_health_score
from classymail.services.azure_clients import Clients, get_clients, readiness_checks
from classymail.services.repository import get_latest_errors, get_stats_summary
import logging
import os

router = APIRouter()
logger = logging.getLogger("ClassyMail.admin")


class UIConfigResponse(BaseModel):
    show_info_modal: bool
    show_developer_tab: bool
    organization_name: str | None = None
    environment: str | None = None
    chat_enabled: bool = False
    chat_streaming: bool = False
    assessment_enabled: bool = False
    commit_sha: str | None = None
    build_timestamp: str | None = None


class QueueMetricsResponse(BaseModel):
    """Queue metrics response."""
    active_message_count: int
    dead_letter_count: int
    scheduled_message_count: int
    transfer_message_count: int
    total_message_count: int
    size_in_bytes: int | None = None
    updated_at: str | None = None
    error: str | None = None


class HealthScoreResponse(BaseModel):
    """System health score response."""
    score: float
    status: str
    factors: dict


class DiagnosticsResponse(BaseModel):
    env: dict
    readiness: dict
    ok: bool


@router.get("/ui-config", response_model=UIConfigResponse)
async def get_ui_config():
    """Returns UI feature flags based on environment variables."""
    return UIConfigResponse(
        show_info_modal=config.UI_SHOW_INFO_MODAL,
        show_developer_tab=config.UI_SHOW_DEVELOPER_TAB,
        organization_name=getattr(config, "ORGANIZATION_NAME", None),
        environment=getattr(config, "AZURE_ENV", None),
        chat_enabled=bool(getattr(config, "CHAT_DEPLOYMENT", None) and getattr(config, "EMBEDDING_DEPLOYMENT", None)),
        chat_streaming=bool(getattr(config, "CHAT_STREAMING", False)),
        assessment_enabled=bool(getattr(config, "PHI_ENDPOINT", None)),
        commit_sha=os.getenv("COMMIT_SHA"),
        build_timestamp=os.getenv("BUILD_TIMESTAMP"),
    )


@router.get("/version")
async def version():
    env_version = os.getenv("APP_VERSION")
    return {"version": env_version or "unknown"}


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def diagnostics(clients: Clients = Depends(get_clients)):
    ok, readiness = await readiness_checks(clients=clients, deep=True)
    env = {
        "subscription_id": os.getenv("AZURE_SUBSCRIPTION_ID"),
        "tenant_id": os.getenv("AZURE_TENANT_ID"),
        "resource_group": os.getenv("AZURE_RESOURCE_GROUP"),
        "app_version": os.getenv("APP_VERSION"),
        "service_bus_fqdn": config.SERVICE_BUS_FQDN,
        "service_bus_queue": config.SERVICE_BUS_QUEUE,
        "storage_account_url": config.BLOB_ACCOUNT_URL,
        "storage_container": config.BLOB_CONTAINER_INPUT,
        "cosmos_endpoint": config.COSMOS_ENDPOINT,
        "cosmos_db": config.COSMOS_DB,
        "cosmos_container": config.COSMOS_CONTAINER,
        "cosmos_query_max_limit": getattr(config, "COSMOS_QUERY_MAX_LIMIT", None),
        "ai_endpoint": config.MISTRAL_ENDPOINT or config.PHI_ENDPOINT,
        "mistral_deployment": config.MISTRAL_DEPLOYMENT,
        "phi_deployment": config.PHI_DEPLOYMENT,
        "chat_deployment": config.CHAT_DEPLOYMENT,
    }
    return DiagnosticsResponse(env=env, readiness=readiness, ok=ok)


@router.get("/validate-aca-env")
async def validate_aca_environment():
    """
    Validate Azure Container Apps environment variables.
    Returns status of required and optional variables for operational visibility.
    """
    try:
        required_vars = [
            "AZURE_CLIENT_ID",
            "COSMOS_ENDPOINT",
            "COSMOS_DATABASE_NAME",
            "COSMOS_CONTAINER_NAME",
            "COSMOS_CHAT_CONTAINER",
            "STORAGE_ACCOUNT_NAME",
            "CONTAINER_NAME_PDF",
            "SERVICE_BUS_FQDN",
            "QUEUE_NAME_PDF",
            "AI_ENDPOINT",
            "AI_API_VERSION",
            "PHI_DEPLOYMENT",
            "PHI_FALLBACK_DEPLOYMENT",
            "MISTRAL_DEPLOYMENT",
            "MISTRAL_MODE",
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "LOG_ANALYTICS_WORKSPACE_ID",
            "OTEL_SERVICE_NAME"
        ]

        optional_vars = [
            "AZURE_LANGUAGE_ENDPOINT",
            "CHAT_DEPLOYMENT",
            "GPT_DEPLOYMENT",
            "OCR_DEPLOYMENT",
            "UI_SHOW_INFO_MODAL",
            "UI_SHOW_DEVELOPER_TAB",
            "ORGANIZATION_NAME"
        ]

        def check_var(var_name: str) -> dict:
            value = os.getenv(var_name)
            present = value is not None and value != ""
            masked_value = None
            if present and value:
                masked_value = value[:20] + "..." if len(value) > 20 else value
            return {
                "name": var_name,
                "present": present,
                "value": masked_value
            }

        required_status = [check_var(var) for var in required_vars]
        optional_status = [check_var(var) for var in optional_vars]

        all_required_present = all(item["present"] for item in required_status)
        missing_required = [item["name"] for item in required_status if not item["present"]]

        return {
            "status": "ok" if all_required_present else "missing_required",
            "required": required_status,
            "optional": optional_status,
            "all_required_present": all_required_present,
            "missing_required": missing_required,
            "summary": {
                "required_count": len(required_vars),
                "required_present": sum(1 for item in required_status if item["present"]),
                "optional_count": len(optional_vars),
                "optional_present": sum(1 for item in optional_status if item["present"])
            }
        }
    except Exception as e:
        logger.error(f"ACA environment validation failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/metrics/queue", response_model=QueueMetricsResponse)
async def queue_metrics(clients: Clients = Depends(get_clients)):
    """Get Service Bus queue metrics including message counts."""
    metrics = await get_queue_metrics(
        sb_client=clients.sb_client,
        credential=clients.credential,
    )
    return QueueMetricsResponse(**metrics)


@router.get("/metrics/health", response_model=HealthScoreResponse)
async def health_score(clients: Clients = Depends(get_clients)):
    """Get overall system health score (0-100)."""
    queue_metrics_data = await get_queue_metrics(
        sb_client=clients.sb_client,
        credential=clients.credential,
    )

    try:
        errors = await get_latest_errors(limit=100, clients=clients)
        error_count = len(errors)
    except Exception:
        error_count = 0

    try:
        stats = await get_stats_summary(clients=clients)
        total_count = stats.get("total", 0)
    except Exception:
        total_count = 0

    health = get_system_health_score(
        queue_metrics=queue_metrics_data,
        error_count=error_count,
        total_count=max(total_count, 1),
    )

    return HealthScoreResponse(**health)
