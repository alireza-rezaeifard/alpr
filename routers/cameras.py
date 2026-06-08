"""
routers/cameras.py
Camera management API: create, list, update, and delete camera definitions, plus
the license-guarded camera-start route.

Every endpoint is guarded by ``require_permission("manage_cameras")`` so only a
role holding that permission (Operator or Admin) may manage cameras
(Requirements 2.6, 4.1-4.5). The camera-start route additionally depends on
``require_license(check_camera_limit=True, ...)`` so that the **license
camera-limit check runs before** the ``CameraManager`` concurrency check
(Requirement 3.6): the dependency is evaluated before the route body, and only
the body invokes ``manager.start_camera`` (which performs the concurrency/FIFO
check).

Endpoints (this task — camera CRUD + start guard):
    * ``POST   /api/cameras``              — persist a camera and return it with
      its assigned id (Requirement 4.1).
    * ``GET    /api/cameras``              — list all cameras with their current
      status (Requirement 4.2).
    * ``PATCH  /api/cameras/{id}``         — update name / URL / skip-frame and
      return the updated camera; 404 on unknown id (Requirements 4.3, 4.4).
    * ``DELETE /api/cameras/{id}``         — stop any running processor, close its
      session, and remove the record; 404 on unknown id (Requirements 4.4, 4.5).
    * ``POST   /api/cameras/{id}/start``   — start a camera behind the license
      camera-limit check + permission (Requirements 3.6, 5.1, 5.2).

Skip-frame values are restricted to the inclusive range 1..1000 by the pydantic
``Field`` constraints on ``CameraCreate`` / ``CameraUpdate`` in ``schemas.py``
(Requirement 4.7).

The ``CameraManager`` is a process-wide singleton owned by ``api.py``; it is
injected via :func:`set_camera_manager` during app composition so this module
holds no hard dependency on the ML models or the global task registry. The
later concurrency-config task (9.4) extends this same router with the
concurrency-limit setter and the start/stop/start-all/stop-all routes; the
injection hook and helpers below are shared so that extension does not conflict.

All errors use the standard ``{ error, code }`` envelope (schemas.ErrorResponse /
schemas.ErrorCode).

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 3.6
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from auth.dependencies import (
    AuthenticatedUser,
    require_license,
    require_permission,
    set_running_camera_count_provider,
)
from audit.service import write_audit
from schemas import (
    CameraCreate,
    CameraUpdate,
    CameraView,
    ConcurrencyConfig,
    ConcurrencyView,
    ErrorCode,
    StartResult,
    StopResult,
)

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

# Statuses that occupy a concurrency slot, i.e. count as "running" for the
# license camera-limit check (Requirement 3.6).
_RUNNING_STATUSES = ("connecting", "connected", "streaming")


# ---------------------------------------------------------------------------
# Camera-manager injection
# ---------------------------------------------------------------------------
# The CameraManager singleton is created and owned by api.py (it needs the ML
# model loader and the shared task registry). It is injected here during app
# composition so this router has no hard dependency on those globals.
_manager = None


def set_camera_manager(manager) -> None:
    """Register the process-wide :class:`CameraManager` for the camera routes.

    Called once during app composition (api.py). Also wires the running-camera
    count provider used by :func:`require_license` so the license camera-limit
    check (Requirement 3.6) knows how many cameras currently occupy a slot.
    """
    global _manager
    _manager = manager
    set_running_camera_count_provider(running_camera_count)


def get_camera_manager():
    """Return the injected camera manager or raise if it was never wired."""
    if _manager is None:
        raise RuntimeError("camera manager has not been configured")
    return _manager


def running_camera_count() -> int:
    """Count cameras currently occupying a concurrency slot (Requirement 3.6).

    Used as the ``running_count_provider`` for the camera-start license check so
    the limit comparison happens before the manager's own concurrency check.
    """
    if _manager is None:
        return 0
    return sum(
        1 for c in _manager.list_cameras_view()
        if c.get("status") in _RUNNING_STATUSES
    )


def restore_cameras(manager=None) -> list[dict]:
    """Restore persisted cameras to their last-known status on startup (Req 4.6).

    Callable from the api.py lifespan. Loads every persisted camera into the
    manager's in-memory map. Cameras are restored to their last persisted state
    (``stopped`` by default — no real RTSP connection is opened here). Returns
    the restored camera views.
    """
    mgr = manager or _manager
    if mgr is None:
        return []
    mgr.restore_on_startup()
    return mgr.list_cameras_view()


# ---------------------------------------------------------------------------
# Error helpers — every error uses the { error, code } envelope
# ---------------------------------------------------------------------------
def _envelope(message: str, code: ErrorCode) -> dict:
    return {"error": message, "code": code.value}


def _http_error(status_code: int, message: str, code: ErrorCode) -> HTTPException:
    return HTTPException(status_code=status_code, detail=_envelope(message, code))


def _not_found(camera_id: int) -> HTTPException:
    return _http_error(
        status.HTTP_404_NOT_FOUND,
        f"no camera with id {camera_id}",
        ErrorCode.NOT_FOUND,
    )


# ---------------------------------------------------------------------------
# POST /api/cameras — create a camera (Requirement 4.1)
# ---------------------------------------------------------------------------
@router.post("", response_model=CameraView, status_code=status.HTTP_201_CREATED)
def create_camera(
    body: CameraCreate,
    user: AuthenticatedUser = Depends(require_permission("manage_cameras")),
) -> CameraView:
    """Persist a camera and return it with its assigned identifier.

    Skip-frame is constrained to 1..1000 by ``CameraCreate`` (Requirement 4.7).
    Logs the camera creation (Requirement 15.2).
    """
    view = get_camera_manager().add_camera(
        name=body.name,
        url=body.url,
        skip_frames=body.skip_frames,
    )
    write_audit(user.username, "create_camera", f"camera:{view['id']}", "success")
    return CameraView(**view)


# ---------------------------------------------------------------------------
# GET /api/cameras — list all cameras with status (Requirement 4.2)
# ---------------------------------------------------------------------------
@router.get("", response_model=list[CameraView])
def list_cameras(
    _user: AuthenticatedUser = Depends(require_permission("manage_cameras")),
) -> list[CameraView]:
    return [CameraView(**c) for c in get_camera_manager().list_cameras_view()]


# ---------------------------------------------------------------------------
# PATCH /api/cameras/{camera_id} — update name / URL / skip-frame (Req 4.3, 4.4)
# ---------------------------------------------------------------------------
@router.patch("/{camera_id}", response_model=CameraView)
def update_camera(
    camera_id: int,
    body: CameraUpdate,
    user: AuthenticatedUser = Depends(require_permission("manage_cameras")),
) -> CameraView:
    """Persist name/URL/skip-frame changes and return the updated camera.

    Returns ``404 not_found`` for an unknown id (Requirement 4.4). Skip-frame is
    constrained to 1..1000 by ``CameraUpdate`` (Requirement 4.7).
    Logs the camera update (Requirement 15.2).
    """
    view = get_camera_manager().update_camera_info(
        camera_id=camera_id,
        name=body.name,
        url=body.url,
        skip_frames=body.skip_frames,
    )
    if view is None:
        raise _not_found(camera_id)
    write_audit(user.username, "update_camera", f"camera:{camera_id}", "success")
    return CameraView(**view)


# ---------------------------------------------------------------------------
# DELETE /api/cameras/{camera_id} — stop, close session, remove (Req 4.4, 4.5)
# ---------------------------------------------------------------------------
@router.delete("/{camera_id}", status_code=status.HTTP_200_OK)
def delete_camera(
    camera_id: int,
    user: AuthenticatedUser = Depends(require_permission("manage_cameras")),
) -> dict:
    """Stop any running processor, close its session, and remove the record.

    Returns ``404 not_found`` for an unknown id (Requirement 4.4). The manager's
    ``remove_camera`` performs the stop-and-close side-effects (Requirement 4.5).
    Logs the camera deletion (Requirement 15.2).
    """
    removed = get_camera_manager().remove_camera(camera_id)
    if not removed:
        raise _not_found(camera_id)
    write_audit(user.username, "delete_camera", f"camera:{camera_id}", "success")
    return {"status": "deleted", "id": camera_id}


# ---------------------------------------------------------------------------
# POST /api/cameras/{camera_id}/start — start with license guard (Req 3.6, 5.1)
# ---------------------------------------------------------------------------
@router.post("/{camera_id}/start", response_model=StartResult)
def start_camera(
    camera_id: int,
    # Authentication -> authorization -> licensing (design "Backend Request
    # Pipeline"). Both dependencies are evaluated before the route body, so the
    # license camera-limit check runs before the manager's concurrency check
    # inside start_camera (Requirement 3.6).
    _perm: AuthenticatedUser = Depends(require_permission("manage_cameras")),
    _lic: AuthenticatedUser = Depends(
        require_license(
            check_camera_limit=True,
            running_count_provider=running_camera_count,
        )
    ),
) -> StartResult:
    """Start a camera, reporting status ``running`` or ``queued``.

    The license camera-limit check (Requirement 3.6) has already passed by the
    time this body runs; the manager then applies the concurrency limit and FIFO
    queueing (Requirements 5.1, 5.2). A missing camera yields ``404 not_found``.
    """
    result = get_camera_manager().start_camera(camera_id)
    if result.get("status") == "error":
        raise _not_found(camera_id)
    return StartResult(**result)


# ---------------------------------------------------------------------------
# Concurrency-limit configuration (Requirements 5.6, 5.7)
# ---------------------------------------------------------------------------
# Guarded by ``require_permission("manage_config")`` so only an Admin may change
# the limit. The setter relies on the pydantic ``ConcurrencyConfig`` Field
# (``ge=1, le=64``) so out-of-range values are rejected before the manager is
# touched; a defensive ``ValueError`` catch maps any limit the manager itself
# rejects to the same ``validation_error`` envelope (HTTP 422).
@router.get("/concurrency-limit", response_model=ConcurrencyView)
def get_concurrency_limit(
    _user: AuthenticatedUser = Depends(require_permission("manage_config")),
) -> ConcurrencyView:
    """Return the current concurrency limit (Requirement 5.6)."""
    return ConcurrencyView(concurrency_limit=get_camera_manager().get_limit())


@router.put("/concurrency-limit", response_model=ConcurrencyView)
def set_concurrency_limit(
    body: ConcurrencyConfig,
    _user: AuthenticatedUser = Depends(require_permission("manage_config")),
) -> ConcurrencyView:
    """Persist and apply a new concurrency limit in the inclusive range 1..64.

    The value is constrained to 1..64 by ``ConcurrencyConfig`` (Requirement 5.7),
    so an out-of-range request is rejected before this body runs. The
    ``ValueError`` guard maps any value the manager itself rejects to a
    ``validation_error`` envelope so out-of-range never silently slips through
    (Requirement 5.6).
    """
    manager = get_camera_manager()
    try:
        manager.set_concurrency_limit(body.value)
    except ValueError as exc:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            str(exc),
            ErrorCode.VALIDATION_ERROR,
        )
    return ConcurrencyView(concurrency_limit=manager.get_limit())


# ---------------------------------------------------------------------------
# POST /api/cameras/start-all — start every stopped camera (Requirement 5.4)
# ---------------------------------------------------------------------------
@router.post("/start-all", response_model=list[StartResult])
def start_all_cameras(
    _user: AuthenticatedUser = Depends(require_permission("manage_cameras")),
) -> list[StartResult]:
    """Attempt to start every stopped/error camera subject to the limit.

    The manager applies the concurrency limit and FIFO queueing, so cameras
    beyond the limit come back as ``queued`` (Requirement 5.4).
    """
    results = get_camera_manager().start_all()
    return [StartResult(**r) for r in results]


# ---------------------------------------------------------------------------
# POST /api/cameras/stop-all — stop every running camera (Requirement 5.5)
# ---------------------------------------------------------------------------
@router.post("/stop-all", response_model=StopResult)
def stop_all_cameras(
    _user: AuthenticatedUser = Depends(require_permission("manage_cameras")),
) -> StopResult:
    """Stop every running camera, close their sessions, and clear the queue.

    Delegates to the manager's ``stop_all`` which clears the FIFO queue so no
    queued camera is left waiting (Requirement 5.5).
    """
    get_camera_manager().stop_all()
    return StopResult(status="stopped")


# ---------------------------------------------------------------------------
# POST /api/cameras/{camera_id}/stop — stop one camera, promote queue (Req 5.3)
# ---------------------------------------------------------------------------
@router.post("/{camera_id}/stop", response_model=StopResult)
def stop_camera(
    camera_id: int,
    _user: AuthenticatedUser = Depends(require_permission("manage_cameras")),
) -> StopResult:
    """Stop a running or queued camera and promote the earliest-queued camera.

    Returns ``404 not_found`` for an unknown id. When a running slot is freed the
    manager promotes the earliest-queued camera (Requirement 5.3).
    """
    result = get_camera_manager().stop_camera(camera_id)
    if result.get("status") == "not_found":
        raise _not_found(camera_id)
    return StopResult(status=result.get("status", "stopped"))
