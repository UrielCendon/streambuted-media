import logging
import time
from typing import Any

import httpx
import jwt
from jwt import InvalidTokenError, PyJWK, PyJWKError

from app.auth.models import AuthenticatedUser, normalize_role
from app.errors import AppError

logger = logging.getLogger(__name__)


class JwtValidator:
    """Validates RS256 JWT access tokens using a cached JWKS document."""

    def __init__(
        self,
        jwks_url: str,
        issuer: str,
        audience: str | None = None,
        cache_ttl_seconds: int = 600,
    ) -> None:
        """Create a JWT validator.

        Args:
            jwks_url: Absolute URL where Identity Service publishes JWKS.
            issuer: Expected JWT issuer.
            audience: Optional expected JWT audience.
            cache_ttl_seconds: In-memory JWKS cache lifetime.
        """
        if not jwks_url.strip():
            raise ValueError("JWT_JWKS_URL must be configured.")
        if not issuer.strip():
            raise ValueError("JWT_ISSUER must be configured.")

        self._jwks_url = jwks_url.strip()
        self._issuer = issuer.strip()
        self._audience = audience.strip() if audience and audience.strip() else None
        self._cache_ttl_seconds = cache_ttl_seconds
        self._jwks: dict[str, Any] | None = None
        self._jwks_loaded_at = 0.0

    def validate_authorization_header(
        self,
        authorization_header: str | None,
    ) -> AuthenticatedUser:
        """Validate a Bearer token from the Authorization header.

        Args:
            authorization_header: Raw Authorization header value.

        Returns:
            Authenticated user represented by the JWT subject and role.

        Raises:
            AppError: If the header is missing or the token is invalid.
        """
        token = self._extract_bearer_token(authorization_header)
        return self.validate_token(token)

    def validate_token(self, token: str) -> AuthenticatedUser:
        """Validate a compact JWT and return its authenticated user.

        Args:
            token: Compact JWT string.

        Returns:
            Authenticated user represented by the JWT subject and role.

        Raises:
            AppError: If the token cannot be validated.
        """
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            logger.info("Rejected malformed JWT header: %s", exc)
            raise AppError(401, "Unauthorized", "Invalid JWT token.") from exc

        algorithm = header.get("alg")
        if algorithm != "RS256":
            raise AppError(401, "Unauthorized", "Unsupported JWT algorithm.")

        kid = header.get("kid")
        if not isinstance(kid, str) or not kid.strip():
            raise AppError(401, "Unauthorized", "JWT key id is missing.")

        signing_key = self._get_signing_key(kid)
        payload = self._decode_token(token, signing_key)
        subject = payload.get("sub")
        role = payload.get("role")

        if not isinstance(subject, str) or not subject.strip():
            raise AppError(401, "Unauthorized", "JWT subject claim is missing.")
        if not isinstance(role, str) or not role.strip():
            raise AppError(401, "Unauthorized", "JWT role claim is missing.")

        try:
            normalized_role = normalize_role(role)
        except ValueError as exc:
            raise AppError(401, "Unauthorized", "JWT role claim is invalid.") from exc

        return AuthenticatedUser(subject=subject.strip(), role=normalized_role)

    def _decode_token(self, token: str, signing_key: Any) -> dict[str, Any]:
        options = {
            "require": ["exp", "sub"],
            "verify_aud": self._audience is not None,
        }

        try:
            decoded = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                options=options,
            )
        except InvalidTokenError as exc:
            logger.info("Rejected invalid JWT: %s", exc)
            raise AppError(
                401,
                "Unauthorized",
                "Invalid or expired JWT token.",
            ) from exc

        if not isinstance(decoded, dict):
            raise AppError(401, "Unauthorized", "Invalid JWT payload.")
        return decoded

    def _get_signing_key(self, kid: str) -> Any:
        jwks = self._get_cached_jwks()
        key_data = self._find_key(jwks, kid)

        if key_data is None:
            jwks = self._refresh_jwks()
            key_data = self._find_key(jwks, kid)

        if key_data is None:
            raise AppError(401, "Unauthorized", "JWT signing key not found.")

        try:
            return PyJWK.from_dict(key_data).key
        except (InvalidTokenError, PyJWKError, ValueError, TypeError) as exc:
            logger.error("Failed to build public key from JWKS: %s", exc)
            raise AppError(401, "Unauthorized", "Invalid JWT signing key.") from exc

    def _get_cached_jwks(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._jwks and now - self._jwks_loaded_at < self._cache_ttl_seconds:
            return self._jwks
        return self._refresh_jwks()

    def _refresh_jwks(self) -> dict[str, Any]:
        try:
            response = httpx.get(self._jwks_url, timeout=5.0)
            response.raise_for_status()
            jwks = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("Failed to fetch JWKS from Identity Service: %s", exc)
            raise AppError(
                401,
                "Unauthorized",
                "JWT validation is temporarily unavailable.",
            ) from exc

        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            raise AppError(401, "Unauthorized", "Invalid JWKS document.")

        self._jwks = jwks
        self._jwks_loaded_at = time.monotonic()
        return jwks

    @staticmethod
    def _find_key(jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            return None

        for key in keys:
            if isinstance(key, dict) and key.get("kid") == kid:
                return key
        return None

    @staticmethod
    def _extract_bearer_token(authorization_header: str | None) -> str:
        if not authorization_header:
            raise AppError(
                401,
                "Unauthorized",
                "Missing or invalid Authorization header.",
            )

        parts = authorization_header.strip().split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise AppError(
                401,
                "Unauthorized",
                "Missing or invalid Authorization header.",
            )

        return parts[1]
