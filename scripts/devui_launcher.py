"""Local DevUI launcher for ClassyMail chat agent.

Provides an interactive debugging UI (http://localhost:8080) wrapping the
production ``ClassyMailChatAgent`` so we can exercise tool calls, system
prompt, and grounding behavior without going through the FastAPI + Vue
front-end.

Usage:
    uv run python scripts/devui_launcher.py
    # add --port 9000 to change port

Notes:
    * Dev-only — relies on ``agent-framework-devui`` (pre-release) which is
      pinned in the ``dev`` dependency group. Never imported by production
      code (``classymail/app.py`` and ``classymail/worker_main.py``).
    * Requires the same env vars as the API (CHAT_ENDPOINT,
      AZURE_OPENAI_API_KEY or DefaultAzureCredential, ...).
    * Tools that touch Cosmos/Blob/Service Bus still resolve via
      ``Clients.create()`` exactly like in production.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("classymail.devui")


def _build_agent():
    """Build the same Agent the production chat service uses, with a Clients
    instance bound to the ContextVar before each tool call."""
    from classymail.services import chat_agent as ca
    from classymail.services.azure_clients import Clients

    agent_service = ca.agent  # singleton ClassyMailChatAgent
    inner = agent_service._get_or_create_agent("en")
    if inner is None:
        raise RuntimeError(
            "Chat agent not configured. Set CHAT_ENDPOINT (and AZURE_OPENAI_API_KEY "
            "or run with a credential that can hit it) before launching DevUI."
        )

    # Bind Clients once for the DevUI session so tool functions can call
    # _current_clients() the same way they do under FastAPI.
    clients = asyncio.get_event_loop().run_until_complete(Clients.create())
    ca._clients_ctx.set(clients)
    logger.info("Bound Clients to ContextVar for DevUI session.")
    return inner


def main() -> int:
    parser = argparse.ArgumentParser(description="ClassyMail DevUI launcher")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port (default 8080)")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open the browser")
    args = parser.parse_args()

    try:
        from agent_framework.devui import serve  # type: ignore
    except ImportError:
        try:
            from agent_framework_devui import serve  # type: ignore
        except ImportError:
            logger.error(
                "agent-framework-devui is not installed. Run: uv sync --group dev"
            )
            return 1

    agent = _build_agent()
    logger.info("Launching DevUI on http://localhost:%d", args.port)
    serve(entities=[agent], port=args.port, auto_open=not args.no_open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
