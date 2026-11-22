"""Remediation 3 regression tests (R3-A..R3-F, audit F-1..F-11).

All persistence uses isolated temporary SQLite databases (autouse fixture in
``tests/conftest.py`` redirects ``db.DB_PATH``; the repository-wide guard
installed from the root ``conftest.py`` refuses the production database).
"""
from __future__ import annotations

import os
import sqlite3
import threading

import numpy as np
import pytest

import db as db_module
import pipeline.integration as pipeline_integration
from pipeline.config import PipelineConfig
from pipeline.integration import EventPipeline
from pipeline.retention import (
    CONFLICT,
    EXHAUSTED,
    PENDING,
    REQUEST,
    UnifiedRetentionStore,
)
from pipeline.track_manager import TrackManager
from pipeline.types import (Box, EmissionRequest, PlateRead, Track,
                            TrackUpdate, VehicleEvent)


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def event_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "r3.db"))
    db_module.init_db()
    return db_module


def _box(x=0.1):
    return Box(x, 0.1, x + 0.1, 0.3, conf=0.9, cls=2)


def _read(text="12b34567"):
    return PlateRead(
        frame_idx=1, ts="t", text=text, char_count=8,
        plate_det_conf=0.9, plate_area_px=4800, aspect_ratio=4.6,
        sharpness=120.0, brightness_ok=True, usable=True, weight=0.9,
    )


def _event(event_key="1:42:1", event_uid="uid-1"):
    event = VehicleEvent(
        event_key=event_key, event_uid=event_uid, track_id=event_key,
        track_kind="vehicle", first_seen="a", last_seen="b",
        plate_number="12b34567", plate_norm="12b34567",
        confidence=0.9, agreement_ratio=0.9, status="confirmed",
        camera_id=1, session_id=42, source_type="rtsp",
        source_file="rtsp://cam1",
    )
    event.finalize_reason = "force_at_close"
    return event


def _track(key="1:42:1", uid="uid-1", state="COMPLETED"):
    return Track(
        track_key=key, kind="vehicle", state=state,
        first_ts=0.0, last_ts=0.0, event_uid=uid,
        observations=[_read()],
    )



def _park(ep, key="1:42:1", uid="uid-1", state="COMPLETED", plate="12b34567"):
    """Park one emission request in a fresh REQUEST slot for *key*.

    ``plate`` should differ between simultaneously parked requests: the
    §2.5 fragmentation-absorption safety net absorbs a second emission of
    the SAME plate with an overlapping window, which is intended behavior,
    not a test subject here.
    """
    ep._lifecycle._tracks[key] = _track(key, uid, state)
    ep._lifecycle._tracks[key].observations = [_read(plate)]
    token = ep._retention.reserve(
        "close", key, "emit", "unconfirmed", True, "force_at_close",
        event_uid=uid)
    request = EmissionRequest(key, "emit", "unconfirmed", True,
                              "force_at_close", event_uid=uid)
    ep._retention.park_request(token, request)
    return token


def _zero_retry_cfg():
    return PipelineConfig(retention_retry_interval_s=0.0,
                          retention_max_attempts=3)


class _StepClock:
    """Deterministic strictly-increasing monotonic clock for recovery tests.

    Windows ``time.monotonic()`` has a coarse tick (~15.6 ms); two calls
    inside one tick are equal, which would make the §2.5 fragmentation
    absorption absorb a same-plate retry inside tests. Injecting a stepping
    clock keeps these tests deterministic without sleeps.
    """

    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        self.t += 1.0
        return self.t


def _recovery_cfg(max_recovery=2):
    """Tiny fragmentation window so same-plate retries are never absorbed.

    Combined with the ``_StepClock`` (1.0 s steps), a retry's emission time
    always exceeds the previous attempt's window.
    """
    return PipelineConfig(retention_retry_interval_s=0.0,
                          fragment_window_s=1e-6,
                          retention_max_recovery_attempts=max_recovery)


# ---------------------------------------------------------------------------
# R3-A — PENDING retry path (audit F-1)
# ---------------------------------------------------------------------------

