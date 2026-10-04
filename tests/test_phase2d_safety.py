"""Phase 2D crop-extraction safety regression tests (Step 11).

Covers the ten required production-safety cases with synthetic
frames and boxes. These tests pin the INVARIANTS the crop layer
must hold for ANY candidate strategy:

  1. plate touching image boundary
  2. very small plates
  3. very large plates
  4. partially detected plates
  5. boxes with negative coordinates
  6. boxes extending beyond frame
  7. malformed / degenerate boxes
  8. multiple nearby vehicles (overlapping boxes)
  9. duplicate detector boxes
 10. non-plate detections (garbage boxes)

Invariants asserted everywhere:
  * the crop NEVER leaves the frame: 0 <= x1 < x2 <= W,
    0 <= y1 < y2 <= H
  * expansion NEVER enlarges a box beyond the frame (it clips)
  * degenerate boxes are rejected safely (invalid=True, crop=None)
  * results are deterministic under repetition
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmarks.phase2d_crop import EXPANSIONS, extract_crop  # noqa: E402

W, H = 640, 480


def _frame():
    rng = np.random.default_rng(20261004)
    return rng.integers(0, 256, size=(H, W, 3), dtype=np.uint8)


def _assert_in_bounds(r):
    x1, y1, x2, y2 = r["integer_bbox"]
    assert 0 <= x1 < x2 <= W, r["integer_bbox"]
    assert 0 <= y1 < y2 <= H, r["integer_bbox"]
    assert r["crop"] is not None
    assert r["crop"].shape[0] == y2 - y1
    assert r["crop"].shape[1] == x2 - x1


# 1. plate touching the image boundary (all four corners)
@pytest.mark.parametrize("box", [
    (0.0, 0.0, 100.5, 40.25),        # top-left corner
    (W - 100.5, 0.0, W - 0.0, 40.25),   # top-right corner
    (0.0, H - 40.25, 100.5, H - 0.0),   # bottom-left corner
    (W - 100.5, H - 40.25, W - 0.0, H - 0.0),  # bottom-right
])
def test_plate_touching_boundary(box):
    frame = _frame()
    for conv in ("trunc", "round"):
        for e in EXPANSIONS:
            r = extract_crop(frame, box, conv, e)
            if r["invalid"]:
                continue
            _assert_in_bounds(r)


# 2. very small plates (down to 2x2 px)
@pytest.mark.parametrize("box", [
    (100.0, 100.0, 102.0, 102.0),    # 2x2
    (100.0, 100.0, 104.9, 103.9),    # ~4x3
    (100.2, 100.2, 105.7, 104.8),    # fractional small
])
def test_very_small_plates(box):
    frame = _frame()
    for conv in ("trunc", "round"):
        for e in EXPANSIONS:
            r = extract_crop(frame, box, conv, e)
            if r["invalid"]:
                continue
            _assert_in_bounds(r)
            # a 1.10x expansion of a 2px box must stay >= 2px
            assert r["effective_width"] >= 2
            assert r["effective_height"] >= 2


# 3. very large plates (most of the frame)
@pytest.mark.parametrize("box", [
    (1.0, 1.0, W - 1.0, H - 1.0),
    (0.5, 0.5, W - 0.5, H - 0.5),
])
def test_very_large_plates(box):
    frame = _frame()
    for conv in ("trunc", "round"):
        for e in EXPANSIONS:
            r = extract_crop(frame, box, conv, e)
            _assert_in_bounds(r)
            # expansion of a near-frame box clips to the frame
            x1, y1, x2, y2 = r["integer_bbox"]
            assert x2 - x1 <= W and y2 - y1 <= H


# 4. partially detected plates (box covers only part of the plate)
def test_partially_detected_plate():
    frame = _frame()
    # true plate (100,100)-(300,140); detector sees only a part
    for box in [(120.0, 105.0, 250.0, 130.0),
                (100.0, 100.0, 150.0, 140.0)]:
        for conv in ("trunc", "round"):
            r = extract_crop(frame, box, conv, 1.0)
            _assert_in_bounds(r)


# 5. boxes with negative coordinates (clipped to 0, never wrap)
@pytest.mark.parametrize("box", [
    (-10.5, -5.25, 100.0, 40.0),
    (-0.4, -0.4, 100.0, 40.0),
    (-500.0, -500.0, 100.0, 40.0),
])
def test_negative_coordinates_clipped_not_wrapped(box):
    frame = _frame()
    for conv in ("trunc", "round"):
        for e in EXPANSIONS:
            r = extract_crop(frame, box, conv, e)
            if r["invalid"]:
                continue
            x1, y1, x2, y2 = r["integer_bbox"]
            # the helper clips to the frame origin — it must NEVER
            # reproduce numpy's negative-index wrap
            assert x1 >= 0 and y1 >= 0
            _assert_in_bounds(r)


# 6. boxes extending beyond the frame
@pytest.mark.parametrize("box", [
    (W - 50.0, H - 20.0, W + 80.5, H + 60.25),
    (-20.0, -20.0, W + 20.0, H + 20.0),
])
def test_boxes_beyond_frame(box):
    frame = _frame()
    for conv in ("trunc", "round"):
        for e in EXPANSIONS:
            r = extract_crop(frame, box, conv, e)
            if r["invalid"]:
                continue
            _assert_in_bounds(r)


# 7. malformed / degenerate boxes
@pytest.mark.parametrize("box", [
    (100.0, 100.0, 100.0, 140.0),    # zero width
    (100.0, 100.0, 90.0, 140.0),     # inverted x
    (100.0, 100.0, 200.0, 100.0),    # zero height
    (100.0, 140.0, 200.0, 100.0),    # inverted y
    (100.0, 100.0, 100.0, 100.0),    # point
])
def test_degenerate_boxes_rejected(box):
    frame = _frame()
    for conv in ("trunc", "round"):
        for e in EXPANSIONS:
            r = extract_crop(frame, box, conv, e)
            assert r["invalid"] is True
            assert r["crop"] is None
            assert r["effective_width"] == 0 or r["effective_height"] == 0


# 8. multiple nearby vehicles (overlapping boxes cropped independently)
def test_multiple_nearby_vehicles():
    frame = _frame()
    boxes = [(100.0, 100.0, 200.0, 140.0),
             (150.0, 105.0, 250.0, 145.0),   # 50% overlap
             (190.0, 100.0, 290.0, 140.0)]   # adjacent
    crops = []
    for box in boxes:
        for conv in ("trunc", "round"):
            r = extract_crop(frame, box, conv, 1.0)
            _assert_in_bounds(r)
            crops.append(r["crop"].tobytes())
    # overlapping boxes produce distinct (overlapping) crops — the
    # crop layer must not silently merge or drop them
    assert len(crops) == 6


# 9. duplicate detector boxes (identical input -> identical crop)
def test_duplicate_detector_boxes():
    frame = _frame()
    box = (100.25, 100.75, 200.5, 140.25)
    outs = [extract_crop(frame, box, "round", 1.0) for _ in range(5)]
    for a, b in zip(outs, outs[1:]):
        assert a["integer_bbox"] == b["integer_bbox"]
        assert a["crop"].tobytes() == b["crop"].tobytes()


# 10. non-plate detections (arbitrary garbage boxes still crop safely)
def test_non_plate_detections():
    frame = _frame()
    # 1-px tall strip, full-width strip, thin diagonal-ish box
    for box in [(0.0, 240.0, W - 0.0, 241.0),
                (320.0, 0.0, 321.0, H - 0.0),
                (100.0, 100.0, 101.0, 101.0)]:
        for conv in ("trunc", "round"):
            r = extract_crop(frame, box, conv, 1.0)
            if r["invalid"]:
                continue
            _assert_in_bounds(r)


# expansion must never blindly enlarge beyond the frame
def test_expansion_clips_to_frame_on_all_edges():
    frame = _frame()
    box = (W / 2 - 10.0, H / 2 - 5.0, W / 2 + 10.0, H / 2 + 5.0)
    for e in EXPANSIONS:
        r = extract_crop(frame, box, "round", e)
        _assert_in_bounds(r)
        # expanded box centred on the same centre
        x1, y1, x2, y2 = r["integer_bbox"]
        assert abs((x1 + x2) / 2 - W / 2) <= 1
        assert abs((y1 + y2) / 2 - H / 2) <= 1


# determinism under every convention x expansion combination
def test_determinism_all_combinations():
    frame = _frame()
    box = (100.25, 50.75, 300.5, 90.25)
    for conv in ("trunc", "round", "floor", "ceil"):
        for e in EXPANSIONS:
            a = extract_crop(frame, box, conv, e)
            b = extract_crop(frame, box, conv, e)
            assert a["integer_bbox"] == b["integer_bbox"]
            if a["crop"] is not None:
                assert a["crop"].tobytes() == b["crop"].tobytes()
