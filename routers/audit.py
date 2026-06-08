"""
routers/audit.py
Audit log read endpoint.

This router exposes a single protected endpoint that returns audit log entries
ordered from most recent to least recent (Requirements 15.3, 15.4):

* ``GET /api/audit`` — returns audit entries, guarded by the ``view_audit``
  permission (Admin only). Accepts an optional ``limit`` query parameter:
  when ``limit > 0``, return at most that many entries; when ``limit == 0``,
  return all entries.

The storage layer exposes no update or delete operation for audit rows, so the
API never offers a mutation path (Requirement 15.5). Audit writes happen via
``audit.service.write_audit`` at the point where the audited action occurs
(login/logout, camera/user/watchlist/license CRUD) — Requirements 15.1, 15.2.

Requirements: 15.3, 15.4, 15.5
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth.dependencies import AuthenticatedUser, require_permission
from audit.service import list_audit
from schemas import AuditEntryView

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditEntryView])
def get_audit_log(
    limit: Optional[int] = Query(100, ge=0, description="Number of entries to return; 0 returns all"),
    user: AuthenticatedUser = Depends(require_permission("view_audit")),
) -> list[AuditEntryView]:
    """Return audit log entries ordered from most recent to least recent.

    When ``limit > 0``, return at most that many entries (Requirement 15.3).
    When ``limit == 0``, return all entries (Requirement 15.4).

    Guarded by the ``view_audit`` permission (Admin only).

    Args:
        limit: The maximum number of entries to return. When 0, return all.
            Defaults to 100.
        user: The authenticated user, resolved by the ``require_permission``
            dependency. Must have the ``view_audit`` permission.

    Returns:
        A list of AuditEntryView objects, each containing: id, username, action,
        resource, outcome, timestamp.

    Raises:
        401 when unauthenticated.
        403 when the user lacks the ``view_audit`` permission.

    Example:
        GET /api/audit?limit=50
        GET /api/audit?limit=0  # all entries
    """
    entries = list_audit(limit if limit is not None else 100)
    return [
        AuditEntryView(
            id=int(e["id"]),
            username=e["username"],
            action=str(e["action"]),
            resource=e["resource"],
            outcome=str(e["outcome"]),
            timestamp=str(e["timestamp"]),
        )
        for e in entries
    ]
