"""Observability: distributed tracing, metrics, and logging for ClassyMail.

Supports two tiers:

  1. **Full distro** (``azure-monitor-opentelemetry``): Application Map,
     Agents View, GenAI tracing, Live Metrics — preferred in production.
  2. **Exporter-only fallback** (``azure-monitor-opentelemetry-exporter``):
     trace-only, for lighter local-dev setups.

Set ``APPLICATIONINSIGHTS_CONNECTION_STRING`` to enable Azure Monitor.

Application Map
~~~~~~~~~~~~~~~
Each Container App sets ``OTEL_SERVICE_NAME`` (``classymail-api`` /
``classymail-worker``) and ``OTEL_RESOURCE_ATTRIBUTES`` with
``service.namespace=classymail`` so that Application Map groups both roles
under one logical application and shows the dependency topology
(Service Bus, Cosmos DB, AI Foundry, Storage).

Agents View  (Preview)
~~~~~~~~~~~~~~~~~~~~~~
Enable GenAI tracing via ``AZURE_MONITOR_ENABLE_GENAI_TRACES=true``.
The LLM pipeline already emits ``gen_ai.*`` span attributes (system,
operation, model, token usage) following the OpenTelemetry GenAI Semantic
Conventions.  The Agents View surfaces these spans in Application Insights
→ **Agents (Preview)**.
"""
from __future__ import annotations

import logging
import os
import socket

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resource builder (cloud role name + namespace + instance for App Map)
# ---------------------------------------------------------------------------

def _build_resource() -> Resource:
    """Build an OTel ``Resource`` with service identity for Application Map.

    Application Map uses:
    * ``service.name``      → cloud role name  (classymail-api / classymail-worker)
    * ``service.namespace`` → groups components under one logical application
    * ``service.instance.id`` → differentiates replicas (hostname by default)

    Extra attributes from ``OTEL_RESOURCE_ATTRIBUTES`` are merged in.
    """
    service_name = os.getenv("OTEL_SERVICE_NAME", "classymail-api")
    instance_id = os.getenv("OTEL_SERVICE_INSTANCE_ID", socket.gethostname())

    # Parse extra resource attributes (e.g. "service.namespace=classymail,deployment.env=prod")
    extra: dict[str, str] = {}
    for pair in os.getenv("OTEL_RESOURCE_ATTRIBUTES", "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            extra[k.strip()] = v.strip()

    return Resource.create({
        "service.name": service_name,
        "service.namespace": extra.pop("service.namespace", "classymail"),
        "service.instance.id": instance_id,
        **extra,
    })


# ---------------------------------------------------------------------------
# Tier 1 — Full distro  (Application Map + Agents View + Live Metrics)
# ---------------------------------------------------------------------------

def _try_configure_distro(conn_str: str, resource: Resource) -> bool:
    """Attempt to use ``azure-monitor-opentelemetry`` (the full distro).

    Returns *True* on success so the caller can skip the manual fallback.
    """
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=conn_str,
            enable_live_metrics=True,
            logger_name="",
        )
        logger.info(
            "Azure Monitor OpenTelemetry distro enabled "
            "(Application Map + Agents View + Live Metrics)"
        )
        return True
    except ImportError:
        return False
    except Exception as exc:
        logger.warning("azure-monitor-opentelemetry distro init failed, falling back: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Tier 2 — Exporter-only  (trace-only, no metrics/logs/live-metrics)
# ---------------------------------------------------------------------------

def _fallback_exporter(conn_str: str, resource: Resource) -> None:
    """Manual TracerProvider + LoggerProvider + Azure Monitor exporters (fallback)."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=resource)

    try:
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

        provider.add_span_processor(
            BatchSpanProcessor(AzureMonitorTraceExporter(connection_string=conn_str))
        )
        logger.info("Azure Monitor Trace Exporter enabled (exporter-only mode)")
    except ImportError:
        logger.warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING is set but "
            "'azure-monitor-opentelemetry-exporter' is missing — no telemetry will be sent."
        )
    except Exception as exc:
        logger.error("AzureMonitorTraceExporter init failed: %s", exc)

    # Log exporter so Python logs appear in App Insights → Traces
    try:
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter
        from opentelemetry._logs import set_logger_provider

        log_provider = LoggerProvider(resource=resource)
        log_provider.add_log_record_processor(
            BatchLogRecordProcessor(AzureMonitorLogExporter(connection_string=conn_str))
        )
        set_logger_provider(log_provider)

        otel_handler = LoggingHandler(level=logging.INFO, logger_provider=log_provider)
        logging.getLogger().addHandler(otel_handler)
        logger.info("Azure Monitor Log Exporter enabled (fallback mode)")
    except ImportError:
        logger.warning("AzureMonitorLogExporter not available — logs will not be sent to App Insights")
    except Exception as exc:
        logger.error("AzureMonitorLogExporter init failed: %s", exc)

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))

    trace.set_tracer_provider(provider)


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def init_telemetry(app=None) -> None:
    """Initialise OpenTelemetry for ClassyMail.

    Attempts the full ``azure-monitor-opentelemetry`` distro first
    (Application Map, Agents View, Live Metrics, GenAI traces).
    Falls back to the trace-only exporter when the distro is absent.

    Args:
        app: Optional FastAPI instance to instrument (pass ``None`` for the
             standalone worker process).
    """
    # Guard against double-init (tests, lifespan re-entrance, worker inside API)
    if not isinstance(trace.get_tracer_provider(), trace.NoOpTracerProvider):
        return

    resource = _build_resource()
    conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    used_distro = False

    if conn_str:
        used_distro = _try_configure_distro(conn_str, resource)
        if not used_distro:
            _fallback_exporter(conn_str, resource)
    else:
        # No connection string — local dev; set up a bare provider for spans
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider(resource=resource)
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
        trace.set_tracer_provider(provider)

    # Instrument the existing FastAPI app instance.
    # (The distro patches the class but may miss an already-created instance.)
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
        except Exception:
            pass

    # HTTPX: manual instrumentation only in fallback mode (the distro handles it)
    if not used_distro:
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
        except Exception:
            pass
