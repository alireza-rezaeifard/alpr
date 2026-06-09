"""
Integration tests for camera / live-stream side-effects (task 9.7).

Feature: anpr-system-redesign

Covers:
    * Camera delete side-effects (Req 4.5): deleting a running Camera stops its
      processor, closes its Session, and removes the Camera record.
    * Running-processor error side-effects (Req 5.8): when a running processor
      enters an error state, the Camera_Manager sets the Camera status to error,
      closes its Session, and promotes the earliest-queued Camera.
    * Unknown-id not-found (Req 4.4 / 6.3): delete/stop of an unknown Camera id
      reports not-found.
    * Live MJPEG stream delivery (Req 6.1) and latest-frame delivery (Req 6.2),
      plus not-found for an unknown task id (Req 6.3).

Layer under test (documented per task note):
    * Delete / error / promotion side-effects and the unknown-id not-found for
      camera delete/stop are tested at the **CameraManager** layer (with the
      backing **db.py** session/camera tables verified directly), because that
      is where Req 4.5 / 5.8 side-effects are implemented.
    * MJPEG + latest-frame delivery and the unknown-task not-found are tested at
      the **api.py** layer via FastAPI's TestClient. The live-stream endpoints
      (``/api/detect/rtsp/{task_id}/mjpeg`` and ``.../frame``) currently live in
      ``api.py`` and have NOT yet been migrated into a ``routers/`` module behind
      the view-streams permission (that wiring is deferred to the Flutter/router
      tasks). So delivery + not-found are validated at the layer that exists
      today; the view-permission guard is intentionally not asserted here.

Testing notes (per spec): a MOCKED processor stands in for the real
RTSPStreamProcessor so no RTSP I/O or ML inference runs; a temporary SQLite
database backs all session/camera bookkeeping.
"""
from __future__ import annotations

import os
import sys
import threading

import pytest

# Ensure the project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import video_processor
import camera_manager
from camera_manager import CameraManager


# Manager statuses that occupy a concurrency slot ("running").
RUNNING_STATES = ("connecting", "connected", "streaming")

# Capture the genuine watcher implementation BEFORE any monkeypatch replaces it,
# so the error-state test can drive the real promotion logic deterministically
# (without the background daemon thread).
ORIGINAL_WATCH = CameraManager._watch_processor


# ---------------------------------------------------------------------------
# Fake processor used by the CameraManager-layer tests
# ---------------------------------------------------------------------------
class FakeProcessor:
    """Deterministic stand-in for RTSPStreamProcessor (no thread / no OpenCV).

    ``start()`` flips to a running state instantly; ``stop()`` records that it
    was stopped so delete/stop side-effects can be asserted. ``status`` is a
    plain attribute the error-state test can mutate to simulate a fault.
    """

    def __init__(self, *args, **kwargs):
        self.lock = threading.Lock()
        self.status = "initialized"
        self.running = False
        self.stop_count = 0
        self.plate_history = []
        self.live_detections = []

    def start(self):
        with self.lock:
            self.running = True
            self.status = "streaming"
        return True

    def stop(self):
        with self.lock:
            self.running = False
            self.status = "stopped"
            self.stop_count += 1

    def get_state(self):
        with self.lock:
            return {
                "running": self.running,
                "status": self.status,
                "history": list(self.plate_history),
                "live_detections": list(self.live_detections),
            }


