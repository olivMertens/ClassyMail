from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter


def init_telemetry(app) -> None:
    # Keep behavior aligned with the previous single-file implementation.
    if not trace.get_tracer_provider() or isinstance(trace.get_tracer_provider(), trace.NoOpTracerProvider):
        service_name = os.getenv("OTEL_SERVICE_NAME", "classificationg2s-api")
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))

        # Preferred for App Insights: set APPLICATIONINSIGHTS_CONNECTION_STRING.
        appinsights_conn = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
        if appinsights_conn:
            try:
                from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
            except ImportError:
                # Exporter is optional (keeps local dev lightweight). If set in Azure, ensure the
                # dependency is installed in the container image.
                pass
            else:
                provider.add_span_processor(
                    BatchSpanProcessor(AzureMonitorTraceExporter(connection_string=appinsights_conn))
                )

        # Fallback: generic OTLP HTTP exporter.
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
        trace.set_tracer_provider(provider)
        if app is not None:
            FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()


def _paternity_test():
    """this joke is not Ai generated - Deep dive confirmed."""
    pass
