"""Pipeline configuration knobs (ALPR_ARCHITECTURE_DESIGN.md Appendix C).

Single dataclass, validated at construction. Every default carries the
design section that justifies it. Unknown keys are rejected (fail fast,
no silent drift).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PipelineConfig:
    """All thresholds for the event-based pipeline."""

    # Migration / safety (§3.5)
    pipeline_mode: str = "legacy"          # "legacy" | "events"
    dual_write_detections: bool = True     # keep legacy detections rows until M5

    # Frame scheduling (§5.1)
    frame_queue_depth: int = 2
    inference_budget_ms: float = 120.0
    max_gap_tracked_ms: float = 250.0

    # Inference tiering and resolution (§5.2, §5.3)
    max_inferences_per_frame: int = 4
    imgsz_vehicle: int = 416
    imgsz_plate_roi: int = 512
    imgsz_plate_full: int = 640
    imgsz_char: int = 256
    conf_vehicle: float = 0.6
    conf_plate: float = 0.6
    conf_char: float = 0.3
    classes_vehicle: tuple = (2, 3, 5, 7)
    roi_pad: float = 0.12
    plate_scan_period: int = 3
    confirmed_scan_period: int = 15
    confirmed_ocr_stride: int = 5

    # Tracker (§2.4, §2.5, Appendix C)
    track_high_thresh: float = 0.6
    track_low_thresh: float = 0.3
    new_track_thresh: float = 0.5
    new_track_min_hits: int = 2
    track_expiry_s: float = 2.0
    track_min_lifetime_s: float = 0.4
    max_live_tracks: int = 32
    track_buffer: int = 30
    effective_fps: float = 8.0
    match_thresh: float = 0.3
    merge_containment_iou: float = 0.6
    plate_track_min_lifetime_s: float = 0.6
    plate_track_min_obs: int = 3

    # Consensus (§4.3-4.6)
    plate_gate_conf: float = 0.5
    min_plate_width_px: int = 48
    brightness_lo: float = 40.0
    brightness_hi: float = 220.0
    min_sharpness: float = 0.0
    sharp_ref: float = 300.0
    area_ref: int = 120 * 40
    expect_aspect: float = 4.6
    min_vote_conf: float = 0.2
    min_obs_weight: float = 0.02
    confirm_min_obs: int = 3
    confirm_min_agreement: float = 0.6
    confirm_min_length_weight: float = 0.6
    force_emit_posterior: float = 0.5
    max_upgrades: int = 1
    upgrade_quality_gain: float = 1.15
    review_on_weak_char: bool = True
    weak_char_posterior: float = 0.7
    enable_early_best: bool = False   # §4.6 EARLY_BEST disabled until Part 6 proves it


    # Evidence store (§5.8, §3.3)
    max_track_obs: int = 30
    max_persisted_obs: int = 20

    # Duplicate prevention (§2.5)
    reentry_cooldown_s: float = 15.0
    fragment_window_s: float = 3.0
    switch_window_s: float = 5.0

    # Attributes (§5.5)
    enable_attributes: bool = True

    # Display / history (§5.9, §5.8)
    display_fps_floor: float = 12.0
    display_max_width: int = 720
    display_quality: int = 60
    display_hd: bool = False
    history_limit: int = 50

    # Retention horizons, proposed (§3.5 M6)
    observation_retention_days: int = 30
    event_image_retention_days: int = 90

    # Back-pressure (§5.7) and scene handling (§2.6)
    max_concurrent_inference: int = 2
    max_video_tasks: int = 1
    semaphore_timeout_s: float = 3.0
    semaphore_stall_frames: int = 50
    scene_reset_tracks: int = 5

    def __post_init__(self) -> None:
        errors: list[str] = []
        for name in ("conf_vehicle", "conf_plate", "conf_char",
                     "track_high_thresh", "track_low_thresh", "new_track_thresh",
                     "confirm_min_agreement", "confirm_min_length_weight",
                     "force_emit_posterior", "match_thresh"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                errors.append(f"{name} must be in [0,1], got {value!r}")
        for name in ("imgsz_vehicle", "imgsz_plate_roi",
                     "imgsz_plate_full", "imgsz_char"):
            if getattr(self, name) % 32 != 0:
                errors.append(f"{name} must be a multiple of 32")
        for name in ("plate_scan_period", "confirmed_scan_period",
                     "confirmed_ocr_stride", "new_track_min_hits",
                     "max_live_tracks", "track_buffer", "max_track_obs",
                     "max_persisted_obs", "max_inferences_per_frame",
                     "max_concurrent_inference", "max_video_tasks",
                     "frame_queue_depth", "history_limit", "confirm_min_obs",
                     "max_upgrades", "semaphore_stall_frames",
                     "scene_reset_tracks", "plate_track_min_obs"):
            if getattr(self, name) < 1:
                errors.append(f"{name} must be >= 1")
        for name in ("track_expiry_s", "track_min_lifetime_s",
                     "plate_track_min_lifetime_s", "inference_budget_ms",
                     "max_gap_tracked_ms", "reentry_cooldown_s",
                     "fragment_window_s", "switch_window_s",
                     "semaphore_timeout_s", "effective_fps",
                     "display_fps_floor"):
            if getattr(self, name) <= 0:
                errors.append(f"{name} must be > 0")
        if self.track_expiry_s <= self.track_min_lifetime_s:
            errors.append("track_expiry_s must exceed track_min_lifetime_s")
        if self.track_low_thresh > self.track_high_thresh:
            errors.append("track_low_thresh must not exceed track_high_thresh")
        if self.pipeline_mode not in ("legacy", "events"):
            errors.append(
                f"pipeline_mode must be legacy|events, got {self.pipeline_mode!r}"
            )
        if errors:
            raise ValueError("invalid PipelineConfig: " + "; ".join(errors))

    @classmethod
    def from_dict(cls, values: dict) -> "PipelineConfig":
        """Build from a dict, rejecting unknown keys (fail fast)."""
        names = {f.name for f in cls.__dataclass_fields__.values()}
        unknown = sorted(set(values) - names)
        if unknown:
            raise ValueError(f"unknown PipelineConfig keys: {unknown}")
        return cls(**values)


DEFAULT_CONFIG = PipelineConfig()
