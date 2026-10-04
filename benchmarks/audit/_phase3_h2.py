"""H2 test: does Detector A output for IDENTICAL
frame-200 bytes depend on call history (cold first
call vs after warmup frames) within ONE process?"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")
sys.path.insert(0, "benchmarks")

import cv2  # noqa: E402

from run_phase3 import build_detectors  # noqa: E402


def main():
    f200 = cv2.imread(
        "benchmarks/audit/_jitter_frame.png")
    other = cv2.imread(
        "benchmarks/audit/_rt.png")
    assert (f200 == other).all()  # same bytes, sanity
    detectors = build_detectors()
    fn = detectors["detector_a_current"]

    def sig(boxes):
        return sorted(round(b["confidence"], 6)
                      for b in boxes)

    # cold: frame 200 as the VERY FIRST call
    first = sig(fn(f200.copy()))
    print("cold first call on f200:", first)
    # warm up on other frames
    for _ in range(30):
        fn(other.copy())
    # same bytes again after warmup
    after = sig(fn(f200.copy()))
    print("after 30 warmup calls:", after)
    # repeat alternating to see stability
    for i in range(5):
        fn(other.copy())
        print(f"alt {i}:", sig(fn(f200.copy())))


if __name__ == "__main__":
    main()