def test_r3a_first_failure_converts_once_then_retry_advances_attempts(
        event_db, monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42,
                       cfg=_zero_retry_cfg())
    calls = {"n": 0}

    def always_fail(event):
        calls["n"] += 1
        return db_module.EventPersistResult("persist_failure", None,
                                            event.event_uid, "db down")

    monkeypatch.setattr(db_module, "persist_event", always_fail)

    token = ep._retention.reserve(
        "close", "1:42:1", "emit", "unconfirmed", True, "force_at_close",
        event_uid="uid-1")
    event = _event()
    ep._retention.park_request(
        token, EmissionRequest("1:42:1", "emit", "unconfirmed", True,
                               "force_at_close", event_uid="uid-1"))

    # First failure: REQUEST -> PENDING conversion happens exactly once.
    ep._persist(event, token)
    slot = ep._retention._slots[token.slot]
    assert slot.state == PENDING
    assert slot.attempts == 1
    assert slot.event is event
    conversions = calls["n"]

    # Retry through drain_retention: no second conversion, attempts advance.
    ep.drain_retention()
    assert calls["n"] == conversions + 1
    assert slot.attempts == 2
    assert slot.state == PENDING
    assert ep._retention.payload(token) is event
    assert slot.event.event_uid == "uid-1"
    assert slot.event.event_key == "1:42:1"


def test_r3a_retry_failure_backoff_exhaustion_and_no_retries_after_terminal(
        event_db, monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42,
                       cfg=_zero_retry_cfg())
    calls = {"n": 0}

    def always_fail(event):
        calls["n"] += 1
        return db_module.EventPersistResult("persist_failure", None,
                                            event.event_uid, "db down")

    monkeypatch.setattr(db_module, "persist_event", always_fail)

    token = ep._retention.reserve(
        "close", "1:42:1", "emit", "unconfirmed", True, "x",
        event_uid="uid-1")
    event = _event()
    ep._retention.convert(token, event)
    slot = ep._retention._slots[token.slot]
    previous_attempt = None

    for expected_attempts in (1, 2, 3):
        ep.drain_retention()
        assert slot.attempts == expected_attempts
        assert slot.last_attempt >= (previous_attempt or 0.0)
        previous_attempt = slot.last_attempt

    assert slot.state == EXHAUSTED
    assert ep._retention.count(EXHAUSTED) == 1

    # EXHAUSTED entries are never retried by subsequent drains.
    settled = calls["n"]
    ep.drain_retention()
    ep.drain_retention()
    assert calls["n"] == settled
    assert slot.attempts == 3
    assert slot.event.event_uid == "uid-1"
    assert slot.event.event_key == "1:42:1"


def test_r3a_retry_failure_updates_backoff_with_nonzero_interval(
        event_db, monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42,
                       cfg=PipelineConfig(retention_retry_interval_s=5.0,
                                          retention_max_attempts=5))
    def fail(event):
        return db_module.EventPersistResult("persist_failure", None,
                                            event.event_uid, "db down")
    monkeypatch.setattr(db_module, "persist_event", fail)
    token = ep._retention.reserve(
        "close", "1:42:1", "emit", "unconfirmed", True, "x",
        event_uid="uid-1")
    ep._retention.convert(token, _event())
    slot = ep._retention._slots[token.slot]
    ep.drain_retention()  # due only if last_attempt is stale; first drain runs
    assert slot.attempts == 1
    # Backoff now defers the retry: delay counts down from last_attempt.
    delay = ep._retention.next_retry_delay()
    assert 0.0 < delay <= 5.0
    assert ep._retention.due() == []
    # Simulate elapsed backoff; the retry must then fire exactly once.
    slot.last_attempt -= 6.0
    assert ep._retention.due() == [token]


def test_r3a_retry_success_releases_and_registers_exactly_once(
        event_db, monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42,
                       cfg=_zero_retry_cfg())
    real = db_module.persist_event
    calls = {"n": 0}

    def fail_then_real(event):
        calls["n"] += 1
        if calls["n"] == 1:
            return db_module.EventPersistResult("persist_failure", None,
                                                event.event_uid, "transient")
        return real(event)

    monkeypatch.setattr(db_module, "persist_event", fail_then_real)
    token = ep._retention.reserve(
        "close", "1:42:1", "emit", "unconfirmed", True, "x",
        event_uid="uid-1")
    event = _event()
    ep._retention.convert(token, event)

    ep.drain_retention()  # failure -> PENDING, attempts 1
    ep.drain_retention()  # success -> released + registered
    assert ep._registry.is_emitted("1:42:1")
    assert ep.get_metrics()["events_finalized"] == 1
    assert ep._retention.free() == ep.cfg.retention_capacity

    ep.drain_retention()  # idempotent: no second bookkeeping
    assert ep.get_metrics()["events_finalized"] == 1


