"""Phase 2D — pure, deterministic crop-extraction helper (benchmark-only).

This module is a THIN, PURE wrapper over the frozen Phase 2C canonical
extractor (benchmarks/phase2c_canonical.py). It exists so the Phase 2D
experiments (quantization sweep, expansion sweep, post-fix matrix) all call
ONE documented function with the signature required by the task:

    extract_crop(frame, bbox, convention, expansion)
      -> {crop, integer_bbox, effective_width, effective_height,
          clipping_status, ...}

It NEVER imports or mutates production code (alpr_engine.py is only read,
never imported here). Determinism is a hard requirement:

  * same (frame, bbox, convention, expansion) -> identical integer bbox
  * same bbox -> byte-identical crop pixels
  * no randomness, no clock, no platform-dependent rounding
  * degenerate boxes (x2 <= x1 or y2 <= y1 after conversion) are rejected
    safely as invalid, never cropped

Conventions:
  trunc  — frozen production convention (alpr_engine.py:363 astype(int))
  floor  — mathematical floor
  round  — half-away-from-zero (documented; NOT Python banker's rounding)
  ceil   — mathematical ceiling

Expansion (1.00 = none) is centre-preserving and applied in FLOAT space
before integer conversion, identical for both detectors (phase2c_canonical.
expand_box).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from benchmarks.phase2c_canonical import (
    CONVENTIONS as _PHASE2C_CONVENTIONS,
    convert_box,
    expand_box,
)

# Conventions supported by the Phase 2D helper (a subset of the Phase 2C
# matrix: floor_dy-1 is a Phase 2B artifact convention and is not part of
# the Phase 2D experiment set).
CONVENTIONS = ("trunc", "floor", "round", "ceil")

# Expansion factors evaluated in Phase 2D (task Step 5).
EXPANSIONS = (1.00, 1.01, 1.02, 1.03, 1.05, 1.07, 1.10)

PRODUCTION_CONVENTION = "trunc"


def _validate_convention(convention: str) -> str:
    if convention not in CONVENTIONS:
        raise ValueError(
            f"unknown convention {convention!r}; "
            f"supported: {', '.join(CONVENTIONS)}")
    return convention


def _validate_expansion(expansion: float) -> float:
    if isinstance(expansion, bool) or not isinstance(expansion, (int, float)):
        raise ValueError(
            f"expansion must be a number >= 1.0, got {expansion!r}")
    e = float(expansion)
    if not (math.isfinite(e) and e >= 1.0):
        raise ValueError(
            f"expansion must be a finite float >= 1.0, got {expansion!r}")
    return e


def _validate_bbox(bbox) -> tuple[float, float, float, float]:
    if bbox is None or len(bbox) < 4:
        raise ValueError(f"bbox must have >= 4 values, got {bbox!r}")
    vals = tuple(float(v) for v in bbox[:4])
    if not all(math.isfinite(v) for v in vals):
        raise ValueError(f"bbox contains non-finite values: {bbox!r}")
    return vals


def integer_bbox(bbox, convention: str = PRODUCTION_CONVENTION,
                 expansion: float = 1.0) -> tuple[int, int, int, int]:
    """Deterministic float-box -> integer-pixel conversion.

    Order (frozen): expand (float space) -> convert (convention) ->
    (caller clips at slice time). This matches production exactly when
    expansion == 1.0 and convention == 'trunc'.
    """
    _validate_convention(convention)
    _validate_expansion(expansion)
    x1, y1, x2, y2 = _validate_bbox(bbox)
    if expansion != 1.0:
        x1, y1, x2, y2 = expand_box((x1, y1, x2, y2), expansion)
    return convert_box((x1, y1, x2, y2), convention)


def extract_crop(frame: np.ndarray, bbox, convention: str = PRODUCTION_CONVENTION,
                 expansion: float = 1.0, clip: bool = True) -> dict[str, Any]:
    """Extract a plate crop under one deterministic convention/expansion.

    Returns a dict:
        crop            — np.ndarray (H×W×3 BGR) or None when invalid
        integer_bbox    — (x1, y1, x2, y2) int pixels USED after clipping
        raw_integer_bbox— (x1, y1, x2, y2) int pixels before clipping
        effective_width — x2_i - x1_i after clipping (0 when invalid)
        effective_height— y2_i - y1_i after clipping (0 when invalid)
        clipping_status — dict(left/right/top/bottom/any booleans, computed
                            BEFORE clipping so the caller always sees the
                            true pre-clip geometry)
        invalid         — bool (degenerate box rejected safely)
        invalid_reason  — None | "zero_width" | "zero_height"
        convention      — echo of the requested convention
        expansion       — echo of the requested expansion
        float_bbox      — the (expanded) float box actually converted

    Determinism: pure function of (frame bytes, bbox, convention, expansion,
    clip). No RNG, no clock, no global state.
    """
    _validate_convention(convention)
    _validate_expansion(expansion)
    x1f, y1f, x2f, y2f = _validate_bbox(bbox)
    if expansion != 1.0:
        x1f, y1f, x2f, y2f = expand_box((x1f, y1f, x2f, y2f), expansion)

    fh, fw = frame.shape[:2]
    rx1, ry1, rx2, ry2 = convert_box((x1f, y1f, x2f, y2f), convention)

    clipped_left = rx1 < 0
    clipped_top = ry1 < 0
    clipped_right = rx2 > fw
    clipped_bottom = ry2 > fh

    x1, y1, x2, y2 = rx1, ry1, rx2, ry2
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

    status = {
        "left": bool(clipped_left),
        "right": bool(clipped_right),
        "top": bool(clipped_top),
        "bottom": bool(clipped_bottom),
        "any": bool(clipped_left or clipped_right or clipped_top
                    or clipped_bottom),
    }
    out = {
        "crop": None if reason else frame[y1:y2, x1:x2],
        "integer_bbox": (x1, y1, x2, y2),
        "raw_integer_bbox": (rx1, ry1, rx2, ry2),
        "effective_width": max(0, w),
        "effective_height": max(0, h),
        "clipping_status": status,
        "invalid": reason is not None,
        "invalid_reason": reason,
        "convention": convention,
        "expansion": float(expansion),
        "float_bbox": (x1f, y1f, x2f, y2f),
    }
    return out


# Backwards-compatible alias for callers that prefer the Phase 2C name shape.
extract_plate_crop_2d = extract_crop
