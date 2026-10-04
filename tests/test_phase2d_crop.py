"""Tests for the Phase 2D pure crop-extraction helper.

Pure unit tests: no model loading, no video decoding, no network. Proves the
determinism contract required by Phase 2D Step 3:

  * same input -> identical integer bbox
  * same bbox -> identical crop bytes
  * no hidden randomness
  * no platform-dependent behavior
  * clipping is deterministic
  * degenerate boxes are rejected safely
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmarks.phase2d_crop import (  # noqa: E402
    CONVENTIONS, EXPANSIONS, PRODUCTION_CONVENTION, extract_crop,
    integer_bbox,
)
from benchmarks.phase2c_canonical import convert_coord  # noqa: E402


def _frame(w=200, h=100, seed=0):
    """Deterministic non-uniform frame so byte-identity is meaningful."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


_BBOX = (100.25, 50.75, 180.5, 90.25)


# ------------------------------------------------------------- determinism
def test_same_input_gives_identical_integer_bbox():
    frame = _frame()
    a = extract_crop(frame, _BBOX, "trunc", 1.0)
    b = extract_crop(frame, _BBOX, "trunc", 1.0)
    assert a["integer_bbox"] == b["integer_bbox"]
    assert a["raw_integer_bbox"] == b["raw_integer_bbox"]


def test_same_bbox_gives_identical_crop_bytes():
    frame = _frame()
    a = extract_crop(frame, _BBOX, "trunc", 1.0)["crop"]
    b = extract_crop(frame, _BBOX, "trunc", 1.0)["crop"]
    assert a is not None and b is not None
    assert a.shape == b.shape
    assert a.tobytes() == b.tobytes()


def test_no_hidden_randomness_across_repeats():
    frame = _frame()
    seen = set()
    for _ in range(50):
        r = extract_crop(frame, _BBOX, "round", 1.02)
        seen.add((r["integer_bbox"], r["crop"].tobytes(),
                  r["effective_width"], r["effective_height"]))
    assert len(seen) == 1


def test_pure_function_no_global_state_mutation():
    """Calling the helper must not mutate its inputs."""
    frame = _frame()
    before = frame.tobytes()
    bbox = list(_BBOX)
    extract_crop(frame, bbox, "ceil", 1.05)
    assert frame.tobytes() == before
    assert bbox == list(_BBOX)


# ------------------------------------------------------- platform behavior
def test_trunc_is_toward_zero_matching_numpy_astype():
    rng = np.random.default_rng(20261004)
    for _ in range(2000):
        v = float(rng.uniform(-500, 2000))
        assert convert_coord(v, "trunc") == int(np.asarray([v]).astype(int)[0])


def test_round_is_half_away_from_zero():
    # Documented rule, explicitly not Python banker's rounding.
    assert convert_coord(10.5, "round") == 11
    assert convert_coord(11.5, "round") == 12
    assert convert_coord(-10.5, "round") == -11


def test_convention_differences_only_in_rounding_direction():
    # On a fractional box the four conventions differ by at most 1 px/edge.
    base = integer_bbox(_BBOX, "trunc")
    for conv in ("floor", "round", "ceil"):
        other = integer_bbox(_BBOX, conv)
        assert all(abs(a - b) <= 1 for a, b in zip(base, other))


def test_integer_valued_box_is_convention_invariant():
    box = (100.0, 50.0, 180.0, 90.0)
    assert len({integer_bbox(box, c) for c in CONVENTIONS}) == 1


# ------------------------------------------------------------- expansion
def test_expansion_one_is_identity():
    frame = _frame()
    a = extract_crop(frame, _BBOX, "trunc", 1.0)
    b = extract_crop(frame, _BBOX, "trunc", 1.00)
    assert a["integer_bbox"] == b["integer_bbox"]
    assert a["float_bbox"] == b["float_bbox"]


def test_expansion_is_centre_preserving():
    x1, y1, x2, y2 = _BBOX
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    for e in EXPANSIONS:
        ex1, ey1, ex2, ey2 = extract_crop(_frame(), _BBOX, "trunc", e)["float_bbox"]
        assert abs((ex1 + ex2) / 2 - cx) < 1e-9
        assert abs((ey1 + ey2) / 2 - cy) < 1e-9
        # area scales by factor^2
        w0, h0 = x2 - x1, y2 - y1
        assert abs((ex2 - ex1) * (ey2 - ey1) - w0 * h0 * e * e) < 1e-6


