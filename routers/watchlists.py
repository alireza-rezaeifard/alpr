"""
routers/watchlists.py
Watchlist management endpoints.

Create/add/remove operations are guarded by
``require_permission("manage_watchlists")`` so only roles holding that
permission (Operator, Admin) may modify watchlists (Requirements 2.6, 12.1–12.3).
Listing watchlists requires the same management permission, since the lists
themselves are an operational concern.

Endpoints (design.md "Watchlist & Alerting Component"):
    * ``POST   /api/watchlists``                  — create a watchlist
      (name, list type) — Requirement 12.1.
    * ``GET    /api/watchlists``                  — list watchlists with their
      entries — Requirements 12.1, 12.2.
    * ``POST   /api/watchlists/{id}/entries``     — add an entry (plate value,
      optional label/reason) — Requirement 12.2.
    * ``DELETE /api/watchlists/entries/{entry_id}`` — remove an entry —
      Requirement 12.3.

The ``GET /api/alerts`` endpoint lives in ``routers/alerts.py`` (it is gated by
the read-only ``view`` permission rather than ``manage_watchlists``).

All errors use the standard ``{ error, code }`` envelope (schemas.ErrorResponse /
schemas.ErrorCode).

Requirements: 12.1, 12.2, 12.3
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from auth.dependencies import AuthenticatedUser, require_permission
from audit.service import write_audit
from schemas import ErrorCode, WatchlistEntryView, WatchlistView
from watchlist import service

router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class WatchlistCreate(BaseModel):
    """Body for creating a watchlist (Requirement 12.1)."""
    name: str = Field(..., min_length=1, max_length=150)
    list_type: str = Field(..., min_length=1, max_length=50)


class WatchlistEntryCreate(BaseModel):
    """Body for adding a watchlist entry (Requirement 12.2)."""
    plate_value: str = Field(..., min_length=1)
    label: str | None = Field(None, max_length=150)
    reason: str | None = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Error helpers — every error uses the { error, code } envelope
# ---------------------------------------------------------------------------
def _envelope(message: str, code: ErrorCode) -> dict:
    return {"error": message, "code": code.value}


def _http_error(status_code: int, message: str, code: ErrorCode) -> HTTPException:
    return HTTPException(status_code=status_code, detail=_envelope(message, code))


# ---------------------------------------------------------------------------
# POST /api/watchlists — create a watchlist (Requirement 12.1)
# ---------------------------------------------------------------------------
@router.post("", response_model=WatchlistView, status_code=status.HTTP_201_CREATED)
def create_watchlist(
    body: WatchlistCreate,
    user: AuthenticatedUser = Depends(require_permission("manage_watchlists")),
) -> WatchlistView:
    """Create a watchlist (Requirement 12.1).
    
    Logs the watchlist creation (Requirement 15.2).
    """
    created = service.create_watchlist(body.name, body.list_type)
    write_audit(user.username, "create_watchlist", f"watchlist:{created['id']}", "success")
    return WatchlistView(**created)


# ---------------------------------------------------------------------------
# GET /api/watchlists — list watchlists with their entries (Req 12.1, 12.2)
# ---------------------------------------------------------------------------
@router.get("", response_model=list[WatchlistView])
def list_watchlists(
    _user: AuthenticatedUser = Depends(require_permission("manage_watchlists")),
) -> list[WatchlistView]:
    return [WatchlistView(**wl) for wl in service.list_watchlists()]


# ---------------------------------------------------------------------------
# POST /api/watchlists/{watchlist_id}/entries — add an entry (Req 12.2)
# ---------------------------------------------------------------------------
@router.post(
    "/{watchlist_id}/entries",
    response_model=WatchlistEntryView,
    status_code=status.HTTP_201_CREATED,
)
def add_entry(
    watchlist_id: int,
    body: WatchlistEntryCreate,
    user: AuthenticatedUser = Depends(require_permission("manage_watchlists")),
) -> WatchlistEntryView:
    """Add an entry to a watchlist (Requirement 12.2).
    
    Logs the watchlist entry addition (Requirement 15.2).
    """
    if service.get_watchlist(watchlist_id) is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            f"no watchlist with id {watchlist_id}",
            ErrorCode.NOT_FOUND,
        )
    created = service.add_entry(
        watchlist_id,
        plate_value=body.plate_value,
        label=body.label,
        reason=body.reason,
    )
    write_audit(user.username, "add_watchlist_entry", f"watchlist:{watchlist_id}", "success")
    return WatchlistEntryView(**created)


# ---------------------------------------------------------------------------
# DELETE /api/watchlists/entries/{entry_id} — remove an entry (Req 12.3)
# ---------------------------------------------------------------------------
@router.delete("/entries/{entry_id}", status_code=status.HTTP_200_OK)
def remove_entry(
    entry_id: int,
    user: AuthenticatedUser = Depends(require_permission("manage_watchlists")),
) -> dict:
    """Remove a watchlist entry (Requirement 12.3).
    
    Logs the watchlist entry removal (Requirement 15.2).
    """
    if not service.remove_entry(entry_id):
        write_audit(user.username, "remove_watchlist_entry", f"entry:{entry_id}", "failure")
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            f"no watchlist entry with id {entry_id}",
            ErrorCode.NOT_FOUND,
        )
    write_audit(user.username, "remove_watchlist_entry", f"entry:{entry_id}", "success")
    return {"status": "deleted", "id": entry_id}
