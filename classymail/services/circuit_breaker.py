"""
Circuit breaker patterns for external service calls.

Prevents cascading failures by failing fast when external services are unavailable.
Configured for AI endpoints (Mistral OCR, Azure OpenAI) with appropriate thresholds.
"""
from __future__ import annotations

import logging
from functools import wraps
from pybreaker import CircuitBreaker

logger = logging.getLogger(__name__)


class ManagedCircuitBreaker(CircuitBreaker):
    """CircuitBreaker subclass with explicit ``success()``/``failure()`` helpers.

    ``pybreaker.CircuitBreaker`` manages state internally via ``call()`` /
    ``call_async()``.  When pipeline code performs the call *outside* the
    breaker wrapper (e.g. inline ``await func(...)``), it needs a way to
    manually notify the breaker of the outcome.  ``success()`` resets the
    failure counter; ``failure()`` increments it so the breaker eventually
    trips.
    """

    def success(self) -> None:
        """Notify the breaker of a successful call (resets failure counter)."""
        self._state_storage.reset_counter()

    def failure(self) -> None:
        """Notify the breaker of a failed call (increments failure counter)."""
        self._inc_counter()


# Circuit breaker for Mistral OCR endpoint
# Fails after 5 consecutive errors, stays open for 60 seconds before retry
mistral_ocr_breaker = ManagedCircuitBreaker(
    fail_max=5,
    reset_timeout=60,
    name="mistral_ocr"
)

# Circuit breaker for Azure OpenAI classification endpoint
# More lenient since classification is less expensive than OCR
classification_breaker = ManagedCircuitBreaker(
    fail_max=7,
    reset_timeout=45,
    name="classification"
)

# Circuit breaker for chat/RAG endpoint
chat_breaker = ManagedCircuitBreaker(
    fail_max=5,
    reset_timeout=60,
    name="chat"
)

# Circuit breaker for Document Intelligence OCR fallback
doc_intelligence_breaker = ManagedCircuitBreaker(
    fail_max=5,
    reset_timeout=120,
    name="document_intelligence"
)


def should_trip_on_exception(exc: Exception) -> bool:
    """
    Determines if an exception should count towards circuit breaker failure count.

    We trip on:
    - 503 Service Unavailable (service down)
    - 429 Too Many Requests (rate limit exhausted)
    - Timeouts
    - Connection errors

    We don't trip on:
    - 400 Bad Request (our fault)
    - 401/403 Auth errors (config issue, not transient)
    - Validation errors
    """
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        # Trip on 503 (service unavailable) and 429 (rate limit)
        return exc.response.status_code in [503, 429, 502, 504]

    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True

    # For other exceptions, check error message
    error_str = str(exc).lower()
    if any(keyword in error_str for keyword in ["timeout", "connection", "unavailable", "rate limit"]):
        return True

    return False


def with_circuit_breaker(breaker: CircuitBreaker):
    """
    Decorator to apply circuit breaker to async functions.

    Usage:
        @with_circuit_breaker(mistral_ocr_breaker)
        async def call_mistral_api(...):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await breaker.call_async(func, *args, **kwargs)
            except Exception as exc:
                # Log circuit breaker state changes
                if breaker.current_state == "open":
                    logger.warning(
                        "Circuit breaker '%s' is OPEN - failing fast to prevent cascading failures",
                        breaker.name
                    )

                # Check if this exception should trip the breaker
                if should_trip_on_exception(exc):
                    logger.error(
                        "Circuit breaker '%s' failure %d/%d: %s",
                        breaker.name,
                        breaker.fail_counter,
                        breaker.fail_max,
                        exc
                    )

                raise
        return wrapper
    return decorator


# Convenience decorators for specific services
def with_ocr_circuit_breaker(func):
    """Apply OCR circuit breaker to function."""
    return with_circuit_breaker(mistral_ocr_breaker)(func)


def with_classification_circuit_breaker(func):
    """Apply classification circuit breaker to function."""
    return with_circuit_breaker(classification_breaker)(func)


def with_chat_circuit_breaker(func):
    """Apply chat circuit breaker to function."""
    return with_circuit_breaker(chat_breaker)(func)
