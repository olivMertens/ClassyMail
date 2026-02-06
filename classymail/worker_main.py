from __future__ import annotations

import asyncio
import logging
import sys

from classymail.core import config
from classymail.core.telemetry import init_telemetry
from classymail.services.azure_clients import Clients, set_default_clients
from classymail.services.worker import worker_loop_forever

# Ensure all log output reaches container stdout/stderr so it appears in
# ``az containerapp logs show --type console``.  The Azure Monitor OTel
# distro adds its own handler for App Insights but does NOT add a
# StreamHandler, leaving container logs completely empty.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
# Reduce noise from azure SDK & OTel internals
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("opentelemetry").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def main():
    logger.info("worker_main starting…")

    # Initialise OpenTelemetry early so all worker spans (Service Bus receive,
    # OCR, classification, Cosmos writes) flow to Application Insights.
    # Enables Application Map topology and Agents View GenAI tracing.
    init_telemetry()

    clients = Clients()
    await clients.init()
    set_default_clients(clients)
    try:
        await worker_loop_forever(
            clients=clients,
            queue_name=config.SERVICE_BUS_QUEUE,
            get_settings=lambda: {},
        )
    finally:
        await clients.close()


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
