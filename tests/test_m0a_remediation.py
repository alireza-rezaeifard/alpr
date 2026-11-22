"""Focused regression tests for the M0-A audit remediation (R1-R6).

These tests use only temporary SQLite files. The repository-wide guard in the
root ``conftest.py`` refuses the production database before SQLite opens it.
"""
from __future__ import annotations

import sqlite3

import pytest

import db as db_module
from pipeline.config import PipelineConfig
from pipeline.integration import EventPipeline
from pipeline.retention import (
    CONFLICT,
    EXHAUSTED,
    PENDING,
    UnifiedRetentionStore,
)
from pipeline.track_manager import TrackManager
from pipeline.types import Box, PlateRead, Track, VehicleEvent


@pytest.fixture()
def event_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "remediation.db"))
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
    event = VehicleEvent(**data)
    event.finalize_reason = "force_at_close"
    return event


def _box():
    return Box(0.1, 0.1, 0.2, 0.3, conf=0.9, cls=2)


def _read():
    return PlateRead(
        frame_idx=1, ts="t", text="12b34567", char_count=8,
        plate_det_conf=0.9, plate_area_px=4800, aspect_ratio=4.6,
        sharpness=120.0, brightness_ok=True, usable=True, weight=0.9,
    )


def _track(key="1:42:1", uid="uid-1"):
    return Track(
        track_key=key, kind="vehicle", state="TRACKING",
        first_ts=0.0, last_ts=0.0, event_uid=uid,
        observations=[_read()],
    )


def _fill_slot(store, event=None):
    token = store.reserve("close", "1:42:1", "emit", "unconfirmed", True, "x")
    assert token is not None
    store.convert(token, event or _event())
    return token


# --- R1: shutdown admission / no loss -------------------------------------

def test_expire_all_keeps_track_when_no_slot_is_available():
    tm = TrackManager()
    tm._tracks["1:42:1"] = _track()
    store = UnifiedRetentionStore(capacity=1)
    held = _fill_slot(store)

    requests, tokens = tm.expire_all_admitted("shutdown", store)

    assert requests == []
    assert tokens == []
    assert tm.get("1:42:1").state == "TRACKING"
    assert store.free() == 0

    store.release(held)
    requests, tokens = tm.expire_all_admitted("shutdown", store)
    assert len(requests) == len(tokens) == 1
    assert requests[0].event_uid == "uid-1"
    assert tm.get("1:42:1").state == "EXPIRED"


def test_event_pipeline_expire_retains_blocked_track(event_db):
    ep = EventPipeline(
        source_type="rtsp", camera_id=1, session_id=42,
        cfg=PipelineConfig(retention_capacity=1),
    )
    ep._lifecycle._tracks["1:42:1"] = _track()
    held = _fill_slot(ep._retention)
    ep._retention.mark_result(held, "identity_conflict", "held terminal")

    assert ep.expire("shutdown") == []
    assert ep._lifecycle.get("1:42:1").state == "TRACKING"
    assert ep.get_metrics()["retention"]["blocked"] is True
    assert ep.get_metrics().get("retention_blocked", 0) == 1

    ep._retention.release(held)
    events = ep.expire("shutdown")
    assert len(events) == 1
    assert events[0].event_uid == "uid-1"
    assert ep._lifecycle.get("1:42:1").state == "EXPIRED"


def test_expire_all_requires_admission():
    tm = TrackManager()
    tm._tracks["1:42:1"] = _track()
    with pytest.raises(ValueError, match="requires an admission store"):
        tm.expire_all("shutdown")


# --- R2: retry timing / exhaustion / saturation ---------------------------

def test_pending_retry_honors_interval_then_exhausts():
    store = UnifiedRetentionStore(capacity=1, retry_interval_s=5.0,
                                  max_attempts=2)
    token = _fill_slot(store)
    store.mark_result(token, "persist_failure", "db down")

    assert store.due() == []
    store._slots[token.slot].last_attempt -= 6.0
    assert store.due() == [token]

    store.mark_result(token, "persist_failure", "still down")
    assert store.count(EXHAUSTED) == 1
    assert store.due() == []
    assert store.blocked() is True


