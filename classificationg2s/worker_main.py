from __future__ import annotations

import asyncio

from classificationg2s.core import config
from classificationg2s.services.azure_clients import Clients, set_default_clients
from classificationg2s.services.worker import worker_loop_forever


async def main():
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
