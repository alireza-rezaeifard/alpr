"""M0-A focused tests (reconstructed SPEC-01..43 groups).

The canonical 43-scenario artifact is not present in the repository; these
tests cover the approved identity, source, persistence, migration, retention,
and concurrency contracts.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

import db as db_module
from pipeline.config import PipelineConfig
from pipeline.event_builder import make_event_key
from pipeline.integration import EventPipeline
from pipeline.retention import CONFLICT, PENDING, UnifiedRetentionStore
from pipeline.track_manager import TrackManager
from pipeline.types import Box, EmissionRequest, TrackUpdate, VehicleEvent


@pytest.fixture()
def identity_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "m0a.db"))
    db_module.init_db()
    return db_module


def _event(**over):
    data = dict(
        event_key="cam1:42:1",
        event_uid="uid-a",
        track_id="cam1:42:1",
        track_kind="vehicle",
        first_seen="2026-01-01T00:00:00",
        last_seen="2026-01-01T00:00:02",
        plate_number="12b34567",
        plate_norm="12b34567",
        confidence=0.9,
        agreement_ratio=0.9,
        status="confirmed",
        camera_id=1,
        session_id=42,
        source_type="rtsp",
        source_file="rtsp://cam1",
    )
    data.update(over)
    return VehicleEvent(**data)


def _box(x=0.1):
    return Box(x, 0.1, x + 0.1, 0.3, conf=0.9, cls=2)


# --- SPEC-01..08: identity generation -------------------------------------
def test_track_gets_one_stable_uuid():
    tm = TrackManager()
    store = UnifiedRetentionStore(capacity=4)
    update = TrackUpdate("cam1:42:1", "vehicle", _box(), "NEW", 1, 1, 0)
    tm.apply_updates_admitted([update], 0.0, store)
    track = tm.get("cam1:42:1")
    assert track.event_uid and uuid.UUID(track.event_uid).version == 4
    first = track.event_uid
    tm.apply_updates_admitted([TrackUpdate("cam1:42:1", "vehicle", _box(0.12),
                                           "TRACKED", 2, 2, 0)], 0.1, store)
    assert tm.get("cam1:42:1").event_uid == first


def test_new_manager_new_uuid():
    def uid():
        tm = TrackManager()
        tm.apply_updates_admitted([TrackUpdate("cam1:42:1", "vehicle", _box(),
                                               "NEW", 1, 1, 0)], 0.0,
                                  UnifiedRetentionStore(capacity=4))
        return tm.get("cam1:42:1").event_uid
    assert uid() != uid()


def test_unadmitted_apply_updates_is_rejected_without_mutation():
    tm = TrackManager()
    with pytest.raises(ValueError, match="requires admission"):
        tm.apply_updates([TrackUpdate("cam1:42:1", "vehicle", _box(),
                                      "NEW", 1, 1, 0)], now=0.0)
    assert tm.get("cam1:42:1") is None


def test_pipeline_key_uses_session_not_zero():
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42)
    update = ep._tracker.update([_box()], 0.0)[0]
    assert update.track_key == "1:42:1"
    assert ":0:" not in update.track_key


def test_pipeline_without_session_gets_run_instance():
    ep = EventPipeline(source_type="video", camera_id=None)
    update = ep._tracker.update([_box()], 0.0)[0]
    parts = update.track_key.split(":")
    assert parts[0] == "video"
    assert parts[1] and parts[1] != "0"
    assert parts[2] == "1"


def test_event_key_deterministic():
    assert make_event_key(1, 42, 7) == make_event_key(1, 42, 7)
    assert make_event_key(1, 42, 7) != make_event_key(1, 43, 7)
    assert make_event_key(1, 42, 7) != make_event_key(2, 42, 7)


def test_plate_fallback_uid_and_key_parse():
    ep = EventPipeline(source_type="video", session_id=7)
    box = _box()
    ep._plate_tracker.update([box], 0.0)
    key = ep._plate_tracker.update([box], 0.1)[0].track_key
    assert ":plate:" in key
    from pipeline.event_builder import local_track_id_from_key
    assert local_track_id_from_key(key) == 1


# --- SPEC-09..17: source/session lifecycle --------------------------------
def test_event_pipeline_receives_session_and_source():
    ep = EventPipeline(source_type="video", camera_id=None, session_id=9,
                       source_file="clip.mp4")
    assert ep.session_id == 9
    assert ep.source_instance_id == 9
    assert ep.source_file == "clip.mp4"


def test_stop_start_new_session_new_key():
    a = EventPipeline(source_type="rtsp", camera_id=1, session_id=10)
    b = EventPipeline(source_type="rtsp", camera_id=1, session_id=11)
    assert a._tracker.update([_box()], 0.0)[0].track_key == "1:10:1"
    assert b._tracker.update([_box()], 0.0)[0].track_key == "1:11:1"


def test_two_video_sessions_distinct_keys():
    a = EventPipeline(source_type="video", session_id=20)
    b = EventPipeline(source_type="video", session_id=21)
    assert a._tracker.update([_box()], 0.0)[0].track_key != \
        b._tracker.update([_box()], 0.0)[0].track_key


def test_replay_symbolic_camera_normalized():
    import os
    keys = ("ALPR_PIPELINE_VIDEO", "ALPR_PIPELINE_MODE")
    saved = {k: os.environ.get(k) for k in keys}
    saved_db_path = db_module.DB_PATH
    try:
        from validation.replay_runner import normalize_replay_camera_id
        assert normalize_replay_camera_id("cam1") is None
        assert normalize_replay_camera_id("7") == 7
        assert normalize_replay_camera_id(7) == 7
    finally:
        db_module.DB_PATH = saved_db_path
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# --- SPEC-18..23: compatibility -------------------------------------------
def test_track_id_equals_event_key():
    from pipeline.event_builder import build_event
    from pipeline.types import ConsensusResult, PlateRead
    best = PlateRead(frame_idx=1, ts="t", text="12b34567", char_count=8,
                     plate_det_conf=0.9, plate_area_px=100, aspect_ratio=2.0,
                     sharpness=1.0, brightness_ok=True, usable=True, weight=0.8)
    result = ConsensusResult(track_key="1:42:1", plate="12b34567",
                             char_conf=(0.9,) * 8, agreement_ratio=0.9,
                             confidence=0.9, posterior_min=0.8,
                             length_mode_weight=1.0, best=best)
    ev = build_event("1:42:1", result, track_kind="vehicle", first_seen="a",
                     last_seen="b", frame_count=2, observation_count=1,
                     duration_ms=1, plate_valid=True)
    assert ev.track_id == ev.event_key == "1:42:1"


# --- SPEC-24..33: persistence / retention ---------------------------------
def test_persist_created_then_updated(identity_db):
    ev = _event()
    first = identity_db.persist_event(ev)
    second = identity_db.persist_event(ev)
    assert first.outcome == "created"
    assert second.outcome == "updated"
    assert first.event_row_id == second.event_row_id


def test_persist_same_key_different_uid_conflicts(identity_db):
    assert identity_db.persist_event(_event()).outcome == "created"
    result = identity_db.persist_event(_event(event_uid="uid-b",
                                              plate_number="99z99999"))
    assert result.outcome == "identity_conflict"
    conn = identity_db.get_conn()
    try:
        row = conn.execute("SELECT plate_number FROM vehicle_events").fetchone()
        assert row["plate_number"] == "12b34567"
    finally:
        conn.close()


def test_persist_same_uid_different_key_conflicts(identity_db):
    assert identity_db.persist_event(_event()).outcome == "created"
    result = identity_db.persist_event(_event(event_key="cam1:42:2"))
    assert result.outcome == "identity_conflict"


def test_persist_metadata_mismatch_conflicts(identity_db):
    assert identity_db.persist_event(_event()).outcome == "created"
    result = identity_db.persist_event(_event(session_id=43))
    assert result.outcome == "identity_conflict"
    assert "session_id" in (result.detail or "")


def test_persist_failure_is_structured(identity_db, monkeypatch):
    def boom():
        raise sqlite3.OperationalError("db down")
    monkeypatch.setattr(identity_db, "get_conn", boom)
    result = identity_db.persist_event(_event())
    assert result.outcome == "persist_failure"
    assert "db down" in (result.detail or "")


def test_retention_reserve_convert_release():
    store = UnifiedRetentionStore(capacity=2)
    token = store.reserve("confirm", "1:42:1", "emit", "confirmed", False,
                          "consensus_confirm")
    assert token is not None
    assert store.free() == 1
    store.park_request(token, EmissionRequest("1:42:1", "emit", "confirmed"))
    store.convert(token, _event())
    assert store.payload(token).event_uid == "uid-a"
    store.release(token)
    assert store.free() == 2


def test_retention_capacity_is_hard():
    store = UnifiedRetentionStore(capacity=2)
    assert store.reserve("close", "a:1:1", "emit", "unconfirmed", True, "x")
    assert store.reserve("close", "a:1:2", "emit", "unconfirmed", True, "x")
    assert store.reserve("close", "a:1:3", "emit", "unconfirmed", True, "x") is None
    assert store.free() == 0


def test_integration_persist_failure_retained_and_drained(identity_db, monkeypatch):
    calls = {"n": 0}
    real = identity_db.persist_event

    def fail_once(event):
        calls["n"] += 1
        if calls["n"] == 1:
            return identity_db.EventPersistResult("persist_failure", None,
                                                  event.event_uid, "transient")
        return real(event)

    monkeypatch.setattr(identity_db, "persist_event", fail_once)
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42)
    # Build a track and force a finalized event through the pipeline.
    box = _box()
    for i in range(8):
        ep._tracker.update([box], i * 0.125)
        ep._lifecycle.apply_updates_admitted(
            [TrackUpdate("1:42:1", "vehicle", box, "TRACKED", i + 1, i + 1, 0)],
            i * 0.125, ep._retention)
        ep._lifecycle.attach_read("1:42:1", __import__("pipeline.types", fromlist=["PlateRead"]).PlateRead(
            frame_idx=i, ts="t", text="12b34567", char_count=8,
            plate_det_conf=0.9, plate_area_px=100, aspect_ratio=2.0,
            sharpness=1.0, brightness_ok=True, usable=True, weight=0.9), now=i * 0.125)
    token = ep._retention.reserve(
        "confirm", "1:42:1", "emit", "confirmed", False,
        "consensus_confirm", event_uid=ep._lifecycle.get("1:42:1").event_uid)
    request = ep._lifecycle.mark_confirmed("1:42:1", ep._retention, token)
    assert request is not None
    assert ep._finalize(request, 1.0, closing=True, token=token) is None
    assert ep.get_metrics()["retention"]["pending"] >= 1
    # PENDING retries now honor the configured backoff; simulate elapsed time.
    for slot in ep._retention._slots:
        if slot.state == "PENDING":
            slot.last_attempt -= ep.cfg.retention_retry_interval_s + 1.0
    ep.drain_retention()
    assert ep.get_metrics()["retention"]["pending"] == 0


# --- SPEC-34..39: migration/backfill --------------------------------------
def test_init_db_idempotent(identity_db):
    identity_db.init_db()
    identity_db.init_db()
    conn = identity_db.get_conn()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(vehicle_events)")}
        assert "event_uid" in cols
        assert conn.execute("SELECT count(*) FROM vehicle_events").fetchone()[0] == 0
    finally:
        conn.close()


def test_backfill_existing_table_without_uid(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
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
        VALUES ('cam1:0:1', 'cam1:0:1', 'a', 'b', '12b34567', '12b34567', 'a', 'b');
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(db_module, "DB_PATH", str(path))
    # The UUID5 backfill is an explicitly authorized data migration (R3-F);
    # ordinary init_db() no longer runs it implicitly.
    db_module.init_db(run_migrations=True)
    first = sqlite3.connect(path)
    uid1 = first.execute("SELECT event_uid FROM vehicle_events").fetchone()[0]
    first.close()
    db_module.init_db(run_migrations=True)
    second = sqlite3.connect(path)
    uid2 = second.execute("SELECT event_uid FROM vehicle_events").fetchone()[0]
    second.close()
    assert uid1 and uid1 == uid2
    # Historical key/plate preserved.
    check = sqlite3.connect(path)
    row = check.execute("SELECT event_key, plate_number FROM vehicle_events").fetchone()
    check.close()
    assert row == ("cam1:0:1", "12b34567")


def test_fresh_db_has_uid_column_and_index(identity_db):
    conn = identity_db.get_conn()
    try:
        idx = {r["name"] for r in conn.execute("PRAGMA index_list(vehicle_events)")}
        assert "idx_events_uid" in idx
    finally:
        conn.close()


# --- SPEC-40..41: concurrency ---------------------------------------------
def test_concurrent_same_uid_one_created(identity_db):
    barrier = threading.Barrier(2)

    def run(_):
        barrier.wait()
        return identity_db.persist_event(_event()).outcome

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, range(2)))
    assert sorted(outcomes) == ["created", "updated"]
    conn = identity_db.get_conn()
    try:
        assert conn.execute("SELECT count(*) FROM vehicle_events").fetchone()[0] == 1
    finally:
        conn.close()


def test_close_gate_tokens_stay_positionally_aligned():
    from pipeline.types import PlateRead, Track

    tm = TrackManager()
    now = 100.0
    for i, key in enumerate(("1:42:1", "1:42:2", "1:42:3"), start=1):
        tm._tracks[key] = Track(
            track_key=key, kind="vehicle", state="TRACKING",
            first_ts=0.0, last_ts=0.0, event_uid=f"uid-{i}",
            observations=[PlateRead(
                frame_idx=1, ts="t", text="12b34567", char_count=8,
                plate_det_conf=0.9, plate_area_px=100, aspect_ratio=2.0,
                sharpness=1.0, brightness_ok=True, usable=True, weight=0.9)])

    class Admission:
        def __init__(self):
            self.released = []

        def reserve_close(self, key, event_uid=None):
            return None if key.endswith(":2") else f"token:{key}"

        def release(self, token):
            self.released.append(token)

        def park_request(self, token, request):
            self.parked = getattr(self, "parked", [])
            self.parked.append((token, request))

    admission = Admission()
    requests, tokens = tm.apply_updates_admitted([], now, admission)
    assert [r.track_key for r in requests] == ["1:42:1", "1:42:3"]
    assert tokens == ["token:1:42:1", "token:1:42:3"]
    assert tm.get("1:42:2").state == "TRACKING"


def test_full_retention_pauses_generation():
    ep = EventPipeline(source_type="video", session_id=5)
    for i in range(ep.cfg.retention_capacity):
        assert ep._retention.reserve("close", f"v:{i}", "emit",
                                     "unconfirmed", True, "x") is not None
    ep.process_results(0, 100, 100, [])
    assert ep.get_metrics()["retention_paused_frames"] == 1


def test_concurrent_conflicting_uid_no_overwrite(identity_db):
    assert identity_db.persist_event(_event()).outcome == "created"
    barrier = threading.Barrier(2)

    def run(uid):
        barrier.wait()
        plate = "12b34567" if uid == "uid-a" else "99z99999"
        return identity_db.persist_event(
            _event(event_uid=uid, plate_number=plate)).outcome

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, ["uid-a", "uid-b"]))
    assert "identity_conflict" in outcomes
    conn = identity_db.get_conn()
    try:
        row = conn.execute("SELECT event_uid, plate_number FROM vehicle_events").fetchone()
        assert row["event_uid"] == "uid-a"
        assert row["plate_number"] == "12b34567"
    finally:
        conn.close()
