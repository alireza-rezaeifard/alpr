"""
routers/retention.py
Data retention policy configuration API.

Exposes ``GET /api/config/retention`` and ``PUT /api/config/retention`` behind
``require_permission("manage_config")`` so only a role holding that permission
(Admin) may view or modify the retention policy (Requirements 2.2–2.4, 16.1).

Endpoints:
    * ``GET /api/config/retention``  — retrieve the current retention policy.
    * ``PUT /api/config/retention``  — set a new retention policy (days > 0).

A ``PUT`` request with ``days <= 0`` is rejected with a ``validation_error``
(Requirement 16.4).

All errors use the standard ``{ error, code }`` envelope (schemas.ErrorResponse /
schemas.ErrorCode).

Requirements: 16.1, 16.4
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from auth.dependencies import AuthenticatedUser, require_permission
from retention.service import RetentionPolicyError, set_retention_policy, get_retention_policy
from schemas import ErrorCode, RetentionConfig

router = APIRouter(prefix="/api/config", tags=["config"])


# ---------------------------------------------------------------------------
# Error helpers — every error uses the { error, code } envelope
# ---------------------------------------------------------------------------
def _envelope(message: str, code: ErrorCode) -> dict:
    return {"error": message, "code": code.value}


def _http_error(status_code: int, message: str, code: ErrorCode) -> HTTPException:
    return HTTPException(status_code=status_code, detail=_envelope(message, code))


# ---------------------------------------------------------------------------
# GET /api/config/retention — retrieve retention policy
# ---------------------------------------------------------------------------
@router.get("/retention", response_model=RetentionConfig)
def get_retention(
    _user: AuthenticatedUser = Depends(require_permission("manage_config")),
) -> RetentionConfig:
    """Retrieve the current retention policy (Requirement 16.1).

    Returns:
        A RetentionConfig with the current retention period in days. If no
        policy is configured, returns the database default (90 days).
    """
    days = get_retention_policy()
    # If no policy is explicitly configured, return the database default
    if days is None:
        # Per the design, we return 90 as the default (from db.get_retention_days)
        import db
        days = db.get_retention_days()
    return RetentionConfig(days=days)


# ---------------------------------------------------------------------------
# PUT /api/config/retention — set retention policy
# ---------------------------------------------------------------------------
@router.put("/retention", response_model=RetentionConfig)
def update_retention(
    body: RetentionConfig,
    _user: AuthenticatedUser = Depends(require_permission("manage_config")),
) -> RetentionConfig:
    """Set a new retention policy (Requirement 16.1).

    Requirement 16.4: reject ``days <= 0`` with a validation error.

    Args:
        body: A RetentionConfig with the desired retention period in days.

    Returns:
        The updated RetentionConfig.

    Raises:
        HTTPException: 422 validation_error when ``days <= 0``.
    """
    try:
        set_retention_policy(body.days)
    except RetentionPolicyError as exc:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            str(exc),
            ErrorCode.VALIDATION_ERROR,
        )
    return RetentionConfig(days=body.days)
