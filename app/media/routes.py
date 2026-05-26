from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.auth.models import AuthenticatedUser, UserRole
from app.auth.jwt_validator import JwtValidator
from app.errors import AppError
from app.media.schemas import AssetMetadataResponse, AssetType, AssetUploadResponse
from app.media.service import MediaService

router = APIRouter(prefix="/api/v1/media", tags=["Media"])


def get_media_service(request: Request) -> MediaService:
    """Resolve the media service from application state."""
    return request.app.state.media_service


def get_jwt_validator(request: Request) -> JwtValidator:
    """Resolve the JWT validator from application state."""
    return request.app.state.jwt_validator


def get_current_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    validator: JwtValidator = Depends(get_jwt_validator),
) -> AuthenticatedUser:
    """Resolve the authenticated user from the Authorization header."""
    return validator.validate_authorization_header(authorization)


def assert_artist_role(user: AuthenticatedUser) -> None:
    """Require the authenticated user to be an artist."""
    if user.role != UserRole.ARTIST:
        raise AppError(
            403,
            "Forbidden",
            "Solo los artistas pueden subir este tipo de archivo.",
        )


@router.get("/health")
async def public_health() -> dict[str, str]:
    """Return public Media Service health for gateway checks."""
    return {"status": "UP", "service": "media-service"}


@router.post(
    "/profile-image",
    response_model=AssetUploadResponse,
    status_code=201,
)
async def upload_profile_image(
    file: Annotated[UploadFile, File(...)],
    current_user: AuthenticatedUser = Depends(get_current_user),
    media_service: MediaService = Depends(get_media_service),
) -> AssetUploadResponse:
    """Upload a profile image for any authenticated user."""
    return await media_service.upload_asset(
        file=file,
        asset_type=AssetType.PROFILE_IMAGE,
        owner=current_user,
    )


@router.post("/audio", response_model=AssetUploadResponse, status_code=201)
async def upload_audio(
    file: Annotated[UploadFile, File(...)],
    current_user: AuthenticatedUser = Depends(get_current_user),
    media_service: MediaService = Depends(get_media_service),
) -> AssetUploadResponse:
    """Upload an audio asset for an authenticated artist."""
    assert_artist_role(current_user)
    return await media_service.upload_asset(
        file=file,
        asset_type=AssetType.AUDIO,
        owner=current_user,
    )


@router.post("/images", response_model=AssetUploadResponse, status_code=201)
async def upload_catalog_image(
    file: Annotated[UploadFile, File(...)],
    usage: Annotated[str, Form(...)],
    current_user: AuthenticatedUser = Depends(get_current_user),
    media_service: MediaService = Depends(get_media_service),
) -> AssetUploadResponse:
    """Upload a reusable image asset for catalog or playlist covers."""
    try:
        asset_type = AssetType(usage.strip().upper())
    except ValueError as exc:
        raise AppError(
            400,
            "ValidationError",
            "usage debe ser TRACK_COVER, ALBUM_COVER o PLAYLIST_COVER.",
        ) from exc

    if asset_type not in {AssetType.TRACK_COVER, AssetType.ALBUM_COVER, AssetType.PLAYLIST_COVER}:
        raise AppError(
            400,
            "ValidationError",
            "usage debe ser TRACK_COVER, ALBUM_COVER o PLAYLIST_COVER.",
        )

    if asset_type in {AssetType.TRACK_COVER, AssetType.ALBUM_COVER}:
        assert_artist_role(current_user)

    return await media_service.upload_asset(
        file=file,
        asset_type=asset_type,
        owner=current_user,
    )


@router.get(
    "/assets/{asset_id}/metadata",
    response_model=AssetMetadataResponse,
)
async def get_asset_metadata(
    asset_id: UUID,
    media_service: MediaService = Depends(get_media_service),
) -> AssetMetadataResponse:
    """Return metadata for an asset stored in MinIO."""
    return media_service.get_metadata(asset_id)


@router.get("/assets/{asset_id}")
async def get_asset(
    asset_id: UUID,
    media_service: MediaService = Depends(get_media_service),
) -> StreamingResponse:
    """Stream an asset from MinIO by asset id."""
    metadata = media_service.get_metadata(asset_id)
    if metadata.asset_type in {AssetType.AUDIO, AssetType.AUDIO.value}:
        raise AppError(404, "AssetNotFound", "El archivo multimedia no existe o ya no esta disponible.")

    stored_object = media_service.open_asset(asset_id)
    return StreamingResponse(
        stored_object.content,
        media_type=stored_object.content_type,
        headers={"Content-Length": str(stored_object.size_bytes)},
    )
