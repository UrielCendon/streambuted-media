# StreamButed Media Service

Media Service manages binary media assets for StreamButed. It validates uploads,
stores the real files in MinIO, stores minimal metadata as MinIO object metadata,
returns UUID asset references, streams files by asset id, and publishes a
`media.asset.ready` event after a successful upload. It also exposes an
internal gRPC metadata contract for Catalog Service asset validation.

## Architecture Decision

Media Service does not use its own database.

- MinIO stores the binary object at `assets/{assetId}`.
- MinIO object metadata stores the minimal asset metadata.
- Identity Service stores `user_profile.profile_image_asset_id`.
- Catalog Service stores `track.audio_asset_id`, `track.cover_asset_id`, and
  `album.cover_asset_id`.

This design lets Media Service find any object using only `assetId`.

## Environment Variables

```env
MEDIA_PORT=8083
MEDIA_GRPC_PORT=9093

MINIO_ENDPOINT=minio:9000
MINIO_PUBLIC_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=streambuted
MINIO_SECRET_KEY=replace_with_your_minio_secret
MINIO_BUCKET=streambuted-media
MINIO_SECURE=false

MEDIA_MAX_AUDIO_SIZE_MB=200
MEDIA_MAX_IMAGE_SIZE_MB=5
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost

JWT_ISSUER=http://identity-service:8081
JWT_JWKS_URL=http://identity-service:8081/api/v1/auth/.well-known/jwks.json
JWT_AUDIENCE=

RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_DEFAULT_USER=streambuted
RABBITMQ_DEFAULT_PASS=replace_with_your_rabbitmq_password
EVENT_SIGNING_SECRET=CHANGE_ME_SECRET_64_CHARS
```

## Asset Types

- `PROFILE_IMAGE`: profile image uploaded by any authenticated user.
- `AUDIO`: song audio uploaded only by artists.
- `TRACK_COVER`: track cover uploaded only by artists.
- `ALBUM_COVER`: album cover uploaded only by artists.

## Permissions

- `POST /api/v1/media/profile-image`: `LISTENER`, `ARTIST`, `ADMIN`.
- `POST /api/v1/media/audio`: `ARTIST`.
- `POST /api/v1/media/images`: `ARTIST`.
- `GET /api/v1/media/assets/{assetId}`: public file delivery.
- `MediaAssetService.GetAssetMetadata`: internal gRPC metadata lookup for
  Catalog validation. Requires `authorization: Bearer <accessToken>` metadata.

JWT tokens are validated with RS256 and JWKS from Identity Service. The role
claim accepts `LISTENER`, `ARTIST`, `ADMIN`, lowercase variants, and `ROLE_*`
variants.

Catalog Service uses gRPC at `media-service:9093` for immediate validation of
`audio_asset_id`, `track.cover_asset_id`, and `album.cover_asset_id`. The call
does not pass through the API Gateway. Media authorizes metadata by
`ownerUserId == sub` or role `ADMIN`.

## Upload Flow

1. The client sends a multipart upload through the gateway.
2. Media Service validates JWT and role.
3. Media Service validates content type, size, and magic bytes.
4. Media Service generates a UUID v4 asset id.
5. Media Service stores the file in MinIO at `assets/{assetId}`.
6. Media Service stores metadata as MinIO object metadata and stores
   `Content-Type` as the object content-type header.
7. Media Service publishes `media.asset.ready` as best-effort.

## Stored Metadata

The following metadata is stored with the MinIO object:

- `asset-id`
- `asset-type`
- `owner-user-id`
- `original-filename`
- `size-bytes`
- `uploaded-at`

`contentType` returned by HTTP/gRPC is read from the MinIO object
`Content-Type` header. It is intentionally not duplicated as custom metadata
`content-type`, because that can conflict with S3 signing in MinIO uploads.

## Upload Limits And Formats

```text
Audio max size: 200 MB
Image max size: 5 MB
Accepted audio: MP3, WAV, FLAC, OGG, WEBM
Accepted images: JPEG, PNG, WEBP
```

The FastAPI app enables CORS for explicit origins from `CORS_ALLOWED_ORIGINS`
and accepts preflight `OPTIONS` for authenticated upload routes used by the
browser frontend.

## Endpoints

```http
GET  /health
GET  /api/v1/media/health
POST /api/v1/media/profile-image
POST /api/v1/media/audio
POST /api/v1/media/images
GET  /api/v1/media/assets/{assetId}
```

Internal gRPC:

```text
streambuted.media.v1.MediaAssetService.GetAssetMetadata
```

## RabbitMQ Event

Exchange:

```text
media.events
```

Routing key:

```text
media.asset.ready
```

Payload:

```json
{
  "eventId": "uuid",
  "eventType": "media.asset.ready",
  "assetId": "uuid",
  "assetType": "AUDIO",
  "ownerUserId": "uuid-del-usuario",
  "contentType": "audio/mpeg",
  "sizeBytes": 12345,
  "originalFilename": "song.mp3",
  "occurredAt": "2026-04-29T12:00:00Z"
}
```

The payload is serialized as stable JSON and signed with HMAC-SHA256 using
`EVENT_SIGNING_SECRET`. The signature is sent in the `X-Event-Signature`
header.

Event publication is best-effort in this version. If MinIO upload succeeds but
RabbitMQ publication fails, the file is kept and the error is logged. There is
no outbox because Media Service intentionally has no database.

## Run

From the repository root:

```bash
docker compose up -d --build
```

The intended external path is:

```text
Client -> Gateway -> Media Service
```

Media Service HTTP and gRPC ports are not published directly to the host.

## Test MinIO

Open the MinIO console:

```text
http://localhost:9001
```

Use `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` from `.env`.

The bucket is created automatically on Media Service startup. Uploaded files are
stored under:

```text
streambuted-media/assets/{assetId}
```

## Curl Examples

Health through the gateway:

```bash
curl http://localhost/api/v1/media/health
```

Upload a profile image:

```bash
curl -X POST http://localhost/api/v1/media/profile-image \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F "file=@profile.png;type=image/png"
```

Upload audio as an artist:

```bash
curl -X POST http://localhost/api/v1/media/audio \
  -H "Authorization: Bearer $ARTIST_ACCESS_TOKEN" \
  -F "file=@song.mp3;type=audio/mpeg"
```

Upload a track cover:

```bash
curl -X POST http://localhost/api/v1/media/images \
  -H "Authorization: Bearer $ARTIST_ACCESS_TOKEN" \
  -F "usage=TRACK_COVER" \
  -F "file=@cover.jpg;type=image/jpeg"
```

Upload an album cover:

```bash
curl -X POST http://localhost/api/v1/media/images \
  -H "Authorization: Bearer $ARTIST_ACCESS_TOKEN" \
  -F "usage=ALBUM_COVER" \
  -F "file=@cover.jpg;type=image/jpeg"
```

Download or stream the asset:

```bash
curl -L http://localhost/api/v1/media/assets/$ASSET_ID --output asset.bin
```

## Verify RabbitMQ Event

Open RabbitMQ Management:

```text
http://localhost:15672
```

Use `RABBITMQ_DEFAULT_USER` and `RABBITMQ_DEFAULT_PASS` from `.env`, then check:

- Exchange: `media.events`
- Type: `topic`
- Routing key: `media.asset.ready`
- Header: `X-Event-Signature`

## Tests

From `services/media-service`:

```bash
pytest
```

The tests use mocks for MinIO, JWT, and RabbitMQ.
