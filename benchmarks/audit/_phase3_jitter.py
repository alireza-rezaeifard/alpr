"""Run Detector A on one frozen frame many times
across processes; print UNROUNDED confidences to
detect sub-rounding floating-point jitter."""
from __future__ import annotations

import subprocess
import sys

CODE = """
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'benchmarks')
import cv2
from run_phase3 import build_detectors
detectors = build_detectors()
fn = detectors['detector_a_current']
fr = cv2.imread('benchmarks/audit/_jitter_frame.png')
boxes = fn(fr)
for b in sorted(boxes, key=lambda x: -x['confidence']):
    print(repr(b['confidence']), [repr(v) for v in b['bbox']])
"""


def main():
    import cv2
    cap = cv2.VideoCapture("cam2.mp4")
    idx = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if idx == 200:
            cv2.imwrite(
                "benchmarks/audit/_jitter_frame.png", fr)
            break
        idx += 1
    cap.release()
    seen = []
    for i in range(6):
        proc = subprocess.run(
            [sys.executable, "-c", CODE],
            capture_output=True, text=True,
            cwd="D:\\alpr", timeout=600)
        if proc.returncode != 0:
            print("FAILED:", proc.stderr[-1500:])
            return
        lines = [ln for ln in proc.stdout.strip(
            ).splitlines() if ln and not ln.startswith(
                ("Loading", "ALPR"))]
        seen.append(tuple(lines))
        print(f"run{i}: {lines[0] if lines else '(no boxes)'}")
    uniq = set(seen)
    print(f"\ndistinct outputs: {len(uniq)} / {len(seen)}")
    if len(uniq) > 1:
        print("CONFIRMED: sub-rounding score jitter "
              "across processes on identical bytes.")
    else:
        print("outputs identical at full precision.")


if __name__ == "__main__":
    main()
