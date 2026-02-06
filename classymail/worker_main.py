from __future__ import annotations

import asyncio

from classymail.core import config
from classymail.core.telemetry import init_telemetry
from classymail.services.azure_clients import Clients, set_default_clients
from classymail.services.worker import worker_loop_forever


async def main():
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
