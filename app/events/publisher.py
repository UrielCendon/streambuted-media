import logging
from typing import Any, Protocol

import pika
from pika.exceptions import AMQPError

from app.config import Settings
from app.events.signer import canonical_json, sign_serialized_payload

logger = logging.getLogger(__name__)

MEDIA_EXCHANGE = "media.events"
MEDIA_ASSET_READY_ROUTING_KEY = "media.asset.ready"


class AssetEventPublisher(Protocol):
    """Publishes media asset lifecycle events."""

    def publish_asset_ready(self, event: dict[str, Any]) -> bool:
        """Publish a media.asset.ready event.

        Args:
            event: Event payload.

        Returns:
            True if the event was published, otherwise False.
        """


class NoopAssetEventPublisher:
    """Publisher used when event configuration is intentionally unavailable."""

    def publish_asset_ready(self, event: dict[str, Any]) -> bool:
        """Skip publishing while keeping upload flow available."""
        logger.warning(
            "Skipping media.asset.ready publish for assetId=%s; "
            "RabbitMQ signing is not configured.",
            event.get("assetId"),
        )
        return False


class RabbitMqAssetEventPublisher:
    """Best-effort RabbitMQ publisher for media asset events."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        signing_secret: str,
    ) -> None:
        """Create a RabbitMQ asset event publisher.

        Args:
            host: RabbitMQ hostname.
            port: RabbitMQ AMQP port.
            username: RabbitMQ username.
            password: RabbitMQ password.
            signing_secret: Shared HMAC signing secret.
        """
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._signing_secret = signing_secret

    def publish_asset_ready(self, event: dict[str, Any]) -> bool:
        """Publish a media.asset.ready event after a successful upload."""
        payload_json = canonical_json(event)
        signature = sign_serialized_payload(payload_json, self._signing_secret)
        credentials = pika.PlainCredentials(self._username, self._password)
        parameters = pika.ConnectionParameters(
            host=self._host,
            port=self._port,
            credentials=credentials,
            heartbeat=30,
            blocked_connection_timeout=5,
            connection_attempts=1,
        )

        connection: pika.BlockingConnection | None = None
        try:
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            channel.exchange_declare(
                exchange=MEDIA_EXCHANGE,
                exchange_type="topic",
                durable=True,
            )
            channel.basic_publish(
                exchange=MEDIA_EXCHANGE,
                routing_key=MEDIA_ASSET_READY_ROUTING_KEY,
                body=payload_json.encode("utf-8"),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    content_encoding="utf-8",
                    delivery_mode=2,
                    headers={"X-Event-Signature": signature},
                ),
            )
            logger.info(
                "Published media.asset.ready for assetId=%s",
                event.get("assetId"),
            )
            return True
        except (AMQPError, OSError) as exc:
            logger.error(
                "Failed to publish media.asset.ready for assetId=%s: %s",
                event.get("assetId"),
                exc,
                exc_info=True,
            )
            return False
        finally:
            if connection and connection.is_open:
                connection.close()


def build_event_publisher(settings: Settings) -> AssetEventPublisher:
    """Build the configured asset event publisher.

    Args:
        settings: Runtime application settings.

    Returns:
        RabbitMQ publisher when configured; otherwise a no-op publisher.
    """
    if not settings.event_signing_secret.strip():
        return NoopAssetEventPublisher()
    if not settings.rabbitmq_default_pass.strip():
        return NoopAssetEventPublisher()

    return RabbitMqAssetEventPublisher(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        username=settings.rabbitmq_default_user,
        password=settings.rabbitmq_default_pass,
        signing_secret=settings.event_signing_secret,
    )
