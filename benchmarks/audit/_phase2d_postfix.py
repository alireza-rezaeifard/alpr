"""Step 9 + Step 5 (contamination proxy) — post-fix benchmark analysis.

Computes, on cam1 verified GT only:
  * Detector effect  — same crop extractor (round): A vs B, paired,
    McNemar exact.
  * Crop effect      — same detector: trunc vs round, per detector.
  * Interaction      — detector x crop: where the 6 discordant pairs
    live and how they resolve.
  * Contamination proxy — for the 6 discordant frames, pixel-level
    diff of trunc vs round crops: which rows/cols change and whether
    the changed pixels are plate-content or vehicle-body/background.
    (Direct visual inspection is unavailable in-session — no image
    input — so this is a documented proxy, not a visual sign-off.)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "benchmarks")

from run_phase2d import (DISCORDANT_FRAMES, DETECTORS,  # noqa: E402
                         build_detectors, load_gt, read_frames)
from benchmarks.phase2d_crop import extract_crop  # noqa: E402

ROOT = Path(".").resolve()
RESULTS = ROOT / "benchmarks" / "results"


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return None, n
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return round(min(1.0, 2 * tail), 6), n


def paired_table(records, conv, cam="cam1.mp4"):
    """Frame-aligned pairing on verified frames, highest-conf box."""
    sel = [r for r in records if r["convention"] == conv
           and r["camera"] == cam and r["gt_status"] == "LABELED"]
    best = {}
    for r in sel:
        k = (r["frame"], r["detector"])
        if r.get("ocr_text") is None:
            best.setdefault(k, {"exact": False})
            continue
        cur = best.get(k)
        if cur is None or (r.get("confidence") or 0) > (cur.get("confidence") or 0):
            best[k] = {"exact": bool(r["exact"]),
                       "confidence": r.get("confidence")}
    frames = sorted({f for f, _ in best})
    table = {"both_correct": 0, "a_correct_b_wrong": 0,
             "a_wrong_b_correct": 0, "both_wrong": 0}
    discordant = []
    for f in frames:
        a = best.get((f, "detector_a_current"), {}).get("exact", False)
        b = best.get((f, "detector_b_iranplate"), {}).get("exact", False)
        if a and b:
            table["both_correct"] += 1
        elif a and not b:
            table["a_correct_b_wrong"] += 1
            discordant.append(f)
        elif not a and b:
            table["a_wrong_b_correct"] += 1
        else:
            table["both_wrong"] += 1
    p, n = mcnemar_exact(table["a_correct_b_wrong"],
                         table["a_wrong_b_correct"])
    return {"table": table, "discordant_pairs": n,
            "mcnemar_exact_p": p, "discordant_frames": discordant,
            "verified_frames": len(frames)}


def per_detector(records, det, conv, cam="cam1.mp4"):
    sel = [r for r in records if r["convention"] == conv
           and r["camera"] == cam and r["detector"] == det
           and r["gt_status"] == "LABELED"
           and r.get("ocr_text") is not None]
    n = len(sel)
    ex = sum(1 for r in sel if r["exact"])
    char = sum(r["char_accuracy"] for r in sel if r["char_accuracy"] is not None)
    return {"n": n, "exact": ex, "exact_rate": round(ex / n, 4) if n else None,
            "char_accuracy": round(char / n, 4) if n else None}


def contamination_proxy():
    """For the 6 discordant frames: which pixel rows differ between the
    trunc crop and the round crop, and what is their content?

    Under trunc the B box (y1=595.72, y2=646.88) yields rows [595, 646);
    under round rows [596, 647). So round DROPS row 595 and ADDS row 646.
    We measure the mean colour of those two rows inside the box x-range
    and classify plate-content vs non-plate by distance to the plate's
    own interior mean (plate backgrounds in this footage are bright).
    """
    gt = load_gt()
    detectors = build_detectors()
    frames = {i: fr for (v, i, fr) in read_frames(5)
              if v == "cam1.mp4" and i in DISCORDANT_FRAMES}
    out = {}
    for f in DISCORDANT_FRAMES:
        frame = frames[f]
        fh, fw = frame.shape[:2]
        boxes = detectors["detector_b_iranplate"](frame)
        if not boxes:
            continue
        bx = max(boxes, key=lambda b: b["confidence"])
        x1f, y1f, x2f, y2f = bx["bbox"]
        r_trunc = extract_crop(frame, bx["bbox"], "trunc", 1.0)
        r_round = extract_crop(frame, bx["bbox"], "round", 1.0)
        xa, xb = r_trunc["integer_bbox"][0], r_trunc["integer_bbox"][2]
        # rows that differ between the two integer boxes
        t_y1, t_y2 = r_trunc["integer_bbox"][1], r_trunc["integer_bbox"][3]
        r_y1, r_y2 = r_round["integer_bbox"][1], r_round["integer_bbox"][3]
        dropped = list(range(t_y1, r_y1)) if r_y1 > t_y1 else []
        added = list(range(t_y2, r_y2)) if r_y2 > t_y2 else []

        def row_stats(row):
            strip = frame[row, max(0, xa):min(fw, xb)]
            if strip.size == 0:
                return None
            return {"mean_bgr": [round(float(v), 1) for v in
                                  strip.mean(axis=0)],
                    "brightness": round(float(strip.mean()), 1)}

        # interior reference rows (middle of the trunc crop)
        mid = t_y1 + (t_y2 - t_y1) // 2
        interior = [row_stats(y) for y in range(mid - 2, mid + 3)]
        interior_b = float(np.mean([s["brightness"] for s in interior
                                    if s]))
        out[str(f)] = {
            "bbox_float": [round(v, 2) for v in bx["bbox"]],
            "trunc_rows": [t_y1, t_y2],
            "round_rows": [r_y1, r_y2],
            "rows_dropped_by_round": dropped,
            "rows_added_by_round": added,
            "dropped_row_stats": [row_stats(y) for y in dropped],
            "added_row_stats": [row_stats(y) for y in added],
            "interior_brightness_reference": round(interior_b, 1),
            "crop_bytes_identical": bool(
                r_trunc["crop"].tobytes() == r_round["crop"].tobytes()),
        }
    return out


def main():
    recs = json.loads((RESULTS / "phase2d_records.json")
                      .read_text(encoding="utf-8"))
    q = recs["quantization_records"]

    out = {"generated_for": "Phase 2D Step 9 post-fix matrix"}

    # ---- detector effect (same extractor: round) --------------------
    out["detector_effect_same_extractor_round"] = paired_table(q, "round")
    out["detector_effect_same_extractor_trunc"] = paired_table(q, "trunc")
    out["detector_effect_same_extractor_floor"] = paired_table(q, "floor")
    out["detector_effect_same_extractor_ceil"] = paired_table(q, "ceil")

    # ---- crop effect (same detector) -------------------------------
    out["crop_effect"] = {}
    for det in DETECTORS:
        out["crop_effect"][det] = {
            "trunc": per_detector(q, det, "trunc"),
            "round": per_detector(q, det, "round"),
            "floor": per_detector(q, det, "floor"),
            "ceil": per_detector(q, det, "ceil"),
        }

    # ---- interaction ------------------------------------------------
    # where the 6 discordant pairs live under trunc, and their fate
    # under round
    trunc_pairs = paired_table(q, "trunc")
    round_pairs = paired_table(q, "round")
    out["interaction"] = {
        "trunc_discordant_frames": trunc_pairs["discordant_frames"],
        "round_discordant_frames": round_pairs["discordant_frames"],
        "resolved_by_round": [f for f in trunc_pairs["discordant_frames"]
                              if f not in round_pairs["discordant_frames"]],
        "created_by_round": [f for f in round_pairs["discordant_frames"]
                             if f not in trunc_pairs["discordant_frames"]],
    }

    # ---- contamination proxy ----------------------------------------
    out["contamination_proxy_discordant_frames"] = contamination_proxy()

    (RESULTS / "phase2d_postfix_matrix.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({
        "detector_effect_round": out["detector_effect_same_extractor_round"],
        "detector_effect_trunc": out["detector_effect_same_extractor_trunc"],
        "crop_effect": out["crop_effect"],
        "interaction": out["interaction"],
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
