import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Controlled application error translated into a REST response."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        """Create a controlled application error.

        Args:
            status_code: HTTP status code.
            code: Stable error code.
            message: Client-safe error message.
            details: Optional client-safe details.
        """
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def utc_timestamp() -> str:
    """Return the current UTC timestamp formatted for JSON responses."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """Handle controlled application errors."""
    log_payload = {
        "code": exc.code,
        "message": exc.message,
        "status_code": exc.status_code,
        "details": exc.details,
    }
    if exc.status_code >= 500:
        logger.error("Handled application error: %s", log_payload)
    else:
        logger.warning("Handled application error: %s", log_payload)

    payload: dict[str, Any] = {
        "error": exc.code,
        "message": exc.message,
        "statusCode": exc.status_code,
        "timestamp": utc_timestamp(),
    }
    if exc.details is not None:
        payload["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=payload)


async def validation_error_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle FastAPI request validation errors."""
    logger.warning("Request validation failed: %s", exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "error": "ValidationError",
            "message": "Request validation failed.",
            "statusCode": 422,
            "details": exc.errors(),
            "timestamp": utc_timestamp(),
        },
    )


async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected errors without exposing internal details."""
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred.",
            "statusCode": 500,
            "timestamp": utc_timestamp(),
        },
    )
