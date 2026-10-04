"""Full-frame DETECTOR -> CROP -> OCR benchmark (tasks §17/§8/§9).

For every sampled frame of cam1/cam2:
  1. detector produces plate boxes (production plate model, IranPlate-Vision)
  2. each box is cropped from the SAME frame
  3. every OCR model reads each crop
  4. the reading is scored against that frame's verified ground truth
     (cam2 = UNLABELED -> excluded from accuracy, still counted for
      invalid/failed/latency)

Headline combinations (task §9):
  current detector + current OCR
  IranPlate-Vision + current OCR
  current detector + Hezar
  IranPlate-Vision + Hezar
  IranPlate-Vision + YOLO11 OCR
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

from adapters.registry import ALL_OCR_ADAPTERS  # noqa: E402
from metrics import aggregate, is_valid_iranian, score_pair, width_bucket  # noqa: E402
from normalization import normalize_plate_text  # noqa: E402

DS = ROOT / "benchmarks" / "dataset"
RESULTS = ROOT / "benchmarks" / "results"
SAMPLE_INTERVAL = 5

HEADLINE = [
    ("current_detector", "current_production"),
    ("iranplate_vision", "current_production"),
    ("current_detector", "hezar_crnn_v2"),
    ("iranplate_vision", "hezar_crnn_v2"),
    ("iranplate_vision", "persian_lpr_yolo11"),
    ("current_detector", "persian_lpr_yolo11"),
    ("current_detector", "plr_crnn"),
    ("iranplate_vision", "plr_crnn"),
]


def frame_gt_map() -> dict:
    """(video, frame) -> verified plate text (Persian) where available."""
    labels = json.loads((DS / "gt_labels.json").read_text(encoding="utf-8"))
    out = {}
    for lab in labels["labels"].values():
        if not lab.get("verified"):
            continue
        for lo, hi in lab["applies_to"]["frame_ranges"]:
            for f in range(lo, hi + 1):
                out[(lab["applies_to"]["source_video"], f)] = lab["plate_text"]
    return out


def main() -> None:
    from api import _ensure_models
    engine = _ensure_models()
    from adapters.registry import IranPlateDetectorAdapter

    ocr = {c.id: c for c in (cls() for cls in ALL_OCR_ADAPTERS)}
    for o in ocr.values():
        o.is_available()
    ipv = IranPlateDetectorAdapter()
    ipv_ok = ipv.is_available()
    gt = frame_gt_map()

    def _norm_boxes(boxes):
        """Normalize detector output (dicts or tuples) to [x1,y1,x2,y2]."""
        out = []
        for b in boxes:
            bb = b["bbox"] if isinstance(b, dict) else b
            out.append([int(v) for v in bb[:4]])
        return out

    def prod_crop_boxes(frame):
        t0 = time.perf_counter()
        try:
            det = engine._plate_model.predict(frame, verbose=False, conf=0.5)[0]
        except Exception:
            return [], (time.perf_counter() - t0) * 1000
        ms = (time.perf_counter() - t0) * 1000
        boxes = []
        if det.boxes is not None:
            for b in det.boxes.data.tolist():
                boxes.append([int(v) for v in b[:4]])
        return boxes, ms

    records = []
    for video in ("cam1.mp4", "cam2.mp4"):
        cap = cv2.VideoCapture(str(ROOT / video))
        idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % SAMPLE_INTERVAL == 0:
                det_out = {"current_detector": prod_crop_boxes(frame)}
                if ipv_ok:
                    _b, _ms = ipv.detect(frame, conf=0.4)
                    det_out["iranplate_vision"] = (_norm_boxes(_b), _ms)
                for det_name, (boxes, det_ms) in det_out.items():
                    for (x1, y1, x2, y2) in boxes:
                        h, w = frame.shape[:2]
                        c = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
                        if c.size == 0:
                            continue
                        for ocr_name in {o for _, o in HEADLINE}:
                            a = ocr[ocr_name]
                            r = a.predict(c)
                            ref = gt.get((video, idx))
                            rec = {
                                "video": video, "frame": idx,
                                "detector": det_name, "ocr": ocr_name,
                                "combo": f"{det_name}+{ocr_name}",
                                "crop_w": c.shape[1], "crop_h": c.shape[0],
                                "bucket": width_bucket(c.shape[1]),
                                "raw_text": r["raw_text"], "text": r["text"],
                                "latency_ms": (r["latency_ms"] or 0) + det_ms,
                                "invalid": not is_valid_iranian(
                                    r["raw_text"], r["confidence"] or 0.9),
                                "failed": not r["text"],
                                "gt_status": "LABELED" if ref else "UNLABELED",
                            }
                            if ref:
                                rec.update(score_pair(r["raw_text"], ref))
                            else:
                                rec.update({"exact": None, "char_accuracy": None,
                                            "edit_distance": None})
                            records.append(rec)
            idx += 1
        cap.release()

    summary = {}
    for combo in sorted({r["combo"] for r in records}):
        sub = [r for r in records if r["combo"] == combo]
        entry = {"classification": "DETECTOR_PLUS_OCR",
                 "overall": aggregate(sub)["all"]}
        for vid in ("cam1.mp4", "cam2.mp4"):
            entry[vid] = aggregate([r for r in sub if r["video"] == vid])["all"]
        entry["by_width_bucket"] = {
            b: aggregate([r for r in sub if r["bucket"] == b])["all"]
            for b in ("lt100", "100-150", "ge150")
            if any(r["bucket"] == b for r in sub)}
        lat = [r["latency_ms"] for r in sub if r["latency_ms"]]
        entry["latency_ms_median"] = round(statistics.median(lat), 1) if lat else None
        entry["latency_ms_p95"] = round(
            sorted(lat)[int(0.95 * (len(lat) - 1))], 1) if lat else None
        summary[combo] = entry

    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "sample_interval": SAMPLE_INTERVAL,
           "headline_combinations": [f"{d}+{o}" for d, o in HEADLINE],
           "note": "cam2 rows are UNLABELED (excluded from accuracy); "
                   "invalid/failed/latency still reported.",
           "summary": summary,
           "records": records}
    RESULTS.mkdir(parents=True, exist_ok=True)
    with open(RESULTS / "combo_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("%-42s %-8s %-8s %-8s %-8s" % ("combo", "exact", "characc", "invalid", "med_ms"))
    for combo, e in summary.items():
        o = e["overall"]
        print("%-42s %-8s %-8s %-8s %-8s" % (
            combo, o["exact_accuracy"], o["char_accuracy"],
            o["invalid_rate"], e["latency_ms_median"]))


if __name__ == "__main__":
    main()
