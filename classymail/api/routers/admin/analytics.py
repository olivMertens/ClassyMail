"""Admin analytics — search, errors, stats, intents, telemetry, deadletter, deployments."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from classymail.core import config
from classymail.services.azure_clients import Clients, get_clients, blob_id_from_url
from classymail.services.repository import (
    search_email_records,
    get_latest_errors,
    get_stats_summary,
    get_top_intents,
    get_low_confidence_items,
    get_processing_stats_by_day,
)
from classymail.services.messages import extract_blob_url
from azure.servicebus import ServiceBusSubQueue
from azure.monitor.query.aio import LogsQueryClient
from azure.monitor.query import LogsQueryStatus
import logging
import json
from datetime import datetime, timedelta

router = APIRouter()
logger = logging.getLogger("ClassyMail.admin")


class SearchResponse(BaseModel):
    items: list[dict]


class ErrorsResponse(BaseModel):
    items: list[dict]


class StatsSummaryResponse(BaseModel):
    total: int
    pending: int
    processing: int
    processed: int
    error: int
    review_required: int
    average_confidence: float


class IntentsResponse(BaseModel):
    items: list[dict]


class LowConfidenceResponse(BaseModel):
    items: list[dict]


class AppInsightLog(BaseModel):
    timestamp: datetime
    message: str
    severity_level: int | None
    type: str
    properties: dict | None


class LogsResponse(BaseModel):
    items: list[AppInsightLog]


# Re-use DeadLetterMessage from data_ops to avoid duplication
from classymail.api.routers.admin.data_ops import DeadLetterMessage, DeadLetterSummary  # noqa: E402


@router.get("/search", response_model=SearchResponse)
async def search_emails(q: str, limit: int = 5, clients: Clients = Depends(get_clients)):
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query too short")
    limit = min(max(limit, 1), config.COSMOS_QUERY_MAX_LIMIT)
    items = await search_email_records(q, limit=limit, clients=clients)
    return SearchResponse(items=items)


@router.get("/errors/latest", response_model=ErrorsResponse)
async def latest_errors(limit: int = 5, clients: Clients = Depends(get_clients)):
    limit = min(max(limit, 1), config.COSMOS_QUERY_MAX_LIMIT)
    items = await get_latest_errors(limit=limit, clients=clients)
    return ErrorsResponse(items=items)


@router.get("/stats/summary", response_model=StatsSummaryResponse)
async def stats_summary(clients: Clients = Depends(get_clients)):
    summary = await get_stats_summary(clients=clients)
    return StatsSummaryResponse(**summary)


@router.get("/stats/processing")
async def processing_stats(days: int = 7, clients: Clients = Depends(get_clients)):
    days = max(1, min(days, 30))
    stats = await get_processing_stats_by_day(days=days, clients=clients)
    return stats


@router.get("/intents/top", response_model=IntentsResponse)
async def top_intents(limit: int = 5, clients: Clients = Depends(get_clients)):
    limit = min(max(limit, 1), config.COSMOS_QUERY_MAX_LIMIT)
    items = await get_top_intents(limit=limit, clients=clients)
    return IntentsResponse(items=items)


@router.get("/low-confidence", response_model=LowConfidenceResponse)
async def low_confidence(limit: int = 5, intent: str | None = None, clients: Clients = Depends(get_clients)):
    limit = min(max(limit, 1), config.COSMOS_QUERY_MAX_LIMIT)
    items = await get_low_confidence_items(limit=limit, intent=intent, clients=clients)
    return LowConfidenceResponse(items=items)


@router.get("/telemetry/logs", response_model=LogsResponse)
async def get_app_insights_logs(days: int = 1, limit: int = 50, clients: Clients = Depends(get_clients)):
    """Fetches recent traces and exceptions from Application Insights via Log Analytics."""
    workspace_id = config.LOG_ANALYTICS_WORKSPACE_ID
    if not workspace_id:
        logger.warning("LOG_ANALYTICS_WORKSPACE_ID not set. Cannot fetch logs.")
        return LogsResponse(items=[])

    try:
        query = f"""
        union AppTraces, AppExceptions
        | where TimeGenerated > ago({days}d)
        | project TimeGenerated, Message, SeverityLevel, Type, Properties
        | order by TimeGenerated desc
        | take {limit}
        """

        async with LogsQueryClient(clients.credential) as client:
            response = await client.query_workspace(
                workspace_id=workspace_id,
                query=query,
                timespan=timedelta(days=days)
            )

        if response.status == LogsQueryStatus.FAILURE:
            logger.error(f"Logs query failed: {response.partial_error}")
            raise HTTPException(status_code=502, detail="Logs query failed")

        logs = []
        for table in response.tables:
            for row in table.rows:
                data = {c.name: row[i] for i, c in enumerate(table.columns)}

                props = data.get("Properties")
                if isinstance(props, str) and props:
                    try:
                        props = json.loads(props)
                    except ValueError:
                        pass
                elif not isinstance(props, dict):
                    props = {}

                logs.append(AppInsightLog(
                    timestamp=data["TimeGenerated"],
                    message=data.get("Message") or "No message",
                    severity_level=data.get("SeverityLevel"),
                    type=data.get("Type"),
                    properties=props
                ))

        return LogsResponse(items=logs)

    except Exception as e:
        logger.error(f"Failed to query Log Analytics: {e}")
        return LogsResponse(items=[])


@router.get("/deadletter", response_model=DeadLetterSummary)
async def deadletter_summary(clients: Clients = Depends(get_clients)):
    """Peek the dead-letter queue and return a summary for admin UI."""
    if not clients.sb_client:
        raise HTTPException(status_code=503, detail="Service Bus client not initialized")

    try:
        messages: list[DeadLetterMessage] = []
        async with clients.sb_client.get_queue_receiver(
            queue_name=config.SERVICE_BUS_QUEUE,
            sub_queue=ServiceBusSubQueue.DEAD_LETTER,
            max_wait_time=5,
        ) as receiver:
            peeked = await receiver.peek_messages(max_message_count=10)
            for m in peeked:
                body_bytes = b"".join([b for b in m.body])
                try:
                    payload = json.loads(body_bytes.decode())
                except Exception:
                    payload = {"raw": body_bytes.decode(errors="ignore")}
                blob_url = extract_blob_url(payload)
                blob_id = blob_id_from_url(blob_url) if blob_url else None
                processing_log = None
                cosmos_status = None
                cosmos_error = None
                cosmos_error_stage = None
                if blob_id:
                    try:
                        await clients.ensure_cosmos_container()
                        doc = await clients.cosmos_container.read_item(item=blob_id, partition_key=blob_id)
                        processing_log = doc.get("processing_log")
                        cosmos_status = doc.get("status")
                        cosmos_error = doc.get("error")
                        cosmos_error_stage = doc.get("error_stage")
                    except Exception:
                        pass

                app_props = getattr(m, "application_properties", None)
                if app_props:
                    app_props = {
                        (k.decode() if isinstance(k, bytes) else str(k)):
                        (v.decode() if isinstance(v, bytes) else v)
                        for k, v in app_props.items()
                    }

                try:
                    body_preview = body_bytes.decode(errors="replace")[:500]
                except Exception:
                    body_preview = None

                messages.append(
                    DeadLetterMessage(
                        message_id=getattr(m, "message_id", None),
                        delivery_count=getattr(m, "delivery_count", None),
                        dead_letter_reason=getattr(m, "dead_letter_reason", None),
                        dead_letter_error_description=getattr(m, "dead_letter_error_description", None),
                        dead_letter_source=getattr(m, "dead_letter_source", None),
                        blob_url=blob_url,
                        blob_id=blob_id,
                        enqueued_time_utc=getattr(m, "enqueued_time_utc", None),
                        sequence_number=getattr(m, "sequence_number", None),
                        content_type=getattr(m, "content_type", None),
                        subject=getattr(m, "subject", None),
                        correlation_id=getattr(m, "correlation_id", None),
                        application_properties=app_props,
                        body_preview=body_preview,
                        cosmos_status=cosmos_status,
                        cosmos_error=cosmos_error,
                        cosmos_error_stage=cosmos_error_stage,
                        processing_log=processing_log,
                    )
                )
    except Exception as ex:
        logger.exception("Failed to peek dead-letter queue: %s", ex)
        raise HTTPException(status_code=500, detail=f"Failed to peek dead-letter queue: {ex}") from ex

    return DeadLetterSummary(count=len(messages), messages=messages)


@router.get("/deployments")
async def list_deployments(clients: Clients = Depends(get_clients)):
    """List OpenAI model deployments available on the configured Azure AI endpoint."""
    import httpx
    from classymail.services.azure_clients import auth_headers

    endpoint = config.PHI_ENDPOINT
    if not endpoint:
        raise HTTPException(
            status_code=503,
            detail="PHI_ENDPOINT / AZURE_AI_ENDPOINT not configured.",
        )

    url = f"{endpoint.rstrip('/')}/openai/deployments?api-version={config.AI_API_VERSION}"
    headers = await auth_headers(clients, model_type="openai")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error("Failed to list deployments: %s %s", exc.response.status_code, exc.response.text[:300])
        raise HTTPException(
            status_code=502,
            detail=f"Azure AI returned {exc.response.status_code}",
        )
    except Exception as exc:
        logger.error("Failed to list deployments: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    data = resp.json()
    deployments = data.get("data", [])

    return {
        "deployments": [
            {
                "id": d.get("id", ""),
                "model": d.get("model", ""),
                "status": d.get("status", ""),
            }
            for d in deployments
            if d.get("status") == "succeeded"
        ],
    }
