"""
LLM API Compatibility Layer

Handles differences between model families (GPT-4.x, GPT-5.x, o-series)
for Azure OpenAI Chat Completions API parameters.

GPT-5 and o-series are reasoning models that:
- Reject ``temperature`` and ``top_p`` parameters
- Require ``max_completion_tokens`` instead of ``max_tokens``
"""

from __future__ import annotations

# Model families that use reasoning and have restricted API parameters.
# These models reject ``temperature`` / ``top_p`` and require
# ``max_completion_tokens`` instead of the legacy ``max_tokens``.
_REASONING_FAMILIES: tuple[str, ...] = ("o1", "o3", "o4", "gpt-5", "gpt5", "kimi")


def is_reasoning_model(deployment: str) -> bool:
    """Return *True* if *deployment* is a reasoning model.

    Reasoning models (o1, o3, o4-mini, GPT-5.x including nano/mini):
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
    deployment: str,
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

    Usage::

        payload = {
            "model": deployment,
            "messages": [...],
            **build_chat_params(deployment, temperature=0.0, max_output_tokens=2000),
        }
    """
    params: dict = {}
    reasoning = is_reasoning_model(deployment)
    # model-router may route to a reasoning model; use max_completion_tokens
    # (accepted by all modern Azure OpenAI models) for safety.
    is_router = deployment and deployment.lower().strip() == "model-router"

    if max_output_tokens is not None:
        if reasoning or is_router:
            params["max_completion_tokens"] = max_output_tokens
        else:
            params["max_tokens"] = max_output_tokens

    if temperature is not None and not reasoning:
        params["temperature"] = temperature

    return params


def extract_message_content(message: dict) -> str | None:
    """Extract text content from a chat completion message.

    Some reasoning models (Kimi-K2.5, certain o-series) return their
    output in ``reasoning_content`` instead of ``content``.  This helper
    checks both fields and returns whichever is non-empty.
    """
    return message.get("content") or message.get("reasoning_content")


def supports_response_format(deployment: str) -> bool:
    """Return *True* if the model supports ``response_format: json_object``.

    Reasoning models (o1, o3, o4, GPT-5.x, Kimi) do **not** support
    the ``response_format`` API parameter.  They must be instructed via
    the system prompt to return JSON instead.

    ``model-router`` may route to a reasoning model, so it is treated
    as unsupported to avoid runtime failures.
    """
    if not deployment:
        return True
    if deployment.lower().strip() == "model-router":
        return False
    return not is_reasoning_model(deployment)
