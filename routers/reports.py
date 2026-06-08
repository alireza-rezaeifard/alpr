"""
routers/reports.py
Detection reporting and analytics endpoints.

This router exposes the seven reporting endpoints required by Requirement 13
(Detection Reporting and Analytics). All endpoints reuse the existing query
functions in ``db.py`` and are behind the ``view`` permission (Viewer, Operator,
and Admin roles).

**Endpoints:**

* ``GET /api/reports/detections`` — paginated, filtered, searchable detection list
  with a total count (Req 13.1, 13.2).
* ``GET /api/reports/timeline`` — per-day detection counts over a day range
  (Req 13.3).
* ``GET /api/reports/stats`` — aggregate detection and session statistics
  (Req 13.4).
* ``GET /api/reports/source-distribution`` — detection counts grouped by source
  type (Req 13.5).
* ``GET /api/reports/confidence-distribution`` — detection counts grouped by
  confidence bins (Req 13.6).
* ``GET /api/reports/sessions`` — session history ordered most-recent-first
  (Req 13.7).

Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

import db
from auth.dependencies import AuthenticatedUser, require_permission

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/detections")
def list_detections(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    source_type: str | None = Query(None),
    search: str | None = Query(None),
    _user: AuthenticatedUser = Depends(require_permission("view")),
) -> dict[str, Any]:
    """Return paginated, filtered, searchable detections with a total count.

    **Parameters:**
        * ``limit`` — page size, restricted to 1..1000 (Req 13.2)
        * ``offset`` — row offset for pagination (Req 13.1)
        * ``source_type`` — optional filter by source type (e.g. 'image', 'video',
          'rtsp', 'camera') or ``None`` / 'all' for all types (Req 13.1)
        * ``search`` — optional search term matched against ``plate_dtrb`` and
          ``plate_persian`` columns (Req 13.1)

    **Returns:**
        A dict ``{ detections: list[dict], total: int }`` where ``detections``
        holds the matching rows (ordered newest-first) and ``total`` is the
        matching row count before pagination, allowing the client to build a
        page-control UI (Req 13.1).

    **Permission:** ``view`` (Viewer, Operator, Admin).

    Requirements: 13.1, 13.2
    """
    detections, total = db.get_all_detections(
        limit=limit,
        offset=offset,
        source_type=source_type,
        search=search,
    )
    return {"detections": detections, "total": total}


@router.get("/timeline")
def detection_timeline(
    days: int = Query(7, ge=1, le=90),
    _user: AuthenticatedUser = Depends(require_permission("view")),
) -> dict[str, Any]:
    """Return per-day detection counts over the past ``days`` (Req 13.3).

    **Parameters:**
        * ``days`` — number of days to include, restricted to 1..90 (Req 13.3)

    **Returns:**
        A dict ``{ timeline: list[dict] }`` where each timeline entry is
        ``{ dt: str, cnt: int }`` with ``dt`` as the ISO date (YYYY-MM-DD) and
        ``cnt`` as the detection count for that day. Ordered oldest-to-newest.

    **Permission:** ``view`` (Viewer, Operator, Admin).

    Requirements: 13.3
    """
    timeline = db.get_detections_timeline(days=days)
    return {"timeline": timeline}


@router.get("/stats")
def aggregate_stats(
    _user: AuthenticatedUser = Depends(require_permission("view")),
) -> dict[str, Any]:
    """Return aggregate detection and session statistics (Req 13.4).

    **Returns:**
        A dict containing:
            * ``total_detections`` — total detection count
            * ``unique_plates`` — distinct plate count
            * ``avg_confidence`` — average confidence (rounded to 4 decimals)
            * ``total_sessions`` — total session count
            * ``sessions_7d`` — session count in the past 7 days
            * ``detections_7d`` — detection count in the past 7 days

        All as specified in ``db.get_stats()``.

    **Permission:** ``view`` (Viewer, Operator, Admin).

    Requirements: 13.4
    """
    stats = db.get_stats()
    return stats


@router.get("/source-distribution")
def source_distribution(
    _user: AuthenticatedUser = Depends(require_permission("view")),
) -> dict[str, Any]:
    """Return detection counts grouped by source type (Req 13.5).

    **Returns:**
        A dict ``{ distribution: list[dict] }`` where each distribution entry is
        ``{ source_type: str, cnt: int }`` with ``source_type`` as the detection
        source (e.g. 'image', 'video', 'rtsp', 'camera') and ``cnt`` as the count.

    **Permission:** ``view`` (Viewer, Operator, Admin).

    Requirements: 13.5
    """
    distribution = db.get_source_distribution()
    return {"distribution": distribution}


@router.get("/confidence-distribution")
def confidence_distribution(
    _user: AuthenticatedUser = Depends(require_permission("view")),
) -> dict[str, Any]:
    """Return detection counts grouped by confidence bins (Req 13.6).

    **Returns:**
        A dict ``{ distribution: list[dict] }`` where each distribution entry is
        ``{ bin: float, cnt: int }`` with ``bin`` as the rounded confidence value
        (0.1 resolution) and ``cnt`` as the count. Ordered by bin ascending.

    **Permission:** ``view`` (Viewer, Operator, Admin).

    Requirements: 13.6
    """
    distribution = db.get_confidence_distribution()
    return {"distribution": distribution}


@router.get("/sessions")
def session_history(
    limit: int = Query(20, ge=1),
    _user: AuthenticatedUser = Depends(require_permission("view")),
) -> dict[str, Any]:
    """Return session history ordered most-recent-first (Req 13.7).

    **Parameters:**
        * ``limit`` — maximum number of sessions to return (positive integer,
          default 20)

    **Returns:**
        A dict ``{ sessions: list[dict] }`` where each session entry contains
        the fields ``id``, ``source_type``, ``source_file``, ``started_at``,
        ``ended_at``, ``total_frames``, ``total_plates``, ``unique_plates``,
        and ``status``. Ordered from most recent to least recent (by id DESC).

    **Permission:** ``view`` (Viewer, Operator, Admin).

    Requirements: 13.7
    """
    sessions = db.get_sessions_history(limit=limit)
    return {"sessions": sessions}
