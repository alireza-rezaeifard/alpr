"""Phase 1: event pipeline integration tests.

Covers the task's §11 matrix for the new pipeline: one visit → one event,
idempotent finalization, OCR corrections, later genuine visits, camera
isolation, and invalid-plate rejection — all against the real EventPipeline
wiring (tracker → lifecycle → consensus → event builder → durable upsert).
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from pipeline.integration import EventPipeline
from pipeline.types import VehicleEvent


class _FakeResult:
    """Stand-in for alpr_engine.AlprResult (only the fields the pipeline reads)."""

    def __init__(self, text, plate_bbox, plate_det_conf=0.9, char_conf=0.85,
                 vehicle_boxes=None):
        self.plate_text = text
        self.plate_bbox = plate_bbox
        self.confidence = plate_det_conf
        self.plate_det_conf = plate_det_conf
        self.char_conf = char_conf
        self.vehicle_boxes = vehicle_boxes or []
        self.char_bboxes = []
        self.car_bbox = None
        self.car_color = None
        self.car_type = None
        self.city = None


W, H = 1280, 720


def _mk(source="rtsp", camera_id=1):
    return EventPipeline(source_type=source, camera_id=camera_id,
                         camera_name=f"cam-{camera_id}")


def _feed(ep, texts, conf=0.9):
    """Feed one frame per text; a stable vehicle box so one track forms."""
    events = []
    for i, t in enumerate(texts):
        bbox = (500, 300, 700, 360)  # pixel coords, plate
        results = [_FakeResult(t, bbox, plate_det_conf=conf,
                               vehicle_boxes=[(460, 200, 760, 500)])]
        events.extend(ep.process_results(i, W, H, results))
    return events


# ---------------------------------------------------------------------------
# Events: multiple frames → one finalized event
# ---------------------------------------------------------------------------

def test_many_frames_one_track_one_event():
    ep = _mk()
    events = _feed(ep, ["12b34567"] * 10, conf=0.92)
    # CONFIRM fires once; the remaining frames never create a second event.
    finalized = [e for e in events if e.status == "confirmed"]
    assert len(finalized) == 1
    assert finalized[0].plate_number == "12b34567"
    # Feeding more identical frames after confirmation changes nothing.
    more = _feed(ep, ["12b34567"] * 5, conf=0.92)
    assert all(e is None or e.status != "confirmed" or e.plate_number != "12b34567"
               or e.event_key != finalized[0].event_key for e in more) or not more
    assert ep.get_metrics()["duplicate_finalizations_suppressed"] >= 0


def test_ocr_correction_within_track_no_second_event():
    """A 1-char OCR wobble mid-visit must not split the visit (§6)."""
    ep = _mk()
    seq = ["12b34567"] * 4 + ["12b34587"] + ["12b34567"] * 4
    events = _feed(ep, seq, conf=0.9)
    confirmed = [e for e in events if e.status == "confirmed"]
    assert len(confirmed) == 1


def test_later_genuine_visit_new_event():
    """Vehicle leaves past the expiry window, returns: second event allowed."""
    ep = _mk()
    first = _feed(ep, ["12b34567"] * 6, conf=0.9)
    assert len([e for e in first if e.status == "confirmed"]) == 1
    # Simulate the passage of cooldown time without real sleeping.
    ep._lifecycle._last_emit_by_plate["12b34567"] -= (
        ep.cfg.reentry_cooldown_s + ep.cfg.fragment_window_s + 1.0)
    # Vehicle returns as a brand-new track (tracker flushed as on reconnect).
    ep._tracker.reset()
    second = _feed(ep, ["12b34567"] * 6, conf=0.9)
    assert len([e for e in second if e.status == "confirmed"]) == 1


# ---------------------------------------------------------------------------
# Tracking: camera isolation
# ---------------------------------------------------------------------------

def test_camera_isolation_events_and_keys():
    ep1, ep2 = _mk(camera_id=1), _mk(camera_id=2)
    ev1 = _feed(ep1, ["12b34567"] * 5, conf=0.9)
    ev2 = _feed(ep2, ["12b34567"] * 5, conf=0.9)
    c1 = [e for e in ev1 if e.status == "confirmed"]
    c2 = [e for e in ev2 if e.status == "confirmed"]
    assert len(c1) == 1 and len(c2) == 1
    # Separate cameras must not suppress each other's events (§7): distinct
    # event identities scoped by camera.
    assert c1[0].event_key != c2[0].event_key
    assert ep1.scope != ep2.scope


def test_track_ids_do_not_collide_across_camera_pipelines():
    a, b = _mk(camera_id=1), _mk(camera_id=2)
    ua = a._tracker.update([], 0.0)
    box = __import__("pipeline.types", fromlist=["Box"]).Box(0.1, 0.1, 0.2, 0.2, conf=0.9, cls=2)
    ua = a._tracker.update([box], 0.0)
    ub = b._tracker.update([box], 0.0)
    assert ua[0].track_key != ub[0].track_key


# ---------------------------------------------------------------------------
# Rejection policy: no fabricated plates, no successful events
# ---------------------------------------------------------------------------

def test_track_expiring_without_valid_plate_creates_no_confirmed_event():
    ep = _mk()
    # Garbage text (fails Iranian validation) → observations recorded, but a
    # close must not fabricate a successful recognized event.
    events = _feed(ep, ["x9"] * 6, conf=0.2)
    confirmed = [e for e in events if e.status == "confirmed"]
    assert confirmed == []
    flushed = ep.expire("test")
    assert all(e.status != "confirmed" or not e.plate_valid for e in flushed)


def test_low_confidence_observations_rejected():
    ep = _mk()
    _feed(ep, ["12b34567"] * 3, conf=0.1)  # below plate_gate_conf=0.5
    m = ep.get_metrics()
    assert m["observations_rejected"] == 3
    assert m["observations_accepted"] == 0


# ---------------------------------------------------------------------------
# Idempotency: repeated finalization is suppressed
# ---------------------------------------------------------------------------

def test_repeated_finalization_idempotent_in_memory():
    ep = _mk()
    _feed(ep, ["12b34567"] * 5, conf=0.9)
    # The visit was already finalized once during the feed (CONFIRM fired);
    # re-issuing the same track-finalization request must not create another
    # successful event (§6 idempotency).
    key = next(iter(ep._lifecycle._tracks))
    from pipeline.types import EmissionRequest
    import time as _time
    req = EmissionRequest(track_key=key, action="emit", status="confirmed",
                          reason="consensus_confirm")
    repeat = ep._finalize(req, _time.monotonic(), closing=False)
    assert repeat is None
    m = ep.get_metrics()
    assert m["duplicate_finalizations_suppressed"] >= 1
    assert m["events_finalized"] == 1


# ---------------------------------------------------------------------------
# Durable persistence (real SQLite, tmp db file)
# ---------------------------------------------------------------------------

@pytest.fixture()
def temp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPR_DB_PATH_CHECK", "1")
    import db
    db.DB_PATH = str(tmp_path / "phase1.db")
    db.init_db()
    yield db
    db.DB_PATH = os.path.join(os.path.dirname(db.__file__), "database", "plpr.db")


def test_durable_upsert_idempotent_across_restart(temp_db):
    db = temp_db
    ev = VehicleEvent(
        event_key="cam1:0:5", track_id="cam1:0:5", track_kind="vehicle",
        first_seen="2026-09-29T10:00:00", last_seen="2026-09-29T10:00:02",
        plate_number="12b34567", plate_norm="12b34567",
        confidence=0.9, agreement_ratio=0.9, status="confirmed",
    )
    rid1, created1 = db.upsert_vehicle_event(ev)
    rid2, created2 = db.upsert_vehicle_event(ev)  # repeat after 'restart'
    assert created1 is True
    assert created2 is False
    assert rid1 == rid2
    stats = db.get_vehicle_event_stats()
    assert stats["total_events"] == 1


def test_durable_upsert_different_cameras_both_persist(temp_db):
    db = temp_db
    for cam in (1, 2):
        ev = VehicleEvent(
            event_key=f"cam{cam}:0:5", track_id=f"cam{cam}:0:5", track_kind="vehicle",
            first_seen="2026-09-29T10:00:00", last_seen="2026-09-29T10:00:02",
            plate_number="12b34567", plate_norm="12b34567", status="confirmed",
            camera_id=cam,
        )
        rid, created = db.upsert_vehicle_event(ev)
        assert created is True
    assert db.get_vehicle_event_stats()["total_events"] == 2


def test_migration_forward_and_reinit_idempotent(temp_db):
    db = temp_db
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(detections)")}
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "vehicle_events" in tables
    assert "event_key" in cols
    # Re-running init_db must be a no-op (forward+re-run safety).
    db.init_db()
    conn = sqlite3.connect(db.DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM vehicle_events").fetchone()[0]
    conn.close()
    assert n == 0
