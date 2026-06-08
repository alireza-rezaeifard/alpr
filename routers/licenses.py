"""
routers/licenses.py
License management endpoints.

Two endpoints, both reachable while no license exists so the system can be
activated from a clean state (Requirement 3.7) — neither depends on
``require_license``:

* ``POST /api/licenses/activate`` — activate a license from a submitted key.
  Guarded by ``require_permission("manage_licenses")`` so only Admins may
  activate (Requirement 2.5). A key that fails validation is rejected with a
  ``validation_error`` envelope and nothing is stored (Requirements 3.1, 3.2).
* ``GET /api/licenses/status`` — report activation state, expiry, camera limit,
  and configured-camera count (Requirement 3.5). Guarded only by
  ``current_user`` so it is authenticated but never license-gated.

All errors use the standard ``{ error, code }`` envelope
(schemas.ErrorResponse / schemas.ErrorCode).

Requirements: 3.1, 3.2, 3.5, 3.7
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from auth.dependencies import AuthenticatedUser, current_user, require_permission
from audit.service import write_audit
from licensing import service
from licensing.service import LicenseValidationError
from schemas import ErrorCode, LicenseActivate, LicenseStatus

router = APIRouter(prefix="/api/licenses", tags=["licenses"])


def _envelope(message: str, code: ErrorCode) -> dict:
    return {"error": message, "code": code.value}


@router.post("/activate", response_model=LicenseStatus)
def activate(
    payload: LicenseActivate,
    user: AuthenticatedUser = Depends(require_permission("manage_licenses")),
) -> LicenseStatus:
    """Activate a license from a submitted key and return the resulting status.

    Rejects invalid keys with ``400`` ``validation_error`` and stores nothing
    (Requirement 3.2); on success stores the active license (Requirement 3.1).
    Logs the license activation attempt (Requirement 15.2).
    """
    try:
        service.activate_license(payload.key)
        write_audit(user.username, "activate_license", "license", "success")
    except LicenseValidationError as exc:
        write_audit(user.username, "activate_license", "license", "failure")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_envelope(str(exc), ErrorCode.VALIDATION_ERROR),
        )
    return service.get_license_status()


@router.get("/status", response_model=LicenseStatus)
def get_status(
    user: AuthenticatedUser = Depends(current_user),
) -> LicenseStatus:
    """Return the current license status (Requirement 3.5)."""
    return service.get_license_status()
