"""Step 4 smoke probe: reproduce the six Phase-2C discordant frames.

Checks the Phase 2C expectations BEFORE the full benchmark:
  A/trunc correct; B/trunc wrong; B/round correct; B/ceil correct;
  B/trunc+1.05x correct. Any deviation is a STOP condition.
"""
from __future__ import annotations

import sys

import cv2

sys.path.insert(0, ".")
sys.path.insert(0, "benchmarks")

from run_phase2d import (DISCORDANT_FRAMES, build_detectors,  # noqa: E402
                         evaluate_variant, load_gt)
from adapters.registry import ProductionOCRAdapter  # noqa: E402
from metrics import score_pair  # noqa: E402


def main():
    gt = load_gt()
    ocr = ProductionOCRAdapter()
    ocr.is_available()
    detectors = build_detectors()

    cap = cv2.VideoCapture("cam1.mp4")
    frames = {}
    idx = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if idx in DISCORDANT_FRAMES:
            frames[idx] = fr
        idx += 1
    cap.release()
    print("decoded discordant frames:", sorted(frames))

    all_ok = True
    for f in DISCORDANT_FRAMES:
        ref = gt.get(("cam1.mp4", f))
        frame = frames[f]
        print(f"--- cam1 frame {f}  GT={ref} ---")
        for det_name, fn in detectors.items():
            boxes = fn(frame)
            for bx in boxes:
                tag = ("A" if det_name == "detector_a_current" else "B")
                for conv in ("trunc", "round", "ceil"):
                    rec = evaluate_variant(frame, bx, ocr, conv, 1.0)
                    exact = score_pair(rec["ocr_text"], ref)["exact"] if ref else None
                    print(f"  {tag}/{conv:5s} bbox={[round(v, 2) for v in bx['bbox']]} "
                          f"int={rec['integer_bbox']} {rec['crop_width']}x{rec['crop_height']} "
                          f"ocr={rec['ocr_text']!r} exact={exact}")
                    if tag == "A" and conv == "trunc" and exact is False:
                        all_ok = False
                    if tag == "B" and conv == "trunc" and exact is True:
                        all_ok = False
                    if tag == "B" and conv in ("round", "ceil") and exact is False:
                        all_ok = False
                rec = evaluate_variant(frame, bx, ocr, "trunc", 1.05)
                exact = score_pair(rec["ocr_text"], ref)["exact"] if ref else None
                print(f"  {A_B(tag)}/trunc+1.05x int={rec['integer_bbox']} "
                      f"{rec['crop_width']}x{rec['crop_height']} "
                      f"ocr={rec['ocr_text']!r} exact={exact}")
                if tag == "B" and exact is False:
                    all_ok = False
    print(f"\nSTEP4 EXPECTATIONS ALL MATCH PHASE 2C: {all_ok}")
    if not all_ok:
        print("STOP: investigate before proceeding (task Step 4).")
        sys.exit(2)


def A_B(tag):
    return tag


if __name__ == "__main__":
    main()
