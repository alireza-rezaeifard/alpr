"""Step 12 — steady-state latency benchmark (warm-up >= 20,
measure >= 100; model loading excluded; YOLO never reloaded).

Reports p50 / p95 / max for:
  * detector (per detector)
  * crop extraction (baseline trunc vs candidate round)
  * OCR (shared)
  * total (crop + OCR, per convention)

Cold-start / model-load latency is deliberately NOT measured or
compared.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, ".")
sys.path.insert(0, "benchmarks")

from adapters.registry import IranPlateDetectorAdapter, ProductionOCRAdapter  # noqa: E402
from benchmarks.phase2d_crop import extract_crop  # noqa: E402
from run_phase2d import build_detectors, read_frames  # noqa: E402

RESULTS = Path("benchmarks/results")
WARMUP = 20
MEASURED = 100


def pct(values, p):
    v = sorted(values)
    k = min(len(v) - 1, max(0, math.ceil(p / 100.0 * len(v)) - 1))
    return round(float(v[k]), 4)


def stats(v):
    return {"p50": pct(v, 50), "p95": pct(v, 95),
            "max": round(float(max(v)), 4),
            "mean": round(statistics.fmean(v), 4),
            "n": len(v)}


def main():
    frames = read_frames(5)
    # a representative cam1 frame with a verified plate
    frame = next(fr for (v, i, fr) in frames
                 if v == "cam1.mp4" and i == 180)

    ocr = ProductionOCRAdapter()
    ocr.is_available()
    detectors = build_detectors()

    # ---- detector latency (warm-up 20, measure 100) -----------
    det_ms = {k: [] for k in detectors}
    for fn in detectors.values():
        for _ in range(WARMUP):
            fn(frame)
    for _ in range(MEASURED):
        for name, fn in detectors.items():
            t0 = time.perf_counter()
            boxes = fn(frame)
            det_ms[name].append((time.perf_counter() - t0) * 1000.0)

    # pick a real box for crop/OCR measurement
    a_boxes = detectors["detector_a_current"](frame)
    b_boxes = detectors["detector_b_iranplate"](frame)
    box_a = max(a_boxes, key=lambda b: b["confidence"])["bbox"]
    box_b = max(b_boxes, key=lambda b: b["confidence"])["bbox"]

    # ---- crop + OCR latency per convention ----------------------
    out = {"warmup_calls": WARMUP, "measured_calls": MEASURED,
           "note": "steady-state only; model load excluded; "
                   "YOLO not reloaded between measurements"}
    out["detector"] = {k: stats(v) for k, v in det_ms.items()}

    crop_ms = {}
    ocr_ms = {}
    total_ms = {}
    for conv in ("trunc", "round"):
        # warm-up
        for _ in range(WARMUP):
            c, _r = extract_crop(frame, box_a, conv, 1.0), None
            if c["crop"] is not None:
                ocr.predict(c["crop"])
        cs, os_, ts = [], [], []
        for _ in range(MEASURED):
            t0 = time.perf_counter()
            r = extract_crop(frame, box_a, conv, 1.0)
            t1 = time.perf_counter()
            ocr.predict(r["crop"])
            t2 = time.perf_counter()
            cs.append((t1 - t0) * 1000.0)
            os_.append((t2 - t1) * 1000.0)
            ts.append((t2 - t0) * 1000.0)
        crop_ms[conv] = stats(cs)
        ocr_ms[conv] = stats(os_)
        total_ms[conv] = stats(ts)

    out["crop_extraction"] = crop_ms
    out["ocr"] = ocr_ms
    out["total_crop_plus_ocr"] = total_ms
    out["measurement_box"] = {
        "detector": "detector_a_current",
        "bbox_float": [round(v, 4) for v in box_a],
        "detector_b_bbox_float": [round(v, 4) for v in box_b],
    }

    # crop-extraction-only delta between conventions (should be ~0)
    out["convention_delta_crop_extraction"] = {
        "round_p50_minus_trunc_p50_ms":
            round(crop_ms["round"]["p50"] - crop_ms["trunc"]["p50"], 4)}

    (RESULTS / "phase2d_latency.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
