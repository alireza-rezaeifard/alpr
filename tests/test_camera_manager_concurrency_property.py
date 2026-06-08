"""
Property-based test for CameraManager concurrency + FIFO promotion.

Feature: anpr-system-redesign, Property 12

Property 12: The camera manager never exceeds its concurrency limit and
    promotes FIFO.
    For any sequence of start, stop, start-all, and stop-all operations against
    a concurrency limit, the number of running cameras never exceeds the limit,
    cameras started beyond the limit are queued, freeing a running slot promotes
    the earliest-queued camera, and stop-all leaves no running cameras and an
    empty queue.

Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.8

Testing notes (per spec): the camera-manager property tests use a MOCKED
processor so the queueing/promotion logic is exercised without real RTSP I/O or
ML inference. The real RTSPStreamProcessor is replaced by a deterministic
FakeProcessor whose start()/stop() are instantaneous, and the manager's
background watcher thread is neutralised so status transitions are driven
synchronously. A temporary SQLite database backs session bookkeeping.
"""
from __future__ import annotations

import os
import tempfile
import threading

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import db
import video_processor
import camera_manager
from camera_manager import CameraManager


# Manager statuses that occupy a concurrency slot ("running").
RUNNING_STATES = ("connecting", "connected", "streaming")


class FakeProcessor:
    """Deterministic stand-in for RTSPStreamProcessor.

    start() flips the processor to a running state instantly (no thread, no
    OpenCV capture); stop() flips it to stopped. No real I/O or ML inference.
    """

    def __init__(self, *args, **kwargs):
        self.lock = threading.Lock()
        self.status = "initialized"
        self.running = False
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

    def get_state(self):
        with self.lock:
            return {
                "running": self.running,
                "status": self.status,
                "history": list(self.plate_history),
                "live_detections": list(self.live_detections),
            }


@pytest.fixture()
def cm_env(monkeypatch):
    """Point db at a temp SQLite file, mock the processor, and disable the
    background watcher thread so status transitions are fully synchronous."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "camera_manager_concurrency_test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()

    # Mock the processor so starting a camera is instantaneous and side-effect
    # free. `_start_processor_locked` does `from video_processor import
    # RTSPStreamProcessor`, which reads this attribute at call time.
    monkeypatch.setattr(video_processor, "RTSPStreamProcessor", FakeProcessor)

    # Neutralise the watcher daemon thread: it only mirrors a running processor
    # status onto the runtime (which our fake keeps "running") and would
    # otherwise add background nondeterminism. Promotion on explicit stop is
    # synchronous in stop_camera and is unaffected.
    monkeypatch.setattr(camera_manager.CameraManager, "_watch_processor", lambda self, cid: None)

    yield path
    try:
        os.remove(path)
    except OSError:
        pass


def _mgr_running_ids(mgr: CameraManager) -> set[int]:
    return {
        cid for cid, rt in mgr._cameras.items() if rt.status in RUNNING_STATES
    }


def _mgr_queued_order(mgr: CameraManager) -> list[int]:
    return list(mgr._queue)


class RefModel:
    """Reference model mirroring CameraManager's start/stop/queue semantics."""

    def __init__(self, camera_ids: list[int], limit: int):
        self.ids = list(camera_ids)
        self.limit = limit
        self.running: list[int] = []   # membership only; order not significant
        self.queue: list[int] = []     # FIFO order is significant

    def _status(self, cid: int) -> str:
        if cid in self.running:
            return "running"
        if cid in self.queue:
            return "queued"
        return "stopped"

    def start(self, cid: int) -> None:
        s = self._status(cid)
        if s in ("running", "queued"):
            return  # idempotent
        if len(self.running) < self.limit:
            self.running.append(cid)
        else:
            self.queue.append(cid)

    def _promote(self) -> None:
        while len(self.running) < self.limit and self.queue:
            self.running.append(self.queue.pop(0))

    def stop(self, cid: int) -> None:
        was_running = cid in self.running
        if cid in self.running:
            self.running.remove(cid)
        if cid in self.queue:
            self.queue.remove(cid)
        if was_running:
            self._promote()

    def start_all(self) -> None:
        # Mirrors start_all: iterate cameras in sorted id order, starting each
        # stopped camera through the same per-camera start path.
        for cid in sorted(self.ids):
            if self._status(cid) == "stopped":
                self.start(cid)

    def stop_all(self) -> None:
        self.running.clear()
        self.queue.clear()


# Feature: anpr-system-redesign, Property 12
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(data=st.data())
def test_concurrency_invariant_and_fifo_promotion(cm_env, data) -> None:
    limit = data.draw(st.integers(min_value=1, max_value=5), label="limit")
    n_cams = data.draw(st.integers(min_value=1, max_value=8), label="n_cams")

    mgr = CameraManager(ensure_models_fn=lambda: (None, None, None))
    mgr.set_concurrency_limit(limit)
    cam_ids = [
        mgr.add_camera(f"cam{i}", f"rtsp://host/{i}")["id"] for i in range(n_cams)
    ]
    model = RefModel(cam_ids, limit)

    # Operation strategy over the fixed camera pool.
    cid_strat = st.sampled_from(cam_ids)
    op_strat = st.one_of(
        st.tuples(st.just("start"), cid_strat),
        st.tuples(st.just("stop"), cid_strat),
        st.tuples(st.just("start_all"), st.none()),
        st.tuples(st.just("stop_all"), st.none()),
    )
    ops = data.draw(st.lists(op_strat, min_size=1, max_size=40), label="ops")

    for kind, arg in ops:
        if kind == "start":
            mgr.start_camera(arg)
            model.start(arg)
        elif kind == "stop":
            mgr.stop_camera(arg)
            model.stop(arg)
        elif kind == "start_all":
            mgr.start_all()
            model.start_all()
        else:  # stop_all
            mgr.stop_all()
            model.stop_all()

        running_ids = _mgr_running_ids(mgr)

        # Headline invariant (Req 5.1, 5.2): never exceed the concurrency limit.
        assert len(running_ids) <= limit, (
            f"running {len(running_ids)} exceeds limit {limit} after {kind}"
        )

        # Manager state matches the reference model: running membership and
        # FIFO queue order (Req 5.1-5.4, promotion choke-point for 5.3/5.8).
        assert running_ids == set(model.running), (
            f"running mismatch after {kind} {arg}: "
            f"mgr={running_ids} model={set(model.running)}"
        )
        assert _mgr_queued_order(mgr) == model.queue, (
            f"queue order mismatch after {kind} {arg}: "
            f"mgr={_mgr_queued_order(mgr)} model={model.queue}"
        )

        # Whenever a camera is queued, every running slot must be occupied
        # (Req 5.2: enqueue only happens at the limit).
        if model.queue:
            assert len(running_ids) == limit

        # stop_all leaves no running cameras and an empty queue (Req 5.5).
        if kind == "stop_all":
            assert running_ids == set()
            assert _mgr_queued_order(mgr) == []
