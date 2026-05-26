import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def flatten_details(details: Any | None) -> dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    return details


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
        **flatten_details(exc.details),
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
    details = sanitize_validation_errors(exc.errors())
    logger.warning("Request validation failed: %s", details)
    return JSONResponse(
        status_code=422,
        content={
            "error": "ValidationError",
            "message": "La solicitud no cumple con el formato esperado.",
            "statusCode": 422,
            "details": details,
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
            "message": "Ocurrio un error interno. Intenta de nuevo mas tarde.",
            "statusCode": 500,
            "timestamp": utc_timestamp(),
        },
    )


def sanitize_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert validation errors into client-safe Spanish details."""
    sanitized_errors: list[dict[str, Any]] = []
    for error in errors:
        sanitized_error = dict(error)
        context = sanitized_error.get("ctx")
        if isinstance(context, dict):
            sanitized_context = dict(context)
            context_error = sanitized_context.get("error")
            if context_error is not None:
                sanitized_context["error"] = str(context_error)
            sanitized_error["ctx"] = sanitized_context
        sanitized_error["msg"] = spanish_validation_message(sanitized_error)
        sanitized_errors.append(sanitized_error)
    return sanitized_errors


def spanish_validation_message(error: dict[str, Any]) -> str:
    """Return a generic Spanish validation message without leaking internals."""
    error_type = str(error.get("type") or "")
    context = error.get("ctx")
    if error_type == "value_error" and isinstance(context, dict) and context.get("error"):
        return str(context["error"])
    if "missing" in error_type:
        return "El campo es obligatorio."
    if "uuid" in error_type:
        return "El valor debe ser un UUID valido."
    if "greater_than" in error_type:
        return "El valor debe ser mayor al minimo permitido."
    if "less_than" in error_type:
        return "El valor debe ser menor al maximo permitido."
    if "string_too_short" in error_type:
        return "El texto es demasiado corto."
    if "string_too_long" in error_type:
        return "El texto es demasiado largo."
    return "El valor no cumple con el formato esperado."
