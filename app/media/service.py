from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

from fastapi import UploadFile
try:
    from mutagen import File as MutagenFile
except ImportError:  # pragma: no cover - production image installs mutagen.
    MutagenFile = None

from app.auth.models import AuthenticatedUser
from app.config import Settings
from app.events.publisher import AssetEventPublisher
from app.media.schemas import AssetMetadataResponse, AssetType, AssetUploadResponse
from app.media.validation import validate_audio_upload, validate_image_upload
from app.storage.minio_client import MinioStorage, StoredAssetMetadata


class MediaService:
    """Coordinates validation, storage, metadata, and event publishing."""

    def __init__(
        self,
        settings: Settings,
        storage: MinioStorage,
        event_publisher: AssetEventPublisher,
    ) -> None:
        """Create a media service.

        Args:
            settings: Runtime application settings.
            storage: Binary storage adapter.
            event_publisher: Best-effort asset event publisher.
        """
        self._settings = settings
        self._storage = storage
        self._event_publisher = event_publisher

    async def upload_asset(
        self,
        file: UploadFile,
        asset_type: AssetType,
        owner: AuthenticatedUser,
    ) -> AssetUploadResponse:
        """Validate and store an asset.

        Args:
            file: Uploaded file.
            asset_type: Asset type to assign.
            owner: Authenticated owner.

        Returns:
            Basic upload metadata.
        """
        if asset_type == AssetType.AUDIO:
            upload = await validate_audio_upload(
                file,
                self._settings.max_audio_size_bytes,
            )
            duration_seconds = extract_audio_duration_seconds(upload.content)
        else:
            upload = await validate_image_upload(
                file,
                self._settings.max_image_size_bytes,
            )
            duration_seconds = None

        asset_id = uuid4()
        uploaded_at = utc_now()
        metadata = StoredAssetMetadata(
            asset_id=str(asset_id),
            asset_type=asset_type,
            owner_user_id=owner.subject,
            content_type=upload.content_type,
            size_bytes=upload.size_bytes,
            duration_seconds=duration_seconds,
            original_filename=upload.original_filename,
            uploaded_at=uploaded_at,
        )

        self._storage.upload_asset(asset_id, upload.content, metadata)
        self._event_publisher.publish_asset_ready(
            build_asset_ready_event(metadata, uploaded_at),
        )

        return AssetUploadResponse(
            assetId=str(asset_id),
            assetType=asset_type,
            contentType=metadata.content_type,
            sizeBytes=metadata.size_bytes,
            durationSeconds=metadata.duration_seconds,
        )

    def get_metadata(self, asset_id: UUID) -> AssetMetadataResponse:
        """Return asset metadata from storage.

        Args:
            asset_id: Asset UUID.

        Returns:
            Stored asset metadata.
        """
        metadata = self._storage.get_metadata(asset_id)
        return AssetMetadataResponse(
            assetId=metadata.asset_id,
            assetType=metadata.asset_type,
            ownerUserId=metadata.owner_user_id,
            contentType=metadata.content_type,
            sizeBytes=metadata.size_bytes,
            durationSeconds=metadata.duration_seconds,
            originalFilename=metadata.original_filename,
            exists=True,
        )

    def open_asset(self, asset_id: UUID):
        """Open an asset stream from storage.

        Args:
            asset_id: Asset UUID.

        Returns:
            Storage-backed object stream.
        """
        return self._storage.open_asset(asset_id)


def utc_now() -> str:
    """Return the current UTC timestamp for metadata and events."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_asset_ready_event(
    metadata: StoredAssetMetadata,
    occurred_at: str,
) -> dict[str, Any]:
    """Build a media.asset.ready event payload.

    Args:
        metadata: Stored asset metadata.
        occurred_at: Event timestamp.

    Returns:
        Event payload ready to publish.
    """
    return {
        "eventId": str(uuid4()),
        "eventType": "media.asset.ready",
        "assetId": metadata.asset_id,
        "assetType": metadata.asset_type.value,
        "ownerUserId": metadata.owner_user_id,
        "contentType": metadata.content_type,
        "sizeBytes": metadata.size_bytes,
        "durationSeconds": metadata.duration_seconds,
        "originalFilename": metadata.original_filename,
        "occurredAt": occurred_at,
    }


def extract_audio_duration_seconds(content: bytes) -> float | None:
    """Return audio duration in seconds using the already validated upload bytes."""
    if MutagenFile is None:
        return None

    try:
        audio = MutagenFile(BytesIO(content))
    except Exception:
        return None

    duration = getattr(getattr(audio, "info", None), "length", None)
    if not isinstance(duration, (int, float)) or duration <= 0:
        return None
    return float(duration)
