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
_REASONING_FAMILIES: tuple[str, ...] = ("o1", "o3", "o4", "gpt-5", "gpt5")


def is_reasoning_model(deployment: str) -> bool:
    """Return *True* if *deployment* is a reasoning model.

    Reasoning models (o1, o3, o4-mini, GPT-5.x):
    - Do **not** support ``temperature`` or ``top_p``
    - Require ``max_completion_tokens`` instead of ``max_tokens``
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

    if max_output_tokens is not None:
        if reasoning:
            params["max_completion_tokens"] = max_output_tokens
        else:
            params["max_tokens"] = max_output_tokens

    if temperature is not None and not reasoning:
        params["temperature"] = temperature

    return params
