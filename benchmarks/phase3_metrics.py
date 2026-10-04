"""Phase 3 — evaluation metrics.

Everything is reported as raw numerator/denominator with
explicit scope keys; nothing hides its base rate.

OCR metrics (task §18) — kept distinct:
  exact          normalized strings equal
  char_accuracy  1 - Levenshtein/max_len (canonical form)
  edit_distance  raw Levenshtein
  invalid        output violates Iranian plate grammar
                 (production validator, unchanged)
  failed         empty OCR output

Temporal consistency (task §24) is computed per physical
vehicle instance.

Statistical helpers: Wilson score intervals for
proportions, exact McNemar for paired binary outcomes.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter

from benchmarks.phase3_matching import detection_metrics
from benchmarks.phase3_normalization import (  # noqa: E402
    normalize_to_ascii)
from benchmarks.normalization import edit_distance  # noqa: E402
from metrics import is_valid_iranian  # noqa: E402


def pct(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (same convention as the
    Phase 2/2D benchmarks)."""
    if not values:
        return None
    v = sorted(values)
    k = min(len(v) - 1,
            max(0, math.ceil(p / 100.0 * len(v)) - 1))
    return round(float(v[k]), 4)


def ratio(num: int, den: int) -> dict:
    return {"numerator": num, "denominator": den,
            "value": round(num / den, 4) if den else None}


def wilson_ci(num: int, den: int,
              z: float = 1.96) -> dict | None:
    """Wilson score interval for a proportion."""
    if den == 0:
        return None
    p = num / den
    d = 1 + z * z / den
    centre = (p + z * z / (2 * den)) / d
    half = (z * math.sqrt(
        p * (1 - p) / den + z * z / (4 * den * den))) / d
    return {
        "centre": round(centre, 4),
        "lower": round(max(0.0, centre - half), 4),
        "upper": round(min(1.0, centre + half), 4),
        "level": 0.95,
    }


def mcnemar_exact(b: int, c: int) -> dict:
    """Exact two-sided McNemar (binomial) p-value for
    discordant pairs b (A correct, B wrong) and
    c (A wrong, B correct)."""
    n = b + c
    if n == 0:
        return {"discordant_pairs": 0, "p": None,
                "note": "no discordant pairs; no test "
                        "to perform"}
    k = min(b, c)
    tail = sum(math.comb(n, i)
               for i in range(0, k + 1)) / (2 ** n)
    return {"discordant_pairs": n,
            "p": round(min(1.0, 2 * tail), 6)}


# ------------------------------------------------------------------- OCR
def score_ocr_record(ocr_text: str | None,
                     confidence: float | None,
                     ground_truth_ascii: str | None
                     ) -> dict:
    """Score ONE OCR output against ONE verified
    reference (canonical ascii forms)."""
    pred = normalize_to_ascii(ocr_text)
    ref = normalize_to_ascii(ground_truth_ascii) \
        if ground_truth_ascii else ""
    valid = bool(ocr_text) and is_valid_iranian(
        ocr_text, confidence or 0.9)
    rec = {
        "pred_ascii": pred,
        "ref_ascii": ref,
        "exact": bool(ref) and pred == ref,
        "char_accuracy": None,
        "edit_distance": None,
        "ocr_valid": valid,
        "failed": not bool((ocr_text or "").strip()),
    }
    if ref:
        ed = edit_distance(pred, ref)
        rec["edit_distance"] = ed
        rec["char_accuracy"] = round(
            max(0.0, 1.0 - ed / max(len(pred), len(ref))),
            4)
    return rec


