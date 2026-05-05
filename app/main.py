import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.auth.jwt_validator import JwtValidator
from app.config import Settings, get_settings
from app.errors import (
    AppError,
    app_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.events.publisher import AssetEventPublisher, build_event_publisher
from app.media.routes import router as media_router
from app.media.service import MediaService
from app.storage.minio_client import MinioStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def create_app(
    settings: Settings | None = None,
    storage: MinioStorage | None = None,
    event_publisher: AssetEventPublisher | None = None,
    jwt_validator: JwtValidator | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional runtime settings for tests.
        storage: Optional storage adapter for tests.
        event_publisher: Optional publisher for tests.
        jwt_validator: Optional JWT validator for tests.

    Returns:
        Configured FastAPI application.
    """
    app_settings = settings or get_settings()
    app_storage = storage or MinioStorage.from_settings(app_settings)
    app_event_publisher = event_publisher or build_event_publisher(app_settings)
    app_jwt_validator = jwt_validator or JwtValidator(
        jwks_url=app_settings.jwt_jwks_url,
        issuer=app_settings.jwt_issuer,
        audience=app_settings.jwt_audience,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        app_storage.ensure_bucket()
        yield

    app = FastAPI(
        title="StreamButed Media Service",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.media_service = MediaService(
        settings=app_settings,
        storage=app_storage,
        event_publisher=app_event_publisher,
    )
    app.state.jwt_validator = app_jwt_validator

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.get("/health")
    async def internal_health() -> dict[str, str]:
        """Return internal service health."""
        return {"status": "UP"}

    app.include_router(media_router)
    return app
