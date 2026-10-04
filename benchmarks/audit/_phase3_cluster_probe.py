"""Cluster cam2 detections into provisional vehicle instances
(spatiotemporal grouping — PROVISIONAL pending human verification).

Also summarizes cam1 verified-frame coverage per plate instance.
"""
from __future__ import annotations

import json

recs = json.load(open("benchmarks/results/phase2d_records.json",
                          encoding="utf-8"))
q = recs["quantization_records"]

# --- cam2 clusters (detector A, trunc convention) -------------------
a = [r for r in q if r["camera"] == "cam2.mp4"
     and r["detector"] == "detector_a_current"
     and r["convention"] == "trunc"]
a.sort(key=lambda r: r["frame"])
print("cam2 A detections:", len(a))
clusters = []
for r in a:
    x1, y1, x2, y2 = r["integer_bbox"]
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    placed = False
    for c in clusters:
        # same vehicle if within 120 px of cluster centre AND
        # within 25 frames of the cluster's frame range
        if (abs(cx - c["cx"]) < 120 and abs(cy - c["cy"]) < 120
                and c["fmin"] - 25 <= r["frame"] <= c["fmax"] + 25):
            c["frames"].append(r["frame"])
            c["cx"] = (c["cx"] * (len(c["frames"]) - 1) + cx) / len(
                c["frames"])
            c["cy"] = (c["cy"] * (len(c["frames"]) - 1) + cy) / len(
                c["frames"])
            c["fmin"] = min(c["fmin"], r["frame"])
            c["fmax"] = max(c["fmax"], r["frame"])
            c["widths"].append(r["crop_width"])
            placed = True
            break
    if not placed:
        clusters.append({"cx": cx, "cy": cy, "fmin": r["frame"],
                         "fmax": r["frame"], "frames": [r["frame"]],
                         "widths": [r["crop_width"]]})
for i, c in enumerate(sorted(clusters, key=lambda c: c["fmin"]), 1):
    print(f"  cam2 cluster {i}: frames {c['fmin']}-{c['fmax']} "
          f"({len(c['frames'])} detections) centre=({c['cx']:.0f},"
          f"{c['cy']:.0f}) medianW="
          f"{sorted(c['widths'])[len(c['widths'])//2]}")

# --- cam1 verified coverage per plate instance ------------------------
gt = json.load(open("benchmarks/dataset/gt_labels.json",
                        encoding="utf-8"))
for name, lab in gt["labels"].items():
    if lab.get("verified"):
        ranges = lab["applies_to"]["frame_ranges"]
        n = sum(hi - lo + 1 for lo, hi in ranges)
        print(f"cam1 verified instance {name}: {lab['plate_text']} "
              f"({lab['plate_text_ascii']}) ranges={ranges} "
              f"({n} frames)")

# cam1 sampled frames at interval 5 inside each verified range
cam1_frames = [r["frame"] for r in q if r["camera"] == "cam1.mp4"
               and r["detector"] == "detector_a_current"
               and r["convention"] == "trunc"
               and r["detection_status"] == "DETECTED"]
for name, lab in gt["labels"].items():
    if not lab.get("verified"):
        continue
    inside = set()
    for lo, hi in lab["applies_to"]["frame_ranges"]:
        inside |= {f for f in range(lo, hi + 1) if f % 5 == 0}
    detected = [f for f in cam1_frames if f in inside]
    print(f"  {name}: sampled-in-range={len(inside)} "
          f"detected={len(detected)}")
