"""Phase 0: track lifecycle state machine — every valid transition (§2.4)
plus invalid-transition rejection. Design D.1 row 5."""
from __future__ import annotations

import pytest

from pipeline import track_manager as tm
from pipeline.config import PipelineConfig
from pipeline.track_manager import InvalidTransition, TrackManager
from pipeline.types import Box, PlateRead, Track, TrackUpdate

CFG = PipelineConfig()


def box(conf=0.8):
    return Box(x1=0.1, y1=0.4, x2=0.3, y2=0.6, conf=conf, cls=2)


def update(key="1:1:1", state="TRACKED", hits=2, tsi=0):
    return TrackUpdate(track_key=key, kind="vehicle", box=box(), state=state,
                       hits=hits, age=hits, time_since_update=tsi)


def usable_read(frame_idx=0, weight=0.5):
    return PlateRead(frame_idx=frame_idx, ts="2026-09-29T00:00:00Z",
                     text="12b34567", char_count=8, plate_det_conf=0.9,
                     plate_area_px=4800, aspect_ratio=4.6, sharpness=120.0,
                     brightness_ok=True, usable=True, weight=weight)


def make_tracked_manager(now=0.0) -> tuple:
    m = TrackManager(CFG)
    m.apply_updates([update(hits=1)], now=now)      # NEW (hits=1 < min 2)
    m.apply_updates([update(hits=2)], now=now + 0.125)  # NEW -> TRACKING
    assert m.get("1:1:1").state == tm.TRACKING
    return m, now + 0.125


def test_new_to_tracking():
    m, _ = make_tracked_manager()
    assert m.get("1:1:1").state == tm.TRACKING


def test_tracking_to_plate_captured():
    m, now = make_tracked_manager()
    m.attach_read("1:1:1", usable_read(), now=now)
    assert m.get("1:1:1").state == tm.PLATE_CAPTURED


def test_plate_captured_to_confirmed_emits_once():
    m, now = make_tracked_manager()
    m.attach_read("1:1:1", usable_read(), now=now)
    req = m.mark_confirmed("1:1:1")
    assert req is not None
    assert req.action == "emit"
    assert req.status == "confirmed"
    assert m.get("1:1:1").state == tm.CONFIRMED
    # Explicit EVENT_EMITTED flag: second emission refused (§2.5 rule 2).
    assert m.mark_confirmed("1:1:1") is None
    assert m.double_emit_blocked == 1


def test_confirmed_to_completed_on_expiry():
    m, now = make_tracked_manager()
    m.attach_read("1:1:1", usable_read(), now=now)
    m.mark_confirmed("1:1:1")
    # No association for > track_expiry_s (2.0 s at 8 fps).
    m.apply_updates([], now=now + 10.0)
    track = m.get("1:1:1")
    assert track.state == tm.COMPLETED


def test_tracking_to_completed_with_evidence_requests_force_emit():
    m, now = make_tracked_manager()
    m.attach_read("1:1:1", usable_read(), now=now)   # PLATE_CAPTURED, not confirmed
    requests = m.apply_updates([], now=now + 10.0)
    assert [r.action for r in requests] == ["emit"]
    assert requests[0].status == "unconfirmed"
    assert requests[0].needs_review is True         # §4.6 FORCE_AT_CLOSE
    assert requests[0].reason == "force_at_close"
    assert m.get("1:1:1").state == tm.COMPLETED


def test_tracking_to_completed_without_evidence_dropped():
    m, now = make_tracked_manager()
    requests = m.apply_updates([], now=now + 10.0)
    assert requests == []
    assert m.tracks_dropped_no_evidence == 1
    assert m.get("1:1:1").state == tm.COMPLETED


def test_new_to_expired_on_glint():
    """A never-confirmed one-hit track expires without an event (§2.4 NEW→EXPIRED)."""
    m = TrackManager(CFG)
    m.apply_updates([update(hits=1)], now=0.0)     # stays NEW
    requests = m.apply_updates([], now=10.0)
    assert requests == []
    assert m.tracks_rejected_new == 1
    assert m.get("1:1:1").state == tm.EXPIRED


def test_any_to_expired_flush_keeps_evidence():
    m, now = make_tracked_manager()
    m.attach_read("1:1:1", usable_read(), now=now)
    requests = m.expire_all(reason="shutdown")
    assert len(requests) == 1
    assert requests[0].status == "unconfirmed"
    assert m.get("1:1:1").state == tm.EXPIRED
    # Terminal: nothing else can move it.
    assert m.expire_all() == []


def test_lost_then_resume_keeps_lifecycle_state():
    m, now = make_tracked_manager()
    m.attach_read("1:1:1", usable_read(), now=now)
    m.apply_updates([update(state="LOST", hits=3, tsi=1)], now=now + 0.125)
    assert m.get("1:1:1").state == tm.PLATE_CAPTURED   # LOST does not regress
    m.apply_updates([update(state="TRACKED", hits=4, tsi=0)], now=now + 0.250)
    assert m.get("1:1:1").state == tm.PLATE_CAPTURED


def test_invalid_transition_raises():
    m = TrackManager(CFG)
    track = Track(track_key="1:1:9", kind="vehicle", state=tm.COMPLETED)
    with pytest.raises(InvalidTransition):
        m._transition(track, tm.TRACKING)
    track2 = Track(track_key="1:1:8", kind="vehicle", state=tm.EXPIRED)
    with pytest.raises(InvalidTransition):
        m._transition(track2, tm.PLATE_CAPTURED)
    # Same-state is a no-op, not an error.
    m._transition(track, tm.COMPLETED)


def test_valid_transition_table_complete():
    """Every §2.4 row is in the allow-list (and nothing else is)."""
    allowed = tm._VALID_TRANSITIONS
    assert allowed[tm.NEW] == {tm.TRACKING, tm.EXPIRED}
    assert allowed[tm.TRACKING] == {tm.TRACKING, tm.PLATE_CAPTURED,
                                   tm.COMPLETED, tm.EXPIRED}
    assert allowed[tm.PLATE_CAPTURED] == {tm.PLATE_CAPTURED, tm.CONFIRMED,
                                         tm.COMPLETED, tm.EXPIRED}
    assert allowed[tm.CONFIRMED] == {tm.CONFIRMED, tm.COMPLETED, tm.EXPIRED}
    assert allowed[tm.COMPLETED] == set()
    assert allowed[tm.EXPIRED] == set()
    # No terminal-state resurrection.
    assert tm.COMPLETED not in allowed[tm.EXPIRED]
    assert tm.TRACKING not in allowed[tm.COMPLETED]
