import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Iterator
from uuid import UUID

from minio import Minio
from minio.error import S3Error

from app.config import Settings
from app.errors import AppError
from app.media.schemas import AssetType

logger = logging.getLogger(__name__)

OBJECT_KEY_PREFIX = "assets"


@dataclass(frozen=True)
class StoredAssetMetadata:
    """Metadata describing a stored asset."""

    asset_id: str
    asset_type: AssetType
    owner_user_id: str
    content_type: str
    size_bytes: int
    original_filename: str
    uploaded_at: str


@dataclass(frozen=True)
class StoredObjectStream:
    """Streaming handle for a stored object."""

    content: Iterator[bytes]
    content_type: str
    size_bytes: int


def build_object_key(asset_id: UUID | str) -> str:
    """Build the MinIO object key for an asset id.

    Args:
        asset_id: Asset UUID.

    Returns:
        Object key using assets/{assetId}.
    """
    return f"{OBJECT_KEY_PREFIX}/{asset_id}"


class MinioStorage:
    """MinIO-backed binary storage for media assets."""

    def __init__(
        self,
        client: Minio,
        bucket_name: str,
    ) -> None:
        """Create a MinIO storage adapter.

        Args:
            client: Configured MinIO client.
            bucket_name: Bucket used by Media Service.
        """
        if not bucket_name.strip():
            raise ValueError("MINIO_BUCKET must be configured.")
        self._client = client
        self._bucket_name = bucket_name

    @classmethod
    def from_settings(cls, settings: Settings) -> "MinioStorage":
        """Create MinIO storage from runtime settings."""
        client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        return cls(client=client, bucket_name=settings.minio_bucket)

    def ensure_bucket(self) -> None:
        """Create the configured bucket if it does not exist."""
        try:
            if not self._client.bucket_exists(self._bucket_name):
                self._client.make_bucket(self._bucket_name)
                logger.info("Created MinIO bucket %s", self._bucket_name)
        except S3Error as exc:
            logger.error("Failed to ensure MinIO bucket: %s", exc, exc_info=True)
            raise AppError(
                503,
                "StorageUnavailable",
                "Media storage is unavailable.",
            ) from exc

    def upload_asset(
        self,
        asset_id: UUID,
        content: bytes,
        metadata: StoredAssetMetadata,
    ) -> None:
        """Store an asset binary and metadata in MinIO.

        Args:
            asset_id: Asset UUID.
            content: Binary content.
            metadata: Metadata to store as object metadata.

        Raises:
            AppError: If the upload fails.
        """
        object_metadata = {
            "asset-id": metadata.asset_id,
            "asset-type": metadata.asset_type.value,
            "owner-user-id": metadata.owner_user_id,
            "original-filename": metadata.original_filename,
            "size-bytes": str(metadata.size_bytes),
            "uploaded-at": metadata.uploaded_at,
        }

        try:
            self._client.put_object(
                bucket_name=self._bucket_name,
                object_name=build_object_key(asset_id),
                data=BytesIO(content),
                length=len(content),
                content_type=metadata.content_type,
                metadata=object_metadata,
            )
        except S3Error as exc:
            logger.error("Failed to upload asset to MinIO: %s", exc, exc_info=True)
            raise AppError(
                503,
                "StorageUnavailable",
                "Media storage is unavailable.",
            ) from exc

    def get_metadata(self, asset_id: UUID | str) -> StoredAssetMetadata:
        """Read asset metadata from MinIO object metadata.

        Args:
            asset_id: Asset UUID.

        Returns:
            Stored asset metadata.

        Raises:
            AppError: If the object does not exist or storage fails.
        """
        try:
            stat = self._client.stat_object(
                bucket_name=self._bucket_name,
                object_name=build_object_key(asset_id),
            )
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                raise AppError(404, "AssetNotFound", "Asset not found.") from exc
            logger.error("Failed to stat MinIO object: %s", exc, exc_info=True)
            raise AppError(
                503,
                "StorageUnavailable",
                "Media storage is unavailable.",
            ) from exc

        normalized_metadata = normalize_minio_metadata(stat.metadata or {})
        asset_type = normalized_metadata.get("asset-type")
        try:
            parsed_asset_type = AssetType(asset_type)
        except ValueError as exc:
            logger.error("Stored asset has invalid asset type metadata.")
            raise AppError(
                500,
                "InvalidStoredAsset",
                "Stored asset metadata is invalid.",
            ) from exc

        return StoredAssetMetadata(
            asset_id=normalized_metadata.get("asset-id", str(asset_id)),
            asset_type=parsed_asset_type,
            owner_user_id=normalized_metadata.get("owner-user-id", ""),
            content_type=normalized_metadata.get(
                "content-type",
                stat.content_type or "application/octet-stream",
            ),
            size_bytes=int(normalized_metadata.get("size-bytes", stat.size or 0)),
            original_filename=normalized_metadata.get(
                "original-filename",
                "upload.bin",
            ),
            uploaded_at=normalized_metadata.get("uploaded-at", ""),
        )

    def open_asset(self, asset_id: UUID | str) -> StoredObjectStream:
        """Open an asset for streaming from MinIO.

        Args:
            asset_id: Asset UUID.

        Returns:
            Object stream with content type and size.

        Raises:
            AppError: If the object does not exist or storage fails.
        """
        metadata = self.get_metadata(asset_id)
        try:
            response = self._client.get_object(
                bucket_name=self._bucket_name,
                object_name=build_object_key(asset_id),
            )
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                raise AppError(404, "AssetNotFound", "Asset not found.") from exc
            logger.error("Failed to read MinIO object: %s", exc, exc_info=True)
            raise AppError(
                503,
                "StorageUnavailable",
                "Media storage is unavailable.",
            ) from exc

        def iter_content() -> Iterator[bytes]:
            try:
                yield from response.stream(32 * 1024)
            finally:
                response.close()
                response.release_conn()

        return StoredObjectStream(
            content=iter_content(),
            content_type=metadata.content_type,
            size_bytes=metadata.size_bytes,
        )


def normalize_minio_metadata(metadata: dict[str, str]) -> dict[str, str]:
    """Normalize MinIO metadata keys to app-level names.

    Args:
        metadata: Raw metadata returned by MinIO.

    Returns:
        Metadata with lowercase keys and no x-amz-meta prefix.
    """
    normalized: dict[str, str] = {}
    for key, value in metadata.items():
        normalized_key = key.lower()
        if normalized_key.startswith("x-amz-meta-"):
            normalized_key = normalized_key.removeprefix("x-amz-meta-")
        normalized[normalized_key] = value
    return normalized
