import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
PUBLIC_ERROR_MESSAGES = {
    "conflict_or_state_changed": "El contenido cambio y no se pudo completar la accion. Intenta nuevamente.",
    "dependency_validation_failed": "No se pudo validar la informacion relacionada con esta accion. Intenta nuevamente.",
    "invalid_input": "La solicitud no cumple con el formato esperado.",
    "network_unreachable": "No se pudo conectar. Revisa tu conexion e intentalo de nuevo.",
    "request_timeout": "La solicitud tardo demasiado y no se pudo completar. Intenta nuevamente.",
    "resource_not_found": "El contenido solicitado ya no esta disponible.",
    "service_temporarily_unavailable": "Esta funcion no esta disponible en este momento. Intenta de nuevo mas tarde.",
    "unauthorized": "Tu sesion expiro. Inicia sesion nuevamente.",
    "unexpected_operation_failure": "No se pudo completar la accion en este momento. Intenta de nuevo mas tarde.",
    "forbidden": "No tienes permisos para esta accion.",
}


def flatten_details(details: Any | None) -> dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    return details


def normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def contains_internal_markers(message: str | None) -> bool:
    normalized = normalize_text(message)
    return any(
        marker in normalized
        for marker in (
            "jwks",
            "grpc",
            "rabbitmq",
            "minio",
            "prisma",
            "postgres",
            "mongodb",
            "redis",
            "identity service",
            "catalog service",
            "media service",
            "analytics service",
            "streaming service",
            "live service",
            "database",
        )
    )


def infer_public_code(status_code: int, error_code: str, message: str) -> str:
    if error_code == "ACCOUNT_BANNED" or error_code == "AccountBannedException":
        return "ACCOUNT_BANNED"
    normalized = f"{normalize_text(error_code)} {normalize_text(message)}"
    if any(marker in normalized for marker in ("timeout", "deadline exceeded", "tardo demasiado")):
        return "request_timeout"
    if any(marker in normalized for marker in ("serviceunavailable", "unavailable", "no esta disponible temporalmente")):
        return "service_temporarily_unavailable"
    if any(marker in normalized for marker in ("no pudo validar", "no es accesible", "dependency")):
        return "dependency_validation_failed"
    if any(marker in normalized for marker in ("conflict", "changed")):
        return "conflict_or_state_changed"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "resource_not_found"
    if status_code in (408, 504):
        return "request_timeout"
    if status_code == 409:
        return "conflict_or_state_changed"
    if status_code in (400, 422):
        return "invalid_input"
    if status_code >= 500:
        return "service_temporarily_unavailable"
    return "unexpected_operation_failure"


def resolve_public_message(public_code: str, raw_message: str) -> str:
    if public_code == "ACCOUNT_BANNED":
        return raw_message
    if not raw_message or contains_internal_markers(raw_message):
        return PUBLIC_ERROR_MESSAGES[public_code]
    return raw_message


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
    public_code = infer_public_code(exc.status_code, exc.code, exc.message)
    public_message = resolve_public_message(public_code, exc.message)
    log_payload = {
        "code": exc.code,
        "public_code": public_code,
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
        "code": public_code,
        **flatten_details(exc.details),
        "message": public_message,
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
            "code": "invalid_input",
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
            "code": "unexpected_operation_failure",
            "message": PUBLIC_ERROR_MESSAGES["unexpected_operation_failure"],
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
