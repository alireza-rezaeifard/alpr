"""Domain types for the event-based pipeline (design Appendix A).

Pure data structures: no torch, no cv2, no DB, no network, no Flutter.
Decoupled from ``db.py`` rows and from ``flutter_app`` models on purpose —
mapping to either side is a Phase 1+ sink concern.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Box:
    """Bounding box in normalized 0..1 coordinates (§2.5)."""

    x1: float
    y1: float
    x2: float
    y2: float
    conf: float
    cls: int

    def area(self) -> float:
        """Normalized area, clamped at zero for degenerate boxes."""
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)


def box_iou(a: Box, b: Box) -> float:
    """Intersection-over-union in [0, 1]; 0.0 for non-overlapping boxes."""
    inter_x1 = max(a.x1, b.x1)
    inter_y1 = max(a.y1, b.y1)
    inter_x2 = min(a.x2, b.x2)
    inter_y2 = min(a.y2, b.y2)
    inter = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
    union = a.area() + b.area() - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def containment_iou(inner: Box, outer: Box) -> float:
    """Fraction of *inner* covered by *outer* (plate-in-vehicle merge, §2.3)."""
    inner_area = inner.area()
    if inner_area <= 0.0:
        return 0.0
    inter_x1 = max(inner.x1, outer.x1)
    inter_y1 = max(inner.y1, outer.y1)
    inter_x2 = min(inner.x2, outer.x2)
    inter_y2 = min(inner.y2, outer.y2)
    inter = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
    return inter / inner_area


@dataclass
class Track:
    """Mutable per-vehicle track state owned by TrackManager (§2.4/§2.5)."""

    track_key: str
    kind: str                      # "vehicle" | "plate"
    state: str                     # NEW | TRACKING | PLATE_CAPTURED | CONFIRMED |
                                   # COMPLETED | EXPIRED
    hits: int = 0
    age: int = 0
    time_since_update: int = 0
    box: Box | None = None
    first_ts: float | None = None
    last_ts: float | None = None
    event_emitted: bool = False
    merged_into: str | None = None
    observations: list = field(default_factory=list)  # PlateObservation list


@dataclass(frozen=True)
class TrackUpdate:
    """One tracker association result (§1.2, Appendix A)."""

    track_key: str
    kind: str
    box: Box
    state: str                     # NEW | TRACKED | LOST
    hits: int
    age: int
    time_since_update: int


@dataclass
class PlateRead:
    """One usable OCR pass over a plate crop (§4.1). Immutable by builders."""

    frame_idx: int
    ts: str
    text: str
    char_candidates: list = field(default_factory=list)  # per position, top-K
    char_count: int = 0
    plate_det_conf: float = 0.0
    plate_area_px: int = 0
    aspect_ratio: float = 0.0
    sharpness: float = 0.0
    brightness_ok: bool = False
    usable: bool = False
    weight: float = 0.0
    bbox: Box | None = None
    vehicle_bbox: Box | None = None

    def mean_char_conf(self) -> float:
        """Mean rank-0 candidate confidence across positions."""
        if not self.char_candidates:
            return 0.0
        total = 0.0
        count = 0
        for position in self.char_candidates:
            if position:
                total += float(position[0][1])
                count += 1
        return total / count if count else 0.0


@dataclass
class PlateObservation:
    """Persistable per-frame evidence (§3.3, Appendix B plate_observations)."""

    event_key: str
    track_id: str
    frame_idx: int
    ts: str
    plate_text: str
    plate_det_conf: float = 0.0
    char_conf: float = 0.0
    char_count: int = 0
    quality: float = 0.0
    sharpness: float = 0.0
    plate_area_px: int = 0
    aspect_ratio: float = 0.0
    bbox: Box | None = None
    vehicle_bbox: Box | None = None
    agreed_with_consensus: bool | None = None
    event_id: int | None = None
    camera_id: int | None = None


@dataclass(frozen=True)
class ConsensusCandidate:
    """One candidate plate with its accumulated vote weight (§4.5)."""

    text: str
    weight: float


@dataclass(frozen=True)
class ConsensusResult:
    """Output of the consensus engine (§4.5, Appendix A)."""

    track_key: str
    plate: str
    char_conf: tuple = ()
    agreement_ratio: float = 0.0
    confidence: float = 0.0
    posterior_min: float = 0.0
    length_mode_weight: float = 0.0
    best: PlateRead | None = None
    alternates: tuple = ()


@dataclass(frozen=True)
class ScheduleDecision:
    """Frame scheduler output (§1.2, Appendix A)."""

    sample: bool
    tier: str                      # "full" | "track_only" | "skip"
    reason: str


@dataclass(frozen=True)
class EmissionRequest:
    """Lifecycle → EventBuilder handoff (§2.4 side effects)."""

    track_key: str
    action: str                    # "emit" | "upgrade" | "close" | "suppress"
    status: str = ""               # "confirmed" | "unconfirmed" | ""
    needs_review: bool = False
    reason: str = ""


@dataclass
class VehicleEvent:
    """One row of the future vehicle_events table (§3.2, Appendix A)."""

    event_key: str
    track_id: str
    track_kind: str
    first_seen: str
    last_seen: str
    plate_number: str
    plate_norm: str
    confidence: float = 0.0
    agreement_ratio: float = 0.0
    quality_score: float = 0.0
    frame_count: int = 0
    observation_count: int = 0
    duration_ms: int = 0
    status: str = "confirmed"
    needs_review: bool = False
    id_switch_suspect: bool = False
    plate_persian: str | None = None
    char_confidences: list = field(default_factory=list)
    alternates: list = field(default_factory=list)
    plate_valid: bool = False
    plate_category: str | None = None
    plate_color_scheme: str | None = None
    region_code: str | None = None
    region_name: str | None = None
    city: str | None = None
    vehicle_type: str | None = None
    vehicle_make: str | None = None
    vehicle_color: str | None = None
    attribute_confidence: float | None = None
    attribute_computed_at: str | None = None
    best_frame_path: str | None = None
    best_frame_plate_path: str | None = None
    best_frame_frame_idx: int | None = None
    fragment_of_event_id: int | None = None
    alert_count: int = 0
    camera_id: int | None = None
    camera_name: str | None = None
    session_id: int | None = None
    source_type: str = "rtsp"
    source_file: str | None = None
