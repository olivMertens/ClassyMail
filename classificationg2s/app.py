from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from classificationg2s.core.paths import project_root
from classificationg2s.core.telemetry import init_telemetry
from classificationg2s.core import config
from classificationg2s.services.azure_clients import Clients, set_default_clients
from classificationg2s.services.worker import worker_loop_forever
from classificationg2s.services.settings_store import load_settings

from classificationg2s.api.routers.health import router as health_router
from classificationg2s.api.routers.ui import router as ui_router
from classificationg2s.api.routers.settings import router as settings_router
from classificationg2s.api.routers.upload import router as upload_router
from classificationg2s.api.routers.emails import router as emails_router
from classificationg2s.api.routers.webhook import router as webhook_router
from classificationg2s.api.routers.costs import router as costs_router
from classificationg2s.api.routers.docs import router as docs_router
from classificationg2s.api.routers.admin import router as admin_router


def create_app() -> FastAPI:
    app = FastAPI()

    static_dir = project_root() / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.state.cost_overrides = {}

    app.include_router(health_router)
    app.include_router(docs_router)
    app.include_router(settings_router)
    app.include_router(upload_router)
    app.include_router(emails_router)
    app.include_router(webhook_router)
    app.include_router(costs_router)
    app.include_router(admin_router)
    # UI router must be last to handle catch-all for SPA
    app.include_router(ui_router)

    @app.on_event("startup")
    async def on_startup():
        missing_env: list[str] = []
        if not config.SERVICE_BUS_FQDN:
            missing_env.append("AZURE_SERVICE_BUS_FQDN")
        if not config.BLOB_ACCOUNT_URL:
            missing_env.append("AZURE_STORAGE_ACCOUNT_URL")
        if not config.COSMOS_ENDPOINT:
            missing_env.append("AZURE_COSMOS_ENDPOINT")
        if not config.MISTRAL_ENDPOINT:
            missing_env.append("MISTRAL_ENDPOINT")
        if not config.PHI_ENDPOINT:
            missing_env.append("PHI_ENDPOINT (or AZURE_AI_ENDPOINT)")
        if missing_env:
            raise RuntimeError(
                "Missing required environment variables: "
                + ", ".join(missing_env)
                + ". Load secrets.env first (see docs/LOCAL_RUN.md)."
            )

        init_telemetry(app)

        clients = Clients()
        await clients.init()
        app.state.clients = clients
        set_default_clients(clients)

        # Run worker inside API only when explicitly enabled (local dev convenience)
        if os.getenv("ENABLE_WORKER", "false").lower() in {"1", "true", "yes"}:
            app.state.worker_task = asyncio.create_task(
                worker_loop_forever(
                    clients=clients,
                    queue_name=config.SERVICE_BUS_QUEUE,
                    get_settings=load_settings,
                )
            )

    @app.on_event("shutdown")
    async def on_shutdown():
        if task := getattr(app.state, "worker_task", None):
            task.cancel()
        if clients := getattr(app.state, "clients", None):
            await clients.close()

    return app


app = create_app()
