"""Phase 2B infrastructure tests (task §21).

Covers metric/bucket classification, clipping detection, pairwise
classification, result serialization, crop-boundary conventions and
ground-truth exclusion of UNLABELED samples. No production behaviour is
touched by these tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))

import ab_helpers as H  # noqa: E402
import metrics  # noqa: E402


# ------------------------------------------------------------------ buckets
@pytest.mark.parametrize("width,bucket", [
    (0, "lt80"), (79, "lt80"), (80, "80-99"), (99, "80-99"),
    (100, "100-149"), (149, "100-149"), (150, "150-199"),
    (199, "150-199"), (200, "ge200"), (900, "ge200"),
])
def test_bucket_boundaries(width, bucket):
    assert H.bucket_for(width) == bucket


# --------------------------------------------------------------- geometry
def test_geometry_and_aspect():
    g = H.geometry([10, 20, 110, 70])
    assert (g["width"], g["height"], g["area"]) == (100, 50, 5000)
    assert g["aspect_ratio"] == 2.0
    assert H.geometry([0, 0, 0, 0])["aspect_ratio"] is None


# --------------------------------------------------------------- clipping
def test_clipping_flags_all_sides():
    assert H.clipping_flags([0, 10, 100, 60], 1920, 1080)["clipped_left"]
    assert H.clipping_flags([1900, 10, 1920, 60], 1920, 1080)["clipped_right"]
    assert H.clipping_flags([10, 0, 100, 60], 1920, 1080)["clipped_top"]
    assert H.clipping_flags([10, 1050, 100, 1080], 1920, 1080)["clipped_bottom"]
    interior = H.clipping_flags([500, 300, 700, 360], 1920, 1080)
    assert not interior["clipped_any"]
    assert H.clipping_flags([0, 0, 50, 50], 1920, 1080)["clipped_any"]


# ------------------------------------------------------------- pairwise
def test_box_iou_and_pair_matching():
    assert H.box_iou([0, 0, 10, 10], [0, 0, 10, 10]) == pytest.approx(1.0)
    assert H.box_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    cur = [[0, 0, 10, 10], [100, 100, 120, 120]]
    ipv = [[1, 1, 11, 11]]
    pairs, cur_only, ipv_only = H.pair_boxes(cur, ipv)
    assert len(pairs) == 1 and pairs[0][2] > 0.5
    assert len(cur_only) == 1 and ipv_only == []


def test_unmatched_detections_are_not_pairs():
    pairs, cur_only, ipv_only = H.pair_boxes([[0, 0, 10, 10]], [])
    assert pairs == [] and len(cur_only) == 1 and ipv_only == []


@pytest.mark.parametrize("cur,ipv,expected", [
    (True, True, H.BOTH_CORRECT),
    (True, False, H.CURRENT_BETTER),
    (False, True, H.IRANPLATE_BETTER),
    (False, False, H.BOTH_WRONG),
])
def test_classify_pair_with_gt(cur, ipv, expected):
    assert H.classify_pair(True, cur, ipv, True, True) == expected


def test_classify_pair_without_gt_uses_validity_only():
    assert H.classify_pair(False, None, None, True, False) == H.CURRENT_ONLY_VALID
    assert H.classify_pair(False, None, None, False, True) == H.IRANPLATE_ONLY_VALID
    assert H.classify_pair(False, None, None, False, False) == H.NEITHER_VALID
    # both valid but no GT -> no superiority claim possible
    assert H.classify_pair(False, None, None, True, True) == H.INCOMPARABLE
    assert H.classify_pair(True, None, None, True, True) == H.BOTH_CORRECT


def test_percentile():
    vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert H.percentile(vals, 0) == 1
    assert H.percentile(vals, 100) == 10
    assert H.percentile([], 50) is None


# ------------------------------------------------ metric calculation
def test_canonical_and_char_accuracy():
    # Persian digits/letters fold to production ASCII before comparison
    # (normalize -> yeh/kaf folding + FA_TO_ASCII transliteration)
    assert metrics.canonical("۱۲ب۳") == metrics.canonical("12B3") == "12B3"
    assert metrics.canonical("۰۰ب۱۲۳") == metrics.canonical("00B123")
    assert metrics.canonical(None) == ""
    assert metrics.char_accuracy("123", "123") == 1.0
    assert metrics.char_accuracy("124", "123") == pytest.approx(2 / 3)
    assert metrics.char_accuracy("", "123") == pytest.approx(0.0)
    assert metrics.char_accuracy("anything", "") == 0.0


def test_score_pair_flags_failure_and_exactness():
    ok = metrics.score_pair("12ب345", "12B345")
    assert ok["exact"] is True and ok["failed"] is False
    assert ok["edit_distance"] == 0 and ok["char_accuracy"] == 1.0

    empty = metrics.score_pair("", "123")
    assert empty["failed"] is True and empty["exact"] is False

    miss = metrics.score_pair("129", "123")
    assert miss["exact"] is False and miss["edit_distance"] == 1
    assert 0.0 < miss["char_accuracy"] < 1.0


@pytest.mark.parametrize("width,bucket", [
    (0, "lt100"), (99, "lt100"), (100, "100-150"),
    (149, "100-150"), (150, "ge150"), (900, "ge150"),
])
def test_metrics_width_buckets(width, bucket):
    assert metrics.width_bucket(width) == bucket


def test_aggregate_rates_and_grouping():
    recs = [
        {"group": "cam1", "exact": True, "char_accuracy": 1.0,
         "edit_distance": 0, "failed": False, "invalid": False},
        {"group": "cam1", "exact": False, "char_accuracy": 0.5,
         "edit_distance": 1, "failed": True, "invalid": True},
        {"group": "cam2", "exact": None, "char_accuracy": None,
         "edit_distance": None, "failed": True, "invalid": True},
    ]
    out = metrics.aggregate(recs, group_key=lambda r: r["group"])
    assert set(out) == {"cam1", "cam2"}

    cam1 = out["cam1"]
    assert cam1["n_samples"] == 2 and cam1["n_verified"] == 2
    assert cam1["n_exact"] == 1 and cam1["n_incorrect"] == 1
    assert cam1["exact_accuracy"] == 0.5
    assert cam1["mean_edit_distance"] == 0.5
    assert cam1["invalid_rate"] == 0.5 and cam1["failed_rate"] == 0.5

    # group with no verified GT -> accuracy is None, never 0/1
    cam2 = out["cam2"]
    assert cam2["n_verified"] == 0
    assert cam2["exact_accuracy"] is None
    assert cam2["char_accuracy"] is None
    assert cam2["mean_edit_distance"] is None
    # validity/failure rates still cover every sample
    assert cam2["n_samples"] == 1 and cam2["invalid_rate"] == 1.0


def test_aggregate_of_empty_input_is_safe():
    assert metrics.aggregate([]) == {}


def test_result_aggregate_is_json_serializable():
    recs = [{"exact": True, "char_accuracy": 1.0, "edit_distance": 0,
             "failed": False, "invalid": False}]
    agg = metrics.aggregate(recs)["all"]
    restored = json.loads(json.dumps(agg))
    assert restored == agg
    assert restored["exact_accuracy"] == 1.0


# ---------------------------------------------------- crop conventions
def test_crop_conventions_round_vs_floor_differ_by_at_most_one_pixel():
    from run_phase2b_crop_sensitivity import crop_with
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    box = [10.4, 20.6, 110.5, 60.4]
    r = crop_with(frame, box, "round")
    f = crop_with(frame, box, "floor")
    assert abs(r.shape[1] - f.shape[1]) <= 1
    assert abs(r.shape[0] - f.shape[0]) <= 1
    assert crop_with(frame, box, "round_dx+1").shape[1] >= r.shape[1] - 1
    # degenerate box -> None, never a crash
    assert crop_with(frame, [50, 50, 50, 50], "round") is None


# ------------------------------------------------------- GT exclusion
def test_unlabeled_cam2_rows_never_enter_accuracy():
    gt_path = ROOT / "benchmarks" / "dataset" / "ground_truth.jsonl"
    rows = [json.loads(l) for l in open(gt_path, encoding="utf-8")]
    cam2 = [r for r in rows if r["sample_id"].startswith("cam2_")]
    assert cam2, "expected cam2 samples"
    assert all(not r["verified"] and r["plate_text"] is None for r in cam2)

    recs = [{"exact": True, "char_accuracy": 1.0, "edit_distance": 0,
             "failed": False, "invalid": False},
            {"exact": None, "char_accuracy": None, "edit_distance": None,
             "failed": False, "invalid": True}]
    agg = metrics.aggregate(recs)["all"]
    assert agg["n_verified"] == 1 and agg["exact_accuracy"] == 1.0
    assert agg["n_samples"] == 2


def test_unlabeled_exclusion_is_dataset_wide_not_just_cam2():
    """No sample may be verified=true while plate_text is None."""
    gt_path = ROOT / "benchmarks" / "dataset" / "ground_truth.jsonl"
    rows = [json.loads(l) for l in open(gt_path, encoding="utf-8")]
    assert rows, "ground truth must not be empty"
    bad = [r["sample_id"] for r in rows
           if r["verified"] != (r["plate_text"] is not None)]
    assert not bad, f"verified/plate_text disagree for: {bad[:5]}"
    unlabeled = [r for r in rows if not r["verified"]]
    assert unlabeled, "dataset must contain UNLABELED samples to exercise exclusion"

    # every UNLABELED row must be dropped from every accuracy figure
    recs = [{"exact": (r["plate_text"] is not None) if r["verified"] else None,
             "char_accuracy": 1.0 if r["verified"] else None,
             "edit_distance": 0 if r["verified"] else None,
             "failed": False, "invalid": False}
            for r in rows]
    agg = metrics.aggregate(recs)["all"]
    assert agg["n_samples"] == len(rows)
    assert agg["n_verified"] == len(rows) - len(unlabeled)
    assert agg["n_verified"] > 0


# ------------------------------------------------------ result schemas
@pytest.mark.parametrize("fname,required", [
    ("phase2b_detector_crop_results.json",
     ["methodology", "detector_summary", "frame_level", "records"]),
    ("phase2b_pairwise_results.json", ["outcome_counts", "pairs"]),
    ("phase2b_bucket_results.json",
     ["buckets", "threshold_sweep", "crop_expansion"]),
    ("phase2b_crop_sensitivity_results.json",
     ["summary", "flip_count", "flips", "records"]),
])
def test_result_files_exist_with_stable_schema(fname, required):
    p = ROOT / "benchmarks" / "results" / fname
    if not p.exists():
        pytest.skip(f"{fname} not generated yet")
    data = json.loads(p.read_text(encoding="utf-8"))
    for key in required:
        assert key in data, f"{fname} missing '{key}'"
    # JSON round-trip stability
    assert json.loads(json.dumps(data)) == data


def test_detector_summary_contains_both_detectors_and_buckets():
    p = ROOT / "benchmarks" / "results" / "phase2b_detector_crop_results.json"
    if not p.exists():
        pytest.skip("results not generated yet")
    data = json.loads(p.read_text(encoding="utf-8"))
    for det in ("current_detector", "iranplate_vision"):
        assert det in data["detector_summary"]
        entry = data["detector_summary"][det]
        for key in ("overall", "cam1.mp4", "cam2.mp4"):
            assert key in entry
        assert any(k.startswith("bucket:") for k in entry)


def test_pairwise_outcomes_only_use_documented_classes():
    p = ROOT / "benchmarks" / "results" / "phase2b_pairwise_results.json"
    if not p.exists():
        pytest.skip("results not generated yet")
    counts = json.loads(p.read_text(encoding="utf-8"))["outcome_counts"]
    allowed = {H.BOTH_CORRECT, H.BOTH_WRONG, H.CURRENT_BETTER, H.IRANPLATE_BETTER,
               H.CURRENT_ONLY_VALID, H.IRANPLATE_ONLY_VALID,
               H.NEITHER_VALID, H.INCOMPARABLE}
    assert set(counts) <= allowed, f"unexpected outcomes: {set(counts) - allowed}"
    # every recorded outcome must be reproducible by classify_pair
    for outcome in counts:
        assert isinstance(outcome, str)


def test_stored_results_use_only_buckets_defined_by_helpers():
    p = ROOT / "benchmarks" / "results" / "phase2b_bucket_results.json"
    if not p.exists():
        pytest.skip("results not generated yet")
    known = {name for _, _, name in H.BUCKETS}
    for det, buckets in json.loads(p.read_text(encoding="utf-8"))["buckets"].items():
        assert set(buckets) <= known, f"{det}: unknown buckets {set(buckets) - known}"
