"""Compare processed_cam2.mp4 against known-raw cam2 crops to decide whether
the processed file is usable as a cam2 source after the raw file vanished.

Ground truth for "raw" comes from benchmarks/dataset/crops/cam2_*.png, which
were cut from the RAW cam2 during an earlier phase.
"""
import cv2
import numpy as np
from pathlib import Path

ROOT = Path(r"D:\alpr")
CROPS = ROOT / "benchmarks" / "dataset" / "crops"
PROC = ROOT / "io" / "output" / "processed_cam2.mp4"

crops = sorted(CROPS.glob("cam2_*.png"))
print("raw cam2 crops available:", len(crops))
for c in crops[:5]:
    print("   ", c.name)

cap = cv2.VideoCapture(str(PROC))
print("processed_cam2 open:", cap.isOpened(),
      "frames:", int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))

# pull a few frames from the processed video and measure ink coverage
for idx in (210, 320, 500, 540):
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, fr = cap.read()
    if not ok:
        print(idx, "read fail")
        continue
    gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
    # overlay text is usually pure white: count near-255 pixels
    white = float((gray > 250).mean())
    print(f"  frame {idx}: shape={fr.shape} near-white fraction={white:.5f}")
cap.release()
