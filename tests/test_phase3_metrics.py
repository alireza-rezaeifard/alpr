"""Phase 3 tests — OCR metrics, temporal
consistency, and statistics (task §18/§24/§28/§37)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmarks.phase3_metrics import (  # noqa: E402
    aggregate_detection, aggregate_ocr,
    group_by, mcnemar_exact, ratio,
    score_ocr_record, temporal_consistency,
    wilson_ci)


def test_score_exact_match():
    r = score_ocr_record("۱۲د۶۷۴۱۳", 0.9, "12D67413")
    assert r["exact"] is True
    assert r["char_accuracy"] == 1.0
    assert r["edit_distance"] == 0


def test_score_cross_charset_match():
    """Production DTRB output scores against Persian GT."""
    r = score_ocr_record("12d67413", 0.9, "12D67413")
    assert r["exact"] is True


def test_score_wrong_read():
    r = score_ocr_record("12d674913", 0.9, "12D67413")
    assert r["exact"] is False
    assert r["edit_distance"] == 1  # one inserted digit
    assert r["char_accuracy"] < 1.0


def test_failed_means_empty_output():
    r = score_ocr_record("", 0.0, "12D67413")
    assert r["failed"] is True
    assert r["exact"] is False


def test_invalid_means_grammar_violation():
    r = score_ocr_record("999999696", 0.5, "12D67413")
    assert r["ocr_valid"] is False


def test_concepts_stay_distinct():
    """exact / invalid / failed are three separate
    concepts; a wrong-but-plausible read is exact=False,
    invalid=? (validator decides), failed=False."""
    r = score_ocr_record("12d67414", 0.9, "12D67413")
    assert r["exact"] is False
    assert r["failed"] is False  # non-empty output


def test_aggregate_ocr_counts():
    scored = [
        score_ocr_record("۱۲د۶۷۴۱۳", 0.9, "12D67413"),
        score_ocr_record("12d674913", 0.8, "12D67413"),
        score_ocr_record("", 0.0, "12D67413"),
    ]
    agg = aggregate_ocr(scored, label="test")
    assert agg["n_verified"] == 3
    assert agg["exact"] == {"numerator": 1,
                            "denominator": 3,
                            "value": 0.3333}
    assert agg["failed"] == {"numerator": 1,
                             "denominator": 3,
                             "value": 0.3333}
    assert "exact_wilson95" in agg


def test_aggregate_ocr_unlabeled_excluded_from_accuracy():
    scored = [
        score_ocr_record("99919959", 0.8, None),
        score_ocr_record("", 0.0, None),
    ]
    agg = aggregate_ocr(scored)
    assert agg["n_verified"] == 0
    assert agg["exact"]["value"] is None
    # validity still measured over attempted reads
    assert agg["invalid"]["denominator"] == 1


def test_group_by():
    recs = [{"cam": "a"}, {"cam": "a"}, {"cam": "b"}]
    g = group_by(recs, lambda r: r["cam"])
    assert len(g["a"]) == 2
    assert len(g["b"]) == 1


def test_temporal_consistency():
    scored = [
        {"frame_id": 180, "ocr_text": "۱۲د۶۷۴۱۳",
         "ocr_normalized": "۱۲د۶۷۴۱۳",
         "ocr_valid": True, "failed": False,
         "exact": True, "confidence": 0.9},
        {"frame_id": 185, "ocr_text": "12d674913",
         "ocr_normalized": "۱۲D۶۷۴۹۱۳",
         "ocr_valid": False, "failed": False,
         "exact": False, "confidence": 0.7},
        {"frame_id": 190, "ocr_text": "۱۲د۶۷۴۱۳",
         "ocr_normalized": "۱۲د۶۷۴۱۳",
         "ocr_valid": True, "failed": False,
         "exact": True, "confidence": 0.95},
        {"frame_id": 195, "ocr_text": "",
         "ocr_normalized": "",
         "ocr_valid": False, "failed": True,
         "exact": False, "confidence": 0.0},
    ]
    tc = temporal_consistency(scored)
    assert tc["n_frames"] == 4
    assert tc["n_valid_reads"] == 2
    assert tc["unique_ocr_outputs"] == 2
    assert tc["dominant_output"] == "۱۲د۶۷۴۱۳"
    assert tc["dominant_ratio"] == {"numerator": 2,
                                   "denominator": 3,
                                   "value": 0.6667}
    assert tc["exact_frame_count"] == 2
    assert tc["best_frame"] == 190


def test_mcnemar_no_discordant():
    m = mcnemar_exact(0, 0)
    assert m["p"] is None
    assert m["discordant_pairs"] == 0


def test_mcnemar_six_pairs():
    m = mcnemar_exact(6, 0)
    assert m["p"] == 0.03125
    assert m["discordant_pairs"] == 6


def test_wilson_ci_bounds():
    ci = wilson_ci(62, 62)
    assert ci is not None
    assert ci["lower"] <= 1.0 <= ci["upper"]
    ci0 = wilson_ci(0, 0)
    assert ci0 is None


def test_detection_aggregation_flags_unavailable():
    agg = aggregate_detection(None, label="cam1|A")
    assert agg["localization_available"] is False
    assert agg["tp"] is None
    assert agg["fp"] is None
    assert agg["fn"] is None
    assert agg["precision"] is None
    assert agg["recall"] is None
    assert agg["note"]


def test_detection_aggregation_available_computes():
    res = {"tp": 1, "fp": 1, "fn": 1}
    agg = aggregate_detection(res, label="synth",
                              box_gt_available=True)
    assert agg["localization_available"] is True
    assert agg["precision"] == 0.5
    assert agg["recall"] == 0.5


def test_ratio_zero_denominator():
    assert ratio(0, 0) == {"numerator": 0,
                           "denominator": 0, "value": None}
