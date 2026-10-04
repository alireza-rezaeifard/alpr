"""Step 7 — cam2 ground-truth extraction for MANUAL visual verification.

Extracts the 22 original Phase-2B cam2 sample crops (native resolution),
plus 4x-upscaled zooms and full-frame context sheets, so a human (or a
vision-capable reviewer) can attempt to read the plates WITHOUT using any
OCR output as ground truth.

Writes:
  benchmarks/audit/cam2_gt/<id>_crop.png      native crop
  benchmarks/audit/cam2_gt/<id>_zoom4x.png    4x nearest-neighbor zoom
  benchmarks/audit/cam2_gt/<id>_context.png   full frame, box drawn
  benchmarks/audit/cam2_gt/manifest.json      frame/box metadata (no OCR)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "benchmarks")

from run_phase2d import CAM2_PHASE2B_SAMPLES, build_detectors  # noqa: E402

OUT = Path("benchmarks/audit/cam2_gt")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    detectors = build_detectors()
    cap = cv2.VideoCapture("cam2.mp4")
    frames = {}
    idx = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if idx in CAM2_PHASE2B_SAMPLES:
            frames[idx] = fr.copy()
        idx += 1
    cap.release()
    print("decoded cam2 sample frames:", len(frames))

    manifest = []
    for f in CAM2_PHASE2B_SAMPLES:
        frame = frames.get(f)
        if frame is None:
            continue
        fh, fw = frame.shape[:2]
        boxes = detectors["detector_a_current"](frame)
        if not boxes:
            manifest.append({"sample_id": f"cam2_f{f:05d}", "frame": f,
                             "detected": False})
            continue
        bx = max(boxes, key=lambda b: b["confidence"])
        x1f, y1f, x2f, y2f = bx["bbox"]
        x1, y1, x2, y2 = int(x1f), int(y1f), int(x2f), int(y2f)
        x1c, y1c = max(0, x1), max(0, y1)
        x2c, y2c = min(fw, x2), min(fh, y2)
        crop = frame[y1c:y2c, x1c:x2c]
        if crop.size == 0:
            manifest.append({"sample_id": f"cam2_f{f:05d}", "frame": f,
                             "detected": True, "empty_crop": True,
                             "bbox": [x1f, y1f, x2f, y2f]})
            continue
        # 4x nearest-neighbor zoom (no interpolation blur)
        zoom = cv2.resize(crop, None, fx=4, fy=4,
                          interpolation=cv2.INTER_NEAREST)
        # context frame with the box drawn
        ctx = frame.copy()
        cv2.rectangle(ctx, (x1c, y1c), (x2c, y2c), (0, 255, 0), 2)
        sid = f"cam2_f{f:05d}"
        cv2.imwrite(str(OUT / f"{sid}_crop.png"), crop)
        cv2.imwrite(str(OUT / f"{sid}_zoom4x.png"), zoom)
        cv2.imwrite(str(OUT / f"{sid}_context.png"), ctx)
        manifest.append({
            "sample_id": sid, "frame": f, "detected": True,
            "bbox_float": [round(x1f, 2), round(y1f, 2),
                           round(x2f, 2), round(y2f, 2)],
            "integer_bbox": [x1c, y1c, x2c, y2c],
            "crop_width": x2c - x1c, "crop_height": y2c - y1c,
            "confidence": round(bx["confidence"], 4),
            "clipped": bool(x1 < 0 or y1 < 0 or x2 > fw or y2 > fh),
        })
        print(f"  {sid}: bbox=({x1f:.1f},{y1f:.1f},{x2f:.1f},{y2f:.1f}) "
              f"crop={x2c - x1c}x{y2c - y1c} conf={bx['confidence']:.3f}")
    (OUT / "manifest.json").write_text(
        json.dumps({"generated_for": "manual visual verification only",
                    "samples": manifest}, indent=1), encoding="utf-8")
    print("manifest written:", OUT / "manifest.json")


if __name__ == "__main__":
    main()
