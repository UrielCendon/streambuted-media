import asyncio
import hmac
import hashlib
import base64
from io import BytesIO
from uuid import UUID, uuid4

import grpc
from fastapi.testclient import TestClient

from app.auth.models import AuthenticatedUser, UserRole
from app.config import Settings
from app.errors import AppError
from app.events.signer import canonical_json, sign_payload
from app.grpc.generated import media_asset_pb2
from app.grpc.media_asset_service import MediaAssetGrpcService
from app.main import create_app
from app.media.schemas import AssetType
from app.media.service import MediaService
from app.media.validation import validate_audio_upload, validate_image_upload
from app.storage.minio_client import StoredAssetMetadata, StoredObjectStream, build_object_key


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
MP3_BYTES = b"ID3" + b"\x00" * 16
MP4_AUDIO_BYTES = b"\x00\x00\x00\x18ftypdash" + b"\x00" * 16
FLAC_BYTES = b"fLaC" + b"\x00" * 16


class FakeUploadFile:
    def __init__(self, content: bytes, content_type: str, filename: str) -> None:
        self._stream = BytesIO(content)
        self.content_type = content_type
        self.filename = filename

    async def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


class FakeJwtValidator:
    def __init__(self, role: UserRole) -> None:
        self._role = role

    def validate_authorization_header(
        self,
        authorization_header: str | None,
    ) -> AuthenticatedUser:
        if authorization_header != "Bearer token":
            raise AppError(401, "Unauthorized", "Missing or invalid Authorization header.")
        return AuthenticatedUser(
            subject="37f6c3cb-d848-4678-b545-cd81f5d0f4ea",
            role=self._role,
        )


class RejectingJwtValidator:
    def validate_authorization_header(
        self,
        authorization_header: str | None,
    ) -> AuthenticatedUser:
        raise AppError(401, "Unauthorized", "Invalid JWT token.")


class FakeStorage:
    def __init__(self, order: list[str] | None = None) -> None:
        self.assets: dict[str, tuple[bytes, StoredAssetMetadata]] = {}
        self.order = order

    def ensure_bucket(self) -> None:
        return None

    def upload_asset(
        self,
        asset_id: UUID,
        content: bytes,
        metadata: StoredAssetMetadata,
    ) -> None:
        if self.order is not None:
            self.order.append("upload")
        self.assets[str(asset_id)] = (content, metadata)

    def get_metadata(self, asset_id: UUID | str) -> StoredAssetMetadata:
        stored = self.assets.get(str(asset_id))
        if not stored:
            raise AppError(404, "AssetNotFound", "Asset not found.")
        return stored[1]

    def open_asset(self, asset_id: UUID | str) -> StoredObjectStream:
        stored = self.assets.get(str(asset_id))
        if not stored:
            raise AppError(404, "AssetNotFound", "Asset not found.")

        content, metadata = stored
        return StoredObjectStream(
            content=iter([content]),
            content_type=metadata.content_type,
            size_bytes=metadata.size_bytes,
        )


class FakePublisher:
    def __init__(self, order: list[str] | None = None) -> None:
        self.events: list[dict[str, object]] = []
        self.order = order

    def publish_asset_ready(self, event: dict[str, object]) -> bool:
        if self.order is not None:
            self.order.append("publish")
        self.events.append(event)
        return True


class FakeGrpcAbort(Exception):
    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        super().__init__(details)
        self.code = code
        self.details = details


class FakeGrpcContext:
    def __init__(self, metadata: tuple[tuple[str, str], ...] = ()) -> None:
        self._metadata = metadata

    def invocation_metadata(self) -> tuple[tuple[str, str], ...]:
        return self._metadata

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        raise FakeGrpcAbort(code, details)


def run_async(coro):
    return asyncio.run(coro)


def build_settings() -> Settings:
    return Settings(
        minio_secret_key="minio-secret",
        rabbitmq_default_pass="rabbit-secret",
        event_signing_secret="event-secret",
    )


