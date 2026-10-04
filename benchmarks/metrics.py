"""OCR scoring metrics (task §11) with a single canonical comparison form.

canonical(text) maps any model's output into one comparable charset:
  * normalize_plate_text() (digits->ASCII, yeh/kaf folding, separators removed)
  * then documented Persian-letter -> production-ASCII transliteration
    (FA_TO_ASCII) so Persian-output models (hezar) and romanized-output models
    (production DTRB, yolo11, plr_crnn) compare on equal terms.

Accuracy is ONLY computed over samples whose ground truth has verified=true.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT))

from normalization import (FA_TO_ASCII, edit_distance,  # noqa: E402
                           normalize_plate_text,
                           normalized_edit_distance)

WIDTH_BUCKETS = [(0, 100, "lt100"), (100, 150, "100-150"),
                 (150, 10_000, "ge150")]


def canonical(text: str | None) -> str:
    """Canonical comparison form (ASCII digits + ASCII letters)."""
    s = normalize_plate_text(text)
    out = []
    for ch in s:
        if ch.isascii():
            out.append(ch)
        else:
            out.append(FA_TO_ASCII.get(ch, ch))
    return "".join(out)


def char_accuracy(pred: str, ref: str) -> float:
    """1 - levenshtein/max_len over canonical strings (1.0 = perfect)."""
    if not ref:
        return 0.0
    return max(0.0, 1.0 - edit_distance(pred, ref) / max(len(pred), len(ref)))


def width_bucket(width: int) -> str:
    for lo, hi, name in WIDTH_BUCKETS:
        if lo <= width < hi:
            return name
    return "unknown"


def score_pair(pred_raw: str | None, ref_text: str) -> dict:
    """Score one prediction against one verified reference."""
    pred = canonical(pred_raw)
    ref = canonical(ref_text)
    return {
        "pred_canonical": pred,
        "ref_canonical": ref,
        "exact": bool(ref) and pred == ref,
        "char_accuracy": round(char_accuracy(pred, ref), 4),
        "edit_distance": edit_distance(pred, ref),
        "edit_distance_norm": round(normalized_edit_distance(pred, ref), 4),
        "failed": not pred,
    }


def is_valid_iranian(raw_text: str, conf: float = 0.9) -> bool:
    """Format validity via the UNCHANGED production validator."""
    if not raw_text:
        return False
    try:
        from plate_validator import validate_iranian_plate
        return bool(validate_iranian_plate(raw_text, conf).is_valid)
    except Exception:
        return False


def aggregate(records: list[dict], group_key=None) -> dict:
    """Aggregate scored records.

    Each record must carry: exact (bool|None), char_accuracy, edit_distance,
    failed (bool), invalid (bool), and optionally width/video/group.
    Only records with exact is not None (verified GT) enter accuracy metrics.
    """
    groups: dict[str, list[dict]] = {}
    for r in records:
        key = group_key(r) if group_key else "all"
        groups.setdefault(key, []).append(r)

    out = {}
    for key, recs in groups.items():
        verified = [r for r in recs if r.get("exact") is not None]
        n = len(recs)
        out[key] = {
            "n_samples": n,
            "n_verified": len(verified),
            "n_exact": sum(1 for r in verified if r["exact"]),
            "n_incorrect": sum(1 for r in verified if not r["exact"]),
            "exact_accuracy": round(
                sum(1 for r in verified if r["exact"]) / len(verified), 4)
            if verified else None,
            "char_accuracy": round(
                sum(r["char_accuracy"] for r in verified) / len(verified), 4)
            if verified else None,
            "mean_edit_distance": round(
                sum(r["edit_distance"] for r in verified) / len(verified), 4)
            if verified else None,
            "invalid_rate": round(
                sum(1 for r in recs if r.get("invalid")) / n, 4) if n else None,
            "failed_rate": round(
                sum(1 for r in recs if r.get("failed")) / n, 4) if n else None,
            "n_invalid": sum(1 for r in recs if r.get("invalid")),
            "n_failed": sum(1 for r in recs if r.get("failed")),
        }
    return out
