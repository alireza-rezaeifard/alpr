"""Benchmark C — end-to-end combinations (task §16).

Combines runnable plate detectors with runnable OCR models over the SAME
sampled frames. Everything is DETECTOR_PLUS_OCR classification; no full
integrated external pipeline was runnable (see manifest), and no combination
is compared against OCR-only models as equivalent.

No accuracy claims: all samples are UNLABELED. We measure output stability
(share of frames where the pipeline yields a valid-format candidate per the
existing plate_validator — no production change) and latency.
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

from adapters.registry import (ALL_OCR_ADAPTERS,  # noqa: E402
                               ALL_DETECTOR_ADAPTERS)
from normalization import normalize_plate_text  # noqa: E402
from plate_validator import validate_iranian_plate  # noqa: E402

SAMPLE_INTERVAL = 10
RESULTS = ROOT / "benchmarks" / "results"


def main() -> None:
    from api import _ensure_models
    engine = _ensure_models()
    RESULTS.mkdir(parents=True, exist_ok=True)

    ocrs = []
    for cls in ALL_OCR_ADAPTERS:
        a = cls()
        a.is_available()
        ocrs.append(a)
    dets = []
    for cls in ALL_DETECTOR_ADAPTERS:
        d = cls()
        d.is_available()
        dets.append(d)

    # production detector + each OCR  AND  each external detector + each OCR
    frames = []
    for video in ("cam1.mp4", "cam2.mp4"):
        cap = cv2.VideoCapture(str(ROOT / video))
        idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % SAMPLE_INTERVAL == 0:
                frames.append((video, idx, frame))
            idx += 1
        cap.release()

    combos = [(d.id, o.id) for d in dets for o in ocrs]
    combos += [("current_production_plate", o.id) for o in ocrs]
    combos.append(("current_production_plate", "current_production"))

    records: dict[str, list] = {f"{d}+{o}": [] for d, o in combos}
    latency: dict[str, list] = {k: [] for k in records}

    def run_crop_detector(det, frame):
        boxes, ms = det.detect(frame, conf=0.4)
        return boxes, ms

    def prod_crop(frame):
        t0 = time.perf_counter()
        try:
            det = engine._plate_model.predict(frame, verbose=False, conf=0.5)[0]
        except Exception:
            return [], (time.perf_counter() - t0) * 1000
        ms = (time.perf_counter() - t0) * 1000.0
        boxes = []
        if det.boxes is not None:
            for b in det.boxes.data.tolist():
                x1, y1, x2, y2, c, cls = b
                boxes.append({"bbox": [x1, y1, x2, y2], "conf": c})
        return boxes, ms

    for video, fidx, frame in frames:
        # detector outputs for this frame
        det_outputs = {}
        for d in dets:
            if d.is_available():
                det_outputs[d.id] = run_crop_detector(d, frame)
        pb, pms = prod_crop(frame)
        det_outputs["current_production_plate"] = (pb, pms)

        for det_id, (boxes, dms) in det_outputs.items():
            crops = []
            for b in boxes:
                x1, y1, x2, y2 = [int(v) for v in b["bbox"]]
                c = frame[y1:y2, x1:x2]
                if c.size:
                    crops.append(c)
            for o in ocrs:
                key = f"{det_id}+{o.id}"
                for crop in crops:
                    r = o.predict(crop)
                    text = r["text"]
                    valid = False
                    if text:
                        v = validate_iranian_plate(
                            r["raw_text"], r["confidence"] or 0.9)
                        valid = v.is_valid
                    records[key].append({
                        "video": video, "frame": fidx,
                        "text": text, "valid_format": valid,
                        "error": r["error"],
                    })
                    if r["latency_ms"] and r["error"] is None:
                        latency[key].append(dms + r["latency_ms"])

    summary = {}
    for key, recs in records.items():
        texts = [r["text"] for r in recs if r["text"]]
        lat = latency[key]
        summary[key] = {
            "classification": "DETECTOR_PLUS_OCR",
            "n_crops": len(recs),
            "n_nonempty": len(texts),
            "n_valid_format": sum(1 for r in recs if r["valid_format"]),
            "invalid_format_rate": round(
                (len(texts) - sum(1 for r in recs if r["valid_format"]))
                / len(texts), 3) if texts else None,
            "latency_ms_median": round(statistics.median(lat), 1) if lat else None,
            "ground_truth": "NO_GROUND_TRUTH",
        }

    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "note": "Combination matrix over identical frames; format-validity "
                   "uses the unchanged production validator; no accuracy "
                   "claims (UNLABELED data).",
           "summary": summary,
           "records": {k: v[:400] for k, v in records.items()}}
    with open(RESULTS / "pipeline_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
