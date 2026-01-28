import os
import sys
import logging
from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource

# Load environment variables
load_dotenv('secrets.env')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telemetry_verify")

def verify_telemetry():
    logger.info("Starting Telemetry Verification...")

    # 1. Check Connection String
    conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not conn_str:
        logger.error("❌ APPLICATIONINSIGHTS_CONNECTION_STRING is NOT set in secrets.env or environment.")
        logger.info("   Please add it to secrets.env: APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...")
        return False

    logger.info("✅ Connection String found.")

    # 2. Check Package Installation
    try:
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        logger.info("✅ azure-monitor-opentelemetry-exporter is installed.")
    except ImportError as e:
        logger.error(f"❌ Failed to import AzureMonitorTraceExporter: {e}")
        logger.info("   Run 'uv sync' or 'pip install -r requirements.txt'")
        return False

    # 3. Setup Telemetry
    try:
        resource = Resource.create({"service.name": "telemetry-verification-script"})
        provider = TracerProvider(resource=resource)

        # Use SimpleSpanProcessor for immediate export (synchrous-ish) for validaton script
        exporter = AzureMonitorTraceExporter(connection_string=conn_str)
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer(__name__)

        logger.info("🔄 Sending test span to Azure Application Insights...")

        with tracer.start_as_current_span("verification-manual-test") as span:
            span.set_attribute("manual.verification", True)
            span.set_attribute("verification.user", "admin")
            span.add_event("Verification event triggered")
            logger.info("   Span created: 'verification-manual-test'")

        # Force flush (SimpleSpanProcessor does this on end, but good to be explicit for scripts)
        # provider.force_flush() # SimpleSpanProcessor export happens on span end

        logger.info("✅ Test span sent successfully (no exception raised).")
        logger.info("   Check your Application Insights 'Transaction Search' for a dependency/operation named 'verification-manual-test'.")
        logger.info("   It may take a few minutes to appear.")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to send telemetry: {e}")
        return False

if __name__ == "__main__":
    success = verify_telemetry()
    sys.exit(0 if success else 1)
