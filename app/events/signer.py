import base64
import hashlib
import hmac
import json
from typing import Any


def canonical_json(payload: dict[str, Any]) -> str:
    """Serialize a payload deterministically for stable event signatures.

    Args:
        payload: Event payload.

    Returns:
        Canonical JSON string.
    """
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sign_serialized_payload(serialized_payload: str, secret: str) -> str:
    """Sign a serialized payload using HMAC-SHA256.

    Args:
        serialized_payload: JSON payload string to sign.
        secret: Shared event signing secret.

    Returns:
        Base64-encoded HMAC signature.
    """
    digest = hmac.new(
        secret.encode("utf-8"),
        serialized_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def sign_payload(payload: dict[str, Any], secret: str) -> str:
    """Sign a payload using canonical JSON and HMAC-SHA256.

    Args:
        payload: Event payload.
        secret: Shared event signing secret.

    Returns:
        Base64-encoded HMAC signature.
    """
    return sign_serialized_payload(canonical_json(payload), secret)