def test_r3a_identity_conflict_is_terminal_and_not_retried(event_db,
                                                           monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42,
                       cfg=_zero_retry_cfg())
    # Pre-existing row under the same key but a different uid.
    assert db_module.persist_event(_event(event_uid="uid-owner")).outcome == \
        "created"
    calls = {"n": 0}
    real = db_module.persist_event

    def counting(event):
        calls["n"] += 1
        return real(event)

    monkeypatch.setattr(db_module, "persist_event", counting)
    token = ep._retention.reserve(
        "close", "1:42:1", "emit", "unconfirmed", True, "x",
        event_uid="uid-1")
    ep._retention.convert(token, _event(event_uid="uid-1"))
    slot = ep._retention._slots[token.slot]

    ep.drain_retention()
    assert slot.state == CONFLICT
    assert ep._retention.count(CONFLICT) == 1

    # Terminal: identity conflicts are never retried.
    settled = calls["n"]
    ep.drain_retention()
    ep.drain_retention()
    assert calls["n"] == settled
    assert slot.state == CONFLICT


def test_r3a_one_failing_slot_does_not_block_other_due_entries(
        event_db, monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42,
                       cfg=_zero_retry_cfg())
    real = db_module.persist_event

    def selective(event):
        if event.event_key == "1:42:bad":
            return db_module.EventPersistResult("persist_failure", None,
                                                event.event_uid, "down")
        return real(event)

    monkeypatch.setattr(db_module, "persist_event", selective)
    bad = ep._retention.reserve(
        "close", "1:42:bad", "emit", "unconfirmed", True, "x",
        event_uid="uid-bad")
    good = ep._retention.reserve(
        "close", "1:42:good", "emit", "unconfirmed", True, "x",
        event_uid="uid-good")
    ep._retention.convert(bad, _event("1:42:bad", "uid-bad"))
    ep._retention.convert(good, _event("1:42:good", "uid-good"))

    ep.drain_retention()
    assert ep._registry.is_emitted("1:42:good")
    assert ep._retention._slots[good.slot].state == "FREE"
    assert ep._retention._slots[bad.slot].state == PENDING


# ---------------------------------------------------------------------------
# R3-D — bounded REQUEST recovery (audit F-6)
# ---------------------------------------------------------------------------

def test_r3d_recovery_failures_bounded_and_age_preserved(event_db, monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42,
                       cfg=_recovery_cfg(max_recovery=2))
    ep._retention.recovery_timeout_s = 0.0
    token = _park(ep, "1:42:1", "uid-1")
    slot = ep._retention._slots[token.slot]
    original_age = slot.state_since

    def boom(event, token=None):
        raise RuntimeError("finalize boundary")

    monkeypatch.setattr(ep, "_persist", boom)
    monkeypatch.setattr(pipeline_integration, "_now_mono", _StepClock())

    ep.drain_retention()
    assert slot.recovery_attempts == 1
    assert slot.state == REQUEST
    # The original recovery age must not be reset by a failed attempt.
    assert slot.state_since == original_age
    assert "finalize boundary" in (slot.last_error or "")

    ep.drain_retention()
    assert slot.recovery_attempts == 2
    assert slot.state == EXHAUSTED
    assert slot.event is None and slot.request is not None  # payload retained
    assert ep._retention.recovery_exhausted() == 1
    assert ep._retention.snapshot()["recovery_exhausted"] == 1

    # Terminal: no further recovery attempts.
    ep.drain_retention()
    ep.drain_retention()
    assert slot.recovery_attempts == 2
    assert slot.state == EXHAUSTED
    assert slot.request.event_uid == "uid-1"
    assert slot.request.track_key == "1:42:1"


def test_r3d_valid_request_recovered_despite_malformed_one(event_db,
                                                           monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42,
                       cfg=_recovery_cfg(max_recovery=3))
    ep._retention.recovery_timeout_s = 0.0
    bad = _park(ep, "1:42:bad", "uid-bad")
    good = _park(ep, "1:42:good", "uid-good", plate="22s45622")
    monkeypatch.setattr(pipeline_integration, "_now_mono", _StepClock())

    real_persist = ep._persist

    def selective(event, token=None):
        if event.event_key == "1:42:bad":
            raise RuntimeError("malformed request")
        return real_persist(event, token)

    monkeypatch.setattr(ep, "_persist", selective)

    ep.drain_retention()
    bad_slot = ep._retention._slots[bad.slot]
    good_slot = ep._retention._slots[good.slot]
    assert ep._registry.is_emitted("1:42:good")
    assert good_slot.state == "FREE"
    assert bad_slot.state == REQUEST
    assert bad_slot.recovery_attempts == 1


