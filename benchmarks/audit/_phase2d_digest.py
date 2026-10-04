"""Phase 2D analysis digest: quantization + expansion summaries."""
from __future__ import annotations

import json
import sys

s = json.load(open("benchmarks/results/phase2d_summary.json",
                   encoding="utf-8"))
qs = s["quantization_summary"]
es = s["expansion_summary"]

print("=== cam1 verified (quantization sweep) ===")
for det in ("detector_a_current", "detector_b_iranplate"):
    for conv in ("trunc", "floor", "round", "ceil"):
        b = qs[f"{det}|{conv}|cam1"]
        e, ca = b["exact"], b["char_accuracy"]
        inv, fail, clip = (b["invalid_rate"], b["failed_rate"],
                           b["clipping_rate"])
        print(f"{det[-1]} {conv:6s} exact={e['numerator']}/{e['denominator']} "
              f"char={ca['value']} invalid={inv['numerator']}/{inv['denominator']} "
              f"failed={fail['numerator']}/{fail['denominator']} "
              f"clip={clip['numerator']}/{clip['denominator']} "
              f"medW={b['median_crop_width']} medH={b['median_crop_height']} "
              f"conf={b['mean_confidence']}")

print("\n=== cam1 verified (expansion sweep) ===")
for det in ("detector_a_current", "detector_b_iranplate"):
    for e in (1.00, 1.01, 1.02, 1.03, 1.05, 1.07, 1.10):
        b = es[f"{det}|{e:.2f}|cam1"]
        ex = b["exact"]
        inv, fail, clip = (b["invalid_rate"], b["failed_rate"],
                           b["clipping_rate"])
        print(f"{det[-1]} {e:.2f}  exact={ex['numerator']}/{ex['denominator']} "
              f"invalid={inv['numerator']}/{inv['denominator']} "
              f"failed={fail['numerator']}/{fail['denominator']} "
              f"clip={clip['numerator']}/{clip['denominator']} "
              f"medW={b['median_crop_width']}")

print("\n=== cam2 diagnostics (UNLABELED, no accuracy) ===")
for det in ("detector_a_current", "detector_b_iranplate"):
    for conv in ("trunc", "floor", "round", "ceil"):
        b = qs[f"{det}|{conv}|cam2"]
        inv, fail, clip = (b["invalid_rate"], b["failed_rate"],
                           b["clipping_rate"])
        print(f"{det[-1]} {conv:6s} n={b['n_crops']} "
              f"invalid={inv['numerator']}/{inv['denominator']} "
              f"failed={fail['numerator']}/{fail['denominator']} "
              f"clip={clip['numerator']}/{clip['denominator']} "
              f"medW={b['median_crop_width']} medH={b['median_crop_height']} "
              f"conf={b['mean_confidence']}")

print("\ncam2 OCR stability (quantization):",
      json.dumps(s["cam2_ocr_stability_quantization"]))
print("cam2 OCR stability (expansion):",
      json.dumps(s["cam2_ocr_stability_expansion"]))

# crop-change analysis: how many crops actually differ trunc vs round
recs = json.load(open("benchmarks/results/phase2d_records.json",
                      encoding="utf-8"))
q = recs["quantization_records"]
for det in ("detector_a_current", "detector_b_iranplate"):
    for cam in ("cam1.mp4", "cam2.mp4"):
        pairs = {}
        for r in q:
            if r["detector"] == det and r["camera"] == cam:
                pairs.setdefault((r["frame"], r["confidence"]), {})[
                    r["convention"]] = r["integer_bbox"]
        changed = 0
        total = 0
        for _, convs in pairs.items():
            if "trunc" in convs and "round" in convs:
                total += 1
                if convs["trunc"] != convs["round"]:
                    changed += 1
        print(f"{det[-1]} {cam}: integer bbox differs trunc vs round "
              f"on {changed}/{total} crops")
