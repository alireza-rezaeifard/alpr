"""Step 11 — real-data production safety analysis.

Measures, on the REAL Phase 2D frames (not synthetic):
  * clipping frequency per detector x convention (cam1 + cam2)
  * expansion margin: how much of an expanded crop lies OUTSIDE
    the original float box (contamination-risk proxy)
  * multi-box frames (duplicate / nearby-vehicle exposure)
  * the candidate strategy's margin at 1.00x (zero by definition)
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "benchmarks")

from run_phase2d import EXPANSIONS  # noqa: E402

RESULTS = Path("benchmarks/results")


def main():
    recs = json.loads((RESULTS / "phase2d_records.json")
                          .read_text(encoding="utf-8"))
    q = recs["quantization_records"]
    e = recs["expansion_records"]

    out = {"generated_for": "Phase 2D Step 11 safety analysis"}

    # ---- clipping frequency (real data) -------------------------
    clip = {}
    for det in ("detector_a_current", "detector_b_iranplate"):
        for conv in ("trunc", "floor", "round", "ceil"):
            for cam in ("cam1.mp4", "cam2.mp4"):
                rows = [r for r in q if r["detector"] == det
                        and r["convention"] == conv
                        and r["camera"] == cam]
                n = len(rows)
                c = sum(1 for r in rows if r["clipping"]["any"])
                clip[f"{det}|{conv}|{cam}"] = {
                    "crops": n, "clipped": c,
                    "rate": round(c / n, 4) if n else None}
    out["clipping_frequency_real_data"] = clip

    # ---- expansion margin (contamination-risk proxy) ------------
    # fraction of expanded-crop AREA that lies outside the original
    # float box. At factor f the linear margin is (f-1)/2 per side,
    # so area fraction = 1 - 1/f^2. Reported per camera so the
    # small-crop regime (cam2, median 83px) is visible.
    margin = {}
    for det in ("detector_a_current", "detector_b_iranplate"):
        for f in EXPANSIONS:
            for cam in ("cam1.mp4", "cam2.mp4"):
                rows = [r for r in e if r["detector"] == det
                        and r["expansion"] == f and r["camera"] == cam]
                widths = [r["crop_width"] for r in rows
                          if r["crop_width"] > 0]
                margin[f"{det}|{f:.2f}|{cam}"] = {
                    "crops": len(rows),
                    "median_width": sorted(widths)[len(widths) // 2]
                        if widths else None,
                    "area_fraction_outside_original_box":
                        round(1.0 - 1.0 / (f * f), 4),
                    "linear_margin_per_side_px_at_median_width":
                        round((f - 1.0) / 2.0 *
                              (sorted(widths)[len(widths) // 2]
                               if widths else 0), 2),
                }
    out["expansion_margin_analysis"] = margin

    # ---- multi-box frames (duplicate / nearby exposure) ---------
    # count ACTUAL boxes per frame: records are stored once per
    # convention, so count per (frame, convention) and take the max
    multi = {}
    for det in ("detector_a_current", "detector_b_iranplate"):
        for cam in ("cam1.mp4", "cam2.mp4"):
            per_frame_conv = {}
            for r in q:
                if r["detector"] == det and r["camera"] == cam:
                    k = (r["frame"], r["convention"])
                    per_frame_conv[k] = per_frame_conv.get(k, 0) + 1
            boxes_per_frame = {}
            for (f, _c), n in per_frame_conv.items():
                boxes_per_frame[f] = n
            multi[f"{det}|{cam}"] = {
                "frames": len(boxes_per_frame),
                "multi_box_frames": sum(1 for v in boxes_per_frame.values()
                                          if v > 1),
                "max_boxes_on_one_frame": max(boxes_per_frame.values())
                    if boxes_per_frame else 0}
    out["multi_box_frames_real_data"] = multi

    # ---- candidate strategy margin -------------------------------
    out["candidate_strategy"] = {
        "convention": "round",
        "expansion": 1.00,
        "added_margin_px": 0,
        "note": "round with no expansion changes WHICH pixel rows "
                "are included (up to 1px per edge) but adds no "
                "margin beyond the detector box; contamination "
                "risk is limited to the 1-px quantization band, "
                "measured per-frame in phase2d_postfix_matrix.json",
    }

    (RESULTS / "phase2d_safety.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