@pytest.fixture()
def cm_env(tmp_path, monkeypatch):
    """Temp SQLite DB + mocked processor + neutralised background watcher.

    The watcher daemon is replaced with a no-op so status transitions stay
    synchronous; the error-state test invokes the *real* watcher logic
    (``ORIGINAL_WATCH``) explicitly when it needs the promotion path.
    """
    path = str(tmp_path / "camera_stream_integration.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()

    # Mock the processor so starting a camera is instantaneous and side-effect
    # free. `_start_processor_locked` does `from video_processor import
    # RTSPStreamProcessor`, which reads this attribute at call time.
    monkeypatch.setattr(video_processor, "RTSPStreamProcessor", FakeProcessor)

    # Neutralise the watcher daemon thread so it does not add background
    # nondeterminism. Promotion on explicit stop is synchronous in stop_camera.
    monkeypatch.setattr(
        camera_manager.CameraManager, "_watch_processor", lambda self, cid: None
    )

    yield path


def _session_row(session_id: int) -> dict | None:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT id, status, ended_at FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Req 4.5 — deleting a running camera stops the processor, closes the session,
# and removes the record.
# ---------------------------------------------------------------------------
def test_delete_running_camera_stops_processor_closes_session_removes_record(cm_env):
    mgr = CameraManager(ensure_models_fn=lambda: (None, None, None))
    cam = mgr.add_camera("cam-A", "rtsp://host/a")
    cam_id = cam["id"]

    started = mgr.start_camera(cam_id)
    assert started["status"] == "running"

    rt = mgr._cameras[cam_id]
    processor = rt.processor
    session_id = rt.session_id
    assert isinstance(processor, FakeProcessor)
    assert session_id is not None

    # The session is open before deletion.
    before = _session_row(session_id)
    assert before is not None and before["ended_at"] is None

    removed = mgr.remove_camera(cam_id)

    # Delete reports success and the processor was stopped (Req 4.5).
    assert removed is True
    assert processor.stop_count == 1

    # The session is closed (Req 4.5).
    after = _session_row(session_id)
    assert after is not None and after["ended_at"] is not None

    # The camera record is removed from the manager AND from the database.
    assert mgr.get_status(cam_id) is None
    assert db.get_camera(cam_id) is None


# ---------------------------------------------------------------------------
# Req 4.4 / 6.3 — delete / stop of an unknown camera id reports not-found.
# ---------------------------------------------------------------------------
def test_delete_and_stop_unknown_camera_report_not_found(cm_env):
    mgr = CameraManager(ensure_models_fn=lambda: (None, None, None))

    # remove_camera on an unknown id returns False (router maps this to 404).
    assert mgr.remove_camera(999_999) is False

    # stop_camera on an unknown id reports the not_found sentinel (router 404).
    assert mgr.stop_camera(999_999) == {"status": "not_found"}


# ---------------------------------------------------------------------------
# Req 5.8 — a running processor entering an error state sets the camera status
# to error, closes its session, and promotes the earliest-queued camera.
# ---------------------------------------------------------------------------
def test_processor_error_sets_error_closes_session_and_promotes_queue(cm_env, monkeypatch):
    # Keep the watcher's internal sleep from actually pausing the test.
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda *a, **k: None)

    mgr = CameraManager(ensure_models_fn=lambda: (None, None, None))
    mgr.set_concurrency_limit(1)

    cam1 = mgr.add_camera("cam-1", "rtsp://host/1")["id"]
    cam2 = mgr.add_camera("cam-2", "rtsp://host/2")["id"]

    # cam1 occupies the only slot; cam2 is queued.
    assert mgr.start_camera(cam1)["status"] == "running"
    assert mgr.start_camera(cam2)["status"] == "queued"

    rt1 = mgr._cameras[cam1]
    cam1_session = rt1.session_id
    assert cam1_session is not None

    # Simulate the running processor faulting.
    with rt1.processor.lock:
        rt1.processor.status = "error: connection lost"

    # Drive the genuine watcher logic once (deterministically, no daemon).
    ORIGINAL_WATCH(mgr, cam1)

    # cam1 is marked error and its session is closed with status 'error' (Req 5.8).
    assert mgr.get_status(cam1)["status"] == "error"
    sess = _session_row(cam1_session)
    assert sess is not None and sess["status"] == "error" and sess["ended_at"] is not None

    # The freed slot promoted the earliest-queued camera, cam2 (Req 5.8).
    assert mgr.get_status(cam2)["status"] in RUNNING_STATES
    assert mgr._cameras[cam2].processor is not None
    assert cam2 not in mgr._queue


# ===========================================================================
# api.py-layer tests: MJPEG (Req 6.1) + latest-frame (Req 6.2) delivery and
# unknown-task not-found (Req 6.3).
# ===========================================================================
class FakeStreamProcessor:
    """Stand-in processor exposing the attributes the stream endpoints read.

    ``status`` is a property backed by a fixed sequence so the (otherwise
    infinite) MJPEG generator terminates after a bounded number of frames in a
    test: it yields ``streaming`` for ``frames`` reads, then ``stopped``.
    """

    def __init__(self, jpeg=b"\xff\xd8\xff\xe0JPEGDATA\xff\xd9", frames=2):
        self.lock = threading.Lock()
        self.latest_jpeg = jpeg
        self.live_detections = [{"text": "11a22333", "conf": 0.9}]
        self.plate_history = [{"dtrb_text": "11a22333", "persian": "۱۱ الف ۲۲۳ ۳۳"}]
        self._status_seq = ["streaming"] * frames + ["stopped"]
        self._i = 0

    @property
    def status(self):
        with_idx = min(self._i, len(self._status_seq) - 1)
        val = self._status_seq[with_idx]
        self._i += 1
        return val


