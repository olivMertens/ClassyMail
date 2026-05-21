"""Shared factory for Azure OpenAI chat completion clients.

Returns cached ``openai.AsyncAzureOpenAI`` instances per
``(endpoint, api_version)`` pair so that connection pools and credential
refresh are reused across callers (orchestrator, specialized agents,
red team, anonymizer, PII detection, category assessment, etc.).

Authentication priority:
1. ``config.AI_API_KEY`` if set (dev / local with provided key).
2. ``DefaultAzureCredential`` via ``clients.credential`` (managed identity
   in Container Apps, az-cli login locally).

This module also exposes the small set of model-aware parameter
helpers (formerly in ``classymail.core.llm_compat``):

- :func:`is_reasoning_model` - GPT-5 / o1 / o3 / o4 / Kimi family detection.
- :func:`build_chat_params` - choose ``max_tokens`` vs ``max_completion_tokens``
  and drop ``temperature`` for reasoning models.
- :func:`extract_message_content` - prefer ``content`` then ``reasoning_content``.
- :func:`supports_response_format` - ``response_format=json_object`` gate.

Together with :func:`get_chat_client`, these form the canonical
replacement for the ``httpx.AsyncClient`` + ``auth_headers`` + manual
URL construction pattern that previously appeared in every LLM caller.
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

# ---------------------------------------------------------------------------
# Model family detection + parameter helpers
# ---------------------------------------------------------------------------

# Model families that use reasoning and have restricted API parameters.
# These models reject ``temperature`` / ``top_p`` and require
# ``max_completion_tokens`` instead of the legacy ``max_tokens``.
_REASONING_FAMILIES: tuple[str, ...] = ("o1", "o3", "o4", "gpt-5", "gpt5", "kimi")


def is_reasoning_model(deployment: str | None) -> bool:
    """Return ``True`` for reasoning models (GPT-5.x, o1, o3, o4, Kimi).

    Reasoning models:
    - Do **not** support ``temperature`` or ``top_p``
    - Require ``max_completion_tokens`` instead of ``max_tokens``
    - Do **not** support ``response_format: json_object``
    """
    if not deployment:
        return False
    d = deployment.lower().strip()
    for family in _REASONING_FAMILIES:
        if d == family or d.startswith(f"{family}-") or d.startswith(f"{family}."):
            return True
    return False


def build_chat_params(
    deployment: str | None,
    *,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
) -> dict:
    """Build model-aware chat completion parameters.

    For **reasoning** models (GPT-5.x, o1, o3, o4):
    - Uses ``max_completion_tokens`` instead of ``max_tokens``
    - Omits ``temperature`` / ``top_p`` (unsupported)

    For **classic** models (GPT-4o, Phi-4, Mistral, etc.):
    - Uses ``max_tokens``
    - Includes ``temperature`` when provided
    """
    params: dict = {}
    reasoning = is_reasoning_model(deployment)
    # model-router may route to a reasoning model; use max_completion_tokens
    # (accepted by all modern Azure OpenAI models) for safety.
    is_router = bool(deployment) and deployment.lower().strip() == "model-router"

    if max_output_tokens is not None:
        if reasoning or is_router:
            params["max_completion_tokens"] = max_output_tokens
        else:
            params["max_tokens"] = max_output_tokens

    if temperature is not None and not reasoning:
        params["temperature"] = temperature

    return params


def extract_message_content(message: dict | None) -> str | None:
    """Extract text content from a chat completion message.

    Some reasoning models (Kimi-K2.5, certain o-series) return their
    output in ``reasoning_content`` instead of ``content``.
    """
    if not message:
        return None
    return message.get("content") or message.get("reasoning_content")


def supports_response_format(deployment: str | None) -> bool:
    """Return ``True`` if the model supports ``response_format=json_object``."""
    if not deployment:
        return True
    if deployment.lower().strip() == "model-router":
        return False
    return not is_reasoning_model(deployment)


# ---------------------------------------------------------------------------
# Async Azure OpenAI client factory
# ---------------------------------------------------------------------------

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
