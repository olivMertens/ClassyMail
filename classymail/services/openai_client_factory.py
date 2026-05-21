"""Shared factory for Azure OpenAI chat completion clients.

Returns cached ``openai.AsyncAzureOpenAI`` instances per
``(endpoint, api_version)`` pair so that connection pools and credential
refresh are reused across callers (orchestrator, specialized agents,
red team, etc.).

Authentication priority:
1. ``config.AI_API_KEY`` if set (dev / local with provided key).
2. ``DefaultAzureCredential`` via ``clients.credential`` (managed identity
   in Container Apps, az-cli login locally).

The factory is the canonical replacement for the
``httpx.AsyncClient`` + ``auth_headers`` + manual URL construction
pattern that previously appeared in every classification agent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from openai import AsyncAzureOpenAI

from classymail.core import config

if TYPE_CHECKING:
    from classymail.services.azure_clients import Clients

logger = logging.getLogger(__name__)

# (endpoint, api_version) -> client
_clients_by_endpoint: dict[tuple[str, str], AsyncAzureOpenAI] = {}
_lock = asyncio.Lock()


async def _build_client(endpoint: str, api_version: str, clients: "Clients") -> AsyncAzureOpenAI:
    """Create a new AsyncAzureOpenAI client for the given endpoint."""
    api_key = getattr(config, "AI_API_KEY", None)
    if api_key:
        return AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
            timeout=60.0,
            max_retries=2,
        )

    # Bearer-token mode via DefaultAzureCredential. We fetch the token
    # eagerly here (so the first call doesn't pay the cold-start cost)
    # and use an async token provider that re-fetches when needed.
    token = await clients.credential.get_token(config.AI_SCOPE)

    # Capture into a closure that always returns a valid token. The Azure
    # identity cache de-dupes calls, so this is cheap.
    async def _async_provider() -> str:
        tok = await clients.credential.get_token(config.AI_SCOPE)
        return tok.token

    _ = token  # keep eager fetch above for fail-fast behaviour

    return AsyncAzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=_async_provider,
        api_version=api_version,
        timeout=60.0,
        max_retries=2,
    )


async def get_chat_client(
    endpoint: str,
    api_version: str,
    *,
    clients: "Clients | None" = None,
) -> AsyncAzureOpenAI:
    """Return a cached AsyncAzureOpenAI client for (endpoint, api_version).

    Re-uses the same instance across callers — important for HTTP
    connection pooling. Safe to call concurrently.
    """
    from classymail.services.azure_clients import get_default_clients

    clients = clients or get_default_clients()
    key = (endpoint.rstrip("/"), api_version)

    existing = _clients_by_endpoint.get(key)
    if existing is not None:
        return existing

    async with _lock:
        existing = _clients_by_endpoint.get(key)
        if existing is not None:
            return existing
        client = await _build_client(key[0], key[1], clients)
        _clients_by_endpoint[key] = client
        logger.debug("Created AsyncAzureOpenAI client for %s (api=%s)", key[0], key[1])
        return client


async def reset_chat_clients() -> None:
    """Close and clear all cached clients (test helper)."""
    async with _lock:
        for c in _clients_by_endpoint.values():
            try:
                await c.close()
            except Exception:  # pragma: no cover - defensive cleanup
                pass
        _clients_by_endpoint.clear()
