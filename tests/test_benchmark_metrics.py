"""Tests for the verified-ground-truth benchmark layer (metrics, preprocessing,
ground-truth application). No production code is modified or exercised here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))

import metrics  # noqa: E402
import preprocessing  # noqa: E402


# ------------------------------------------------------------------ canonical
def test_canonical_maps_persian_and_ascii_to_one_form():
    # production romanized vs hezar Persian output must compare equal
    assert metrics.canonical("28y68923") == metrics.canonical("۲۸ی۶۸۹۲۳")
    assert metrics.canonical("۱۲د۶۷۴۱۳") == metrics.canonical("12d67413")


def test_canonical_keeps_meaningful_differences():
    assert metrics.canonical("28ی68923") != metrics.canonical("28د68923")
    assert metrics.canonical("12D67413") != metrics.canonical("12D6741")


def test_char_accuracy_and_edit_distance():
    s = metrics.score_pair("12d6741", "۱۲د۶۷۴۱۳")   # missing one digit
    assert s["edit_distance"] == 1
    assert 0.8 < s["char_accuracy"] < 1.0
    assert s["exact"] is False
    assert metrics.score_pair("28y68923", "۲۸ی۶۸۹۲۳")["exact"] is True
    assert metrics.score_pair("", "28Y68923")["failed"] is True


def test_width_buckets():
    assert metrics.width_bucket(80) == "lt100"
    assert metrics.width_bucket(120) == "100-150"
    assert metrics.width_bucket(230) == "ge150"


# ------------------------------------------------------------ GT exclusion
def test_aggregate_excludes_unlabeled_from_accuracy():
    recs = [
        {"exact": True, "char_accuracy": 1.0, "edit_distance": 0,
         "failed": False, "invalid": False},
        {"exact": False, "char_accuracy": 0.5, "edit_distance": 2,
         "failed": False, "invalid": False},
        {"exact": None, "char_accuracy": None, "edit_distance": None,
         "failed": True, "invalid": True},   # UNLABELED row
    ]
    agg = metrics.aggregate(recs)["all"]
    assert agg["n_samples"] == 3
    assert agg["n_verified"] == 2            # unlabeled excluded
    assert agg["exact_accuracy"] == 0.5      # 1 of 2 verified
    assert agg["failed_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert agg["invalid_rate"] == pytest.approx(1 / 3, abs=1e-4)


def test_aggregate_grouping():
    recs = [
        {"exact": True, "char_accuracy": 1.0, "edit_distance": 0, "failed": False,
         "invalid": False, "video": "cam1"},
        {"exact": None, "char_accuracy": None, "edit_distance": None,
         "failed": False, "invalid": True, "video": "cam2"},
    ]
    agg = metrics.aggregate(recs, lambda r: r["video"])
    assert agg["cam1"]["exact_accuracy"] == 1.0
    assert agg["cam2"]["exact_accuracy"] is None


# ------------------------------------------------------------ preprocessing
def test_preprocessing_variants_shapes():
    crop = np.full((40, 160, 3), 120, dtype=np.uint8)
    assert preprocessing.apply_variant(crop, "original").shape == crop.shape
    assert preprocessing.apply_variant(crop, "up2x").shape[:2] == (80, 320)
    assert preprocessing.apply_variant(crop, "up3x").shape[:2] == (120, 480)
    for v in ("gray", "clahe", "sharpen"):
        out = preprocessing.apply_variant(crop, v)
        assert out.shape == crop.shape and out.dtype == np.uint8


def test_perspective_returns_none_or_image():
    flat = np.full((40, 160, 3), 200, dtype=np.uint8)
    out = preprocessing.apply_variant(flat, "persp")
    assert out is None or out.size > 0     # explicit None = "skipped", recorded
    assert preprocessing.VARIANTS[-1] == "persp"
    # order_points is deterministic and ordered TL,TR,BR,BL
    pts = np.array([[0, 0], [10, 0], [10, 4], [0, 4]], dtype="float32")
    ordered = preprocessing.order_points(pts)
    assert ordered[0].tolist() == [0, 0] and ordered[2].tolist() == [10, 4]


def test_unknown_variant_raises():
    with pytest.raises(ValueError):
        preprocessing.apply_variant(np.zeros((5, 5, 3), np.uint8), "nope")


# ------------------------------------------------------------ GT workflow
def test_ground_truth_labels_and_jsonl_consistency():
    ds = ROOT / "benchmarks" / "dataset"
    labels = json.loads((ds / "gt_labels.json").read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in open(ds / "ground_truth.jsonl", encoding="utf-8")]
    meta = [json.loads(l) for l in open(ds / "metadata.jsonl", encoding="utf-8")]
    assert len(rows) == len(meta)
    verified_ids = {r["sample_id"] for r in rows if r["verified"]}
    # cam1 crops must be verified, cam2 must not be
    for m in meta:
        is_verified = m["id"] in verified_ids
        if m["source_video"] == "cam1.mp4":
            assert is_verified, f"{m['id']} should be verified"
        else:
            assert not is_verified, f"{m['id']} cam2 must stay UNLABELED"
    # verified rows carry non-empty text, unverified carry none
    for r in rows:
        if r["verified"]:
            assert r["plate_text"]
        else:
            assert r["plate_text"] is None and r["status"] == "UNLABELED"
    assert labels["labels"]["cam2_plate_X"]["verified"] is False
