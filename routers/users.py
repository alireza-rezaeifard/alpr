"""
routers/users.py
User management API: create, list, update, and delete user accounts.

Every endpoint is guarded by ``require_permission("manage_users")`` so only a
role holding that permission (Admin) may manage users (Requirements 2.2–2.4).

Endpoints (design.md "User Management"):
    * ``POST   /api/users``        — create a user with username, initial
      password, and role (Requirement 2.8).
    * ``GET    /api/users``        — list all user accounts.
    * ``PATCH  /api/users/{id}``   — change role, enable/disable, or reset the
      password. Role changes take effect on the user's subsequent requests
      because ``current_user`` loads the role from the database each request
      (Requirement 2.9).
    * ``DELETE /api/users/{id}``   — delete a user account.

Last-admin protection (Requirement 2.10): a delete, a disable, or a role change
away from Admin is rejected with a ``validation_error`` when it would reduce the
number of enabled Admin accounts to zero.

All errors use the standard ``{ error, code }`` envelope (schemas.ErrorResponse /
schemas.ErrorCode).

Requirements: 2.8, 2.9, 2.10
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

import db
from audit.service import write_audit
from auth.dependencies import AuthenticatedUser, require_permission
from auth.rbac import ROLES
from auth.security import hash_password
from schemas import ErrorCode, UserView

router = APIRouter(prefix="/api/users", tags=["users"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class UserCreate(BaseModel):
    """Body for creating a user (Requirement 2.8)."""
    username: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=1)
    role: str


class UserUpdate(BaseModel):
    """Body for updating a user: any subset of role, disabled, password."""
    role: str | None = None
    disabled: bool | None = None
    password: str | None = Field(None, min_length=1)


# ---------------------------------------------------------------------------
# Error helpers — every error uses the { error, code } envelope
# ---------------------------------------------------------------------------
def _envelope(message: str, code: ErrorCode) -> dict:
    return {"error": message, "code": code.value}


def _http_error(status_code: int, message: str, code: ErrorCode) -> HTTPException:
    return HTTPException(status_code=status_code, detail=_envelope(message, code))


def _validate_role(role: str) -> None:
    """Reject a role that is not one of the supported roles (Requirement 2.1)."""
    if role not in ROLES:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"role must be one of {', '.join(ROLES)}",
            ErrorCode.VALIDATION_ERROR,
        )


def _is_enabled_admin(role: str, disabled: bool) -> bool:
    return role == "Admin" and not disabled


# ---------------------------------------------------------------------------
# POST /api/users — create a user (Requirement 2.8)
# ---------------------------------------------------------------------------
@router.post("", response_model=UserView, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    user: AuthenticatedUser = Depends(require_permission("manage_users")),
) -> UserView:
    """Create a user account (Requirement 2.8).
    
    Logs the user creation (Requirement 15.2).
    """
    _validate_role(body.role)
    try:
        created = db.create_user(body.username, hash_password(body.password), body.role)
        write_audit(user.username, "create_user", f"user:{body.username}", "success")
    except sqlite3.IntegrityError:
        write_audit(user.username, "create_user", f"user:{body.username}", "failure")
        raise _http_error(
            status.HTTP_409_CONFLICT,
            f"a user named '{body.username}' already exists",
            ErrorCode.CONFLICT,
        )
    return UserView(**created)


# ---------------------------------------------------------------------------
# GET /api/users — list all users
# ---------------------------------------------------------------------------
@router.get("", response_model=list[UserView])
def list_users(
    _user: AuthenticatedUser = Depends(require_permission("manage_users")),
) -> list[UserView]:
    return [UserView(**u) for u in db.list_users()]


# ---------------------------------------------------------------------------
# PATCH /api/users/{user_id} — update role / enable-disable / password
# ---------------------------------------------------------------------------
@router.patch("/{user_id}", response_model=UserView)
def update_user(
    user_id: int,
    body: UserUpdate,
    user: AuthenticatedUser = Depends(require_permission("manage_users")),
) -> UserView:
    """Update a user account (Requirement 2.9).
    
    Logs the user update (Requirement 15.2).
    """
    existing = db.get_user_by_id(user_id)
    if existing is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            f"no user with id {user_id}",
            ErrorCode.NOT_FOUND,
        )

    if body.role is not None:
        _validate_role(body.role)

    # Last-admin protection (Requirement 2.10): reject a disable or a role change
    # away from Admin that would drop the enabled-Admin count to zero.
    new_role = body.role if body.role is not None else str(existing["role"])
    new_disabled = (
        body.disabled if body.disabled is not None else bool(existing["disabled"])
    )
    counted_before = _is_enabled_admin(str(existing["role"]), bool(existing["disabled"]))
    counted_after = _is_enabled_admin(new_role, new_disabled)
    if counted_before and not counted_after and db.count_enabled_admins() <= 1:
        write_audit(user.username, "update_user", f"user:{user_id}", "failure")
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "cannot disable or change the role of the last enabled Admin account",
            ErrorCode.VALIDATION_ERROR,
        )

    password_hash = hash_password(body.password) if body.password is not None else None
    updated = db.update_user(
        user_id,
        role=body.role,
        disabled=body.disabled,
        password_hash=password_hash,
    )
    write_audit(user.username, "update_user", f"user:{user_id}", "success")
    return UserView(**updated)


# ---------------------------------------------------------------------------
# DELETE /api/users/{user_id} — delete a user account
# ---------------------------------------------------------------------------
@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
def delete_user(
    user_id: int,
    user: AuthenticatedUser = Depends(require_permission("manage_users")),
) -> dict:
    """Delete a user account (Requirement 2.10).
    
    Logs the user deletion (Requirement 15.2).
    """
    existing = db.get_user_by_id(user_id)
    if existing is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            f"no user with id {user_id}",
            ErrorCode.NOT_FOUND,
        )

    # Last-admin protection (Requirement 2.10): deleting the last enabled Admin
    # would leave zero enabled Admins.
    if _is_enabled_admin(str(existing["role"]), bool(existing["disabled"])) and (
        db.count_enabled_admins() <= 1
    ):
        write_audit(user.username, "delete_user", f"user:{user_id}", "failure")
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "cannot delete the last enabled Admin account",
            ErrorCode.VALIDATION_ERROR,
        )

    db.delete_user(user_id)
    write_audit(user.username, "delete_user", f"user:{user_id}", "success")
    return {"status": "deleted", "id": user_id}
