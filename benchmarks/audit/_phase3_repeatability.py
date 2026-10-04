"""Quantify cross-process detector repeatability.

Decodes the cam2 frames once to PNG (freezing decode),
then runs Detector A in THREE separate processes on the
identical PNG bytes and compares detection sets.
"""
from __future__ import annotations

import subprocess
import sys

CODE = """
import sys, json
sys.path.insert(0, '.')
sys.path.insert(0, 'benchmarks')
import cv2
sys.path.insert(0, '.')
from run_phase3 import build_detectors
detectors = build_detectors()
fn = detectors['detector_a_current']
import glob
out = {}
for p in sorted(glob.glob('benchmarks/audit/_repeat_*.png')):
    fr = cv2.imread(p)
    boxes = fn(fr)
    out[p] = sorted([round(b['confidence'], 4)
                     for b in boxes])
print(json.dumps(out))
"""


def main():
    import cv2
    cap = cv2.VideoCapture("cam2.mp4")
    # the cam2 frames that flipped between Phase 3 runs
    # plus neighbors: 200-230 step 5 and 570-598 step 5
    wanted = set(list(range(200, 231, 5))
                 + list(range(570, 599, 5)))
    idx = 0
    saved = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if idx in wanted:
            p = f"benchmarks/audit/_repeat_{idx:05d}.png"
            cv2.imwrite(p, fr)
            saved.append(p)
        idx += 1
    cap.release()
    print(f"saved {len(saved)} frozen frames", flush=True)
    runs = []
    for i in range(3):
        proc = subprocess.run(
            [sys.executable, "-c", CODE],
            capture_output=True, text=True,
            cwd="D:\\alpr", timeout=600)
        if proc.returncode != 0:
            print("RUN FAILED:", proc.stderr[-2000:])
            return
        import json as _json
        runs.append(_json.loads(
            proc.stdout.strip().splitlines()[-1]))
    import json as _json
    frames = sorted(runs[0])
    diffs = 0
    for f in frames:
        sets = [tuple(runs[i].get(f, [])) for i in range(3)]
        if not (sets[0] == sets[1] == sets[2]):
            diffs += 1
            print(f"NON-REPEATABLE {f}:")
            for i in range(3):
                print(f"  run{i}: {sets[i]}")
    print(f"\nframes compared: {len(frames)}, "
          f"non-repeatable: {diffs}")
    # cleanup
    import os
    for p in saved:
        os.unlink(p)


if __name__ == "__main__":
    main()
