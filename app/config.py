from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    media_port: int = Field(default=8083, alias="MEDIA_PORT")
    media_grpc_port: int = Field(default=9093, alias="MEDIA_GRPC_PORT")

    minio_endpoint: str = Field(default="minio:9000", alias="MINIO_ENDPOINT")
    minio_public_endpoint: str = Field(
        default="localhost:9000",
        alias="MINIO_PUBLIC_ENDPOINT",
    )
    minio_access_key: str = Field(default="streambuted", alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="", alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="streambuted-media", alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")

    media_max_audio_size_mb: int = Field(default=200, alias="MEDIA_MAX_AUDIO_SIZE_MB")
    media_max_image_size_mb: int = Field(default=5, alias="MEDIA_MAX_IMAGE_SIZE_MB")
    cors_allowed_origins: str = Field(
        default="http://localhost:5173,http://localhost",
        alias="CORS_ALLOWED_ORIGINS",
    )

    jwt_issuer: str = Field(
        default="http://identity-service:8081",
        alias="JWT_ISSUER",
    )
    jwt_jwks_url: str = Field(
        default="http://identity-service:8081/api/v1/auth/.well-known/jwks.json",
        alias="JWT_JWKS_URL",
    )
    jwt_audience: str | None = Field(default=None, alias="JWT_AUDIENCE")

    rabbitmq_host: str = Field(default="rabbitmq", alias="RABBITMQ_HOST")
    rabbitmq_port: int = Field(default=5672, alias="RABBITMQ_PORT")
    rabbitmq_default_user: str = Field(
        default="streambuted",
        alias="RABBITMQ_DEFAULT_USER",
    )
    rabbitmq_default_pass: str = Field(default="", alias="RABBITMQ_DEFAULT_PASS")
    event_signing_secret: str = Field(default="", alias="EVENT_SIGNING_SECRET")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("jwt_audience", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: object) -> str | None:
        """Treat blank JWT_AUDIENCE as disabled audience validation."""
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return str(value)

    @property
    def max_audio_size_bytes(self) -> int:
        """Configured maximum audio upload size in bytes."""
        return self.media_max_audio_size_mb * 1024 * 1024

    @property
    def max_image_size_bytes(self) -> int:
        """Configured maximum image upload size in bytes."""
        return self.media_max_image_size_mb * 1024 * 1024

    @property
    def allowed_cors_origins(self) -> list[str]:
        """Configured explicit browser origins allowed to call Media Service."""
        origins = [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]
        if not origins or "*" in origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must define explicit origins and cannot include '*'.")
        return origins


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
