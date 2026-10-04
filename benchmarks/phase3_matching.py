"""Phase 3 — deterministic detector/GT matching.

Policy (frozen, task §20):

  1. Score every (prediction, ground-truth) pair by IoU.
  2. Build a TOTAL order over candidate pairs:
       IoU descending, then confidence descending, then
       prediction box (x1, y1, x2, y2) ascending, then
       GT box (x1, y1, x2, y2) ascending.
  3. Greedy one-to-one assignment along that order: a
     prediction can match at most one GT box and a GT box
     can match at most one prediction.
  4. A matched pair is a TP at threshold tau when
     IoU >= tau; unmatched predictions are FP; unmatched
     GT boxes are FN.
  5. No detector can receive multiple TP credit for one
     plate — the one-to-one assignment makes this
     structurally impossible.

Boxes are integer pixel coordinates with inclusive start /
exclusive end, matching the frozen Phase 2D crop semantics.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    """Axis-aligned integer box, [x1, x2) x [y1, y2)."""

    x1: int
    y1: int
    x2: int
    y2: int

    def __post_init__(self) -> None:
        if not (self.x1 <= self.x2 and self.y1 <= self.y2):
            raise ValueError(
                f"inverted box: {self}")
        if self.x1 < 0 or self.y1 < 0:
            raise ValueError(f"negative box: {self}")

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def area(self) -> int:
        return self.width * self.height

    def as_dict(self) -> dict:
        return {"x1": self.x1, "y1": self.y1,
                "x2": self.x2, "y2": self.y2}


def intersection_area(a: Box, b: Box) -> int:
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0
    return (ix2 - ix1) * (iy2 - iy1)


def union_area(a: Box, b: Box) -> int:
    return a.area + b.area - intersection_area(a, b)


def iou(a: Box, b: Box) -> float:
    """Intersection over union. 0.0 for empty boxes."""
    if a.area <= 0 or b.area <= 0:
        return 0.0
    u = union_area(a, b)
    if u <= 0:
        return 0.0
    return intersection_area(a, b) / u


def iou_matrix(preds: list[Box], gts: list[Box]) -> list[list[float]]:
    return [[iou(p, g) for g in gts] for p in preds]


@dataclass(frozen=True)
class Prediction:
    box: Box
    confidence: float = 0.0
    detector: str = ""
    payload: dict | None = None


@dataclass(frozen=True)
class MatchResult:
    prediction_index: int | None
    gt_index: int | None
    iou: float


def match_predictions(
    predictions: list[Prediction],
    ground_truths: list[Box],
    tau: float = 0.5,
) -> dict:
    """Deterministic one-to-one IoU matching.

    Returns:
        matches     list[MatchResult] for TP pairs (iou >= tau)
        fps         list[int] prediction indices unmatched or
                    matched below tau
        fns         list[int] GT indices unmatched
        all_pairs   every (pred, gt, iou) considered, in the
                    deterministic order they were evaluated
    """
    # Candidate pairs above 0 IoU, totally ordered.
    candidates = []
    for pi, p in enumerate(predictions):
        for gi, g in enumerate(ground_truths):
            v = iou(p.box, g)
            if v > 0.0:
                candidates.append(
                    (-v, -float(p.confidence),
                     p.box.x1, p.box.y1, p.box.x2, p.box.y2,
                     g.x1, g.y1, g.x2, g.y2, pi, gi, v))
    # Sort on the total order (negatives give descending
    # IoU / confidence; ties break on box coordinates).
    candidates.sort()

    pred_used = set()
    gt_used = set()
    matches: list[MatchResult] = []
    for cand in candidates:
        pi, gi, v = cand[10], cand[11], cand[12]
        if pi in pred_used or gi in gt_used:
            continue
        pred_used.add(pi)
        gt_used.add(gi)
        matches.append(MatchResult(pi, gi, round(v, 6)))

    tp_pairs = [m for m in matches if m.iou >= tau]
    matched_preds = {m.prediction_index for m in tp_pairs}
    matched_gts = {m.gt_index for m in tp_pairs}
    fps = [pi for pi in range(len(predictions))
           if pi not in matched_preds]
    fns = [gi for gi in range(len(ground_truths))
           if gi not in matched_gts]

    return {
        "matches": tp_pairs,
        "fps": fps,
        "fns": fns,
        "tau": tau,
        "n_predictions": len(predictions),
        "n_ground_truths": len(ground_truths),
        "tp": len(tp_pairs),
        "fp": len(fps),
        "fn": len(fns),
    }


def detection_metrics(result: dict) -> dict:
    """Precision / recall / F1 from a match result.

    All values are None (NOT_AVAILABLE) when there are no
    predictions AND no ground truth — an empty frame is not
    a 0/0 score.
    """
    tp, fp, fn = result["tp"], result["fp"], result["fn"]
    denom_p, denom_r = tp + fp, tp + fn
    precision = (tp / denom_p) if denom_p else None
    recall = (tp / denom_r) if denom_r else None
    if precision is not None and recall is not None \
            and precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = None
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 4)
            if precision is not None else None,
        "recall": round(recall, 4)
            if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
    }
