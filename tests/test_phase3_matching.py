"""Phase 3 tests — deterministic matching, IoU, and
detection metrics (task §19/§20/§37)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

import pytest  # noqa: E402

from benchmarks.phase3_matching import (  # noqa: E402
    Box, Prediction, detection_metrics, iou,
    match_predictions)


def test_box_rejects_inverted():
    with pytest.raises(ValueError):
        Box(10, 10, 5, 20)
    with pytest.raises(ValueError):
        Box(10, 20, 50, 10)


def test_box_rejects_negative():
    with pytest.raises(ValueError):
        Box(-1, 0, 10, 10)


def test_iou_identical_box_is_one():
    a = Box(0, 0, 100, 50)
    assert iou(a, a) == 1.0


def test_iou_disjoint_is_zero():
    a = Box(0, 0, 10, 10)
    b = Box(100, 100, 200, 200)
    assert iou(a, b) == 0.0


def test_iou_half_overlap():
    a = Box(0, 0, 100, 100)
    b = Box(50, 0, 150, 100)
    # intersection 50x100=5000, union 150x100=15000
    assert abs(iou(a, b) - 5000 / 15000) < 1e-9


def test_iou_empty_box_is_zero():
    a = Box(0, 0, 0, 0)
    b = Box(0, 0, 10, 10)
    assert iou(a, b) == 0.0


def test_one_to_one_no_double_credit():
    """Two predictions on ONE GT box: only the best
    gets TP; the other is FP. A detector can never
    receive multiple TP credit for one plate."""
    gt = [Box(0, 0, 100, 100)]
    preds = [
        Prediction(Box(0, 0, 100, 100), 0.9),
        Prediction(Box(2, 2, 98, 98), 0.8),
    ]
    res = match_predictions(preds, gt, tau=0.5)
    assert res["tp"] == 1
    assert res["fp"] == 1
    assert res["fn"] == 0


def test_one_prediction_matches_one_gt_only():
    """One prediction overlapping two GT boxes matches
    only the higher-IoU one."""
    gts = [Box(0, 0, 100, 100), Box(200, 0, 300, 100)]
    preds = [Prediction(Box(0, 0, 100, 100), 0.9)]
    res = match_predictions(preds, gts, tau=0.5)
    assert res["tp"] == 1
    assert res["fn"] == 1
    assert res["matches"][0].gt_index == 0


def test_deterministic_tie_breaking():
    """Equal IoU and confidence: the tie breaks on box
    coordinates, so the result is reproducible."""
    gt = [Box(0, 0, 100, 100)]
    p1 = Prediction(Box(0, 0, 100, 100), 0.5)
    p2 = Prediction(Box(0, 0, 100, 100), 0.5)
    r1 = match_predictions([p1, p2], gt)
    r2 = match_predictions([p1, p2], gt)
    assert r1["tp"] == r2["tp"] == 1
    assert r1["matches"][0].prediction_index == \
        r2["matches"][0].prediction_index


def test_below_tau_is_fp_not_tp():
    gt = [Box(0, 0, 100, 100)]
    preds = [Prediction(Box(0, 0, 60, 100), 0.99)]
    # IoU = 6000/10000 = 0.6 >= 0.5 -> TP
    res = match_predictions(preds, gt, tau=0.5)
    assert res["tp"] == 1
    # at tau=0.75 the same pair is NOT a TP
    res2 = match_predictions(preds, gt, tau=0.75)
    assert res2["tp"] == 0
    assert res2["fp"] == 1


def test_detection_metrics_none_on_empty():
    res = match_predictions([], [])
    dm = detection_metrics(res)
    assert dm["precision"] is None
    assert dm["recall"] is None
    assert dm["f1"] is None


def test_detection_metrics_perfect():
    gt = [Box(0, 0, 100, 100)]
    preds = [Prediction(Box(0, 0, 100, 100), 0.9)]
    dm = detection_metrics(match_predictions(preds, gt))
    assert dm["precision"] == 1.0
    assert dm["recall"] == 1.0
    assert dm["f1"] == 1.0


def test_fp_fn_counting():
    gt = [Box(0, 0, 100, 100),
          Box(500, 500, 600, 600)]
    preds = [Prediction(Box(0, 0, 100, 100), 0.9),
             Prediction(Box(900, 900, 1000, 1000), 0.9)]
    res = match_predictions(preds, gt)
    dm = detection_metrics(res)
    assert dm["tp"] == 1
    assert dm["fp"] == 1   # spurious detection
    assert dm["fn"] == 1   # missed plate
    assert dm["precision"] == 0.5
    assert dm["recall"] == 0.5