def test_r3d_stale_token_cannot_record_recovery_failure():
    store = UnifiedRetentionStore(capacity=1, max_recovery_attempts=1)
    token = store.reserve("close", "a", "emit", "unconfirmed", True, "x",
                          event_uid="u1")
    store.release(token)
    fresh = store.reserve("close", "b", "emit", "unconfirmed", True, "x",
                          event_uid="u2")
    assert store.note_recovery_failure(token, "stale") is False
    slot = store._slots[fresh.slot]
    assert slot.recovery_attempts == 0
    assert slot.state != EXHAUSTED


# ---------------------------------------------------------------------------
# R3-C — final recovery at verified source end (audit F-5)
# ---------------------------------------------------------------------------

def test_r3c_fresh_request_finalized_at_source_end(event_db, monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42,
                       cfg=_recovery_cfg(max_recovery=2))
    assert ep._retention.recovery_timeout_s > 0.0
    token = _park(ep, "1:42:1", "uid-1")
    monkeypatch.setattr(pipeline_integration, "_now_mono", _StepClock())

    # The request is younger than the recovery timeout: the ordinary drain in
    # expire() must not touch it; the final zero-age pass must finalize it.
    events = ep.expire("video_end")

    assert ep._retention.count(REQUEST) == 0
    assert ep._retention.free() == ep.cfg.retention_capacity
    assert ep._registry.is_emitted("1:42:1")
    assert len(events) == 1
    assert events[0].event_uid == "uid-1"
    assert events[0].event_key == "1:42:1"


def test_r3c_pending_backoff_not_bypassed_at_source_end(event_db, monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42,
                       cfg=_recovery_cfg(max_recovery=2))
    monkeypatch.setattr(pipeline_integration, "_now_mono", _StepClock())

    def fail(event):
        return db_module.EventPersistResult("persist_failure", None,
                                            event.event_uid, "db down")

    monkeypatch.setattr(db_module, "persist_event", fail)
    token = ep._retention.reserve(
        "close", "1:42:1", "emit", "unconfirmed", True, "x",
        event_uid="uid-1")
    ep._retention.convert(token, _event())
    slot = ep._retention._slots[token.slot]

    events = ep.expire("video_end")
    assert events == []
    # The PENDING retry keeps its configured backoff and is not forced.
    assert slot.state == PENDING
    assert slot.attempts == 1
    assert slot.event.event_uid == "uid-1"


def test_r3c_abandoned_reservation_released_only_at_verified_end(event_db):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42)
    token = ep._retention.reserve(
        "close", "1:42:1", "emit", "unconfirmed", True, "x",
        event_uid="uid-1")
    assert ep._retention.count(REQUEST) == 0
    slot = ep._retention._slots[token.slot]
    assert slot.state == "RESERVED"
    # Young reservation survives the ordinary drain inside expire(); the
    # verified end-of-source pass releases it (provably pre-mutation: reserve
    # and park happen synchronously under the pipeline lock).
    events = ep.expire("video_end")
    assert events == []
    assert slot.state == "FREE"
    assert ep._retention.free() == ep.cfg.retention_capacity


def test_r3c_worker_alive_prevents_final_recovery():
    from video_processor import RTSPStreamProcessor

    class _Worker:
        def __init__(self, name, alive):
            self.name = name
            self._alive = alive

        def is_alive(self):
            return self._alive

        def join(self, timeout=None):
            return None

    class _Pipeline:
        def __init__(self):
            self.expire_calls = 0

        def expire(self, reason):
            self.expire_calls += 1
            return []

    p = object.__new__(RTSPStreamProcessor)
    p.lock = threading.Lock()
    p._stop_lock = threading.Lock()
    p.running = True
    p.thread = _Worker("main", False)
    p._reader_thread = _Worker("reader", False)
    p._ml_thread = _Worker("ml", True)  # still mutating tracks
    p._shutdown_flushed = False
    p._shutdown_incomplete = False
    p._error_message = None
    p.status = "streaming"
    p.event_pipeline = _Pipeline()

    p.stop()
    # No final recovery/flush may run while a worker is alive.
    assert p.event_pipeline.expire_calls == 0
    assert p._shutdown_incomplete is True
    assert p.shutdown_completed() is False


# ---------------------------------------------------------------------------
# R3-B — shutdown/session ordering (audit F-2, F-3, F-4)
# ---------------------------------------------------------------------------

