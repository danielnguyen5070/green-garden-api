"""Password hashing and JWT helpers.

Keep cryptography isolated from route handlers.
Do not log passwords or JWT tokens.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings, get_settings

TokenType = Literal["access", "refresh"]

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password with Argon2id."""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against an Argon2id hash."""
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def validate_password_strength(password: str) -> None:
    """
    Enforce reasonable password rules for admin accounts.

    Raises ValueError with a clear message when the password is too weak.
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not any(char.isalpha() for char in password):
        raise ValueError("Password must contain at least one letter")
    if not any(char.isdigit() for char in password):
        raise ValueError("Password must contain at least one digit")


def create_token(
    *,
    subject: uuid.UUID,
    token_type: TokenType,
    settings: Settings | None = None,
) -> str:
    """Create a signed JWT with minimal claims: sub, type, iat, exp."""
    cfg = settings or get_settings()
    now = datetime.now(UTC)

    if token_type == "access":
        expires_delta = timedelta(minutes=cfg.access_token_expire_minutes)
    else:
        expires_delta = timedelta(days=cfg.refresh_token_expire_days)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, cfg.jwt_secret_key, algorithm=cfg.jwt_algorithm)


def decode_token(
    token: str,
    *,
    expected_type: TokenType,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Decode and validate a JWT.

    Raises jwt.PyJWTError on invalid/expired tokens.
    Raises ValueError when token type does not match expected_type.
    """
    cfg = settings or get_settings()
    payload = jwt.decode(
        token,
        cfg.jwt_secret_key,
        algorithms=[cfg.jwt_algorithm],
    )
    token_type = payload.get("type")
    if token_type != expected_type:
        raise ValueError(f"Expected token type '{expected_type}', got '{token_type}'")
    if not payload.get("sub"):
        raise ValueError("Token missing subject")
    return payload


def normalize_email(email: str) -> str:
    """Trim whitespace and lowercase for consistent admin email handling."""
    return email.strip().lower()
