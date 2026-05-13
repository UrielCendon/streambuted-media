from dataclasses import dataclass
from pathlib import PurePath

from fastapi import UploadFile

from app.errors import AppError

ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/x-flac",
    "audio/ogg",
    "audio/webm",
    "audio/mp3",
    "audio/mp4",
    "audio/x-m4a",
    "video/mp4",
}

ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

READ_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ValidatedUpload:
    """Validated upload data ready to be stored."""

    content: bytes
    content_type: str
    original_filename: str
    size_bytes: int


async def validate_audio_upload(
    file: UploadFile,
    max_size_bytes: int,
) -> ValidatedUpload:
    """Validate an audio upload by size, content type, and magic bytes.

    Args:
        file: Uploaded file.
        max_size_bytes: Maximum accepted size in bytes.

    Returns:
        Validated upload data.

    Raises:
        AppError: If the file is invalid.
    """
    return await validate_upload(
        file=file,
        allowed_content_types=ALLOWED_AUDIO_CONTENT_TYPES,
        max_size_bytes=max_size_bytes,
        kind="audio",
    )


async def validate_image_upload(
    file: UploadFile,
    max_size_bytes: int,
) -> ValidatedUpload:
    """Validate an image upload by size, content type, and magic bytes.

    Args:
        file: Uploaded file.
        max_size_bytes: Maximum accepted size in bytes.

    Returns:
        Validated upload data.

    Raises:
        AppError: If the file is invalid.
    """
    return await validate_upload(
        file=file,
        allowed_content_types=ALLOWED_IMAGE_CONTENT_TYPES,
        max_size_bytes=max_size_bytes,
        kind="image",
    )


async def validate_upload(
    file: UploadFile,
    allowed_content_types: set[str],
    max_size_bytes: int,
    kind: str,
) -> ValidatedUpload:
    """Validate a generic uploaded file.

    Args:
        file: Uploaded file.
        allowed_content_types: MIME types accepted by the endpoint.
        max_size_bytes: Maximum accepted size in bytes.
        kind: Human-readable file category.

    Returns:
        Validated upload data.

    Raises:
        AppError: If the upload fails validation.
    """
    content_type = normalize_content_type(file.content_type)
    if content_type not in allowed_content_types:
        raise AppError(
            400,
            "UnsupportedMediaType",
            f"Unsupported {kind} content type.",
        )

    content = await read_limited_file(file, max_size_bytes)
    if not content:
        raise AppError(400, "EmptyFile", "Uploaded file cannot be empty.")

    if not has_valid_magic_bytes(content, content_type):
        raise AppError(
            400,
            "InvalidFileContent",
            "Uploaded file content does not match its content type.",
        )

    return ValidatedUpload(
        content=content,
        content_type=content_type,
        original_filename=safe_original_filename(file.filename),
        size_bytes=len(content),
    )


async def read_limited_file(file: UploadFile, max_size_bytes: int) -> bytes:
    """Read an upload while enforcing a maximum size.

    Args:
        file: Uploaded file.
        max_size_bytes: Maximum accepted size in bytes.

    Returns:
        File content.

    Raises:
        AppError: If the file exceeds the configured size.
    """
    chunks: list[bytes] = []
    total_size = 0

    while True:
        chunk = await file.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_size_bytes:
            raise AppError(
                413,
                "FileTooLarge",
                "Uploaded file exceeds the configured size limit.",
            )
        chunks.append(chunk)

    return b"".join(chunks)


def normalize_content_type(content_type: str | None) -> str:
    """Normalize a Content-Type value.

    Args:
        content_type: Raw Content-Type value.

    Returns:
        Lowercase MIME type without parameters.
    """
    if not content_type:
        return ""
    return content_type.split(";", maxsplit=1)[0].strip().lower()


def safe_original_filename(filename: str | None) -> str:
    """Return a safe filename value for metadata only.

    Args:
        filename: Raw client-provided filename.

    Returns:
        Basename without path components.
    """
    if not filename:
        return "upload.bin"

    cleaned = filename.replace("\\", "/")
    basename = PurePath(cleaned).name.strip()
    return basename or "upload.bin"


def has_valid_magic_bytes(content: bytes, content_type: str) -> bool:
    """Validate magic bytes for supported media types.

    Args:
        content: File bytes.
        content_type: Normalized MIME type.

    Returns:
        True when magic bytes match the expected type.
    """
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    if content_type in {"audio/mpeg", "audio/mp3"}:
        return content.startswith(b"ID3") or (
            len(content) >= 2
            and content[0] == 0xFF
            and (content[1] & 0xE0) == 0xE0
        ) or has_iso_base_media_magic_bytes(content)
    if content_type in {"audio/wav", "audio/x-wav"}:
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WAVE"
    if content_type in {"audio/flac", "audio/x-flac"}:
        return content.startswith(b"fLaC")
    if content_type == "audio/ogg":
        return content.startswith(b"OggS")
    if content_type == "audio/webm":
        return content.startswith(b"\x1a\x45\xdf\xa3")
    if content_type in {"audio/mp4", "audio/x-m4a", "video/mp4"}:
        return has_iso_base_media_magic_bytes(content)
    return False


def has_iso_base_media_magic_bytes(content: bytes) -> bool:
    """Return true for MP4/M4A style audio containers."""
    if len(content) < 12 or content[4:8] != b"ftyp":
        return False

    major_brand = content[8:12]
    compatible_brands = content[16:64]
    brands = {major_brand}
    brands.update(
        compatible_brands[index:index + 4]
        for index in range(0, len(compatible_brands), 4)
        if len(compatible_brands[index:index + 4]) == 4
    )

    return any(
        brand in brands
        for brand in {b"M4A ", b"M4B ", b"mp41", b"mp42", b"isom", b"iso2", b"dash"}
    )
