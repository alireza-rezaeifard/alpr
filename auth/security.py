"""
auth/security.py
Password hashing and session-token signing/verification.

This module holds the pure security primitives for the ANPR system:

* Password hashing uses a salted, one-way ``bcrypt`` hash via ``passlib``
  (Requirement 1.3) - never a hand-rolled scheme.
* Session tokens are stateless, JWT-style tokens carrying ``sub`` (user id),
  ``role``, ``jti`` (token id), ``iat`` and ``exp``, signed with an HMAC
  server secret (HMAC-SHA256). Verification is pure except for two lookups:
  the revocation set and the account-enabled check, both of which are
  injectable so the logic can be tested without a database.

Requirements: 1.1, 1.3, 1.4, 1.5, 1.7
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Callable, Optional, Union

from passlib.context import CryptContext

# ---------------------------------------------------------------------------
# Password hashing (Requirement 1.3)
# ---------------------------------------------------------------------------
# passlib manages per-password salts and the bcrypt work factor internally.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return a salted one-way hash of *plain* (Requirement 1.3).

    Each call generates a fresh random salt, so two hashes of the same
    password differ. The plaintext can never be recovered from the result.
    """
    if not isinstance(plain, str):
        raise TypeError("password must be a string")
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the previously stored *hashed* value.

    Returns False (rather than raising) for malformed or non-matching hashes
    so callers can treat verification failure uniformly.
    """
    if not isinstance(plain, str) or not isinstance(hashed, str):
        return False
    try:
        return _pwd_context.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Token claims and errors
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TokenClaims:
    """Decoded, verified session-token claims (design.md Data Models)."""
    sub: int          # user id
    role: str         # Admin|Operator|Viewer
    jti: str          # token id (for revocation)
    iat: int          # issued-at (unix seconds)
    exp: int          # expiry (unix seconds)


@dataclass(frozen=True)
class AuthError:
    """Returned by :func:`verify_session_token` when a token is rejected.

    ``reason`` is one of: ``malformed``, ``invalid_signature``, ``expired``,
    ``revoked``, ``disabled``.
    """
    reason: str


# ---------------------------------------------------------------------------
# Server secret
# ---------------------------------------------------------------------------
_SECRET_CACHE: Optional[str] = None


def get_secret() -> str:
    """Resolve the HMAC server secret used to sign session tokens.

    Resolution order:
        1. ``ANPR_SECRET_KEY`` environment variable (operator-supplied).
        2. A random secret persisted in ``app_config`` (survives restarts).

    The result is cached for the process lifetime.
    """
    global _SECRET_CACHE
    env = os.environ.get("ANPR_SECRET_KEY")
    if env:
        return env
    if _SECRET_CACHE is None:
        import db
        _SECRET_CACHE = db.get_or_create_session_secret()
    return _SECRET_CACHE


# ---------------------------------------------------------------------------
# base64url helpers (no padding, JWT-style)
# ---------------------------------------------------------------------------
def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


_HEADER_SEGMENT = _b64url_encode(
    json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8")
)


def _sign(signing_input: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return _b64url_encode(sig)


# ---------------------------------------------------------------------------
# Token creation / verification (Requirements 1.1, 1.4, 1.5, 1.7)
# ---------------------------------------------------------------------------
def create_session_token(
    user_id: int,
    role: str,
    ttl: int,
    *,
    now: Optional[int] = None,
    jti: Optional[str] = None,
    secret: Optional[str] = None,
) -> str:
    """Create a signed session token for *user_id* / *role* (Requirement 1.1).

    Args:
        user_id: the subject (``sub``) the token authenticates.
        role: the user's role, embedded for authorization.
        ttl: time-to-live in seconds; the token expires ``ttl`` seconds after
            issuance. Must be positive.
        now: issue time (unix seconds); defaults to the current time.
        jti: token id; a random one is generated when omitted.
        secret: signing secret; resolved from :func:`get_secret` when omitted.

    Returns:
        A compact ``header.payload.signature`` token string.
    """
    if ttl <= 0:
        raise ValueError("ttl must be positive")
    issued = int(now if now is not None else time.time())
    token_id = jti if jti is not None else secrets.token_urlsafe(16)
    key = secret if secret is not None else get_secret()

    payload = {
        "sub": int(user_id),
        "role": role,
        "jti": token_id,
        "iat": issued,
        "exp": issued + int(ttl),
    }
    payload_segment = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{_HEADER_SEGMENT}.{payload_segment}".encode("ascii")
    signature = _sign(signing_input, key)
    return f"{_HEADER_SEGMENT}.{payload_segment}.{signature}"


def verify_session_token(
    token: str,
    *,
    now: Optional[int] = None,
    secret: Optional[str] = None,
    is_revoked: Optional[Callable[[str], bool]] = None,
    is_account_enabled: Optional[Callable[[int], bool]] = None,
) -> Union[TokenClaims, AuthError]:
    """Verify *token* and return its claims, or an :class:`AuthError`.

    Checks, in order: structural validity, HMAC signature, expiry
    (Requirement 1.5), revocation (Requirement 1.7), and that the account is
    enabled (Requirement 1.8). A valid token yields :class:`TokenClaims`,
    establishing the authenticated identity (Requirement 1.4).

    The two side-effecting checks are injectable for testing:
        is_revoked(jti) -> bool       (default: ``db.is_token_revoked``)
        is_account_enabled(sub) -> bool (default: ``db.is_user_enabled``)
    """
    if not isinstance(token, str):
        return AuthError("malformed")

    parts = token.split(".")
    if len(parts) != 3:
        return AuthError("malformed")
    header_segment, payload_segment, signature_segment = parts

    key = secret if secret is not None else get_secret()
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    expected_sig = _sign(signing_input, key)
    # Constant-time comparison to avoid signature timing leaks.
    if not hmac.compare_digest(expected_sig, signature_segment):
        return AuthError("invalid_signature")

    try:
        payload = json.loads(_b64url_decode(payload_segment))
    except (ValueError, json.JSONDecodeError):
        return AuthError("malformed")

    if not isinstance(payload, dict):
        return AuthError("malformed")
    required = ("sub", "role", "jti", "iat", "exp")
    if any(field not in payload for field in required):
        return AuthError("malformed")

    try:
        claims = TokenClaims(
            sub=int(payload["sub"]),
            role=str(payload["role"]),
            jti=str(payload["jti"]),
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
        )
    except (ValueError, TypeError):
        return AuthError("malformed")

    current = int(now if now is not None else time.time())
    if current >= claims.exp:
        return AuthError("expired")

    revoked_check = is_revoked if is_revoked is not None else _default_is_revoked
    if revoked_check(claims.jti):
        return AuthError("revoked")

    enabled_check = (
        is_account_enabled if is_account_enabled is not None else _default_is_enabled
    )
    if not enabled_check(claims.sub):
        return AuthError("disabled")

    return claims


def revoke_token(jti: str, exp: int) -> None:
    """Add a token id to the revocation set so it is rejected (Requirement 1.7).

    *exp* is stored so the entry can later be purged once the token would have
    expired anyway.
    """
    import db
    db.add_revoked_token(jti, int(exp))


# ---------------------------------------------------------------------------
# Default DB-backed lookups (kept thin so the logic above stays testable)
# ---------------------------------------------------------------------------
def _default_is_revoked(jti: str) -> bool:
    import db
    return db.is_token_revoked(jti)


def _default_is_enabled(user_id: int) -> bool:
    import db
    return db.is_user_enabled(user_id)