class _FakeRtspProcessor:
    def __init__(self, completed):
        self._completed = completed
        self.stop_calls = 0
        self.lock = threading.Lock()
        self.plate_history = [{"dtrb_text": "12b34567"}]

    def stop(self):
        self.stop_calls += 1

    def shutdown_completed(self):
        return self._completed

    def get_state(self):
        return {"history": self.plate_history}


def test_r3b_rtsp_stop_flushes_before_session_close(event_db):
    from routers.detection import _stop_rtsp_task_entry

    sid = db_module.start_session("rtsp", "rtsp://test/stream")
    processor = _FakeRtspProcessor(completed=True)
    entry = {"processor": processor, "session_id": sid, "status": "running"}

    result = _stop_rtsp_task_entry(entry)

    assert result == {"status": "stopped", "shutdown_completed": True}
    assert processor.stop_calls == 1
    conn = db_module.get_conn()
    try:
        row = conn.execute(
            "SELECT status, ended_at FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "done"
    assert row["ended_at"]


def test_r3b_rtsp_incomplete_shutdown_keeps_session_open(event_db):
    from routers.detection import _stop_rtsp_task_entry

    sid = db_module.start_session("rtsp", "rtsp://test/stream")
    processor = _FakeRtspProcessor(completed=False)
    entry = {"processor": processor, "session_id": sid, "status": "running"}

    result = _stop_rtsp_task_entry(entry)

    assert result["status"] == "stop_incomplete"
    assert result["shutdown_completed"] is False
    assert processor.stop_calls == 1
    conn = db_module.get_conn()
    try:
        row = conn.execute(
            "SELECT status, ended_at FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
    finally:
        conn.close()
    # The session was NOT falsely closed.
    assert row["status"] == "running"
    assert row["ended_at"] is None
    # The processor reference is retained for a later retry.
    assert entry["processor"] is processor


def test_r3b_later_successful_stop_completes_shutdown_and_clears_state():
    from video_processor import RTSPStreamProcessor

    class _Worker:
        def __init__(self, name):
            self.name = name
            self.alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            return None

    class _Pipeline:
        def __init__(self):
            self.expire_calls = 0

        def expire(self, reason):
            self.expire_calls += 1
            return []

    p = object.__new__(RTSPStreamProcessor)
    p.lock = threading.Lock()
    p._stop_lock = threading.Lock()
    p.running = True
    p.thread = _Worker("main")
    p._reader_thread = _Worker("reader")
    p._ml_thread = _Worker("ml")
    p._shutdown_flushed = False
    p._shutdown_incomplete = False
    p._error_message = None
    p.status = "streaming"
    p.event_pipeline = _Pipeline()

    p.stop()
    assert p.event_pipeline.expire_calls == 0
    assert p._shutdown_incomplete is True
    assert p.status == "error: shutdown timeout"

    # Workers finish later; a subsequent stop must flush and clear the
    # stale incomplete-shutdown state.
    for worker in (p.thread, p._reader_thread, p._ml_thread):
        worker.alive = False
    p.stop()
    assert p.event_pipeline.expire_calls == 1
    assert p._shutdown_incomplete is False
    assert p.shutdown_completed() is True
    assert p.status == "stopped"

    # Idempotent: repeated stops never double-flush.
    p.stop()
    assert p.event_pipeline.expire_calls == 1


def test_r3b_concurrent_stop_callers_flush_exactly_once():
    from video_processor import RTSPStreamProcessor

    class _Worker:
        def __init__(self, name):
            self.name = name
            self.alive = False

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            return None

    class _Pipeline:
        def __init__(self):
            self.expire_calls = 0
            self.lock = threading.Lock()

        def expire(self, reason):
            with self.lock:
                self.expire_calls += 1
            return []

    p = object.__new__(RTSPStreamProcessor)
    p.lock = threading.Lock()
    p._stop_lock = threading.Lock()
    p.running = True
    p.thread = _Worker("main")
    p._reader_thread = _Worker("reader")
    p._ml_thread = _Worker("ml")
    p._shutdown_flushed = False
    p._shutdown_incomplete = False
    p._error_message = None
    p.status = "streaming"
    p.event_pipeline = _Pipeline()

    barrier = threading.Barrier(2)
    errors = []

    def stopper():
        barrier.wait()
        try:
            p.stop()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=stopper) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)
    assert errors == []
    assert p.event_pipeline.expire_calls == 1
    assert p._shutdown_flushed is True
    assert p.shutdown_completed() is True