def aggregate_ocr(scored: list[dict],
                  label: str = "") -> dict:
    """Aggregate scored OCR records. Only records with a
    verified reference (ref_ascii non-empty) enter
    accuracy metrics; invalid/failed are computed over
    all records with an OCR attempt."""
    verified = [s for s in scored if s["ref_ascii"]]
    attempted = [s for s in scored if not s["failed"]]
    out = {
        "label": label,
        "n_scored": len(scored),
        "n_verified": len(verified),
        "n_ocr_attempts": len(attempted),
        "exact": ratio(sum(1 for s in verified if s["exact"]),
                       len(verified)),
        "char_accuracy": ratio(
            round(sum(s["char_accuracy"]
                      for s in verified
                      if s["char_accuracy"] is not None), 6),
            len(verified)),
        "mean_edit_distance": ratio(
            round(sum(s["edit_distance"]
                      for s in verified
                      if s["edit_distance"] is not None), 6),
            len(verified)),
        "invalid": ratio(
            sum(1 for s in attempted if not s["ocr_valid"]),
            len(attempted)),
        "failed": ratio(
            sum(1 for s in scored if s["failed"]),
            len(scored)),
    }
    if verified:
        out["exact_wilson95"] = wilson_ci(
            out["exact"]["numerator"],
            out["exact"]["denominator"])
    return out


def group_by(records: list[dict],
             key_fn) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in records:
        out.setdefault(str(key_fn(r)), []).append(r)
    return out


# ------------------------------------------------------- detection metrics
def aggregate_detection(match_result: dict | None,
                        label: str = "",
                        box_gt_available: bool = False) -> dict:
    """Detection/localization aggregation.

    When the dataset carries no box GT (`box_gt_available`
    False, or `match_result` None), EVERYTHING is None
    (NOT_AVAILABLE) — precision/recall/F1/IoU are never
    approximated by detection counts."""
    unavailable = {
        "label": label,
        "localization_available": False,
        "tp": None, "fp": None, "fn": None,
        "precision": None, "recall": None, "f1": None,
        "note": "plate-box GT is pending human annotation; "
                "precision/recall/F1/IoU are NOT_AVAILABLE. "
                "Detection counts are diagnostic only and "
                "must never be read as recall.",
    }
    if not box_gt_available or match_result is None:
        return unavailable
    dm = detection_metrics(match_result)
    return {
        "label": label,
        "localization_available": True,
        "tp": dm["tp"], "fp": dm["fp"], "fn": dm["fn"],
        "precision": dm["precision"],
        "recall": dm["recall"],
        "f1": dm["f1"],
        "note": "matched at reported tau; see matching "
                "artifact for IoU distribution.",
    }


# ---------------------------------------------------- temporal consistency
def temporal_consistency(
    scored: list[dict]) -> dict:
    """Per vehicle-instance temporal summary (task §24).

    `scored` must be the instance's frame observations,
    each with keys: frame_id, ocr_text, ocr_normalized,
    ocr_valid, failed, exact (bool|None), confidence.
    """
    n_frames = len(scored)
    attempted = [s for s in scored if not s["failed"]]
    valid = [s for s in attempted if s["ocr_valid"]]
    texts = [s["ocr_text"] or "" for s in attempted]
    counter = Counter(texts)
    if counter:
        dominant, dom_count = counter.most_common(1)[0]
    else:
        dominant, dom_count = None, 0
    exact_frames = [s["frame_id"] for s in scored
                    if s.get("exact")]
    verified = [s for s in scored
                if s.get("exact") is not None]
    best = None
    for s in scored:
        if s.get("exact") and (best is None
                                or (s.get("confidence")
                                    or 0) > (best.get(
                                        "confidence") or 0)):
            best = s
    return {
        "n_frames": n_frames,
        "n_valid_reads": len(valid),
        "valid_read_ratio": ratio(len(valid), n_frames),
        "unique_ocr_outputs": len(counter),
        "dominant_output": dominant,
        "dominant_ratio": ratio(dom_count, len(attempted))
            if attempted else ratio(0, 0),
        "exact_frame_count": len(exact_frames),
        "exact_frame_ids": sorted(exact_frames),
        "best_frame": (best or {}).get("frame_id"),
        "verified_frames": len(verified),
    }


# -------------------------------------------------------------- summaries
def median_or_none(values: list) -> float | None:
    if not values:
        return None
    return round(statistics.fmean(values), 4)
