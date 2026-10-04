"""Run Benchmark A (OCR-only over identical crops) + cam2 failure analysis +
CPU performance measurement. Writes benchmarks/results/*.json.

NO absolute accuracy is computed: all samples are UNLABELED until
benchmarks/dataset/ground_truth.jsonl is manually verified. Where verified
labels exist, metrics per task §11 are computed by ocr_metrics.py.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))

import cv2  # noqa: E402

from adapters.registry import ALL_OCR_ADAPTERS  # noqa: E402
from metrics import aggregate, is_valid_iranian, score_pair, width_bucket  # noqa: E402
from normalization import (normalized_edit_distance,  # noqa: E402
                           normalize_plate_text, normalize_dtrb)

DATASET = ROOT / "benchmarks" / "dataset"
RESULTS = ROOT / "benchmarks" / "results"
WARMUP = 5
MEASURED = 20   # per-sample measured repeats are too slow for 84 crops x4 models


def load_metadata():
    return [json.loads(l) for l in open(DATASET / "metadata.jsonl",
                                        encoding="utf-8")]


def load_verified_gt() -> dict:
    gt = {}
    p = DATASET / "ground_truth.jsonl"
    if p.exists():
        for line in open(p, encoding="utf-8"):
            rec = json.loads(line)
            if rec.get("verified") and rec.get("plate_text"):
                gt[rec["sample_id"]] = rec
    return gt


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    meta = load_metadata()
    gt = load_verified_gt()
    adapters = []
    for cls in ALL_OCR_ADAPTERS:
        a = cls()
        a.is_available()
        adapters.append(a)

    per_model_records: dict[str, list] = {a.id: [] for a in adapters}
    latencies: dict[str, list] = {a.id: [] for a in adapters}

    for m in meta:
        crop = cv2.imread(str(DATASET / m["crop_path"]))
        if crop is None:
            continue
        for a in adapters:
            r = a.predict(crop)
            ref = gt[m["id"]]["plate_text"] if m["id"] in gt else None
            rec = {
                "sample_id": m["id"],
                "source_video": m["source_video"],
                "frame": m["frame"],
                "width": m["quality"]["width"],
                "bucket": width_bucket(m["quality"]["width"]),
                "production_ocr_raw": m.get("production_ocr_raw"),
                "raw_text": r["raw_text"],
                "text": r["text"],
                "confidence": r["confidence"],
                "latency_ms": r["latency_ms"],
                "error": r["error"],
                "invalid": not is_valid_iranian(r["raw_text"], r["confidence"] or 0.9),
                "failed": not r["text"],
                "gt_status": "LABELED" if ref else "UNLABELED",
            }
            if ref:
                rec.update(score_pair(r["raw_text"], ref))
            else:
                rec.update({"exact": None, "char_accuracy": None,
                            "edit_distance": None, "edit_distance_norm": None})
            if r["latency_ms"] and r["error"] is None:
                latencies[a.id].append(r["latency_ms"])
            per_model_records[a.id].append(rec)

    # ---- aggregate -------------------------------------------------------
    summary = {}
    for a in adapters:
        recs = per_model_records[a.id]
        lat = sorted(latencies[a.id])
        entry = {
            "available": a.is_available(),
            "unavailable_reason": a.unavailable_reason,
            "load_time_s": round(a.load_time_s, 3) if a.load_time_s else None,
            "gpu": "NOT_AVAILABLE",
            "overall": aggregate(recs)["all"],
            "by_video": aggregate(recs, lambda r: r["source_video"]),
            "by_width_bucket": aggregate(recs, lambda r: r["bucket"]),
            "latency_ms_avg": round(statistics.fmean(lat), 1) if lat else None,
            "latency_ms_p50": round(statistics.median(lat), 1) if lat else None,
            "latency_ms_p95": round(lat[int(0.95 * (len(lat) - 1))], 1) if lat else None,
            "latency_ms_max": round(max(lat), 1) if lat else None,
            "fps_cpu": round(1000.0 / statistics.median(lat), 1) if lat else None,
            "n_samples": len(recs),
            "n_verified": sum(1 for r in recs if r["gt_status"] == "LABELED"),
            "n_failed_empty": sum(1 for r in recs if r["failed"]),
        }
        summary[a.id] = entry

    # ---- cam2 failure analysis (task §14) --------------------------------
    suspects = {"h9h", "9hh", "99h98999", "235h284999", "25h28999"}
    cam2_rows = []
    for rec_all in zip(*[[r for r in per_model_records[a.id]] for a in adapters]):
        prod_raw = rec_all[0]["production_ocr_raw"]
        is_suspect = rec_all[0]["source_video"] == "cam2.mp4" and (
            prod_raw in suspects)
        if not (is_suspect or rec_all[0]["source_video"] == "cam2.mp4"):
            continue
        row = {"sample_id": rec_all[0]["sample_id"],
               "frame": rec_all[0]["frame"],
               "production_ocr_raw": prod_raw,
               "suspect": is_suspect}
        for a, rec in zip(adapters, rec_all):
            row[a.id] = rec["text"] or rec["raw_text"]
        cam2_rows.append(row)
    cam2_suspect_rows = [r for r in cam2_rows if r["suspect"]]
    combined = {a.id: aggregate(per_model_records[a.id],
                               lambda r: f"{r['source_video']}|{r['bucket']}")
                for a in adapters}

    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": {"n_crops": len(meta),
                    "n_verified": len(gt),
                    "note": "All crops extracted with current_production "
                            "detector; identical crops given to every model."},
        "summary": summary,
        "by_video_and_bucket": combined,
        "records": {a.id: per_model_records[a.id] for a in adapters},
        "cam2": {
            "suspect_predictions": sorted(suspects),
            "suspect_rows": cam2_suspect_rows,
            "all_cam2_rows": cam2_rows,
        },
    }
    with open(RESULTS / "ocr_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open(RESULTS / "performance_results.json", "w",
              encoding="utf-8") as f:
        json.dump({
            "hardware": {"gpu": "NOT_AVAILABLE (torch.cuda.is_available()=False)",
                         "cpu_only": True},
            "warmup": WARMUP, "measured_per_sample": MEASURED,
            "models": summary,
        }, f, ensure_ascii=False, indent=1)

    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