class FakeFrameProcessor:
    """Static processor for the latest-frame endpoint (status read once)."""

    def __init__(self, jpeg=b"\xff\xd8\xff\xe0JPEGDATA\xff\xd9"):
        self.lock = threading.Lock()
        self.status = "streaming"
        self.latest_jpeg = jpeg
        self.live_detections = [{"text": "11a22333", "conf": 0.9}]
        self.plate_history = [{"dtrb_text": "11a22333", "persian": "۱۱ الف ۲۲۳ ۳۳"}]


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    """FastAPI TestClient over api.app with a temp DB and a clean task registry.

    The detection/live-stream endpoints now live in ``routers/detection.py``
    behind ``require_permission("run_detection")`` (which itself depends on
    ``current_user``). Tests authenticate by overriding ``current_user`` with an
    Admin identity via FastAPI ``dependency_overrides``; the permission guard
    then resolves against the real RBAC matrix (Admin holds ``run_detection``).
    """
    path = str(tmp_path / "api_stream_integration.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()

    import importlib
    import api as api_module
    importlib.reload(api_module)  # re-run module init against the patched DB path

    from fastapi.testclient import TestClient
    # Override the *exact* ``current_user`` object the detection router captured
    # at import time. Other tests reload ``auth.dependencies`` (e.g.
    # test_auth_router_edge), which rebinds ``auth.dependencies.current_user`` to
    # a new object; the detection router — imported once and never reloaded —
    # still references the original. Reading it back off the router module
    # guarantees the override key matches whatever the router actually uses,
    # regardless of test ordering.
    from routers import detection as detection_module
    from auth.dependencies import AuthenticatedUser
    current_user = detection_module.current_user

    def _admin_user() -> AuthenticatedUser:
        return AuthenticatedUser(
            id=1,
            username="admin",
            role="Admin",
            disabled=False,
            jti="test-jti",
            token_exp=4_000_000_000,
        )

    api_module.app.dependency_overrides[current_user] = _admin_user

    # Clear any inherited tasks and register our fakes.
    with api_module._tasks_lock:
        api_module._tasks.clear()

    try:
        with TestClient(api_module.app) as client:
            yield client, api_module
    finally:
        api_module.app.dependency_overrides.pop(current_user, None)


def test_latest_frame_returns_annotated_frame_and_status(api_client):
    """Req 6.2: latest-frame returns the most recent annotated frame + status."""
    client, api_module = api_client
    task_id = "task-frame-1"
    with api_module._tasks_lock:
        api_module._tasks[task_id] = {
            "processor": FakeFrameProcessor(),
            "session_id": 1,
            "status": "running",
        }

    resp = client.get(f"/api/detect/rtsp/{task_id}/frame")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "streaming"
    # The most recent annotated frame is returned as a base64 data URI.
    assert body["annotated"] is not None
    assert body["annotated"].startswith("data:image/jpeg;base64,")
    # Recent detection history is included (Req 6.4 surface).
    assert isinstance(body["history"], list) and len(body["history"]) == 1


def test_latest_frame_unknown_task_returns_not_found(api_client):
    """Req 6.3: latest-frame for an unknown task id returns not-found."""
    client, _ = api_client
    resp = client.get("/api/detect/rtsp/does-not-exist/frame")
    assert resp.status_code == 404


def test_mjpeg_stream_delivers_annotated_frames(api_client):
    """Req 6.1: a streaming processor yields an MJPEG multipart stream."""
    client, api_module = api_client
    task_id = "task-mjpeg-1"
    with api_module._tasks_lock:
        api_module._tasks[task_id] = {
            "processor": FakeStreamProcessor(frames=2),
            "session_id": 2,
            "status": "running",
        }

    with client.stream("GET", f"/api/detect/rtsp/{task_id}/mjpeg") as resp:
        assert resp.status_code == 200
        assert "multipart/x-mixed-replace" in resp.headers["content-type"]
        chunks = b"".join(resp.iter_bytes())

    # The stream carries the multipart boundary and JPEG content.
    assert b"--frame" in chunks
    assert b"Content-Type: image/jpeg" in chunks
    assert b"JPEGDATA" in chunks


def test_mjpeg_stream_unknown_task_returns_not_found(api_client):
    """Req 6.3: MJPEG for an unknown task id returns not-found."""
    client, _ = api_client
    resp = client.get("/api/detect/rtsp/does-not-exist/mjpeg")
    assert resp.status_code == 404
