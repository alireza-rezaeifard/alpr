"""Two hypotheses for the frame-200 flip:
H1: decode bytes depend on decode history
    (cam1-then-cam2 vs cam2-only).
H2: model output depends on call history
    (warmed-up vs cold single call).

Tests H1 by hashing frame 200 under both
decode patterns in fresh processes.
"""
from __future__ import annotations

import subprocess
import sys

CODE_CAM2_ONLY = """
import sys; sys.path.insert(0, '.')
import cv2, hashlib
cap = cv2.VideoCapture('cam2.mp4')
idx = 0
while True:
    ok, fr = cap.read()
    if not ok: break
    if idx == 200:
        print(hashlib.sha256(fr.tobytes()).hexdigest())
        break
    idx += 1
cap.release()
"""

CODE_CAM1_THEN_CAM2 = """
import sys; sys.path.insert(0, '.')
import cv2, hashlib
cap = cv2.VideoCapture('cam1.mp4')
while True:
    ok, fr = cap.read()
    if not ok: break
cap.release()
cap = cv2.VideoCapture('cam2.mp4')
idx = 0
while True:
    ok, fr = cap.read()
    if not ok: break
    if idx == 200:
        print(hashlib.sha256(fr.tobytes()).hexdigest())
        break
    idx += 1
cap.release()
"""


def run(code):
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        cwd="D:\\alpr", timeout=300)
    return proc.stdout.strip().splitlines()[-1] \
        if proc.returncode == 0 else \
        f"FAILED: {proc.stderr[-500:]}"


def main():
    print("cam2-only pattern:")
    a = [run(CODE_CAM2_ONLY) for _ in range(2)]
    print(" ", a)
    print("cam1-then-cam2 pattern (Phase 3 order):")
    b = [run(CODE_CAM1_THEN_CAM2) for _ in range(2)]
    print(" ", b)
    print("identical across patterns:",
          len(set(a + b)) == 1)


if __name__ == "__main__":
    main()
