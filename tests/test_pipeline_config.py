"""Phase 0: pipeline config validation (design Appendix C, D.1 row 1)."""
from __future__ import annotations

import pytest

from pipeline.config import DEFAULT_CONFIG, PipelineConfig


def test_defaults_match_design_appendix_c():
    cfg = PipelineConfig()
    assert cfg.pipeline_mode == "legacy"          # NEW pipeline disabled by default
    assert cfg.dual_write_detections is True
    assert cfg.track_high_thresh == 0.6
    assert cfg.track_low_thresh == 0.3
    assert cfg.new_track_thresh == 0.5
    assert cfg.new_track_min_hits == 2
    assert cfg.track_expiry_s == 2.0
    assert cfg.track_min_lifetime_s == 0.4
    assert cfg.max_live_tracks == 32
    assert cfg.plate_gate_conf == 0.5
    assert cfg.confirm_min_obs == 3
    assert cfg.confirm_min_agreement == 0.6
    assert cfg.confirm_min_length_weight == 0.6
    assert cfg.force_emit_posterior == 0.5
    assert cfg.imgsz_vehicle == 416
    assert cfg.imgsz_plate_roi == 512
    assert cfg.imgsz_plate_full == 640
    assert cfg.imgsz_char == 256
    assert cfg.max_concurrent_inference == 2
    assert cfg.reentry_cooldown_s == 15.0
    assert cfg.fragment_window_s == 3.0
    assert cfg.max_track_obs == 30
    assert cfg.max_persisted_obs == 20


def test_default_config_is_valid():
    assert DEFAULT_CONFIG.pipeline_mode in ("legacy", "events")


@pytest.mark.parametrize("kwargs", [
    {"conf_vehicle": 1.5},
    {"conf_plate": -0.1},
    {"imgsz_vehicle": 400},          # not a multiple of 32
    {"imgsz_char": 100},
    {"plate_scan_period": 0},
    {"new_track_min_hits": 0},
    {"max_live_tracks": -1},
    {"track_expiry_s": 0.0},
    {"track_expiry_s": 0.2, "track_min_lifetime_s": 0.4},  # expiry <= lifetime
    {"track_low_thresh": 0.9, "track_high_thresh": 0.6},   # low > high
    {"pipeline_mode": "banana"},
    {"effective_fps": 0.0},
    {"history_limit": 0},
])
def test_invalid_knobs_rejected(kwargs):
    with pytest.raises(ValueError):
        PipelineConfig(**kwargs)


def test_unknown_key_rejected():
    with pytest.raises(ValueError, match="unknown PipelineConfig keys"):
        PipelineConfig.from_dict({"no_such_knob": 1})
    # Direct kwargs: dataclass itself rejects unknown fields (TypeError).
    with pytest.raises(TypeError):
        PipelineConfig(magic=5)


def test_from_dict_roundtrip():
    cfg = PipelineConfig.from_dict({"track_expiry_s": 3.0})
    assert cfg.track_expiry_s == 3.0
    assert cfg.pipeline_mode == "legacy"
