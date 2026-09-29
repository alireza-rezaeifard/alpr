"""Phase 0: event-key identity and application-level idempotency (§2.5 rule 2,
§3.2 event_key; design D.1 — event-key/idempotency exit gate)."""
from __future__ import annotations

import pytest

from pipeline.event_builder import (EventIdempotencyRegistry, STATUS_CONFIRMED,
                                    build_event, local_track_id_from_key,
                                    make_event_key)
from pipeline.types import ConsensusResult, PlateRead


def test_event_key_deterministic_and_camera_scoped():
    k1 = make_event_key(camera_id=3, session_epoch=25092901, local_track_id=17)
    k2 = make_event_key(camera_id=3, session_epoch=25092901, local_track_id=17)
    assert k1 == k2 == "3:25092901:17"             # §3.2 format, exactly
    other_cam = make_event_key(4, 25092901, 17)
    other_epoch = make_event_key(3, 25092902, 17)
    assert k1 != other_cam != other_epoch
    assert local_track_id_from_key(k1) == 17


def test_same_visit_recomputed_yields_same_key():
    """Recomputing identity after restart-in-session must not duplicate."""
    first = make_event_key(3, 25092901, 17)
    registry = EventIdempotencyRegistry()
    assert registry.register_emission(first) is True
    # Simulated restart: pipeline rebuilds the same key from same inputs.
    second = make_event_key(3, 25092901, 17)
    assert registry.register_emission(second) is False   # suppressed, not new row
    assert registry.emission_count(first) == 2
    assert registry.snapshot()["keys_emitted"] == 1


def test_idempotency_is_application_level_not_db_only():
    """Registry refuses repeats without any database involvement."""
    reg = EventIdempotencyRegistry()
    key = make_event_key(1, 1, 1)
    results = [reg.register_emission(key) for _ in range(5)]
    assert results == [True, False, False, False, False]
    assert reg.is_emitted(key)
    reg.reset()
    assert reg.register_emission(key) is True


def test_upgrade_slots_respect_max_upgrades():
    reg = EventIdempotencyRegistry()
    key = make_event_key(1, 1, 2)
    assert reg.register_upgrade(key, max_upgrades=1) is True
    assert reg.register_upgrade(key, max_upgrades=1) is False
    assert reg.register_upgrade(key, max_upgrades=2) is True   # slot 2 free
    assert reg.snapshot()["total_upgrades"] == 2


def test_two_sessions_two_events_same_track_id():
    """session_epoch differentiates restarts (§2.3) → distinct identities."""
    a = make_event_key(1, 100, 1)
    b = make_event_key(1, 101, 1)
    reg = EventIdempotencyRegistry()
    assert reg.register_emission(a) is True
    assert reg.register_emission(b) is True          # genuinely new visit epoch


def test_build_event_maps_consensus_fields():
    best = PlateRead(frame_idx=7, ts="t7", text="12b34567", char_count=8,
                     plate_det_conf=0.9, plate_area_px=4800, aspect_ratio=4.6,
                     sharpness=200.0, brightness_ok=True, usable=True,
                     weight=0.77)
    result = ConsensusResult(
        track_key="3:1:17", plate="12b34567", char_conf=(0.99, 0.98, 0.97),
        agreement_ratio=0.8, confidence=0.9, posterior_min=0.7,
        length_mode_weight=1.0, best=best, alternates=("12b34587",))
    event = build_event(
        make_event_key(3, 1, 17), result, track_kind="vehicle",
        first_seen="2026-09-29T00:00:00Z",
        last_seen="2026-09-29T00:00:02Z",
        frame_count=19, observation_count=11, duration_ms=2190,
        plate_valid=True, status=STATUS_CONFIRMED)
    assert event.event_key == "3:1:17"
    assert event.track_id == event.event_key
    assert event.plate_number == "12b34567"
    assert event.confidence == 0.9
    assert event.agreement_ratio == 0.8
    assert event.quality_score == 0.77
    assert event.char_confidences == [0.99, 0.98, 0.97]
    assert event.alternates == ["12b34587"]
    assert event.status == "confirmed"
    assert event.needs_review is False
    assert event.plate_valid is True
    assert event.duration_ms == 2190


def test_malformed_event_key_rejected():
    with pytest.raises(ValueError):
        local_track_id_from_key("no-colon")