def test_conflict_is_terminal_and_saturates_capacity():
    store = UnifiedRetentionStore(capacity=1)
    token = _fill_slot(store)
    store.mark_result(token, "identity_conflict", "key/uid mismatch")

    assert store.count(CONFLICT) == 1
    assert store.free() == 0
    assert store.due() == []
    assert store.blocked() is True
    assert store.snapshot()["conflicts"] == 1


# --- R3: retry exception ownership ----------------------------------------

def test_get_conn_failure_is_persist_failure(event_db, monkeypatch):
    def boom():
        raise sqlite3.OperationalError("cannot connect")
    monkeypatch.setattr(event_db, "get_conn", boom)

    result = event_db.persist_event(_event())
    assert result.outcome == "persist_failure"
    assert "cannot connect" in (result.detail or "")


def test_retry_exception_does_not_abort_drain(event_db, monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42)
    token = ep._retention.reserve("close", "1:42:1", "emit",
                                  "unconfirmed", True, "x")
    ep._retention.convert(token, _event())
    ep._retention._slots[token.slot].last_attempt -= 999.0

    def boom(event):
        raise sqlite3.OperationalError("retry connection failed")
    monkeypatch.setattr(event_db, "persist_event", boom)

    ep.drain_retention()  # must not raise

    payload = ep._retention.payload(token)
    assert payload.event_uid == "uid-a"
    assert ep._retention.count(PENDING) == 1


# --- R4: retry success / classification -----------------------------------



def test_one_failed_retry_does_not_block_other_due_entries(event_db, monkeypatch):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42)
    first = ep._retention.reserve("close", "cam1:42:1", "emit",
                                  "unconfirmed", True, "x")
    second = ep._retention.reserve("close", "cam1:42:2", "emit",
                                   "unconfirmed", True, "x")
    ep._retention.convert(first, _event(event_key="cam1:42:1", event_uid="u1"))
    ep._retention.convert(second, _event(event_key="cam1:42:2", event_uid="u2"))
    for slot in ep._retention._slots:
        slot.last_attempt -= 999.0

    real = event_db.persist_event
    def selective(event):
        if event.event_key == "cam1:42:1":
            raise sqlite3.OperationalError("first failed")
        return real(event)
    monkeypatch.setattr(event_db, "persist_event", selective)

    ep.drain_retention()

    assert ep._registry.is_emitted("cam1:42:2")
    assert not ep._registry.is_emitted("cam1:42:1")
    assert ep._retention.count(PENDING) == 1

def test_retry_success_registers_exactly_once(event_db):
    ep = EventPipeline(source_type="rtsp", camera_id=1, session_id=42)
    token = ep._retention.reserve("close", "1:42:1", "emit",
                                  "unconfirmed", True, "x")
    event = _event()
    ep._retention.convert(token, event)
    ep._retention._slots[token.slot].last_attempt -= 999.0

    ep.drain_retention()
    ep.drain_retention()

    assert ep._registry.is_emitted(event.event_key)
    assert ep.get_metrics()["events_finalized"] == 1
    assert ep.get_metrics()["finalization_reasons"] == {"force_at_close": 1}
    assert ep._retention.free() == ep.cfg.retention_capacity


def test_not_null_error_is_persist_failure_not_identity_conflict(event_db):
    result = event_db.persist_event(_event(plate_number=None))
    assert result.outcome == "persist_failure"
    assert "not null" in (result.detail or "").lower()


# --- R6: replay public identity -------------------------------------------

def test_replay_event_dict_contains_event_uid():
    import os
    keys = ("ALPR_PIPELINE_VIDEO", "ALPR_PIPELINE_MODE")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        from validation.replay_runner import _event_to_dict
        assert _event_to_dict(_event())["event_uid"] == "uid-a"
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
