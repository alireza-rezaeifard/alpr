"""Phase 3 results digest — compact tables for the reports."""
from __future__ import annotations

import json
from pathlib import Path

R = Path("benchmarks/results/phase3")


def load(name):
    return json.loads(
        (R / f"phase3_{name}.json").read_text(
            encoding="utf-8"))


print("=========== DATASET ===========")
d = load("dataset_summary")
for k in ("n_cameras", "n_sessions",
          "n_vehicle_instances",
          "n_verified_vehicle_instances",
          "n_annotations", "n_verified_text",
          "n_provisional_or_pending",
          "n_verified_boxes", "n_frames",
          "n_sampled_frames_cam1",
          "n_sampled_frames_cam2", "splits"):
    print(f"  {k}: {d.get(k, 'MISSING')}")
print("  plate_width:", d["plate_width"])

print("\n=========== DETECTOR (counts diagnostic; "
      "metrics NOT_AVAILABLE) ===========")
e = load("detector_evaluation")["evaluation"]
for k, v in e.items():
    if k.startswith("paired"):
        continue
    print(f"  {k}: frames={v['frames_sampled']} "
          f"detected={v['frames_with_detection']} "
          f"precision={v['precision']} "
          f"recall={v['recall']} "
          f"localization={v['localization_available']}")
p = e["paired_AB_verified_trunc"]
print("  paired_AB:", p["table"], "mcnemar:",
      p["mcnemar"])

print("\n=========== OCR verified exact by config "
      "(cam1) ===========")
o = load("ocr_evaluation")["evaluation"]
for key in sorted(o):
    ex = o[key]["overall_cam1_verified"]["exact"]
    inv = o[key]["overall_cam1_verified"]["invalid"]
    fail = o[key]["overall_cam1_verified"]["failed"]
    print(f"  {key}: exact={ex['numerator']}/"
          f"{ex['denominator']} "
          f"invalid={inv['numerator']}/{inv['denominator']} "
          f"failed={fail['numerator']}/{fail['denominator']}")

print("\n=========== TEMPORAL (A|trunc) ===========")
t = load("temporal_consistency")
for vid, v in t.items():
    if not isinstance(v, dict) or "n_frames" not in v:
        continue
    print(f"  {vid} verified={v['verified']}: "
          f"frames={v['n_frames']} "
          f"valid={v['n_valid_reads']} "
          f"unique={v['unique_ocr_outputs']} "
          f"dominant={v['dominant_output']!r} "
          f"ratio={v['dominant_ratio']['value']} "
          f"exact_frames={v['exact_frame_count']} "
          f"best={v['best_frame']}")

print("\n=========== HARD CASES ===========")
h = load("hard_cases")
print("  n:", h["n_hard_cases"])
from collections import Counter
print("  kinds:", dict(Counter(
    c["kind"] for c in h["cases"])))

print("\n=========== PERFORMANCE ===========")
pf = load("performance")
print("  cold_start:", pf.get("cold_start"))
for k in ("detector", "crop_extraction_trunc",
          "ocr", "total_crop_plus_ocr"):
    v = pf[k]
    if isinstance(v, dict) and "p50" in v:
        print(f"  {k}: p50={v['p50']} "
              f"p95={v['p95']} max={v['max']}")
    else:
        for det, s in v.items():
            print(f"  {k}.{det}: p50={s['p50']} "
                  f"p95={s['p95']} max={s['max']}")
print("  env:", {k: pf["environment"][k]
                  for k in ("python", "torch",
                            "ultralytics", "opencv",
                            "cuda_available",
                            "cpu_count", "ram_gb")})

print("\n=========== CROP CELLS (verified exact, "
      "selected) ===========")
cells = json.loads(
    (R / "phase3_crop_cells.json").read_text(
        encoding="utf-8"))["cells"]
for k, v in sorted(cells.items()):
    if "cam1" in k and v["n_verified"]:
        print(f"  {k}: exact={v['exact']}")
