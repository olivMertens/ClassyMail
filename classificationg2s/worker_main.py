from __future__ import annotations

import asyncio
import logging
import os

from classificationg2s.core import config
from classificationg2s.core.telemetry import init_telemetry
from classificationg2s.services.azure_clients import Clients, set_default_clients
from classificationg2s.services.worker import worker_loop_forever

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# Silence noisy Azure logs
logging.getLogger("azure.servicebus").setLevel(logging.WARNING)
logging.getLogger("azure.core").setLevel(logging.WARNING)
logging.getLogger("uamqp").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)

def _mask(val: str | None) -> str | None:
    if not val:
        return val
    return val[:4] + "..." if len(val) > 8 else val


def log_startup_env() -> None:
    logger.info(
        "Config: SB_FQDN=%s SB_QUEUE=%s STORAGE=%s COSMOS=%s AI_EP=%s MISTRAL_DEPLOYMENT=%s PHI_DEPLOYMENT=%s APPINSIGHTS=%s",
        config.SERVICE_BUS_FQDN,
        config.SERVICE_BUS_QUEUE,
        config.BLOB_ACCOUNT_URL,
        config.COSMOS_ENDPOINT,
        config.MISTRAL_ENDPOINT or config.PHI_ENDPOINT,
        config.MISTRAL_DEPLOYMENT,
        config.PHI_DEPLOYMENT,
        bool(os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")),
    )


async def main():
    init_telemetry(None)
    logger.info(
        "Worker starting: queue=%s servicebus=%s storage=%s cosmos=%s ai=%s",
        config.SERVICE_BUS_QUEUE,
        config.SERVICE_BUS_FQDN,
        config.BLOB_ACCOUNT_URL,
        config.COSMOS_ENDPOINT,
        config.MISTRAL_ENDPOINT or config.PHI_ENDPOINT,
    )
    log_startup_env()
    clients = Clients()
    await clients.init()
    set_default_clients(clients)
    try:
        from classificationg2s.services.settings_store import load_settings_async
        await worker_loop_forever(
            clients=clients,
            queue_name=config.SERVICE_BUS_QUEUE,
            get_settings=lambda: load_settings_async(clients),
        )
    finally:
        await clients.close()


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
