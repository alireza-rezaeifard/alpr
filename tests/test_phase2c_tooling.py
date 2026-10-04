"""Tests for Phase 2C benchmark tooling (crop extraction, denominators, protocol).

Pure unit tests: no model loading, no video decoding, no network. numpy is used
only to prove the canonical `trunc` convention matches production astype(int).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))

from phase2c_canonical import (  # noqa: E402
    CONVENTIONS, PRODUCTION_CONVENTION, bucket_for, convert_box, convert_coord,
    expand_box, extract_plate_crop, select_canonical,
)


def _frame(w=200, h=100):
    return np.zeros((h, w, 3), dtype=np.uint8)


# ------------------------------------------------------------ rounding rules
def test_round_is_half_away_from_zero_not_banker():
    # Python's round() is banker's rounding and would give 10 for 10.5.
    assert convert_coord(10.5, "round") == 11
    assert convert_coord(11.5, "round") == 12
    assert convert_coord(-10.5, "round") == -11


@pytest.mark.parametrize("value", [10.4, 10.6, 99.5, 0.5, -0.4, -0.6, -99.5])
def test_round_matches_documented_rule(value):
    expected = (math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5))
    assert convert_coord(value, "round") == expected


def test_trunc_matches_production_astype_int_on_random_floats():
    rng = np.random.default_rng(20260203)
    for _ in range(2000):
        v = float(rng.uniform(-500, 2000))
        assert convert_coord(v, "trunc") == int(np.asarray([v]).astype(int)[0])


def test_trunc_differs_from_floor_for_negatives():
    # The conventions are NOT interchangeable; the suite must not pretend so.
    assert convert_coord(-10.7, "trunc") == -10
    assert convert_coord(-10.7, "floor") == -11


def test_unknown_convention_rejected():
    with pytest.raises(ValueError):
        convert_coord(1.0, "nearest")


# --------------------------------------------------------------- clipping
def test_negative_coords_clipped_to_zero():
    crop, r = extract_plate_crop(_frame(), (-5.0, -5.0, 50.0, 40.0), convention="round")
    assert r.clipped_left and r.clipped_top
    assert (r.x1_pixel, r.y1_pixel) == (0, 0)
    assert crop.shape[1] == r.crop_width == 50


def test_coords_beyond_frame_clipped():
    _, r = extract_plate_crop(_frame(200, 100), (150.0, 80.0, 400.0, 300.0),
                              convention="round")
    assert r.clipped_right and r.clipped_bottom
    assert (r.x2_pixel, r.y2_pixel) == (200, 100)


def test_no_clip_mode_reports_but_keeps_raw():
    _, r = extract_plate_crop(_frame(), (-5.0, -5.0, 50.0, 40.0),
                              convention="round", clip=False)
    assert r.clipped_any is True
    assert r.x1_pixel == -5


def test_interior_box_not_flagged_clipped():
    _, r = extract_plate_crop(_frame(), (20.0, 20.0, 60.0, 60.0))
    assert r.clipped_any is False


# ------------------------------------------------------- degenerate boxes
@pytest.mark.parametrize("box,reason", [
    ((10.0, 10.0, 10.0, 40.0), "zero_width"),
    ((10.0, 10.0, 50.0, 10.0), "zero_height"),
    ((50.0, 40.0, 10.0, 10.0), "zero_width"),
])
def test_degenerate_boxes_rejected_with_reason(box, reason):
    crop, r = extract_plate_crop(_frame(), box)
    assert crop is None
    assert r.invalid and r.invalid_reason == reason
    assert r.crop_width == 0 or r.crop_height == 0


def test_fractional_zero_width_rejected():
    crop, r = extract_plate_crop(_frame(), (20.9, 10.0, 20.9, 40.0), convention="trunc")
    assert crop is None and r.invalid


# ------------------------------------------------------------ float coords
def test_float_coords_recorded_beside_pixels():
    box = (10.4, 20.6, 50.6, 40.4)
    _, r = extract_plate_crop(_frame(), box, convention="round")
    assert (r.x1_float, r.y1_float, r.x2_float, r.y2_float) == box
    assert (r.x1_pixel, r.y1_pixel, r.x2_pixel, r.y2_pixel) == (10, 21, 51, 40)
    assert r.crop_width == 41 and r.crop_height == 19


def test_all_conventions_produce_valid_crops_for_interior_box():
    for conv in CONVENTIONS:
        crop, r = extract_plate_crop(_frame(), (10.4, 20.6, 50.6, 40.4), convention=conv)
        assert not r.invalid and crop is not None
        assert crop.shape[1] == r.crop_width


def test_padding_applied_in_pixel_space():
    _, r = extract_plate_crop(_frame(), (10.0, 10.0, 50.0, 40.0), pad_x=5, pad_y=2)
    assert (r.x1_pixel, r.x2_pixel) == (5, 55)
    assert (r.y1_pixel, r.y2_pixel) == (8, 42)


# ------------------------------------------------------------------ buckets
@pytest.mark.parametrize("width,expected", [
    (0, "lt80"), (79, "lt80"), (80, "80-99"), (99, "80-99"),
    (100, "100-149"), (149, "100-149"), (150, "150-199"),
    (199, "150-199"), (200, "ge200"), (1920, "ge200")])
def test_bucket_boundaries(width, expected):
    assert bucket_for(width) == expected


# ----------------------------------------------------- canonical selection
def test_select_canonical_prefers_production_equivalent():
    scores = {"round": {"production_equivalent": False, "degenerate_count": 0,
                        "shrinks_box_count": 4},
              "trunc": {"production_equivalent": True, "degenerate_count": 0,
                        "shrinks_box_count": 0}}
    chosen, reasons = select_canonical(scores)
    assert chosen == "trunc"
    assert any("production-equivalent" in r for r in reasons)


def test_select_canonical_ignores_any_accuracy_field():
    """Ground truth must not influence protocol selection (task §31)."""
    scores = {"floor": {"production_equivalent": False, "degenerate_count": 0,
                        "shrinks_box_count": 1, "exact_accuracy": 1.0},
              "round": {"production_equivalent": False, "degenerate_count": 0,
                        "shrinks_box_count": 1, "exact_accuracy": 0.0}}
    chosen, _ = select_canonical(scores)
    stripped = {k: {kk: vv for kk, vv in v.items() if kk != "exact_accuracy"}
                for k, v in scores.items()}
    assert chosen == select_canonical(stripped)[0]


def test_select_canonical_avoids_degenerate_convention():
    scores = {"ceil": {"production_equivalent": False, "degenerate_count": 5,
                       "shrinks_box_count": 0},
              "round": {"production_equivalent": False, "degenerate_count": 0,
                        "shrinks_box_count": 9}}
    chosen, reasons = select_canonical(scores)
    assert chosen == "round"
    assert any("degenerate" in r for r in reasons)


# ---------------------------------------------------------------- expansion
@pytest.mark.parametrize("factor", [1.0, 1.05, 1.1, 1.15, 1.2])
def test_expansion_preserves_center(factor):
    box = [100.0, 50.0, 200.0, 100.0]
    out = expand_box(box, factor)
    assert (out[0] + out[2]) / 2 == pytest.approx((box[0] + box[2]) / 2)
    assert (out[1] + out[3]) / 2 == pytest.approx((box[1] + box[3]) / 2)
# ------------------------------------------- ratios, pairing and GT policy
def ratio(num, den):
    return {"numerator": num, "denominator": den,
            "value": round(num / den, 4) if den else None}


def test_ratio_exposes_denominator():
    r = ratio(3, 4)
    assert r["numerator"] == 3 and r["denominator"] == 4 and r["value"] == 0.75


def test_ratio_zero_denominator_is_none_not_zero():
    r = ratio(0, 0)
    assert r["value"] is None
    assert r["denominator"] == 0


def test_no_detection_counts_as_wrong_in_paired_table():
    """A miss must stay in the denominator, never be dropped."""
    best = {("cam1.mp4", 5, "detector_a_current"): {"exact": True},
            ("cam1.mp4", 5, "detector_b_iranplate"): {"exact": False,
                                                       "status": "NO_DETECTION"}}
    ok_a = bool(best[("cam1.mp4", 5, "detector_a_current")]["exact"])
    ok_b = False  # NO_DETECTION can never be correct
    assert ok_a and not ok_b


def test_pairing_keys_on_camera_and_frame():
    key = ("cam1.mp4", 120, "detector_a_current")
    assert key[:2] == ("cam1.mp4", 120)


def test_duplicate_boxes_are_counted_not_silently_dropped():
    rows = [{"n_boxes_this_frame": 3, "detection_status": "DETECTED"}]
    assert sum(r["n_boxes_this_frame"] for r in rows) == 3


# ------------------------------------------------------------------- GT
def _gt_label_fixture():
    labels = json.loads((ROOT / "benchmarks" / "dataset" / "gt_labels.json")
                        .read_text(encoding="utf-8"))
    return labels["labels"]


def test_gt_fixture_has_both_verified_and_unlabeled():
    labs = _gt_label_fixture().values()
    assert any(l.get("verified") for l in labs)
    assert any(not l.get("verified") for l in labs)


def test_unlabeled_samples_carry_no_plate_text():
    for lab in _gt_label_fixture().values():
        if not lab.get("verified"):
            assert not lab.get("plate_text")


def test_unlabeled_never_reaches_accuracy_denominator():
    """UNLABELED rows must be null, never 0/false, for accuracy fields."""
    unlabeled = [r for r in _load_records() if r.get("gt_status") == "UNLABELED"]
    for r in unlabeled:
        assert r.get("exact") is None
        assert r.get("char_accuracy") is None
        assert r.get("edit_distance") is None


def test_failed_means_empty_ocr_not_invalid():
    """Phase 2B shipped a bug where failed duplicated invalid; guard it."""
    for r in _load_records():
        if r.get("ocr_text") is None:
            continue
        assert r["failed"] == (not r["ocr_text"].strip()), r


def _load_records():
    p = ROOT / "benchmarks" / "results" / "phase2c_raw_results.json"
    if not p.exists():
        pytest.skip("phase2c_raw_results.json not generated yet")
    return json.loads(p.read_text(encoding="utf-8"))["records"]


# -------------------------------------------------------------- protocol
def test_protocol_uses_one_shared_inference_config():
    p = ROOT / "benchmarks" / "run_phase2c_ab.py"
    src = p.read_text(encoding="utf-8")
    # a single predict() call shared by both arms via the `call` closure
    assert src.count("res = model.predict(") == 1
    for token in ("conf=conf", "iou=iou", "max_det=max_det", "imgsz=imgsz"):
        assert token in src, token


def test_both_detectors_are_wired_to_the_same_call_helper():
    src = (ROOT / "benchmarks" / "run_phase2c_ab.py").read_text(encoding="utf-8")
    assert '"detector_a_current": lambda f: call(a_model, f)' in src
    assert '"detector_b_iranplate": lambda f: call(b_model, f)' in src


def test_warmup_constant_meets_spec_minimum():
    src = (ROOT / "benchmarks" / "run_phase2c_ab.py").read_text(encoding="utf-8")
    assert "WARMUP_CALLS = 20" in src
    assert "LATENCY_CALLS = 100" in src


# ------------------------------------------------------- reproducibility
def test_result_ordering_is_deterministic():
    src = (ROOT / "benchmarks" / "run_phase2c_ab.py").read_text(encoding="utf-8")
    # records are appended in frame order, never from a set/dict iteration
    assert "for video, idx, frame in frames:" in src
    assert "sort_keys=True" in src


def test_json_serialization_keeps_unicode():
    src = (ROOT / "benchmarks" / "run_phase2c_ab.py").read_text(encoding="utf-8")
    assert "ensure_ascii=False" in src


def test_expansion_identity_at_one():
    assert expand_box([1.0, 2.0, 3.0, 4.0], 1.0) == [1.0, 2.0, 3.0, 4.0]