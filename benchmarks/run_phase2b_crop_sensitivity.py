"""Phase 2B — crop boundary sensitivity experiment.

Motivation: during the A/B investigation, the production OCR produced
`12d67413` (correct) or `12d674913` (wrong) for the SAME IranPlate-Vision box
depending only on how the crop edges were quantized (round vs floor). This
experiment measures that effect for both detectors so the A/B conclusions are
not an artifact of one runner's cropping convention.

Conventions:
  round   int(round(x)) edges           (used by run_phase2b_ab.py)
  floor   int(x) edges                  (used by run_combo_bench.py)
  round±1 round() edges shifted by 1 px
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

import cv2  # noqa: E402

from adapters.registry import ProductionOCRAdapter  # noqa: E402
from metrics import is_valid_iranian, score_pair  # noqa: E402
from normalization import normalize_plate_text  # noqa: E402
from run_phase2b_ab import collect_frames, frame_gt, make_ipv_detector, make_production_detector  # noqa: E402

RESULTS = ROOT / "benchmarks" / "results"
CONVENTIONS = ["round", "floor", "round_dx-1", "round_dx+1"]


def crop_with(frame, box, convention: str):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in box[:4]]
    dx = dy = 0
    if convention.startswith("round"):
        if "_dx" in convention:
            dx = int(convention.split("_dx")[1])
        cx1, cy1, cx2, cy2 = (int(round(x1)) + dx, int(round(y1)) + dy,
                              int(round(x2)) + dx, int(round(y2)) + dy)
    else:  # floor
        cx1, cy1, cx2, cy2 = int(x1), int(y1), int(x2), int(y2)
    cx1, cy1 = max(0, cx1), max(0, cy1)
    cx2, cy2 = min(w, cx2), min(h, cy2)
    if cx2 <= cx1 or cy2 <= cy1:
        return None
    return frame[cy1:cy2, cx1:cx2]


def main() -> None:
    gt = frame_gt()
    ocr = ProductionOCRAdapter()
    ocr.is_available()
    detectors = {"current_detector": make_production_detector(0.5),
                 "iranplate_vision": make_ipv_detector(0.5)}
    frames = list(collect_frames(5))

    rows = []
    for video, idx, frame in frames:
        ref = gt.get((video, idx))
        for det_name, fn in detectors.items():
            boxes, _, _ = fn(frame)
            for b in boxes:
                for conv in CONVENTIONS:
                    crop = crop_with(frame, b["bbox"], conv)
                    if crop is None:
                        continue
                    r = ocr.predict(crop)
                    rec = {"camera": video, "frame": idx, "detector": det_name,
                           "convention": conv, "width": crop.shape[1],
                           "height": crop.shape[0], "ocr_text": r["raw_text"],
                           "invalid": not is_valid_iranian(r["raw_text"],
                                                           r["confidence"] or 0.9)}
                    if ref:
                        rec.update(score_pair(r["raw_text"], ref))
                    else:
                        rec.update({"exact": None, "char_accuracy": None})
                    rows.append(rec)

    summary = {}
    for det in detectors:
        for conv in CONVENTIONS:
            sub = [r for r in rows if r["detector"] == det and r["convention"] == conv]
            ver = [r for r in sub if r.get("exact") is not None]
            cam1 = [r for r in ver if r["camera"] == "cam1.mp4"]
            cam2 = [r for r in sub if r["camera"] == "cam2.mp4"]
            summary[f"{det}|{conv}"] = {
                "verified_samples": len(ver),
                "exact": round(sum(1 for r in ver if r["exact"]) / len(ver), 4) if ver else None,
                "exact_count": f"{sum(1 for r in ver if r['exact'])}/{len(ver)}",
                "char_accuracy": round(sum(r["char_accuracy"] for r in ver) / len(ver), 4)
                if ver else None,
                "invalid_rate_overall": round(
                    sum(1 for r in sub if r["invalid"]) / len(sub), 4) if sub else None,
                "cam2_invalid_rate": round(
                    sum(1 for r in cam2 if r["invalid"]) / len(cam2), 4) if cam2 else None,
                "n_crops": len(sub),
            }

    # per-sample flip analysis: same detector+frame, differing OCR across conventions
    by_sample = {}
    for r in rows:
        by_sample.setdefault((r["detector"], r["camera"], r["frame"]), {})[r["convention"]] = r["ocr_text"]
    flips = [{"detector": k[0], "camera": k[1], "frame": k[2], "outputs": v}
             for k, v in by_sample.items() if len(set(v.values())) > 1]

    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "note": "crop-boundary quantization sensitivity; identical detector "
                   "outputs, only crop edges differ",
           "summary": summary,
           "flip_count": len(flips),
           "flips": flips,
           "records": rows}
    (RESULTS / "phase2b_crop_sensitivity_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("%-40s %-10s %-10s %-10s" % ("config", "exact", "char_acc", "cam2_invalid"))
    for k, s in summary.items():
        print("%-40s %-10s %-10s %-10s" % (k, s["exact_count"], s["char_accuracy"],
                                           s["cam2_invalid_rate"]))
    print(f"\nsamples whose OCR output changed with crop edges: {len(flips)}")
    for f in flips[:10]:
        print("  ", f["detector"], f["camera"], f["frame"], f["outputs"])


if __name__ == "__main__":
    main()
