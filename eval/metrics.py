"""Pure evaluation metrics (design Part 6.1).

No torch, no cv2, no DB — importable in the CI lint job. Used by
``eval/run_eval.py`` (Phase 0 smoke) and later by the full harness.
"""
from __future__ import annotations


def normalize_plate(text: str) -> str:
    """Canonical comparison form for evaluation.

    Builds on the runtime canonicalizer (digits → ASCII, separators stripped)
    and adds two evaluation-only normalizations that matter for a human-typed
    ground truth: case folding and Persian-letter → latin-letter mapping
    (inverse of ``plate_validator._LATIN_TO_PERSIAN_LETTER``).
    """
    raw = str(text or "")
    try:
        from watchlist.matching import normalize_for_match
        base = normalize_for_match(raw)
    except Exception:                      # pragma: no cover - import guard
        base = "".join(raw.split()).replace("-", "")
    base = base.lower()
    reverse = {}
    try:
        from plate_validator import _LATIN_TO_PERSIAN_LETTER
        for latin, persian in _LATIN_TO_PERSIAN_LETTER.items():
            reverse.setdefault(persian, latin)
    except Exception:                      # pragma: no cover - import guard
        reverse = {}
    return "".join(reverse.get(ch, ch) for ch in base)


def plate_exact_match(predicted: str, truth: str) -> bool:
    """Plate-level exact match after canonicalization (operator metric)."""
    return normalize_plate(predicted) == normalize_plate(truth) and bool(
        normalize_plate(truth))


def levenshtein(a: str, b: str) -> int:
    """Edit distance (used for CER)."""
    a, b = normalize_plate(a), normalize_plate(b)
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1,
                               current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def character_error_rate(predicted: str, truth: str) -> float:
    """CER = edit distance / reference length (0.0 for a perfect read)."""
    ref = normalize_plate(truth)
    if not ref:
        return 0.0 if not normalize_plate(predicted) else 1.0
    return levenshtein(predicted, truth) / len(ref)


def percentile(values: list, pct: float) -> float:
    """Nearest-rank percentile (mirrors eval/bench_latency.py)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = max(0, min(len(ordered) - 1,
                     int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def summarize_events(events: list) -> dict:
    """Event-level accuracy summary for a replayed visit set (§6.1).

    ``events`` items are mappings with ``plate_number``, ``truth``,
    ``confidence``, ``agreement_ratio`` and optional ``needs_review``.
    """
    if not events:
        return {"n": 0, "exact_match": 0.0, "cer": 0.0,
                "needs_review_rate": 0.0, "avg_confidence": 0.0}
    exact = sum(1 for e in events if plate_exact_match(e["plate_number"],
                                                      e["truth"]))
    cer = sum(character_error_rate(e["plate_number"], e["truth"])
              for e in events) / len(events)
    review = sum(1 for e in events if e.get("needs_review")) / len(events)
    conf = sum(float(e.get("confidence", 0.0)) for e in events) / len(events)
    return {
        "n": len(events),
        "exact_match": round(exact / len(events), 4),
        "cer": round(cer, 4),
        "needs_review_rate": round(review, 4),
        "avg_confidence": round(conf, 4),
    }
