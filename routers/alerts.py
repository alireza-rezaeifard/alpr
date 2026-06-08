"""
routers/alerts.py
Alert retrieval endpoint.

Alerts are raised when a detection matches an active watchlist entry. Viewing
them is a read-only operation, so the endpoint is gated by the ``view``
permission (held by every role) rather than ``manage_watchlists``
(Requirement 12.6).

Endpoint (design.md "Watchlist & Alerting Component"):
    * ``GET /api/alerts`` — list alerts most-recent-first (Requirement 12.6).

All errors use the standard ``{ error, code }`` envelope.

Requirements: 12.6
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from auth.dependencies import AuthenticatedUser, require_permission
from schemas import AlertView
from watchlist import service

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


# ---------------------------------------------------------------------------
# GET /api/alerts — list alerts most-recent-first (Requirement 12.6)
# ---------------------------------------------------------------------------
@router.get("", response_model=list[AlertView])
def list_alerts(
    _user: AuthenticatedUser = Depends(require_permission("view")),
) -> list[AlertView]:
    return [AlertView(**a) for a in service.list_alerts()]