def build_client(role: UserRole, storage: FakeStorage | None = None) -> TestClient:
    app = create_app(
        settings=build_settings(),
        storage=storage or FakeStorage(),
        event_publisher=FakePublisher(),
        jwt_validator=FakeJwtValidator(role),
    )
    return TestClient(app)


def build_grpc_service(
    role: UserRole = UserRole.ARTIST,
    storage: FakeStorage | None = None,
    jwt_validator: FakeJwtValidator | RejectingJwtValidator | None = None,
) -> MediaAssetGrpcService:
    service = MediaService(
        settings=build_settings(),
        storage=storage or FakeStorage(),
        event_publisher=FakePublisher(),
    )
    return MediaAssetGrpcService(
        media_service=service,
        jwt_validator=jwt_validator or FakeJwtValidator(role),
    )


def seed_asset(
    storage: FakeStorage,
    asset_id: UUID,
    owner_user_id: str = "37f6c3cb-d848-4678-b545-cd81f5d0f4ea",
    asset_type: AssetType = AssetType.AUDIO,
) -> None:
    content_type = "audio/mpeg" if asset_type == AssetType.AUDIO else "image/png"
    content = MP3_BYTES if asset_type == AssetType.AUDIO else PNG_BYTES
    storage.assets[str(asset_id)] = (
        content,
        StoredAssetMetadata(
            asset_id=str(asset_id),
            asset_type=asset_type,
            owner_user_id=owner_user_id,
            content_type=content_type,
            size_bytes=len(content),
            duration_seconds=123.45 if asset_type == AssetType.AUDIO else None,
            original_filename="song.mp3" if asset_type == AssetType.AUDIO else "cover.png",
            uploaded_at="2026-04-30T00:00:00Z",
        ),
    )


def test_accepts_allowed_audio_content_type() -> None:
    upload = FakeUploadFile(MP3_BYTES, "audio/mpeg", "song.mp3")

    validated = run_async(validate_audio_upload(upload, max_size_bytes=1024))

    assert validated.content_type == "audio/mpeg"
    assert validated.size_bytes == len(MP3_BYTES)


def test_accepts_mp4_audio_container_with_mp3_mime_type() -> None:
    upload = FakeUploadFile(MP4_AUDIO_BYTES, "audio/mpeg", "song.mp3")

    validated = run_async(validate_audio_upload(upload, max_size_bytes=1024))

    assert validated.content_type == "audio/mpeg"
    assert validated.size_bytes == len(MP4_AUDIO_BYTES)


def test_accepts_flac_audio_content_type() -> None:
    upload = FakeUploadFile(FLAC_BYTES, "audio/flac", "song.flac")

    validated = run_async(validate_audio_upload(upload, max_size_bytes=1024))

    assert validated.content_type == "audio/flac"
    assert validated.size_bytes == len(FLAC_BYTES)


