"""Phase 0: in-repo ByteTrack — unit + property (design §2.2-2.5, D.1 row 4)."""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pipeline.config import PipelineConfig
from pipeline.tracker import ByteTracker
from pipeline.types import Box

CFG = PipelineConfig()


def box(x1, y1=0.4, x2=None, y2=0.6, conf=0.8, cls=2) -> Box:
    if x2 is None:
        x2 = x1 + 0.15
    return Box(x1=x1, y1=y1, x2=x2, y2=y2, conf=conf, cls=cls)


def test_new_track_created_and_keyed_per_camera():
    t = ByteTracker(camera_id=7, session_epoch=3, cfg=CFG)
    updates = t.update([box(0.1)], ts=0.0)
    assert len(updates) == 1
    u = updates[0]
    assert u.track_key == "7:3:1"              # camera-scoped: cam:epoch:local
    assert u.state == "NEW"
    assert u.hits == 1


def test_matched_track_keeps_id():
    t = ByteTracker(7, 3)
    first = t.update([box(0.10)], ts=0.0)[0]
    second = t.update([box(0.11)], ts=0.125)[0]
    assert second.track_key == first.track_key  # matched, not re-created
    assert second.state == "TRACKED"
    assert second.hits == 2
    assert second.time_since_update == 0
    assert t.tracks_created == 1


def test_unmatched_track_goes_lost_then_expires():
    cfg = PipelineConfig(effective_fps=8.0, track_expiry_s=2.0)
    t = ByteTracker(1, 1, cfg=cfg)
    t.update([box(0.10)], ts=0.0)
    # No detections for > expiry window (2.0 s * 8 fps = 16 frames).
    for i in range(1, 20):
        updates = t.update([], ts=i * 0.125)
    assert all(u.track_key != "1:1:1" for u in updates)
    assert t.tracks_expired == 1
    assert t.tracks_created == 1


def test_multiple_simultaneous_vehicles_get_distinct_ids():
    t = ByteTracker(1, 1)
    updates = t.update([box(0.05), box(0.60)], ts=0.0)
    keys = {u.track_key for u in updates}
    assert keys == {"1:1:1", "1:1:2"}
    # Second frame keeps both identities.
    updates2 = t.update([box(0.06), box(0.61)], ts=0.125)
    assert {u.track_key for u in updates2} == keys
    assert t.tracks_created == 2


def test_camera_isolation_no_cross_contamination():
    a = ByteTracker(camera_id=1, session_epoch=1, cfg=CFG)
    b = ByteTracker(camera_id=2, session_epoch=1, cfg=CFG)
    ua = a.update([box(0.10)], ts=0.0)
    ub = b.update([box(0.10)], ts=0.0)          # identical scene, other camera
    assert ua[0].track_key != ub[0].track_key   # same local id, distinct key
    assert ua[0].track_key.startswith("1:")
    assert ub[0].track_key.startswith("2:")
    # A's state never influences B: empties in B create nothing new in A.
    b.update([], ts=0.125)
    assert a.tracks_created == 1
    assert b.tracks_created == 1


def test_low_score_box_recovers_track():
    """ByteTrack stage 2: low-conf box keeps identity (occlusion/blur)."""
    t = ByteTracker(1, 1)
    key = t.update([box(0.10, conf=0.85)], ts=0.0)[0].track_key
    lost = t.update([box(0.12, conf=0.20)], ts=0.125)  # below track_low → dropped
    assert lost[0].time_since_update == 1
    assert lost[0].state == "LOST"
    recovered = t.update([box(0.13, conf=0.40)], ts=0.250)  # low-score band
    assert recovered[0].track_key == key          # same id, not a new track
    assert recovered[0].state == "TRACKED"
    assert t.occlusion_recoveries == 1
    assert t.tracks_created == 1


def test_deterministic_ids_identical_inputs():
    def run():
        t = ByteTracker(4, 9)
        out = []
        for i in range(8):
            out.append([(u.track_key, u.state, u.hits)
                        for u in t.update([box(0.10 + i * 0.01),
                                           box(0.55 - i * 0.005),
                                           box(0.30, conf=0.45)], ts=i * 0.125)])
        return out
    assert run() == run()


def test_cap_enforced_max_live_tracks():
    cfg = PipelineConfig(max_live_tracks=3)
    t = ByteTracker(1, 1, cfg=cfg)
    boxes = [box(0.20 * i) for i in range(6)]   # non-overlapping: 6 separate ids
    t.update(boxes, ts=0.0)
    assert len(t._tracks) <= 3
    assert t.tracks_expired >= 3


@settings(max_examples=30, deadline=None)
@given(
    base=st.floats(min_value=0.0, max_value=0.6, allow_nan=False),
    steps=st.lists(st.floats(min_value=0.0, max_value=0.03, allow_nan=False),
                   min_size=1, max_size=12),
)
def test_property_straight_line_keeps_one_track(base, steps):
    """A single object moving in small steps → exactly one id."""
    t = ByteTracker(1, 1)
    for i in range(3):                        # seed beyond new_track_min_hits
        t.update([box(base)], ts=i * 0.125)
    x = base
    for step in steps:
        x = min(0.9, x + step)                # monotone, overlap-preserving
        t.update([box(x)], ts=0.0)
    keys = {u.track_key for u in t.update([box(min(0.9, x + 0.01))], ts=0.0)}
    assert keys == {"1:1:1"}
    assert t.tracks_created == 1


def test_reset_flushes_all_tracks():
    """reset() is the scene-change path (§2.6): no old tracks survive."""
    t = ByteTracker(1, 1)
    t.update([box(0.1)], ts=0.0)
    t.reset()
    updates = t.update([box(0.1)], ts=1.0)
    assert len(updates) == 1
    assert updates[0].state == "NEW"
    assert updates[0].hits == 1               # re-seeded, not carried over

