"""Decode cam2 frame 200 in N separate processes;
compare raw bytes. Determines whether the run-to-run
detection flips come from video-decode jitter."""
from __future__ import annotations

import hashlib
import subprocess
import sys

CODE = """
import sys
sys.path.insert(0, '.')
import cv2, hashlib
cap = cv2.VideoCapture('cam2.mp4')
idx = 0
while True:
    ok, fr = cap.read()
    if not ok:
        break
    if idx == 200:
        print(hashlib.sha256(fr.tobytes()).hexdigest())
        print(int(fr.sum()), int(fr.mean()))
        break
    idx += 1
cap.release()
"""


def main():
    seen = []
    for i in range(4):
        proc = subprocess.run(
            [sys.executable, "-c", CODE],
            capture_output=True, text=True,
            cwd="D:\\alpr", timeout=300)
        if proc.returncode != 0:
            print("FAILED:", proc.stderr[-1500:])
            return
        lines = proc.stdout.strip().splitlines()
        seen.append(tuple(lines[-2:]))
        print(f"run{i}: sha={lines[-2][:32]}... "
              f"sum={lines[-1]}")
    uniq = set(seen)
    print(f"\ndistinct decodes: {len(uniq)} / {len(seen)}")
    if len(uniq) > 1:
        print("CONCLUSION: video decode is NOT "
              "byte-repeatable across processes — "
              "threshold-boundary detection flips are "
              "decode jitter, not model nondeterminism.")
    else:
        print("CONCLUSION: decode is repeatable; the "
              "flips need another explanation.")


if __name__ == "__main__":
    main()
