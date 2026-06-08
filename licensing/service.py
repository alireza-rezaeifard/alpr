"""
licensing/service.py
License activation, status, and limit enforcement against the database.

This module wires the pure license-key logic (``licensing.license_key``) to the
persistence layer (``db``). The on-the-wire key is decoded and verified, and the
resulting claim set is stored as the single active license record. The service
exposes:

* :func:`activate_license` — decode + verify a key, then store the active license
  with its expiry and camera limit, deactivating any prior license. Invalid keys
  are rejected with :class:`LicenseValidationError` and nothing is stored
  (Requirements 3.1, 3.2).
* :func:`get_license_status` — report activation state, expiry, camera limit, and
  the count of configured cameras (Requirement 3.5).
* :func:`get_camera_limit` — expose the active license's camera limit for the
  camera-start limit check (Requirement 3.6).

Activation and status are intentionally free of any license guard so they stay
reachable while no license exists (Requirement 3.7); that wiring lives in the
router.

Requirements: 3.1, 3.2, 3.5, 3.6, 3.7
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import db
from schemas import LicenseStatus

from .license_key import decode_license_key, is_license_valid


class LicenseValidationError(Exception):
    """Raised when a submitted license key fails validation (Requirement 3.2)."""


@dataclass
class License:
    """A stored license activation record."""

    id: int
    key: str
    active: bool
    expiry: str
    camera_limit: int
    activated_at: str


def activate_license(key: str, secret: str | bytes | None = None) -> License:
    """Validate ``key`` and store it as the single active license.

    The key is decoded and its signature verified; a malformed, tampered, or
    forged key yields :class:`LicenseValidationError` and no license is stored
    (Requirement 3.2). On success any prior active license is deactivated and a
    new active record is stored with the decoded expiry and camera limit
    (Requirement 3.1).
    """
    claims = decode_license_key(key, secret)
    if claims is None:
        raise LicenseValidationError("invalid or malformed license key")

    # At most one license is ever active: drop the previous one before storing.
    db.deactivate_licenses()
    record = db.insert_active_license(key, claims.expiry, claims.camera_limit)

    return License(
        id=int(record["id"]),
        key=str(record["key"]),
        active=bool(record["active"]),
        expiry=str(record["expiry"]),
        camera_limit=int(record["camera_limit"]),
        activated_at=str(record["activated_at"]),
    )


def get_license_status(now=None) -> LicenseStatus:
    """Return the current :class:`~schemas.LicenseStatus` (Requirement 3.5).

    ``active`` is true only when an active, unexpired license exists. The expiry
    and camera limit reflect the stored active record (even when it has expired,
    so callers can surface the expiry), and ``configured_cameras`` is the count of
    cameras in the cameras table. ``now`` defaults to today's date.
    """
    if now is None:
        now = date.today()

    record = db.get_active_license()
    configured_cameras = db.count_cameras()

    if record is None:
        return LicenseStatus(
            active=False,
            expiry=None,
            camera_limit=None,
            configured_cameras=configured_cameras,
        )

    return LicenseStatus(
        active=is_license_valid(now),
        expiry=str(record["expiry"]),
        camera_limit=int(record["camera_limit"]),
        configured_cameras=configured_cameras,
    )


def get_camera_limit() -> int | None:
    """Return the active license's camera limit, or ``None`` when none is active.

    Used by the camera-start limit check (Requirement 3.6) to learn the maximum
    number of concurrent cameras the active license permits.
    """
    record = db.get_active_license()
    if record is None:
        return None
    return int(record["camera_limit"])
