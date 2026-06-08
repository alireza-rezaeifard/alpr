"""License key encode/decode/validation (pure logic).

A License_Key is a signed, encoded credential carrying a claim set. The on-the-wire
format is::

    <payload>.<signature>

where ``payload`` is the base64url-encoded JSON claim set ``{"expiry", "camera_limit"}``
and ``signature`` is the base64url-encoded HMAC-SHA256 of the payload bytes computed with
the server secret. Verification is a pure decode-and-verify step: the server secret
prevents forgery, so any tampered or unsigned key fails to decode.

Requirements: 3.1, 3.2, 3.4
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import date, datetime

import db

# ---------------------------------------------------------------------------
# Server secret
# ---------------------------------------------------------------------------

# The secret used to sign/verify license keys. Override via the environment in
# production; the fallback keeps local development and tests deterministic.
_DEFAULT_SECRET = "anpr-dev-license-secret-change-me"


def _get_secret(secret: str | bytes | None = None) -> bytes:
    """Resolve the signing secret as bytes."""
    if secret is None:
        secret = os.environ.get("ANPR_LICENSE_SECRET", _DEFAULT_SECRET)
    if isinstance(secret, str):
        return secret.encode("utf-8")
    return secret


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

@dataclass
class LicenseClaims:
    """Decoded license claim set."""

    expiry: str        # ISO date, e.g. "2030-12-31"
    camera_limit: int


# ---------------------------------------------------------------------------
# base64url helpers (no padding on the wire)
# ---------------------------------------------------------------------------

def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload_b64: str, secret: bytes) -> str:
    digest = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(digest)


# ---------------------------------------------------------------------------
# Encode / decode
# ---------------------------------------------------------------------------

def encode_license_key(claims: LicenseClaims, secret: str | bytes | None = None) -> str:
    """Encode and sign a license key from claims (inverse of ``decode_license_key``)."""
    payload = {"expiry": claims.expiry, "camera_limit": claims.camera_limit}
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_json)
    signature = _sign(payload_b64, _get_secret(secret))
    return f"{payload_b64}.{signature}"


def decode_license_key(key: str, secret: str | bytes | None = None) -> LicenseClaims | None:
    """Decode and verify a license key.

    Returns the :class:`LicenseClaims` when the key is well-formed and its signature
    matches the server secret; returns ``None`` for any malformed, tampered, or forged
    key (Requirements 3.1, 3.2).
    """
    if not isinstance(key, str):
        return None

    parts = key.split(".")
    if len(parts) != 2:
        return None
    payload_b64, signature = parts
    if not payload_b64 or not signature:
        return None

    expected_signature = _sign(payload_b64, _get_secret(secret))
    # Constant-time comparison guards against timing-based forgery attempts.
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload_json = _b64url_decode(payload_b64)
        data = json.loads(payload_json)
    except (ValueError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    expiry = data.get("expiry")
    camera_limit = data.get("camera_limit")
    if not isinstance(expiry, str) or not expiry:
        return None
    # Reject bool explicitly: bool is a subclass of int in Python.
    if not isinstance(camera_limit, int) or isinstance(camera_limit, bool):
        return None

    return LicenseClaims(expiry=expiry, camera_limit=camera_limit)


# ---------------------------------------------------------------------------
# Validity
# ---------------------------------------------------------------------------

def _to_date(value) -> date | None:
    """Coerce a date/datetime/ISO-string into a date for comparison."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            try:
                return datetime.fromisoformat(value).date()
            except ValueError:
                return None
    return None


def _get_active_license_record() -> dict | None:
    """Return the most recent active license record, or ``None`` if none exists."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT id, key, active, expiry, camera_limit, activated_at "
            "FROM licenses WHERE active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def is_license_valid(now) -> bool:
    """Return ``True`` only when an active, unexpired license exists.

    A license is valid when an active record exists and its expiry date is not earlier
    than ``now`` (Requirements 3.3, 3.4). ``now`` may be a ``date``, ``datetime``, or ISO
    string.
    """
    record = _get_active_license_record()
    if record is None:
        return False

    expiry_date = _to_date(record.get("expiry"))
    now_date = _to_date(now)
    if expiry_date is None or now_date is None:
        return False

    return expiry_date >= now_date
