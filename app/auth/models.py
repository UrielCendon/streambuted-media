from dataclasses import dataclass
from enum import Enum


class UserRole(str, Enum):
    """Supported authenticated user roles."""

    LISTENER = "LISTENER"
    ARTIST = "ARTIST"
    ADMIN = "ADMIN"


@dataclass(frozen=True)
class AuthenticatedUser:
    """Authenticated user extracted from a validated JWT."""

    subject: str
    role: UserRole


def normalize_role(role: str) -> UserRole:
    """Normalize a JWT role claim into a supported role.

    Args:
        role: Raw role claim value.

    Returns:
        Normalized user role.

    Raises:
        ValueError: If the role is blank or unsupported.
    """
    normalized_role = role.strip().upper()
    if normalized_role.startswith("ROLE_"):
        normalized_role = normalized_role[5:].strip()

    try:
        return UserRole(normalized_role)
    except ValueError as exc:
        raise ValueError("Unsupported JWT role claim.") from exc
