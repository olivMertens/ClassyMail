"""
Monitoring and metrics collection for the application.

Provides insights into queue health, processing rates, and system performance.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.management import ServiceBusAdministrationClient
from azure.core.credentials import TokenCredential

from classificationg2s.core import config

logger = logging.getLogger(__name__)


async def get_queue_metrics(
    sb_client: ServiceBusClient | None = None,
    credential: TokenCredential | None = None,
) -> dict[str, Any]:
    """
    Gets Service Bus queue metrics including message counts.

    Returns:
        Dictionary with queue metrics:
        - active_message_count: Messages in main queue
        - dead_letter_count: Messages in DLQ
        - scheduled_message_count: Scheduled messages
        - transfer_message_count: Messages in transfer queue
        - total_message_count: Total across all queues
    """
    if not config.SERVICE_BUS_FQDN or not config.SERVICE_BUS_QUEUE:
        logger.warning("Service Bus configuration missing, returning empty metrics")
        return {
            "active_message_count": 0,
            "dead_letter_count": 0,
            "scheduled_message_count": 0,
            "transfer_message_count": 0,
            "total_message_count": 0,
            "error": "Service Bus not configured",
        }

    try:
        # Use management client to get queue properties
        from azure.identity import DefaultAzureCredential
        if credential is None:
            credential = DefaultAzureCredential()

        # Management client requires full namespace URL
        fully_qualified_namespace = config.SERVICE_BUS_FQDN

        # Create management client
        mgmt_client = ServiceBusAdministrationClient(
            fully_qualified_namespace=fully_qualified_namespace,
            credential=credential,
        )

        # Get queue runtime properties
        queue_props = mgmt_client.get_queue_runtime_properties(config.SERVICE_BUS_QUEUE)

        metrics = {
            "active_message_count": queue_props.active_message_count,
            "dead_letter_count": queue_props.dead_letter_message_count,
            "scheduled_message_count": queue_props.scheduled_message_count,
            "transfer_message_count": queue_props.transfer_message_count,
            "total_message_count": queue_props.total_message_count,
            "size_in_bytes": queue_props.size_in_bytes,
            "updated_at": queue_props.updated_at_utc.isoformat() if queue_props.updated_at_utc else None,
        }

        mgmt_client.close()
        return metrics

    except Exception as e:
        logger.exception("Failed to get queue metrics")
        return {
            "active_message_count": 0,
            "dead_letter_count": 0,
            "scheduled_message_count": 0,
            "transfer_message_count": 0,
            "total_message_count": 0,
            "error": str(e),
        }


def calculate_processing_rate(
    processed_count: int,
    start_time: datetime,
    end_time: datetime | None = None,
) -> dict[str, Any]:
    """
    Calculates processing rate metrics.

    Args:
        processed_count: Number of items processed
        start_time: Start of measurement period
        end_time: End of measurement period (defaults to now)

    Returns:
        Dictionary with rate metrics:
        - items_per_second: Processing rate
        - items_per_minute: Processing rate per minute
        - items_per_hour: Processing rate per hour
        - duration_seconds: Measurement period
    """
    if end_time is None:
        end_time = datetime.now(timezone.utc)

    duration = (end_time - start_time).total_seconds()
    if duration <= 0:
        return {
            "items_per_second": 0.0,
            "items_per_minute": 0.0,
            "items_per_hour": 0.0,
            "duration_seconds": 0.0,
        }

    items_per_second = processed_count / duration

    return {
        "items_per_second": round(items_per_second, 2),
        "items_per_minute": round(items_per_second * 60, 2),
        "items_per_hour": round(items_per_second * 3600, 2),
        "duration_seconds": round(duration, 2),
    }


def get_system_health_score(
    queue_metrics: dict[str, Any],
    error_count: int = 0,
    total_count: int = 0,
) -> dict[str, Any]:
    """
    Calculates overall system health score (0-100).

    Factors:
    - Queue backlog (active messages)
    - Dead letter queue size
    - Error rate
    - Processing success rate

    Returns:
        Dictionary with health score and status
    """
    score = 100.0

    # Penalize for queue backlog
    active_count = queue_metrics.get("active_message_count", 0)
    if active_count > 100:
        score -= min(30, (active_count - 100) / 10)  # Max -30 points

    # Penalize for DLQ messages
    dlq_count = queue_metrics.get("dead_letter_count", 0)
    if dlq_count > 0:
        score -= min(20, dlq_count)  # Max -20 points

    # Penalize for error rate
    if total_count > 0:
        error_rate = error_count / total_count
        score -= error_rate * 50  # Max -50 points

    score = max(0, score)

    # Determine status
    if score >= 90:
        status = "healthy"
    elif score >= 70:
        status = "degraded"
    elif score >= 50:
        status = "unhealthy"
    else:
        status = "critical"

    return {
        "score": round(score, 1),
        "status": status,
        "factors": {
            "queue_backlog": active_count,
            "dead_letter_count": dlq_count,
            "error_rate": round(error_rate * 100, 2) if total_count > 0 else 0,
        },
    }
