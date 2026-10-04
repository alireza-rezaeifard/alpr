"""Diff cam2 Detector-A detections between the Phase 2D
run and the current Phase 3 run: which frames flipped,
and how close their confidences are to the 0.50 cut."""
from __future__ import annotations

import json

old = json.load(open(
    "benchmarks/results/phase2d_records.json",
    encoding="utf-8"))["quantization_records"]
new = json.load(open(
    "benchmarks/dataset/phase3/manifest.json",
    encoding="utf-8"))

old_frames = {}
for r in old:
    if r["camera"] == "cam2.mp4" \
            and r["detector"] == "detector_a_current" \
            and r["convention"] == "trunc":
        old_frames[r["frame"]] = r["confidence"]

anns = [json.loads(line) for line in open(
    "benchmarks/dataset/phase3/gt/plates.jsonl",
    encoding="utf-8").read().splitlines()]
new_frames = {}
for a in anns:
    if a["camera_id"] == "cam2":
        m = a["measurements"].get("detector_a_current")
        if m:
            new_frames.setdefault(a["frame_id"], []).append(
                m["confidence"])

print(f"old run A-detected cam2 frames: {len(old_frames)}")
print(f"new run A-detected cam2 frames: {len(new_frames)}")
only_old = sorted(set(old_frames) - set(new_frames))
only_new = sorted(set(new_frames) - set(old_frames))
print(f"only in old ({len(only_old)}): {only_old}")
for f in only_old:
    print(f"   frame {f}: old conf={old_frames[f]}")
print(f"only in new ({len(only_new)}): {only_new}")
# new run confidences for the flipped frames come from
# the fresh phase3 results; load them
res3 = json.load(open(
    "benchmarks/results/phase3/phase3_ocr_evaluation.json",
    encoding="utf-8"))