def test_media_cors_preflight_allows_frontend_origin() -> None:
    client = build_client(UserRole.ARTIST)

    response = client.options(
        "/api/v1/media/audio",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_accepts_allowed_image_content_type() -> None:
    upload = FakeUploadFile(PNG_BYTES, "image/png", "cover.png")

    validated = run_async(validate_image_upload(upload, max_size_bytes=1024))

    assert validated.content_type == "image/png"
    assert validated.original_filename == "cover.png"


def test_rejects_empty_file() -> None:
    upload = FakeUploadFile(b"", "image/png", "empty.png")

    try:
        run_async(validate_image_upload(upload, max_size_bytes=1024))
    except AppError as exc:
        assert exc.status_code == 400
        assert exc.code == "EmptyFile"
    else:
        raise AssertionError("Expected empty upload to be rejected.")


def test_rejects_file_that_exceeds_size_limit() -> None:
    upload = FakeUploadFile(PNG_BYTES, "image/png", "cover.png")

    try:
        run_async(validate_image_upload(upload, max_size_bytes=4))
    except AppError as exc:
        assert exc.status_code == 413
        assert exc.code == "FileTooLarge"
    else:
        raise AssertionError("Expected oversized upload to be rejected.")


def test_rejects_non_artist_audio_upload() -> None:
    client = build_client(UserRole.LISTENER)

    response = client.post(
        "/api/v1/media/audio",
        headers={"Authorization": "Bearer token"},
        files={"file": ("song.mp3", MP3_BYTES, "audio/mpeg")},
    )

    assert response.status_code == 403


def test_accepts_profile_image_for_authenticated_listener() -> None:
    client = build_client(UserRole.LISTENER)

    response = client.post(
        "/api/v1/media/profile-image",
        headers={"Authorization": "Bearer token"},
        files={"file": ("profile.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["assetType"] == "PROFILE_IMAGE"


def test_generates_uuid_v4_and_asset_object_key() -> None:
    storage = FakeStorage()
    publisher = FakePublisher()
    service = MediaService(build_settings(), storage, publisher)
    owner = AuthenticatedUser(
        subject="37f6c3cb-d848-4678-b545-cd81f5d0f4ea",
        role=UserRole.ARTIST,
    )
    upload = FakeUploadFile(MP3_BYTES, "audio/mpeg", "song.mp3")

    response = run_async(service.upload_asset(upload, AssetType.AUDIO, owner))
    asset_uuid = UUID(response.asset_id)

    assert asset_uuid.version == 4
    assert build_object_key(response.asset_id) == f"assets/{response.asset_id}"
    assert hasattr(response, "duration_seconds")


def test_get_metadata_returns_stored_metadata() -> None:
    storage = FakeStorage()
    client = build_client(UserRole.ARTIST, storage=storage)
    upload_response = client.post(
        "/api/v1/media/audio",
        headers={"Authorization": "Bearer token"},
        files={"file": ("song.mp3", MP3_BYTES, "audio/mpeg")},
    )
    asset_id = upload_response.json()["assetId"]

    metadata_response = client.get(f"/api/v1/media/assets/{asset_id}/metadata")

    assert metadata_response.status_code == 200
    assert metadata_response.json()["assetType"] == "AUDIO"
    assert "durationSeconds" in metadata_response.json()
    assert metadata_response.json()["exists"] is True


def test_direct_audio_asset_download_is_blocked() -> None:
    storage = FakeStorage()
    asset_id = uuid4()
    seed_asset(storage, asset_id, asset_type=AssetType.AUDIO)
    client = build_client(UserRole.ARTIST, storage=storage)

    response = client.get(f"/api/v1/media/assets/{asset_id}")

    assert response.status_code == 404


def test_direct_image_asset_download_remains_available() -> None:
    storage = FakeStorage()
    asset_id = uuid4()
    seed_asset(storage, asset_id, asset_type=AssetType.TRACK_COVER)
    client = build_client(UserRole.ARTIST, storage=storage)

    response = client.get(f"/api/v1/media/assets/{asset_id}")

    assert response.status_code == 200
    assert response.content == PNG_BYTES
    assert response.headers["content-type"].startswith("image/png")


def test_missing_asset_returns_404() -> None:
    client = build_client(UserRole.ARTIST)

    response = client.get(f"/api/v1/media/assets/{uuid4()}/metadata")

    assert response.status_code == 404


def test_grpc_get_asset_metadata_requires_authorization_metadata() -> None:
    grpc_service = build_grpc_service()

    try:
        run_async(
            grpc_service.GetAssetMetadata(
                media_asset_pb2.GetAssetMetadataRequest(asset_id=str(uuid4())),
                FakeGrpcContext(),
            )
        )
    except FakeGrpcAbort as exc:
        assert exc.code == grpc.StatusCode.UNAUTHENTICATED
    else:
        raise AssertionError("Expected missing authorization metadata to fail.")


def test_grpc_get_asset_metadata_rejects_invalid_jwt() -> None:
    grpc_service = build_grpc_service(jwt_validator=RejectingJwtValidator())

    try:
        run_async(
            grpc_service.GetAssetMetadata(
                media_asset_pb2.GetAssetMetadataRequest(asset_id=str(uuid4())),
                FakeGrpcContext((("authorization", "Bearer invalid"),)),
            )
        )
    except FakeGrpcAbort as exc:
        assert exc.code == grpc.StatusCode.UNAUTHENTICATED
    else:
        raise AssertionError("Expected invalid JWT to fail.")


def test_grpc_get_asset_metadata_returns_not_found_for_missing_asset() -> None:
    grpc_service = build_grpc_service()

    try:
        run_async(
            grpc_service.GetAssetMetadata(
                media_asset_pb2.GetAssetMetadataRequest(asset_id=str(uuid4())),
                FakeGrpcContext((("authorization", "Bearer token"),)),
            )
        )
    except FakeGrpcAbort as exc:
        assert exc.code == grpc.StatusCode.NOT_FOUND
    else:
        raise AssertionError("Expected missing asset to fail.")


def test_grpc_get_asset_metadata_returns_metadata_for_owner() -> None:
    storage = FakeStorage()
    asset_id = uuid4()
    seed_asset(storage, asset_id)
    grpc_service = build_grpc_service(storage=storage)

    response = run_async(
        grpc_service.GetAssetMetadata(
            media_asset_pb2.GetAssetMetadataRequest(asset_id=str(asset_id)),
            FakeGrpcContext((("authorization", "Bearer token"),)),
        )
    )

    assert response.asset_id == str(asset_id)
    assert response.asset_type == "AUDIO"
    assert response.owner_user_id == "37f6c3cb-d848-4678-b545-cd81f5d0f4ea"
    assert response.exists is True
    assert "bucket" not in response.DESCRIPTOR.fields_by_name
    assert "object_key" not in response.DESCRIPTOR.fields_by_name


def test_grpc_get_asset_metadata_denies_different_user() -> None:
    storage = FakeStorage()
    asset_id = uuid4()
    seed_asset(storage, asset_id, owner_user_id="d3d87e12-3fd0-4d3f-af1e-77330831257b")
    grpc_service = build_grpc_service(storage=storage)

    try:
        run_async(
            grpc_service.GetAssetMetadata(
                media_asset_pb2.GetAssetMetadataRequest(asset_id=str(asset_id)),
                FakeGrpcContext((("authorization", "Bearer token"),)),
            )
        )
    except FakeGrpcAbort as exc:
        assert exc.code == grpc.StatusCode.PERMISSION_DENIED
    else:
        raise AssertionError("Expected asset owned by another user to fail.")


def test_grpc_get_asset_metadata_allows_admin() -> None:
    storage = FakeStorage()
    asset_id = uuid4()
    seed_asset(storage, asset_id, owner_user_id="d3d87e12-3fd0-4d3f-af1e-77330831257b")
    grpc_service = build_grpc_service(role=UserRole.ADMIN, storage=storage)

    response = run_async(
        grpc_service.GetAssetMetadata(
            media_asset_pb2.GetAssetMetadataRequest(asset_id=str(asset_id)),
            FakeGrpcContext((("authorization", "Bearer token"),)),
        )
    )

    assert response.asset_id == str(asset_id)
    assert response.owner_user_id == "d3d87e12-3fd0-4d3f-af1e-77330831257b"


def test_event_signature_uses_hmac_sha256_base64() -> None:
    payload = {"assetId": "asset-1", "eventType": "media.asset.ready"}
    secret = "secret"
    expected = base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            canonical_json(payload).encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("ascii")

    assert sign_payload(payload, secret) == expected


def test_publishes_event_after_successful_upload() -> None:
    order: list[str] = []
    storage = FakeStorage(order)
    publisher = FakePublisher(order)
    service = MediaService(build_settings(), storage, publisher)
    owner = AuthenticatedUser(
        subject="37f6c3cb-d848-4678-b545-cd81f5d0f4ea",
        role=UserRole.ARTIST,
    )
    upload = FakeUploadFile(MP3_BYTES, "audio/mpeg", "song.mp3")

    response = run_async(service.upload_asset(upload, AssetType.AUDIO, owner))

    assert order == ["upload", "publish"]
    assert publisher.events[0]["assetId"] == response.asset_id
    assert publisher.events[0]["eventType"] == "media.asset.ready"
