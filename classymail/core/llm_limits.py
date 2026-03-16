"""
Per-model rate limiting for LLM calls (RPM/TPM).

- RPM enforced via aiolimiter.AsyncLimiter
- TPM (best-effort) via simple leaky bucket token accounting (1-minute window)
"""
from __future__ import annotations

import time
import asyncio
from typing import Dict
from aiolimiter import AsyncLimiter

from classymail.core import config

# Default limits per model (RPM)
DEFAULT_RPM = 60
MODEL_RPM: Dict[str, int] = {
    "mistral": getattr(config, "MISTRAL_RPM", 30),
    "phi": getattr(config, "PHI_RPM", 60),
    "chat": getattr(config, "CHAT_RPM", 60),
}

# Token per minute budgets (best-effort)
MODEL_TPM: Dict[str, int] = {
    "mistral": getattr(config, "MISTRAL_TPM", 60000),
    "phi": getattr(config, "PHI_TPM", 80000),
    "chat": getattr(config, "CHAT_TPM", 80000),
}

_limiters: Dict[str, AsyncLimiter] = {}
_tpm_state: Dict[str, Dict[str, float]] = {}
_tpm_lock = asyncio.Lock()


def _get_limiter(model_key: str) -> AsyncLimiter:
    rpm = MODEL_RPM.get(model_key, DEFAULT_RPM)
    if rpm <= 0:
        rpm = DEFAULT_RPM
    if model_key not in _limiters:
        _limiters[model_key] = AsyncLimiter(rpm, time_period=60)
    return _limiters[model_key]


def _tokens_available(model_key: str, tokens: int) -> bool:
    tpm_budget = MODEL_TPM.get(model_key)
    if not tpm_budget:
        return True
    state = _tpm_state.setdefault(model_key, {"window_start": time.time(), "used": 0})
    now = time.time()
    if now - state["window_start"] >= 60:
        state["window_start"] = now
        state["used"] = 0
    return (state["used"] + tokens) <= tpm_budget


def _consume_tokens(model_key: str, tokens: int) -> None:
    state = _tpm_state.setdefault(model_key, {"window_start": time.time(), "used": 0})
    state["used"] += tokens


class LlmRateLimiter:
    def __init__(self, model_key: str):
        self.model_key = model_key
        self.limiter = _get_limiter(model_key)

    async def __aenter__(self):
        await self.limiter.acquire()
        # TPM best-effort handled externally via consume_if_allowed

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def consume_if_allowed(self, tokens: int) -> bool:
        async with _tpm_lock:
            if not _tokens_available(self.model_key, tokens):
                return False
            _consume_tokens(self.model_key, tokens)
            return True


def get_limiter(model_key: str) -> LlmRateLimiter:
    return LlmRateLimiter(model_key)