class _FakeVideoProcessor:
    """VideoProcessor stand-in whose worker finishes after stop()."""

    def __init__(self, completes_after_stop=True):
        self.completes_after_stop = completes_after_stop
        self.stop_calls = 0
        self.lock = threading.Lock()
        self._terminated = threading.Event()
        self._status = "processing"

    def stop(self):
        self.stop_calls += 1
        if self.completes_after_stop:
            # Worker loop breaks, runs expire(), then reports the terminal
            # status with processing=False.
            self._status = "done"
            self._terminated.set()

    def get_state(self):
        return {
            "processing": not self._terminated.is_set(),
            "status": self._status,
        }

    def finish(self, status="done"):
        self._status = status
        self._terminated.set()


def test_r3b_video_cancellation_waits_for_worker(event_db):
    import api
    from routers.detection import _cancel_video_task

    task_id = "cancel-ok"
    vp = _FakeVideoProcessor(completes_after_stop=True)
    with api._tasks_lock:
        api._tasks[task_id] = {"status": "running"}

    _cancel_video_task(task_id, vp, timeout_s=2.0)

    with api._tasks_lock:
        entry = api._tasks[task_id]
    assert vp.stop_calls == 1
    assert entry["status"] == "cancelled"
    assert "stop_incomplete" not in entry


def test_r3b_video_cancellation_timeout_leaves_session_open(event_db):
    import api
    from routers.detection import _cancel_video_task

    task_id = "cancel-hung"
    vp = _FakeVideoProcessor(completes_after_stop=False)
    with api._tasks_lock:
        api._tasks[task_id] = {"status": "running",
                               "session_id": 123, "processor": vp}

    _cancel_video_task(task_id, vp, timeout_s=0.2)

    with api._tasks_lock:
        entry = api._tasks[task_id]
    assert vp.stop_calls == 1
    # User-facing cancellation semantics preserved...
    assert entry["status"] == "cancelled"
    # ...but the shutdown is surfaced as incomplete, the session stays open
    # and the processor reference is retained for a later safe retry.
    assert entry.get("stop_incomplete") is True
    assert entry.get("processor") is vp
    assert entry.get("session_id") == 123


def test_r3b_video_finalize_triage_respects_incomplete_flag():
    from routers.detection import _finalize_video_session

    closed = []

    def closer(state, status):
        closed.append(status)

    _finalize_video_session({"stop_incomplete": True}, {"status": "cancelled"},
                            closer)
    assert closed == []  # never close on a mere timeout

    _finalize_video_session({}, {"status": "done"}, closer)
    assert closed == ["done"]

    _finalize_video_session({}, {"status": "error: retention blocked"}, closer)
    assert closed == ["done", "error"]

    _finalize_video_session({}, {"status": "processing"}, closer)
    assert closed == ["done", "error", "cancelled"]


