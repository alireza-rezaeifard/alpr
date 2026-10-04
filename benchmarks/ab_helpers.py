"""Phase 2B helpers — crop geometry, clipping, buckets, pairwise matching.

Pure functions only (unit-testable, no model imports). Nothing here touches
production code paths.
"""
from __future__ import annotations

# Crop-width buckets (task §8)
BUCKETS = [
    (0, 80, "lt80"),
    (80, 100, "80-99"),
    (100, 150, "100-149"),
    (150, 200, "150-199"),
    (200, 10 ** 9, "ge200"),
]

# Pairwise outcome classes (task §12)
CURRENT_BETTER = "CURRENT_BETTER"
IRANPLATE_BETTER = "IRANPLATE_BETTER"
BOTH_CORRECT = "BOTH_CORRECT"
BOTH_WRONG = "BOTH_WRONG"
CURRENT_ONLY_VALID = "CURRENT_ONLY_VALID"
IRANPLATE_ONLY_VALID = "IRANPLATE_ONLY_VALID"
NEITHER_VALID = "NEITHER_VALID"
INCOMPARABLE = "INCOMPARABLE"


def bucket_for(width: int) -> str:
    for lo, hi, name in BUCKETS:
        if lo <= width < hi:
            return name
    return "unknown"


def geometry(box) -> dict:
    """Box -> width/height/area/aspect_ratio (boxes are x1,y1,x2,y2 px)."""
    x1, y1, x2, y2 = [float(v) for v in box[:4]]
    w = max(0.0, x2 - x1)
    h = max(0.0, y2 - y1)
    return {
        "width": w,
        "height": h,
        "area": w * h,
        "aspect_ratio": round(w / h, 3) if h > 0 else None,
    }


def clipping_flags(box, frame_w: int, frame_h: int, edge_px: int = 2) -> dict:
    """Which frame borders does this box touch?

    A box touching the frame boundary is flagged because the plate may extend
    beyond the frame (and therefore beyond any crop taken from it).
    """
    x1, y1, x2, y2 = [float(v) for v in box[:4]]
    left = x1 <= edge_px
    right = x2 >= frame_w - edge_px
    top = y1 <= edge_px
    bottom = y2 >= frame_h - edge_px
    return {
        "clipped_left": left,
        "clipped_right": right,
        "clipped_top": top,
        "clipped_bottom": bottom,
        "clipped_any": bool(left or right or top or bottom),
    }


def box_iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = [float(v) for v in a[:4]]
    bx1, by1, bx2, by2 = [float(v) for v in b[:4]]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def pair_boxes(cur_boxes, ipv_boxes, iou_thresh: float = 0.1):
    """Greedy highest-IoU matching between the two detectors' boxes.

    Returns (pairs, cur_only, ipv_only) where pairs are (cur, ipv, iou)
    tuples. Unmatched boxes are reported separately and are NEVER used to
    infer superiority (task §12).
    """
    pairs = []
    remaining_ipv = list(range(len(ipv_boxes)))
    for i, cb in enumerate(cur_boxes):
        best_j, best_iou = None, 0.0
        for j in remaining_ipv:
            v = box_iou(cb, ipv_boxes[j])
            if v > best_iou:
                best_iou, best_j = v, j
        if best_j is not None and best_iou >= iou_thresh:
            pairs.append((cb, ipv_boxes[best_j], round(best_iou, 3)))
            remaining_ipv.remove(best_j)
    matched_cur = {id(p[0]) for p in pairs}
    cur_only = [b for b in cur_boxes if id(b) not in matched_cur]
    ipv_only = [ipv_boxes[j] for j in remaining_ipv]
    return pairs, cur_only, ipv_only


def classify_pair(gt_available: bool, cur_exact, ipv_exact,
                  cur_valid: bool, ipv_valid: bool) -> str:
    """Classify one matched pair.

    With verified GT: correctness decides (CURRENT_BETTER / IRANPLATE_BETTER /
    BOTH_CORRECT / BOTH_WRONG). Without GT (cam2): only validity is known, so
    the *_ONLY_VALID / NEITHER_VALID classes are used — never a superiority
    claim.
    """
    if gt_available and cur_exact is not None and ipv_exact is not None:
        if cur_exact and ipv_exact:
            return BOTH_CORRECT
        if cur_exact and not ipv_exact:
            return CURRENT_BETTER
        if ipv_exact and not cur_exact:
            return IRANPLATE_BETTER
        return BOTH_WRONG
    if cur_valid and ipv_valid:
        return BOTH_CORRECT if gt_available else INCOMPARABLE
    if cur_valid:
        return CURRENT_ONLY_VALID
    if ipv_valid:
        return IRANPLATE_ONLY_VALID
    return NEITHER_VALID


def percentile(values, p: float):
    """Simple nearest-rank percentile (no numpy dependency needed by callers)."""
    if not values:
        return None
    vs = sorted(values)
    idx = min(len(vs) - 1, max(0, int(round((p / 100.0) * (len(vs) - 1)))))
    return vs[idx]
