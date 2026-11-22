"""Final M0-A correctness pass regressions (R2-A through R2-H).

All persistence uses temporary SQLite files. No test opens the production
database.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import db as db_module
from pipeline.config import PipelineConfig
from pipeline.integration import EventPipeline
from pipeline.retention import (
    CONFLICT,
    PENDING,
    REQUEST,
    StaleRetentionToken,
    UnifiedRetentionStore,
)
from pipeline.track_manager import TrackManager
from pipeline.types import Box, EmissionRequest, PlateRead, Track, TrackUpdate
from tests.isolation import is_production_db_path


def _box():
    return Box(0.1, 0.1, 0.2, 0.3, conf=0.9, cls=2)


def _read():
    return PlateRead(
        frame_idx=1, ts="t", text="12b34567", char_count=8,
        plate_det_conf=0.9, plate_area_px=4800, aspect_ratio=4.6,
        sharpness=120.0, brightness_ok=True, usable=True, weight=0.9,
    )


def _event(event_key="1:42:1", event_uid="uid-1"):
    from pipeline.types import VehicleEvent

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


@pytest.fixture()
def event_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "final_pass.db"))
    db_module.init_db()
    return db_module


# R2-A ---------------------------------------------------------------------

def test_unadmitted_apply_updates_fails_before_mutation():
    tm = TrackManager()
    with pytest.raises(ValueError, match="requires admission"):
        tm.apply_updates([TrackUpdate("1:42:1", "vehicle", _box(), "NEW", 1, 1, 0)],
                         now=0.0)
    assert tm.get("1:42:1") is None


def test_admitted_close_full_capacity_preserves_track():
    tm = TrackManager()
    tm._tracks["1:42:1"] = Track(
        track_key="1:42:1", kind="vehicle", state="TRACKING",
        first_ts=0.0, last_ts=0.0, event_uid="uid-1",
        observations=[_read()],
    )
    store = UnifiedRetentionStore(capacity=1)
    held = store.reserve("close", "held", "emit", "unconfirmed", True, "x")
    assert held is not None

    requests, tokens = tm.apply_updates_admitted([], 10.0, store)
    assert requests == [] and tokens == []
    assert tm.get("1:42:1").state == "TRACKING"

    store.release(held)
    requests, tokens = tm.apply_updates_admitted([], 10.0, store)
    assert len(requests) == len(tokens) == 1
    assert tm.get("1:42:1").state == "COMPLETED"
    assert requests[0].event_uid == "uid-1"


# R2-B ---------------------------------------------------------------------

def test_stale_token_cannot_mutate_reused_slot():
    store = UnifiedRetentionStore(capacity=1)
    old = store.reserve("close", "old", "emit", "unconfirmed", True, "x")
    assert old is not None
    assert store.release(old) is True
    new = store.reserve("close", "new", "emit", "unconfirmed", True, "x")
    assert new is not None
    assert store.release(old) is False
    with pytest.raises(StaleRetentionToken):
        store.park_request(old, EmissionRequest("old", "emit", "unconfirmed"))
    assert store.payload(new).track_key == "new"
    assert store.release(new) is True


def test_double_release_is_observable_and_safe():
    store = UnifiedRetentionStore(capacity=1)
    token = store.reserve("close", "a", "emit", "unconfirmed", True, "x")
    assert store.release(token) is True
    assert store.release(token) is False
    assert store.snapshot()["stale_token_attempts"] == 1


def test_recover_parked_request_after_finalize_exception(event_db, monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42)
    ep._retention.recovery_timeout_s = 0.0
    key = "1:42:1"
    ep._lifecycle._tracks[key] = Track(
        track_key=key, kind="vehicle", state="COMPLETED",
        first_ts=0.0, last_ts=0.0, event_uid="uid-1",
        observations=[_read()],
    )
    token = ep._retention.reserve(
        "close", key, "emit", "unconfirmed", True, "force_at_close",
        event_uid="uid-1")
    request = EmissionRequest(key, "emit", "unconfirmed", True,
                              "force_at_close", event_uid="uid-1")
    ep._retention.park_request(token, request)

    real_persist = ep._persist
    def boom(event, token=None):
        raise RuntimeError("finalize boundary")
    monkeypatch.setattr(ep, "_persist", boom)
    with pytest.raises(RuntimeError, match="finalize boundary"):
        ep._finalize(request, 1.0, closing=True, token=token)
    assert ep._retention.count(REQUEST) == 1

    monkeypatch.setattr(ep, "_persist", real_persist)
    ep.drain_retention()
    assert ep._retention.count(REQUEST) == 0
    assert ep._registry.is_emitted(key)


def test_recover_abandoned_pre_mutation_reservation():
    store = UnifiedRetentionStore(capacity=1, recovery_timeout_s=0.0)
    token = store.reserve("close", "a", "emit", "unconfirmed", True, "x")
    assert token is not None
    assert store.release_abandoned_reservations() == 1
    assert store.free() == 1
    assert store.release(token) is False


# R2-C ---------------------------------------------------------------------

class _FakeWorker:
    def __init__(self, alive, name):
        self._alive = alive
        self.name = name

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        return None


def test_rtsp_stop_skips_flush_when_worker_still_alive():
    from video_processor import RTSPStreamProcessor

    class Pipeline:
        def __init__(self):
            self.calls = 0
        def expire(self, reason):
            self.calls += 1
            return []

    p = object.__new__(RTSPStreamProcessor)
    p.lock = threading.Lock()
    p._stop_lock = threading.Lock()
    p.running = True
    p.thread = _FakeWorker(False, "main")
    p._reader_thread = _FakeWorker(False, "reader")
    p._ml_thread = _FakeWorker(True, "ml")
    p._shutdown_flushed = False
    p._shutdown_incomplete = False
    p._error_message = None
    p.status = "streaming"
    p.event_pipeline = Pipeline()

    p.stop()
    assert p.event_pipeline.calls == 0
    assert p._shutdown_incomplete is True
    assert p.status.startswith("error: shutdown timeout")


def test_rtsp_stop_flushes_after_all_workers_join():
    from video_processor import RTSPStreamProcessor

    class Pipeline:
        def __init__(self):
            self.calls = 0
        def expire(self, reason):
            self.calls += 1
            return []

    p = object.__new__(RTSPStreamProcessor)
    p.lock = threading.Lock()
    p._stop_lock = threading.Lock()
    p.running = True
    p.thread = _FakeWorker(False, "main")
    p._reader_thread = _FakeWorker(False, "reader")
    p._ml_thread = _FakeWorker(False, "ml")
    p._shutdown_flushed = False
    p._shutdown_incomplete = False
    p._error_message = None
    p.status = "streaming"
    p.event_pipeline = Pipeline()

    p.stop()
    assert p.event_pipeline.calls == 1
    assert p._shutdown_flushed is True
    p.stop()
    assert p.event_pipeline.calls == 1


# R2-D ---------------------------------------------------------------------

def test_progress_state_distinguishes_backoff_from_terminal():
    store = UnifiedRetentionStore(capacity=1, retry_interval_s=60.0)
    token = store.reserve("close", "a", "emit", "unconfirmed", True, "x")
    store.convert(token, _event())
    store.mark_result(token, "persist_failure", "temporary")
    assert store.progress_state() == "backoff"
    assert store.blocked() is False
    assert store.next_retry_delay() > 0
    store.mark_result(token, "identity_conflict", "terminal")
    assert store.progress_state() == "terminal"
    assert store.blocked() is True


def test_file_waits_for_backoff_then_resumes_and_terminal_stops():
    from video_processor import VideoProcessor

    class Pipeline:
        def __init__(self):
            self.drains = 0
            self.terminal = False
        def retention_free(self):
            return 0 if self.drains < 2 else 1
        def drain_retention(self):
            self.drains += 1
        def retention_progress_state(self):
            return "terminal" if self.terminal else "backoff"
        def retention_next_retry_delay(self):
            return 0.01
        def retention_snapshot(self):
            return {"conflicts": 1 if self.terminal else 0,
                    "exhausted": 0}

    vp = object.__new__(VideoProcessor)
    vp.running = True
    vp.lock = threading.Lock()
    vp.status = "processing"
    vp.error = None
    vp.event_pipeline = Pipeline()
    assert vp._wait_for_retention_room() is True
    assert vp.event_pipeline.drains >= 2

    vp.event_pipeline = Pipeline()
    vp.event_pipeline.terminal = True
    assert vp._wait_for_retention_room() is False
    assert vp.status == "error: retention blocked"


def test_backoff_becomes_due_and_retry_frees_slot():
    store = UnifiedRetentionStore(capacity=1, retry_interval_s=5.0)
    token = store.reserve("close", "a", "emit", "unconfirmed", True, "x")
    store.convert(token, _event())
    store.mark_result(token, "persist_failure", "temporary")
    assert store.due() == []
    store._slots[token.slot].last_attempt -= 6.0
    assert store.due() == [token]
    store.mark_result(token, "created", None)
    assert store.free() == 1
    assert store.progress_state() == "free"


# R2-E ---------------------------------------------------------------------

@pytest.mark.parametrize("candidate", [
    "file:///D:/alpr/database/plpr.db",
    "file:///d:/ALPR/database/plpr.db",
    "file:D:/alpr/database/plpr.db",
    "file:///D:/alpr/database/../database/plpr.db",
    "file:D:/alpr/database/plpr.db?mode=rw",
    "file:D:/alpr/database/plpr.db?mode=ro",
    "file:D:/alpr/database/plpr.db?mode=rwc",
    "file://localhost/D:/alpr/database/plpr.db",
    "file:///D:/alpr/database/plpr%2Edb",
])
def test_production_uri_forms_are_rejected(candidate):
    import sqlite3

    assert is_production_db_path(candidate) is True
    with pytest.raises(RuntimeError, match="Refusing to open"):
        sqlite3.connect(candidate)


def test_dbapi2_connect_is_guarded():
    import sqlite3

    from tests.isolation import _PRODUCTION_DB
    with pytest.raises(RuntimeError, match="Refusing to open"):
        sqlite3.dbapi2.connect(_PRODUCTION_DB)


def test_no_pre_guard_sqlite_connect_alias_in_test_tree():
    import re
    root = Path(__file__).resolve().parent.parent
    pattern = re.compile(r"^\s*from\s+sqlite3(?:\.dbapi2)?\s+import\s+connect",
                         re.MULTILINE)
    offenders = []
    for base in (root / "tests", root / "auth", root / "licensing"):
        for path in base.rglob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(root)))
    if (root / "test_backend.py").exists():
        if pattern.search((root / "test_backend.py").read_text(encoding="utf-8")):
            offenders.append("test_backend.py")
    assert offenders == []


def test_replay_import_does_not_change_db_path():
    import db
    before = db.DB_PATH
    import validation.replay_runner  # noqa: F401
    assert db.DB_PATH == before


# R2-F ---------------------------------------------------------------------

def test_replay_uid_consistent_in_raw_track_and_analysis(tmp_path):
    from validation.analyze_events import analyze
    from validation.replay_runner import _event_to_dict

    event = _event(event_uid="uid-replay")
    raw = _event_to_dict(event)
    event_path = tmp_path / "raw_events.jsonl"
    event_path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    (tmp_path / "observations.jsonl").write_text("", encoding="utf-8")
    summary = {
        "metrics": {"observations_accepted": 1, "tracks_created": 1},
        "video": {"fps": 1, "file": "x.mp4"},
        "run_at": "",
    }
    (tmp_path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    report = analyze(tmp_path)
    assert report["events"][0]["event_uid"] == "uid-replay"


# R2-G ---------------------------------------------------------------------

def test_video_session_closes_on_terminal_error(event_db):
    from routers.detection import _close_video_session

    sid = event_db.start_session("video", "clip.mp4")
    state = {"total_frames": 10, "plate_log": [{"dtrb_text": "12b34567"}]}
    _close_video_session(sid, state, "error")
    _close_video_session(sid, state, "error")

    conn = event_db.get_conn()
    try:
        rows = conn.execute(
            "SELECT status, ended_at FROM sessions WHERE id = ?", (sid,)
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert rows[0]["ended_at"]


# R2-H ---------------------------------------------------------------------

def test_replay_import_restores_global_environment():
    keys = ("ALPR_PIPELINE_VIDEO", "ALPR_PIPELINE_MODE")
    before = {k: os.environ.get(k) for k in keys}
    import validation.replay_runner  # noqa: F401
    assert {k: os.environ.get(k) for k in keys} == before
