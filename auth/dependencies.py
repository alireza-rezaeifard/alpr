"""
auth/dependencies.py
FastAPI dependencies that wire the pure security/licensing logic into the
request pipeline.

The dependency chain enforces, in order, **authentication → authorization →
licensing** (design.md "Backend Request Pipeline"):

* :func:`current_user` extracts and verifies the Bearer token, loads the user,
  and yields the authenticated identity. It raises ``401`` for a missing token
  (``auth_required``) or an expired/invalid/revoked token or disabled account
  (``auth_failed``) — Requirements 1.4, 1.5, 1.6.
* :func:`require_permission` is a dependency factory that permits a request only
  when the user's *current* role holds the required permission, else ``403``
  (``forbidden``). Permission-less protected endpoints still depend on
  :func:`current_user`, so they are always authorization-checked —
  Requirements 2.2, 2.3, 2.4.
* :func:`require_license` guards detection and camera-start paths, raising
  ``license_required`` (no active license, Req 3.3), ``license_expired`` (past
  expiry, Req 3.4), or ``license_limit`` (camera-start beyond the limit,
  Req 3.6). Auth/activation/status endpoints are never license-gated (Req 3.7).

All errors are raised as ``HTTPException`` whose ``detail`` is the standard
``{ error, code }`` envelope (schemas.ErrorResponse / schemas.ErrorCode).

Requirements: 1.4, 1.5, 1.6, 2.2, 2.3, 2.4, 3.3, 3.4, 3.6, 3.7
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import db
from schemas import ErrorCode

from .rbac import Permission, Role, role_has_permission
from .security import AuthError, TokenClaims, get_secret, verify_session_token

# Bearer-token extractor. ``auto_error=False`` so we control the error envelope
# for the missing-token case (Requirement 1.6) instead of FastAPI's default.
_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Authenticated identity
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AuthenticatedUser:
    """The verified identity yielded by :func:`current_user`.

    ``role`` is the user's *current* role loaded from the database (not the
    role embedded in the token) so that role changes take effect on subsequent
    requests (Requirement 2.9). ``jti`` and ``token_exp`` are carried so the
    logout endpoint can revoke the presented token.
    """
    id: int
    username: str
    role: str
    disabled: bool
    jti: str
    token_exp: int


# ---------------------------------------------------------------------------
# Error helpers — every error uses the { error, code } envelope
# ---------------------------------------------------------------------------
def _envelope(message: str, code: ErrorCode) -> dict:
    return {"error": message, "code": code.value}


def _http_error(status_code: int, message: str, code: ErrorCode) -> HTTPException:
    return HTTPException(status_code=status_code, detail=_envelope(message, code))


# Map a token-rejection reason to its error envelope. A missing token is
# "authentication required" (Req 1.6); a present-but-bad token is an
# authentication failure (Req 1.5).
_AUTH_FAILED_MESSAGES = {
    "malformed": "invalid authentication token",
    "invalid_signature": "invalid authentication token",
    "expired": "authentication token has expired",
    "revoked": "authentication token has been revoked",
    "disabled": "user account is disabled",
}


# ---------------------------------------------------------------------------
# current_user — authentication (Requirements 1.4, 1.5, 1.6)
# ---------------------------------------------------------------------------
def current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    """Authenticate the request and return the :class:`AuthenticatedUser`.

    Raises ``401`` with code ``auth_required`` when no Bearer token is present
    (Requirement 1.6), and ``401`` with code ``auth_failed`` when the token is
    expired, invalid, revoked, or the account is disabled (Requirements 1.5,
    1.7, 1.8). A valid token establishes the authenticated identity
    (Requirement 1.4).
    """
    if credentials is None or not credentials.credentials:
        raise _http_error(
            status.HTTP_401_UNAUTHORIZED,
            "authentication required",
            ErrorCode.AUTH_REQUIRED,
        )

    result = verify_session_token(
        credentials.credentials,
        now=int(time.time()),
        secret=get_secret(),
        is_revoked=db.is_token_revoked,
        is_account_enabled=db.is_user_enabled,
    )

    if isinstance(result, AuthError):
        raise _http_error(
            status.HTTP_401_UNAUTHORIZED,
            _AUTH_FAILED_MESSAGES.get(result.reason, "authentication failed"),
            ErrorCode.AUTH_FAILED,
        )

    claims: TokenClaims = result
    user = db.get_user_by_id(claims.sub)
    # The account-enabled check in verify_session_token already guards the
    # common cases; this is a defensive re-check against races (account deleted
    # or disabled between the two lookups).
    if user is None or bool(user["disabled"]):
        raise _http_error(
            status.HTTP_401_UNAUTHORIZED,
            "user account is disabled",
            ErrorCode.AUTH_FAILED,
        )

    return AuthenticatedUser(
        id=int(user["id"]),
        username=str(user["username"]),
        role=str(user["role"]),
        disabled=bool(user["disabled"]),
        jti=claims.jti,
        token_exp=claims.exp,
    )


# ---------------------------------------------------------------------------
# require_permission — authorization (Requirements 2.2, 2.3, 2.4)
# ---------------------------------------------------------------------------
def require_permission(permission: Permission) -> Callable[..., AuthenticatedUser]:
    """Return a dependency that permits the request only if the role holds
    ``permission``.

    The returned dependency depends on :func:`current_user`, so authentication
    always runs first. It raises ``403`` with code ``forbidden`` when the user's
    current role lacks the permission (Requirement 2.3). Endpoints that define
    no specific permission still depend on :func:`current_user` directly, so
    every protected request is authorization-checked (Requirement 2.4).
    """

    def dependency(
        user: AuthenticatedUser = Depends(current_user),
    ) -> AuthenticatedUser:
        if not role_has_permission(user.role, permission):
            raise _http_error(
                status.HTTP_403_FORBIDDEN,
                "you do not have permission to perform this action",
                ErrorCode.FORBIDDEN,
            )
        return user

    return dependency


# ---------------------------------------------------------------------------
# require_license — licensing (Requirements 3.3, 3.4, 3.6, 3.7)
# ---------------------------------------------------------------------------
# Provider for the count of cameras currently occupying a concurrency slot,
# injected by the camera wiring (task 7.5 / 9.1) to avoid importing the camera
# manager singleton here. When unset, the camera-limit check is a no-op.
_running_camera_count_provider: Optional[Callable[[], int]] = None


def set_running_camera_count_provider(provider: Optional[Callable[[], int]]) -> None:
    """Register the function used to count running cameras for the limit check.

    Wiring code (the camera router/manager) calls this so :func:`require_license`
    can enforce the license camera limit (Requirement 3.6) without a hard
    dependency on the camera-manager singleton.
    """
    global _running_camera_count_provider
    _running_camera_count_provider = provider


def _running_camera_count() -> int:
    if _running_camera_count_provider is None:
        return 0
    return int(_running_camera_count_provider())


def _get_active_license() -> Optional[dict]:
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


def require_license(
    *,
    check_camera_limit: bool = False,
    running_count_provider: Optional[Callable[[], int]] = None,
) -> Callable[..., AuthenticatedUser]:
    """Return a dependency that guards license-gated operations.

    Use ``require_license()`` for detection paths and
    ``require_license(check_camera_limit=True)`` for camera-start paths.

    The dependency raises:
        * ``402`` ``license_required`` when no active license exists (Req 3.3),
        * ``402`` ``license_expired`` when the active license is past expiry
          (Req 3.4),
        * ``403`` ``license_limit`` when, for a camera-start, starting another
          camera would exceed the license camera limit (Req 3.6).

    It depends on :func:`current_user` so it is never reachable unauthenticated.
    Auth, license activation, and license status endpoints simply omit this
    dependency and so remain reachable while no license exists (Requirement 3.7).
    """
    from licensing.license_key import is_license_valid

    def dependency(
        user: AuthenticatedUser = Depends(current_user),
    ) -> AuthenticatedUser:
        record = _get_active_license()
        if record is None:
            raise _http_error(
                status.HTTP_402_PAYMENT_REQUIRED,
                "an active license is required to perform this action",
                ErrorCode.LICENSE_REQUIRED,
            )

        # An active record exists but its expiry has passed.
        if not is_license_valid(date.today()):
            raise _http_error(
                status.HTTP_402_PAYMENT_REQUIRED,
                "the active license has expired",
                ErrorCode.LICENSE_EXPIRED,
            )

        if check_camera_limit:
            limit = record.get("camera_limit")
            provider = running_count_provider or _running_camera_count
            running = int(provider())
            if limit is not None and running >= int(limit):
                raise _http_error(
                    status.HTTP_403_FORBIDDEN,
                    "starting this camera would exceed the license camera limit",
                    ErrorCode.LICENSE_LIMIT,
                )

        return user

    return dependency
