import logging
from typing import Any
from uuid import UUID

import grpc

from app.auth.jwt_validator import JwtValidator
from app.auth.models import UserRole
from app.errors import AppError
from app.grpc.generated import media_asset_pb2, media_asset_pb2_grpc
from app.media.service import MediaService

logger = logging.getLogger(__name__)

AUTHORIZATION_METADATA_KEY = "authorization"


class MediaAssetGrpcService(media_asset_pb2_grpc.MediaAssetServiceServicer):
    """gRPC service that exposes internal media asset metadata."""

    def __init__(
        self,
        media_service: MediaService,
        jwt_validator: JwtValidator,
    ) -> None:
        """Create the internal gRPC service.

        Args:
            media_service: Application service that reads metadata from MinIO.
            jwt_validator: JWT validator shared with HTTP endpoints.
        """
        self._media_service = media_service
        self._jwt_validator = jwt_validator

    async def GetAssetMetadata(self, request, context):
        """Return authorized metadata for an asset."""
        user = await self._authenticate(context)

        try:
            asset_id = UUID(request.asset_id)
        except ValueError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "asset_id must be a valid UUID.",
            )
            raise RuntimeError("gRPC abort did not stop execution.")

        try:
            metadata = self._media_service.get_metadata(asset_id)
        except AppError as exc:
            await self._abort_app_error(context, exc)
            raise RuntimeError("gRPC abort did not stop execution.")
        except Exception as exc:
            logger.exception("Unexpected error while reading asset metadata: %s", exc)
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Unable to read asset metadata.",
            )
            raise RuntimeError("gRPC abort did not stop execution.")

        if metadata.owner_user_id != user.subject and user.role != UserRole.ADMIN:
            await context.abort(
                grpc.StatusCode.PERMISSION_DENIED,
                "The asset is not accessible for this user.",
            )
            raise RuntimeError("gRPC abort did not stop execution.")

        return media_asset_pb2.AssetMetadataResponse(
            asset_id=metadata.asset_id,
            asset_type=get_asset_type_value(metadata.asset_type),
            owner_user_id=metadata.owner_user_id,
            content_type=metadata.content_type,
            size_bytes=metadata.size_bytes,
            exists=True,
        )

    async def _authenticate(self, context):
        authorization_header = extract_authorization_metadata(
            context.invocation_metadata(),
        )
        try:
            return self._jwt_validator.validate_authorization_header(
                authorization_header,
            )
        except AppError as exc:
            if exc.status_code >= 500:
                logger.error("JWT validation failed for gRPC metadata: %s", exc.message)
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Missing or invalid authorization token.",
            )
            raise RuntimeError("gRPC abort did not stop execution.")

    @staticmethod
    async def _abort_app_error(context, exc: AppError) -> None:
        if exc.status_code == 404:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Asset not found.")
            return
        if exc.status_code == 503:
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "Media storage is unavailable.",
            )
            return

        logger.error(
            "Unexpected controlled error in gRPC metadata lookup: %s",
            {
                "code": exc.code,
                "status_code": exc.status_code,
            },
        )
        await context.abort(
            grpc.StatusCode.INTERNAL,
            "Unable to read asset metadata.",
        )


def extract_authorization_metadata(metadata: Any) -> str | None:
    """Extract Authorization metadata from a gRPC invocation.

    Args:
        metadata: gRPC metadata sequence.

    Returns:
        Authorization value if present.
    """
    for item in metadata or ():
        key = getattr(item, "key", None)
        value = getattr(item, "value", None)
        if key is None and isinstance(item, tuple) and len(item) == 2:
            key, value = item

        if not isinstance(key, str) or key.lower() != AUTHORIZATION_METADATA_KEY:
            continue

        if isinstance(value, bytes):
            return value.decode("utf-8")
        if isinstance(value, str):
            return value

    return None


def get_asset_type_value(asset_type: Any) -> str:
    """Return the string value for enum or string asset types."""
    value = getattr(asset_type, "value", asset_type)
    return str(value)


def create_media_asset_grpc_server(
    media_service: MediaService,
    jwt_validator: JwtValidator,
    port: int,
):
    """Create the internal MediaAssetService gRPC server."""
    server = grpc.aio.server()
    media_asset_pb2_grpc.add_MediaAssetServiceServicer_to_server(
        MediaAssetGrpcService(media_service, jwt_validator),
        server,
    )
    server.add_insecure_port(f"[::]:{port}")
    return server
