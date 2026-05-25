from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AssetType(str, Enum):
    """Supported media asset types."""

    PROFILE_IMAGE = "PROFILE_IMAGE"
    AUDIO = "AUDIO"
    TRACK_COVER = "TRACK_COVER"
    ALBUM_COVER = "ALBUM_COVER"
    PLAYLIST_COVER = "PLAYLIST_COVER"


class HealthResponse(BaseModel):
    """Health response returned by Media Service endpoints."""

    status: str = Field(..., description="Service health status")
    service: str | None = Field(default=None, description="Service name")


class AssetUploadResponse(BaseModel):
    """Response returned after a successful media upload."""

    asset_id: str = Field(..., alias="assetId")
    asset_type: AssetType = Field(..., alias="assetType")
    content_type: str = Field(..., alias="contentType")
    size_bytes: int = Field(..., alias="sizeBytes")
    duration_seconds: float | None = Field(default=None, alias="durationSeconds")

    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)


class AssetMetadataResponse(BaseModel):
    """Metadata stored as MinIO object metadata for an asset."""

    asset_id: str = Field(..., alias="assetId")
    asset_type: AssetType = Field(..., alias="assetType")
    owner_user_id: str = Field(..., alias="ownerUserId")
    content_type: str = Field(..., alias="contentType")
    size_bytes: int = Field(..., alias="sizeBytes")
    duration_seconds: float | None = Field(default=None, alias="durationSeconds")
    original_filename: str = Field(..., alias="originalFilename")
    exists: bool

    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)
