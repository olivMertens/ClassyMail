from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from classymail.core.paths import project_root
from classymail.core.telemetry import init_telemetry
from classymail.core import config
from classymail.core.rate_limit import limiter
from classymail.core.middleware import RequestContextMiddleware
from classymail.core.errors import AppError, error_handler
from classymail.services.azure_clients import Clients, set_default_clients
from classymail.services.worker import worker_loop_forever
from classymail.services.settings_store import load_settings

from classymail.api.routers.health import router as health_router
from classymail.api.routers.ui import router as ui_router
from classymail.api.routers.settings import router as settings_router
from classymail.api.routers.upload import router as upload_router
from classymail.api.routers.emails import router as emails_router
from classymail.api.routers.webhook import router as webhook_router
from classymail.api.routers.costs import router as costs_router
from classymail.api.routers.docs import router as docs_router
from classymail.api.routers.admin import router as admin_router
from classymail.api.routers.chat import router as chat_router
from classymail.api.category_assessment import router as category_assessment_router


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
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

    yield  # Application running

    # Shutdown logic
    if task := getattr(app.state, "worker_task", None):
        task.cancel()
    if clients := getattr(app.state, "clients", None):
        await clients.close()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Add request context middleware for distributed tracing
    app.add_middleware(RequestContextMiddleware)

    # Add global error handler
    app.add_exception_handler(AppError, error_handler)
    app.add_exception_handler(Exception, error_handler)

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
    app.include_router(chat_router)
    app.include_router(category_assessment_router)
    # UI router must be last to handle catch-all for SPA
    app.include_router(ui_router)

    return app


app = create_app()
