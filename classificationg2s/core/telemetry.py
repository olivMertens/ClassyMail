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
        provider = TracerProvider(resource=Resource.create({"service.name": "classificationg2s-api"}))
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
