"""Detector benchmark (Benchmark B, task §5).

Ground-truth plate boxes for cam1/cam2 do NOT exist, so precision/recall/IoU
would be invented — therefore every detector is reported NO_GROUND_TRUTH with
qualitative/relative output only: detections per sampled frame, confidence
distribution, and per-detector latency on the SAME frames.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from adapters.registry import (ALL_DETECTOR_ADAPTERS,  # noqa: E402
                               IranPlateDetectorAdapter)

SAMPLE_INTERVAL = 10
RESULTS = ROOT / "benchmarks" / "results"


def production_plate_boxes(engine, frame, conf=0.5):
    try:
        from alpr_engine import PLATE_DET_CONF
    except Exception:
        PLATE_DET_CONF = conf
    boxes = []
    try:
        det = engine._plate_model.predict(frame, verbose=False,
                                          conf=PLATE_DET_CONF)[0]
        if det.boxes is not None:
            for b in det.boxes.data.tolist():
                x1, y1, x2, y2, c, cls = b
                boxes.append({"bbox": [x1, y1, x2, y2], "conf": c})
    except Exception as exc:
        print("[warn] production plate det failed:", exc)
    return boxes


def iou_matrix(a, b) -> list[list[float]]:
    def iou(p, q):
        ix1, iy1 = max(p[0], q[0]), max(p[1], q[1])
        ix2, iy2 = min(p[2], q[2]), min(p[3], q[3])
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        ap = (p[2] - p[0]) * (p[3] - p[1])
        bq = (q[2] - q[0]) * (q[3] - q[1])
        return inter / max(1e-6, ap + bq - inter)
    return [[iou(p["bbox"], q["bbox"]) for q in b] for p in a]


def main() -> None:
    from api import _ensure_models
    engine = _ensure_models()
    RESULTS.mkdir(parents=True, exist_ok=True)

    detectors = []
    for cls in ALL_DETECTOR_ADAPTERS:
        d = cls()
        d.is_available()
        detectors.append(d)

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

    records = {d.id: [] for d in detectors}
    records["current_production_plate"] = []
    lat = {k: [] for k in records}

    for video, fidx, frame in frames:
        prod = production_plate_boxes(engine, frame)
        records["current_production_plate"].append(
            {"video": video, "frame": fidx, "n_boxes": len(prod),
             "conf_mean": round(statistics.fmean([b["conf"] for b in prod]), 3)
             if prod else 0.0})
        lat["current_production_plate"].append(0.0)  # measured in pipeline bench
        for d in detectors:
            if not d.is_available():
                records[d.id].append({"video": video, "frame": fidx,
                                      "error": d.unavailable_reason})
                continue
            boxes, ms = d.detect(frame)
            records[d.id].append({"video": video, "frame": fidx,
                                  "n_boxes": len(boxes),
                                  "conf_mean": round(
                                      statistics.fmean([b["conf"] for b in boxes]), 3)
                                  if boxes else 0.0})
            lat[d.id].append(ms)
            # relative agreement with production detector (NOT accuracy):
            if prod or boxes:
                m = iou_matrix(prod, boxes)
                best = max((max(row, default=0.0) for row in m), default=0.0)
                records[d.id][-1]["best_iou_vs_production"] = round(best, 3)

    summary = {}
    for k in records:
        rows = [r for r in records[k] if "n_boxes" in r]
        l = [x for x in lat[k] if x > 0]
        summary[k] = {
            "ground_truth": "NO_GROUND_TRUTH",
            "n_frames": len(rows),
            "frames_with_detection": sum(1 for r in rows if r["n_boxes"] > 0),
            "mean_boxes_per_frame": round(
                statistics.fmean([r["n_boxes"] for r in rows]), 3) if rows else 0,
            "mean_best_iou_vs_production": round(
                statistics.fmean([r["best_iou_vs_production"] for r in rows
                                  if "best_iou_vs_production" in r]), 3)
            if any("best_iou_vs_production" in r for r in rows) else None,
            "latency_ms_p50": round(statistics.median(l), 1) if l else None,
            "status": "runnable" if rows else "blocked",
        }

    out = {"generated_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
           "ground_truth": "NO_GROUND_TRUTH (no annotated plate boxes for "
                           "cam1/cam2 — precision/recall intentionally not "
                           "computed)",
           "summary": summary,
           "records": records}
    with open(RESULTS / "detector_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
