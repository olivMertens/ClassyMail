"""
Standardized error handling for the application.

Provides consistent error responses and logging across all API endpoints.
"""
from __future__ import annotations

import logging
from typing import Any
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    """Standardized error detail structure."""
    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Standardized error response."""
    error: ErrorDetail
    status_code: int


class AppError(Exception):
    """Base application error with structured details."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class ValidationError(AppError):
    """Input validation error (400)."""
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, "VALIDATION_ERROR", 400, details)


class NotFoundError(AppError):
    """Resource not found error (404)."""
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, "NOT_FOUND", 404, details)


class AuthorizationError(AppError):
    """Authorization error (403)."""
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, "FORBIDDEN", 403, details)


class ServiceUnavailableError(AppError):
    """External service unavailable (503)."""
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, "SERVICE_UNAVAILABLE", 503, details)


class RateLimitError(AppError):
    """Rate limit exceeded (429)."""
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, "RATE_LIMIT_EXCEEDED", 429, details)


def create_error_response(
    error: AppError | HTTPException | Exception,
    request_id: str | None = None,
) -> JSONResponse:
    """
    Creates a standardized JSON error response.

    Args:
        error: The error to convert into a response
        request_id: Request ID for tracing

    Returns:
        JSONResponse with standardized error format
    """
    if isinstance(error, AppError):
        error_detail = ErrorDetail(
            code=error.code,
            message=error.message,
            details=error.details,
            request_id=request_id,
        )
        return JSONResponse(
            status_code=error.status_code,
            content={"error": error_detail.model_dump()},
        )

    elif isinstance(error, HTTPException):
        error_detail = ErrorDetail(
            code="HTTP_ERROR",
            message=str(error.detail),
            request_id=request_id,
        )
        return JSONResponse(
            status_code=error.status_code,
            content={"error": error_detail.model_dump()},
        )

    else:
        # Generic exception - log and return 500
        logger.exception("Unhandled exception", extra={"request_id": request_id})
        error_detail = ErrorDetail(
            code="INTERNAL_ERROR",
            message="An internal error occurred",
            request_id=request_id,
        )
        return JSONResponse(
            status_code=500,
            content={"error": error_detail.model_dump()},
        )


async def error_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global exception handler for FastAPI.

    Catches all exceptions and converts them to standardized responses.
    """
    request_id = getattr(request.state, "request_id", None)

    # Log with context
    logger.error(
        "Request error",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "error_type": type(exc).__name__,
        },
        exc_info=True,
    )

    return create_error_response(exc, request_id)
