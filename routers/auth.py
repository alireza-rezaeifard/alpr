"""
routers/auth.py
Authentication endpoints and the first-run default-admin bootstrap.

This router exposes the three session-lifecycle endpoints and is never
license-gated (design.md "Backend Request Pipeline"):

* ``POST /api/auth/login`` validates credentials against a stored account and,
  on success, issues a signed session token together with the role, expiry, and
  the permission set for that role (Requirement 1.1). Invalid credentials and
  disabled accounts are rejected uniformly with ``auth_failed`` so the response
  does not reveal which accounts exist (Requirements 1.2, 1.8).
* ``POST /api/auth/logout`` revokes the presented token's ``jti`` so subsequent
  requests using it are rejected (Requirement 1.7).
* ``GET /api/auth/me`` returns the authenticated user's public profile.

``bootstrap_default_admin()`` creates a single default Admin account the first
time the system starts with an empty users table (Requirement 1.9). It is
called from the application lifespan in ``api.py`` after ``init_db()``.

Requirements: 1.1, 1.2, 1.7, 1.8, 1.9
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

import db
from schemas import ErrorCode, LoginResponse, UserView

from audit.service import write_audit
from auth.dependencies import AuthenticatedUser, current_user
from auth.rbac import ROLE_PERMISSIONS
from auth.security import (
    create_session_token,
    hash_password,
    revoke_token,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Session token lifetime in seconds (8 hours). Long enough for a working shift,
# short enough that a leaked token is not valid indefinitely.
SESSION_TTL_SECONDS = 8 * 60 * 60

# Default Admin account created on first run when no users exist (Requirement
# 1.9). These credentials are intended to be changed immediately after the
# first login; they exist only so the system is reachable out of the box.
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"


class LoginRequest(BaseModel):
    """Credentials submitted at login (Requirement 1.1)."""
    username: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=1)


def _envelope(message: str, code: ErrorCode) -> dict:
    return {"error": message, "code": code.value}


def _auth_failed() -> HTTPException:
    # A single, indistinguishable failure for unknown users, wrong passwords,
    # and disabled accounts (Requirements 1.2, 1.8) — avoids account enumeration.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_envelope("invalid username or password", ErrorCode.AUTH_FAILED),
    )


def _permissions_for(role: str) -> list[str]:
    """Return the sorted permission names granted to *role* (empty if unknown)."""
    return sorted(ROLE_PERMISSIONS.get(role, frozenset()))


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    """Authenticate a user and issue a session token (Requirements 1.1, 1.2, 1.8).

    Rejects unknown usernames, wrong passwords, and disabled accounts with the
    same ``auth_failed`` response so callers cannot probe which accounts exist.
    Logs successful and failed login attempts (Requirement 15.1).
    """
    user = db.get_user_by_username(body.username)
    if user is None:
        write_audit(body.username, "login", None, "failure")
        raise _auth_failed()

    if not verify_password(body.password, str(user["password_hash"])):
        write_audit(body.username, "login", None, "failure")
        raise _auth_failed()

    if bool(user["disabled"]):
        write_audit(body.username, "login", None, "failure")
        raise _auth_failed()

    role = str(user["role"])
    token = create_session_token(int(user["id"]), role, SESSION_TTL_SECONDS)
    expires_at = datetime.now(timezone.utc).timestamp() + SESSION_TTL_SECONDS
    expires_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

    write_audit(body.username, "login", None, "success")

    return LoginResponse(
        token=token,
        role=role,
        expires_at=expires_iso,
        permissions=_permissions_for(role),
    )


@router.post("/logout")
def logout(user: AuthenticatedUser = Depends(current_user)) -> dict:
    """Revoke the presented token so it can no longer be used (Requirement 1.7).
    
    Logs the logout action (Requirement 15.1).
    """
    revoke_token(user.jti, user.token_exp)
    write_audit(user.username, "logout", None, "success")
    return {"status": "ok"}


@router.get("/me", response_model=UserView)
def me(user: AuthenticatedUser = Depends(current_user)) -> UserView:
    """Return the authenticated user's public profile."""
    record = db.get_user_by_id(user.id)
    if record is None:
        # Defensive: the account vanished between authentication and this lookup.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_envelope("user account is disabled", ErrorCode.AUTH_FAILED),
        )
    return UserView(
        id=int(record["id"]),
        username=str(record["username"]),
        role=str(record["role"]),
        disabled=bool(record["disabled"]),
        created_at=str(record["created_at"]),
    )


def bootstrap_default_admin() -> bool:
    """Create one default Admin account when the users table is empty (Req 1.9).

    Safe to call on every startup: it does nothing once any user exists. Returns
    ``True`` when the default account was created, ``False`` otherwise.

    The default credentials are ``admin`` / ``admin`` and SHOULD be changed
    immediately after the first login.
    """
    if db.count_users() > 0:
        return False
    db.create_user(
        DEFAULT_ADMIN_USERNAME,
        hash_password(DEFAULT_ADMIN_PASSWORD),
        "Admin",
    )
    logger.warning(
        "Created default Admin account '%s' with the default password. "
        "Change this password immediately.",
        DEFAULT_ADMIN_USERNAME,
    )
    return True
