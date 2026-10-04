"""Phase 2C — canonical, deterministic crop extraction (benchmark-only).

Phase 2B proved the same detector box can yield different OCR text purely
from box->pixel coordinate conversion (round/floor/dy-1 gave
12d67413 / 12d674913 / 12da67413). Any A/B comparison that lets the two
detectors be cropped by different rules is therefore invalid.

This module defines ONE canonical extractor used by BOTH arms, and a
deterministic conversion for each documented convention so the convention
matrix can be measured instead of guessed.

Production reference (alpr_engine.py:363, read-only, never mutated):
    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)   # truncation
    plate_crop = frame[y1:y2, x1:x2]                          # no clipping
    if plate_crop.shape[0] == 0 or ... : continue            # reject empty
    ... if not plate_text: continue                           # drop empty OCR

Note production `astype(int)` truncates TOWARD ZERO, which differs from
floor() for negative coordinates; we reproduce it exactly so the
"production" convention is a faithful model of the live path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

# Conventions measured in the fidelity matrix (task §11).
CONVENTIONS = ("round", "floor", "ceil", "trunc", "floor_dy-1")

# Which convention reproduces production semantics. See select_canonical().
PRODUCTION_CONVENTION = "trunc"


def convert_coord(value: float, convention: str, axis: str = "y", delta: int = 0) -> int:
    """Deterministic float->int conversion for one coordinate.

    `trunc` is numpy.astype(int) semantics: truncation toward zero, matching
    alpr_engine.py:263/264. `floor_dy-1` applies floor then shifts only the y
    edges by -1 px (the Phase 2B artifact convention). delta applies to y only.
    """
    v = float(value)
    if convention == "round":
        # round-half-away-from-zero: documented, unlike Python's banker's rounding
        return math.floor(v + 0.5) if v >= 0 else math.ceil(v - 0.5)
    if convention == "floor":
        return math.floor(v)
    if convention == "ceil":
        return math.ceil(v)
    if convention == "trunc":
        return int(v)  # toward zero, matches numpy.astype(int)
    if convention == "floor_dy-1":
        base = math.floor(v)
        return base + delta if axis == "y" else base
    raise ValueError(f"unknown convention: {convention}")


@dataclass(frozen=True)
class CropResult:
    """Canonical crop plus the exact coordinates used to take it."""
    x1_float: float
    y1_float: float
    x2_float: float
    y2_float: float
    x1_pixel: int
    y1_pixel: int
    x2_pixel: int
    y2_pixel: int
    crop_width: int
    crop_height: int
    clipped_left: bool
    clipped_right: bool
    clipped_top: bool
    clipped_bottom: bool
    clipped_any: bool
    invalid: bool
    invalid_reason: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def convert_box(bbox, convention: str) -> tuple[int, int, int, int]:
    """(x1,y1,x2,y2) float -> integer pixel coords under one convention."""
    x1, y1, x2, y2 = (float(v) for v in bbox[:4])
    delta = -1 if convention == "floor_dy-1" else 0
    return (
        convert_coord(x1, convention, "x", delta),
        convert_coord(y1, convention, "y", delta),
        convert_coord(x2, convention, "x", delta),
        convert_coord(y2, convention, "y", delta),
    )


def extract_plate_crop(frame, bbox, *, convention: str = "round", clip: bool = True,
                       pad_x: int = 0, pad_y: int = 0):
    """Take the plate crop for one detector box.

    Returns (crop_or_None, CropResult). The CropResult records BOTH the float
    box and the exact integer pixels used, so a consumer never has to guess
    how the crop was taken.

    Ordering is fixed and documented: convert -> pad -> clip -> validate.
    Padding is applied in pixel space AFTER conversion so it is independent of
    the float coordinates.
    """
    fh, fw = frame.shape[:2]
    xf1, yf1, xf2, yf2 = (float(v) for v in bbox[:4])

    x1, y1, x2, y2 = convert_box(bbox, convention)
    x1 -= pad_x
    x2 += pad_x
    y1 -= pad_y
    y2 += pad_y

    clipped_left = x1 < 0
    clipped_top = y1 < 0
    clipped_right = x2 > fw
    clipped_bottom = y2 > fh

    if clip:
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(fw, x2)
        y2 = min(fh, y2)

    w = x2 - x1
    h = y2 - y1
    reason = None
    if w <= 0 or h <= 0:
        reason = "zero_width" if w <= 0 else "zero_height"
    res = CropResult(
        x1_float=xf1, y1_float=yf1, x2_float=xf2, y2_float=yf2,
        x1_pixel=x1, y1_pixel=y1, x2_pixel=x2, y2_pixel=y2,
        crop_width=max(0, w), crop_height=max(0, h),
        clipped_left=clipped_left, clipped_right=clipped_right,
        clipped_top=clipped_top, clipped_bottom=clipped_bottom,
        clipped_any=bool(clipped_left or clipped_right or clipped_top or clipped_bottom),
        invalid=reason is not None, invalid_reason=reason,
    )
    if res.invalid:
        return None, res
    return frame[y1:y2, x1:x2], res


def expand_box(bbox, factor: float):
    """Centre-preserving box expansion by `factor` (1.0 = no change).

    Used ONLY by the crop-expansion experiment. Identical for both arms.
    """
    if factor == 1.0:
        return list(bbox[:4])
    x1, y1, x2, y2 = (float(v) for v in bbox[:4])
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    w, h = (x2 - x1) * factor, (y2 - y1) * factor
    return [cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0]


# Buckets (task §23) — boundary values land in the higher bucket.
WIDTH_BUCKETS = ((0, 80, "lt80"), (80, 100, "80-99"), (100, 150, "100-149"),
                 (150, 200, "150-199"), (200, 10 ** 9, "ge200"))


def bucket_for(width: int) -> str:
    for lo, hi, name in WIDTH_BUCKETS:
        if lo <= width < hi:
            return name
    return "unknown"


def select_canonical(convention_scores: dict) -> tuple[str, list[str]]:
    """Pick the canonical convention using ONLY non-accuracy criteria.

    `convention_scores` maps convention -> dict with the non-accuracy fields we
    are allowed to use for selection:
        `production_equivalent` (bool) — reproduces alpr_engine semantics
        `degenerate_count` (int)     — zero/negative-size crops
        `shrinks_box_count` (int)     — pixels lost vs the float box

    Ground-truth accuracy is deliberately NOT an input, so selection cannot
    leak labels into the protocol (task §31).
    """
    reasons = []
    prod = [c for c, s in convention_scores.items() if s.get("production_equivalent")]
    if prod:
        canonical = sorted(prod)[0]
        reasons.append(f"production-equivalent: {canonical} matches alpr_engine.astype(int)")
    else:
        canonical = min(convention_scores,
                        key=lambda c: (convention_scores[c]["degenerate_count"],
                                       convention_scores[c]["shrinks_box_count"]))
        reasons.append("no convention matches production; chose fewest degenerate crops")

    for c, s in sorted(convention_scores.items()):
        if s["degenerate_count"]:
            reasons.append(f"{c}: {s['degenerate_count']} degenerate crops")
    return canonical, reasons