"""Phase 2C — extract cam2 plate candidates as inspectable PNGs.

Selects by SHARPNESS ONLY (never by OCR output, per task §17) and writes an
enlarged horizontal band for each candidate so a human can read the plate.
"""
from __future__ import annotations

import cv2
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "benchmarks" / "audit" / "cam2_frames"
VID = "cam2.mp4"
RANGES = [(200, 220), (295, 360), (480, 520), (525, 560)]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(ROOT / VID))
    rows = []
    for lo, hi in RANGES:
        for idx in range(lo, hi + 1, 3):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, fr = cap.read()
            if not ok:
                continue
            h, w = fr.shape[:2]
            y1, y2 = int(h * 0.35), int(h * 0.80)
            band = fr[y1:y2, :, :]
            gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
            rows.append((idx, band, gray))
    cap.release()
    # sharpness only
    rows.sort(key=lambda r: -cv2.Laplacian(r[2], cv2.CV_64F).var())
    keep = sorted(rows[:15])
    for idx, band, gray in keep:
        up = cv2.resize(band, (1200, int(1200 * band.shape[0] / band.shape[1])),
                        interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(str(OUT / f"cam2_f{idx:04d}.png"), up)
    print(f"wrote {len(keep)}", [i for i, _, _ in keep])


if __name__ == "__main__":
    main()