# ---------------------------------------------------------------- clipping
def _scalar_signature(r):
    """Deterministic scalar fields of a crop result (crop pixels compared
    separately via tobytes)."""
    return (r["integer_bbox"], r["raw_integer_bbox"], r["effective_width"],
            r["effective_height"], tuple(sorted(r["clipping_status"].items())),
            r["invalid"], r["invalid_reason"], r["convention"], r["expansion"])


def test_clipping_is_deterministic_and_bounded():
    frame = _frame(w=200, h=100)
    box = (-30.5, -20.25, 260.75, 150.5)  # out of bounds on all edges
    results = [extract_crop(frame, box, "trunc", 1.0) for _ in range(10)]
    assert len({_scalar_signature(r) for r in results}) == 1
    assert results[0]["crop"].tobytes() == results[1]["crop"].tobytes()
    r = results[0]
    assert r["clipping_status"] == {"left": True, "right": True,
                                    "top": True, "bottom": True, "any": True}
    x1, y1, x2, y2 = r["integer_bbox"]
    assert 0 <= x1 < x2 <= 200
    assert 0 <= y1 < y2 <= 100


def test_clipping_never_enlarges_beyond_frame():
    frame = _frame(w=200, h=100)
    for e in EXPANSIONS:
        r = extract_crop(frame, _BBOX, "trunc", e)
        x1, y1, x2, y2 = r["integer_bbox"]
        assert x1 >= 0 and y1 >= 0 and x2 <= 200 and y2 <= 100


# ------------------------------------------------------- degenerate boxes
@pytest.mark.parametrize("box", [
    (100.0, 50.0, 100.0, 90.0),    # zero width
    (100.0, 50.0, 99.0, 90.0),     # negative width
    (100.0, 50.0, 180.0, 50.0),    # zero height
    (100.0, 60.0, 180.0, 50.0),    # negative height
    (100.0, 50.0, 100.0, 50.0),    # point
])
def test_degenerate_boxes_rejected_safely(box):
    r = extract_crop(_frame(), box, "trunc", 1.0)
    assert r["invalid"] is True
    assert r["crop"] is None
    assert r["invalid_reason"] in ("zero_width", "zero_height")
    assert r["effective_width"] == 0 or r["effective_height"] == 0


def test_expansion_cannot_resurrect_degenerate_box():
    # A degenerate box expanded about its centre stays degenerate.
    box = (100.0, 50.0, 100.0, 90.0)
    r = extract_crop(_frame(), box, "trunc", 1.10)
    assert r["invalid"] is True and r["crop"] is None


# ------------------------------------------------------------ validation
@pytest.mark.parametrize("conv", ["nearest", "floor_dy-1", "", "TRUNC", None])
def test_unknown_convention_rejected(conv):
    with pytest.raises(ValueError):
        extract_crop(_frame(), _BBOX, conv, 1.0)


@pytest.mark.parametrize("expansion", [0.0, 0.99, -1.0, float("inf"),
                                       float("nan"), "1.05"])
def test_invalid_expansion_rejected(expansion):
    with pytest.raises(ValueError):
        extract_crop(_frame(), _BBOX, "trunc", expansion)


@pytest.mark.parametrize("bbox", [None, (1, 2, 3), (1, 2, 3, float("nan")),
                                  (1, 2, 3, float("inf"))])
def test_invalid_bbox_rejected(bbox):
    with pytest.raises(ValueError):
        extract_crop(_frame(), bbox, "trunc", 1.0)


def test_supported_conventions_and_expansions_frozen():
    assert CONVENTIONS == ("trunc", "floor", "round", "ceil")
    assert PRODUCTION_CONVENTION == "trunc"
    assert EXPANSIONS == (1.00, 1.01, 1.02, 1.03, 1.05, 1.07, 1.10)


def test_crop_slices_match_numpy_semantics():
    """The extracted crop must equal the raw numpy slice of the integer box."""
    frame = _frame()
    r = extract_crop(frame, _BBOX, "trunc", 1.0)
    x1, y1, x2, y2 = r["integer_bbox"]
    assert r["crop"].tobytes() == frame[y1:y2, x1:x2].tobytes()


def test_effective_geometry_matches_integer_bbox():
    frame = _frame()
    for conv in CONVENTIONS:
        for e in (1.0, 1.05):
            r = extract_crop(frame, _BBOX, conv, e)
            x1, y1, x2, y2 = r["integer_bbox"]
            assert r["effective_width"] == x2 - x1
            assert r["effective_height"] == y2 - y1