def test_r3b_watcher_retains_processor_on_incomplete_shutdown(event_db):
    import camera_manager as cm

    manager = cm.CameraManager(ensure_models_fn=lambda: None,
                               tasks_registry={}, tasks_lock=threading.Lock())
    sid = db_module.start_session("rtsp", "rtsp://cam")
    rt = cm.CameraRuntime(camera_id=1, name="c", url="u", skip_frames=15,
                          status="streaming", session_id=sid)
    processor = _FakeRtspProcessor(completed=False)
    rt.processor = processor

    with manager._lock:
        keep = manager._handle_processor_error_locked(rt, processor)

    assert keep is True
    assert rt.processor is processor          # never abandoned
    assert rt.status == "error"               # concurrency slot freed
    assert rt.shutdown_stop_attempts == 1
    conn = db_module.get_conn()
    try:
        row = conn.execute(
            "SELECT status, ended_at FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "running"
    assert row["ended_at"] is None

    # Bounded retries: attempts 2 and 3, then the budget is exhausted.
    with manager._lock:
        manager._handle_processor_error_locked(rt, processor)
        manager._handle_processor_error_locked(rt, processor)
        keep = manager._handle_processor_error_locked(rt, processor)
    assert processor.stop_calls == 3
    assert rt.shutdown_stop_attempts == 3
    assert keep is True
    assert rt.processor is processor

    # A later verified shutdown completes the flush/closure safely.
    processor._completed = True
    with manager._lock:
        keep = manager._handle_processor_error_locked(rt, processor)
    assert keep is False
    assert rt.processor is None
    assert rt.shutdown_stop_attempts == 0
    conn = db_module.get_conn()
    try:
        row = conn.execute(
            "SELECT status, ended_at FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "error"
    assert row["ended_at"] is not None


def test_r3b_stop_camera_locked_incomplete_retains_processor(event_db):
    import camera_manager as cm

    manager = cm.CameraManager(ensure_models_fn=lambda: None,
                               tasks_registry={}, tasks_lock=threading.Lock())
    sid = db_module.start_session("rtsp", "rtsp://cam")
    rt = cm.CameraRuntime(camera_id=1, name="c", url="u", skip_frames=15,
                          status="streaming", task_id="t", session_id=sid)
    manager._cameras[1] = rt
    processor = _FakeRtspProcessor(completed=False)
    rt.processor = processor

    with manager._lock:
        manager._stop_camera_locked(1, end_sess=True)

    # Incomplete: processor and session retained for the watcher.
    assert rt.processor is processor
    assert rt.session_id == sid
    assert rt.status == "error"
    conn = db_module.get_conn()
    try:
        row = conn.execute(
            "SELECT status, ended_at FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "running"

    # A later verified shutdown finishes the closure cleanly.
    processor._completed = True
    with manager._lock:
        manager._stop_camera_locked(1, end_sess=True)
    assert rt.processor is None
    assert rt.session_id is None
    assert rt.status == "stopped"
    conn = db_module.get_conn()
    try:
        row = conn.execute(
            "SELECT status, ended_at FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
    finally:
        conn.close()
    assert row["ended_at"] is not None


# ---------------------------------------------------------------------------
# F-8 — no-evidence tracks close without consuming a slot
# ---------------------------------------------------------------------------

def test_f8_no_payload_track_terminalizes_under_full_capacity():
    tm = TrackManager()
    store = UnifiedRetentionStore(capacity=1)
    held = store.reserve("close", "held", "emit", "unconfirmed", True, "x")
    assert held is not None

    # TRACKING track without observations (no Event payload possible).
    tm._tracks["1:1:1"] = Track(track_key="1:1:1", kind="vehicle",
                                state="TRACKING", first_ts=0.0, last_ts=0.0,
                                event_uid="uid-1")
    requests, tokens = tm.apply_updates_admitted([], 10.0, store)
    assert requests == [] and tokens == []
    assert tm.get("1:1:1").state == "COMPLETED"
    assert store.free() == 0  # the held slot was never touched

    # NEW glint track expires without a slot as well.
    tm._tracks["1:1:2"] = Track(track_key="1:1:2", kind="vehicle",
                                state="NEW", first_ts=0.0, last_ts=0.0,
                                event_uid="uid-2")
    requests, tokens = tm.apply_updates_admitted([], 10.0, store)
    assert requests == [] and tokens == []
    assert tm.get("1:1:2").state == "EXPIRED"
    assert store.free() == 0

    # An event-bearing track under the same full store stays recoverable.
    tm._tracks["1:1:3"] = _track("1:1:3", "uid-3", state="TRACKING")
    requests, tokens = tm.apply_updates_admitted([], 10.0, store)
    assert requests == [] and tokens == []
    assert tm.get("1:1:3").state == "TRACKING"


# ---------------------------------------------------------------------------
# F-10 — legacy wrapper raises instead of silently collapsing outcomes
# ---------------------------------------------------------------------------

def test_f10_upsert_wrapper_explicit_outcomes(event_db, monkeypatch):
    created = db_module.upsert_vehicle_event(_event())
    assert created[1] is True
    updated = db_module.upsert_vehicle_event(_event())
    assert updated[1] is False and updated[0] == created[0]

    with pytest.raises(db_module.EventIdentityConflict):
        db_module.upsert_vehicle_event(_event(event_uid="uid-other"))

    def boom():
        raise sqlite3.OperationalError("cannot connect")
    monkeypatch.setattr(db_module, "get_conn", boom)
    with pytest.raises(db_module.EventPersistenceError):
        db_module.upsert_vehicle_event(_event(event_key="other:1:1",
                                              event_uid="uid-other"))


# ---------------------------------------------------------------------------
# R3-F — production migration/backfill gating (audit F-7)
# ---------------------------------------------------------------------------

def _make_legacy_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE vehicle_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL UNIQUE,
            track_id TEXT NOT NULL,
            camera_id INTEGER, camera_name TEXT, session_id INTEGER,
            source_type TEXT NOT NULL DEFAULT 'rtsp', source_file TEXT,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            frame_count INTEGER NOT NULL DEFAULT 0,
            observation_count INTEGER NOT NULL DEFAULT 0,
            plate_number TEXT NOT NULL, plate_norm TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            agreement_ratio REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'confirmed',
            needs_review INTEGER NOT NULL DEFAULT 0,
            finalize_reason TEXT, plate_valid INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        INSERT INTO vehicle_events
            (event_key, track_id, first_seen, last_seen, plate_number,
             plate_norm, created_at, updated_at)
        VALUES ('cam1:0:1', 'cam1:0:1', 'a', 'b', '12b34567', '12b34567',
                'a', 'b');
    """)
    conn.commit()
    conn.close()


def test_r3f_default_startup_does_not_backfill(tmp_path, monkeypatch):
    path = tmp_path / "legacy_default.db"
    _make_legacy_db(path)
    monkeypatch.setattr(db_module, "DB_PATH", str(path))

    db_module.init_db()  # ordinary startup: additive schema only

    conn = sqlite3.connect(path)
    try:
        uid = conn.execute(
            "SELECT event_uid FROM vehicle_events").fetchone()[0]
    finally:
        conn.close()
    assert uid is None  # no silent data backfill


def test_r3f_explicit_migration_backfills_idempotently(tmp_path, monkeypatch):
    path = tmp_path / "legacy_migrated.db"
    _make_legacy_db(path)
    monkeypatch.setattr(db_module, "DB_PATH", str(path))

    db_module.init_db(run_migrations=True)
    conn = sqlite3.connect(path)
    uid1 = conn.execute(
        "SELECT event_uid FROM vehicle_events").fetchone()[0]
    conn.close()
    assert uid1

    db_module.init_db(run_migrations=True)
    conn = sqlite3.connect(path)
    uid2 = conn.execute(
        "SELECT event_uid FROM vehicle_events").fetchone()[0]
    key = conn.execute(
        "SELECT event_key, plate_number FROM vehicle_events").fetchone()
    conn.close()
    assert uid2 == uid1
    assert key == ("cam1:0:1", "12b34567")  # historical data preserved


# ---------------------------------------------------------------------------
# F-11 — global-state restoration
# ---------------------------------------------------------------------------

def test_f11_replay_restores_globals_after_exception(event_db, monkeypatch,
                                                     tmp_path):
    import cv2

    import api
    import validation.replay_runner as rr
    from video_processor import VideoProcessor
    from pipeline.integration import EventPipeline

    # Build a tiny openable video so probe_video succeeds.
    video_path = tmp_path / "tiny.avi"
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"MJPG"),
                             10.0, (32, 32))
    assert writer.isOpened()
    frame = np.zeros((32, 32, 3), dtype="uint8")
    writer.write(frame)
    writer.write(frame)
    writer.release()

    orig_run = VideoProcessor._run
    orig_process = EventPipeline.process_results
    orig_db_path = db_module.DB_PATH
    orig_env = {k: os.environ.get(k)
                for k in ("ALPR_PIPELINE_VIDEO", "ALPR_PIPELINE_MODE")}

    def _no_engine():
        raise SystemExit("no engine in test")

    monkeypatch.setattr(api, "_ensure_models", _no_engine)

    with pytest.raises(SystemExit):
        rr.run_replay(str(video_path), tmp_path / "out", "cam1", False, 1)

    assert VideoProcessor._run is orig_run
    assert EventPipeline.process_results is orig_process
    assert db_module.DB_PATH == orig_db_path
    assert {k: os.environ.get(k)
            for k in ("ALPR_PIPELINE_VIDEO", "ALPR_PIPELINE_MODE")} == orig_env


def test_f11_detection_test_module_restores_db_path():
    """The import-time DB redirect in the detection integration test module
    is transient: the module captures the then-current DB_PATH as the
    original and restores it in a finally block, so the bootstrap path can
    no longer leak past the import (success or failure)."""
    import sys

    import db

    source_path = "tests.test_detection_pipeline_integration"
    already_imported = source_path in sys.modules
    if not already_imported:
        before = db.DB_PATH
    import tests.test_detection_pipeline_integration as detection_tests

    if already_imported:
        # Imported during collection, with no test fixture active: the
        # transient restore returned DB_PATH to the production default.
        expected = os.path.join(os.path.dirname(db.__file__), "database",
                                "plpr.db")
        assert detection_tests._ORIGINAL_DB_PATH == expected
    else:
        # Imported lazily inside this test: the restore returned DB_PATH to
        # exactly what the import found (the fixture's temporary path).
        assert db.DB_PATH == before
        assert detection_tests._ORIGINAL_DB_PATH == before

    source = open(detection_tests.__file__, encoding="utf-8").read()
    assert "try:\n    _bootstrap_db.init_db()\n    import api\nfinally:\n" \
        "    _bootstrap_db.DB_PATH = _ORIGINAL_DB_PATH" in source
