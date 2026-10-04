"""Phase 2B — Detector A/B + Crop Quality Benchmark.

Detector A: current production plate detector (alpr_engine, conf from
            alpr_engine.PLATE_DET_CONF by default, overridable).
Detector B: IranPlate-Vision best.pt (local artifact under bench/).

Both detectors see the SAME frames; both crops are read by the SAME OCR
(CURRENT_PRODUCTION). Accuracy uses verified ground truth only; cam2 stays
UNLABELED and is reported as diagnostics.

Outputs:
  benchmarks/results/phase2b_detector_crop_results.json
  benchmarks/results/phase2b_pairwise_results.json
  benchmarks/results/phase2b_bucket_results.json
  benchmarks/diagnostics/phase2b/*.html + *.jsonl
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

import cv2  # noqa: E402

from ab_helpers import (  # noqa: E402
    BUCKETS, bucket_for, classify_pair, clipping_flags, geometry, pair_boxes,
    percentile,
)
from adapters.registry import ProductionOCRAdapter  # noqa: E402
from metrics import is_valid_iranian, score_pair  # noqa: E402
from normalization import normalize_plate_text  # noqa: E402

DS = ROOT / "benchmarks" / "dataset"
RESULTS = ROOT / "benchmarks" / "results"
DIAG = ROOT / "benchmarks" / "diagnostics" / "phase2b"
VIDEOS = ("cam1.mp4", "cam2.mp4")
DETECTORS = ("current_detector", "iranplate_vision")


# --------------------------------------------------------------------- GT
def frame_gt() -> dict:
    labels = json.loads((DS / "gt_labels.json").read_text(encoding="utf-8"))
    out = {}
    for name, lab in labels["labels"].items():
        if not lab.get("verified"):
            continue
        for lo, hi in lab["applies_to"]["frame_ranges"]:
            for f in range(lo, hi + 1):
                out[(lab["applies_to"]["source_video"], f)] = lab["plate_text"]
    return out


# -------------------------------------------------------------- detectors
def make_production_detector(conf: float):
    from api import _ensure_models
    engine = _ensure_models()

    def detect(frame):
        t0 = time.perf_counter()
        try:
            out = engine._plate_model.predict(
                frame, show=False, conf=conf, iou=0.45, max_det=12, verbose=False)[0]
        except Exception as exc:
            return [], (time.perf_counter() - t0) * 1000.0, str(exc)
        ms = (time.perf_counter() - t0) * 1000.0
        boxes = []
        if out.boxes is not None:
            for b in out.boxes.data.tolist():
                x1, y1, x2, y2, c, cls = b
                boxes.append({"bbox": [x1, y1, x2, y2], "conf": float(c)})
        return boxes, ms, None

    return detect


def make_ipv_detector(conf: float):
    from adapters.registry import IranPlateDetectorAdapter
    det = IranPlateDetectorAdapter()
    if not det.is_available():
        raise SystemExit(f"IranPlate-Vision unavailable: {det.unavailable_reason}")

    def detect(frame):
        boxes, ms = det.detect(frame, conf=conf)
        return [{"bbox": b["bbox"], "conf": b["conf"]} for b in boxes], ms, None

    return detect


# ------------------------------------------------------------------ crops
def crop_of(frame, box, expand: float = 1.0):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in box[:4]]
    if expand != 1.0:
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        bw, bh = (x2 - x1) * expand, (y2 - y1) * expand
        x1, y1, x2, y2 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2
    ix1, iy1 = max(0, int(round(x1))), max(0, int(round(y1)))
    ix2, iy2 = min(w, int(round(x2))), min(h, int(round(y2)))
    if ix2 <= ix1 or iy2 <= iy1:
        return None
    return frame[iy1:iy2, ix1:ix2]


def collect_frames(interval: int):
    for video in VIDEOS:
        cap = cv2.VideoCapture(str(ROOT / video))
        idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % interval == 0:
                yield video, idx, frame
            idx += 1
        cap.release()


# -------------------------------------------------------------- main pass
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conf", type=float, default=0.5,
                    help="identical confidence threshold for BOTH detectors")
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=6)
    ap.add_argument("--sweep", default="0.2,0.3,0.4,0.5,0.6")
    ap.add_argument("--expand", default="1.00,1.05,1.10,1.15,1.20")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    DIAG.mkdir(parents=True, exist_ok=True)

    gt = frame_gt()
    ocr = ProductionOCRAdapter()
    ocr.is_available()
    detectors = {
        "current_detector": make_production_detector(args.conf),
        "iranplate_vision": make_ipv_detector(args.conf),
    }

    frames = list(collect_frames(args.interval))

    # ---- warm-up (excluded from latency) --------------------------------
    for video, idx, frame in frames[:args.warmup]:
        for fn in detectors.values():
            fn(frame)
        ocr.predict(frame[:64, :64])

    # ---- primary A/B pass ------------------------------------------------
    records = []
    for video, idx, frame in frames:
        h, w = frame.shape[:2]
        for det_name, fn in detectors.items():
            boxes, det_ms, err = fn(frame)
            if err:
                records.append({"camera": video, "frame": idx,
                                "detector": det_name, "error": err})
                continue
            for rank, b in enumerate(boxes):
                box = b["bbox"]
                crop = crop_of(frame, box)
                if crop is None:
                    continue
                t0 = time.perf_counter()
                r = ocr.predict(crop)
                ocr_ms = (time.perf_counter() - t0) * 1000.0
                geo = geometry(box)
                clip = clipping_flags(box, w, h)
                ref = gt.get((video, idx))
                rec = {
                    "camera": video, "frame": idx, "detector": det_name,
                    "box_rank": rank, "confidence": round(float(b["conf"]), 4),
                    "x1": round(float(box[0]), 1), "y1": round(float(box[1]), 1),
                    "x2": round(float(box[2]), 1), "y2": round(float(box[3]), 1),
                    "width": round(geo["width"], 1),
                    "height": round(geo["height"], 1),
                    "area": round(geo["area"], 1),
                    "aspect_ratio": geo["aspect_ratio"],
                    "bucket": bucket_for(int(geo["width"])),
                    **clip,
                    "ocr_text": r["raw_text"],
                    "ocr_confidence": r["confidence"],
                    "ocr_valid": is_valid_iranian(r["raw_text"], r["confidence"] or 0.9),
                    "ground_truth": ref,
                    "gt_status": "LABELED" if ref else "UNLABELED",
                    "detector_latency_ms": round(det_ms, 2),
                    "ocr_latency_ms": round(ocr_ms, 2),
                    "total_latency_ms": round(det_ms + ocr_ms, 2),
                }
                if ref:
                    rec.update(score_pair(r["raw_text"], ref))
                else:
                    rec.update({"exact": None, "char_accuracy": None,
                                "edit_distance": None, "edit_distance_norm": None})
                records.append(rec)

    # ---- frame-level rollup ---------------------------------------------
    frame_rows = []
    for video in VIDEOS:
        for _, idx, _ in [f for f in frames if f[0] == video]:
            ref = gt.get((video, idx))
            for det_name in DETECTORS:
                sub = [r for r in records if r["camera"] == video
                       and r["frame"] == idx and r["detector"] == det_name
                       and "ocr_text" in r]
                if not sub:
                    frame_rows.append({"camera": video, "frame": idx,
                                       "detector": det_name, "n_boxes": 0,
                                       "frame_exact": False if ref else None,
                                       "gt_status": "LABELED" if ref else "UNLABELED"})
                    continue
                exacts = [r.get("exact") for r in sub if r.get("exact") is not None]
                frame_rows.append({
                    "camera": video, "frame": idx, "detector": det_name,
                    "n_boxes": len(sub),
                    "median_crop_width": statistics.median([r["width"] for r in sub]),
                    "any_valid": any(r["ocr_valid"] for r in sub),
                    "all_invalid": not any(r["ocr_valid"] for r in sub),
                    "clipped_any": any(r["clipped_any"] for r in sub),
                    "best_exact": (any(exacts) if exacts else None),
                    "gt_status": "LABELED" if ref else "UNLABELED",
                })

    # ---- detector-level stats -------------------------------------------
    def stats_for(rows):
        if not rows:
            return None
        widths = [r["width"] for r in rows]
        heights = [r["height"] for r in rows]
        confs = [r["confidence"] for r in rows]
        verified = [r for r in rows if r.get("exact") is not None]
        return {
            "n_crops": len(rows),
            "n_verified": len(verified),
            "n_exact": sum(1 for r in verified if r["exact"]),
            "exact_accuracy": round(sum(1 for r in verified if r["exact"]) / len(verified), 4)
            if verified else None,
            "char_accuracy": round(
                sum(r["char_accuracy"] for r in verified) / len(verified), 4)
            if verified else None,
            "mean_edit_distance": round(
                sum(r["edit_distance"] for r in verified) / len(verified), 4)
            if verified else None,
            "invalid_rate": round(sum(1 for r in rows if not r["ocr_valid"]) / len(rows), 4),
            "failed_rate": round(sum(1 for r in rows if not r["ocr_text"]) / len(rows), 4),
            "mean_crop_width": round(statistics.fmean(widths), 1),
            "median_crop_width": round(statistics.median(widths), 1),
            "p10_crop_width": percentile(widths, 10),
            "p25_crop_width": percentile(widths, 25),
            "p50_crop_width": percentile(widths, 50),
            "p75_crop_width": percentile(widths, 75),
            "p90_crop_width": percentile(widths, 90),
            "mean_crop_height": round(statistics.fmean(heights), 1),
            "median_crop_height": round(statistics.median(heights), 1),
            "median_area": round(statistics.median([r["area"] for r in rows]), 1),
            "median_aspect_ratio": round(statistics.median(
                [r["aspect_ratio"] for r in rows if r["aspect_ratio"]]), 3),
            "clipping_rate": round(sum(1 for r in rows if r["clipped_any"]) / len(rows), 4),
            "clipped_left": sum(1 for r in rows if r["clipped_left"]),
            "clipped_right": sum(1 for r in rows if r["clipped_right"]),
            "clipped_top": sum(1 for r in rows if r["clipped_top"]),
            "clipped_bottom": sum(1 for r in rows if r["clipped_bottom"]),
            "detector_conf_mean": round(statistics.fmean(confs), 4),
            "detector_conf_median": round(statistics.median(confs), 4),
            "detector_conf_p10": percentile(confs, 10),
            "detector_conf_p90": percentile(confs, 90),
            "detector_latency_ms_p50": round(statistics.median(
                [r["detector_latency_ms"] for r in rows]), 2),
            "detector_latency_ms_p95": percentile(
                [r["detector_latency_ms"] for r in rows], 95),
            "ocr_latency_ms_p50": round(statistics.median(
                [r["ocr_latency_ms"] for r in rows]), 2),
            "ocr_latency_ms_p95": percentile(
                [r["ocr_latency_ms"] for r in rows], 95),
            "total_latency_ms_p50": round(statistics.median(
                [r["total_latency_ms"] for r in rows]), 2),
        }

    detector_summary = {}
    for det_name in DETECTORS:
        rows = [r for r in records if r["detector"] == det_name and "ocr_text" in r]
        entry = {"overall": stats_for(rows)}
        for video in VIDEOS:
            entry[video] = stats_for([r for r in rows if r["camera"] == video])
        for bucket in [b[2] for b in BUCKETS]:
            entry[f"bucket:{bucket}"] = stats_for(
                [r for r in rows if r["bucket"] == bucket])
        verified = [r for r in rows if r.get("exact") is not None]
        entry["confidence_vs_correctness"] = {
            "mean_conf_correct": round(statistics.fmean(
                [r["confidence"] for r in verified if r["exact"]]), 4)
            if any(r["exact"] for r in verified) else None,
            "mean_conf_incorrect": round(statistics.fmean(
                [r["confidence"] for r in verified if not r["exact"]]), 4)
            if any(not r["exact"] for r in verified) else None,
        }
        detector_summary[det_name] = entry

    # frame-level detector comparison (cam1 verified only)
    frame_summary = {}
    for det_name in DETECTORS:
        rows = [f for f in frame_rows if f["detector"] == det_name]
        labeled = [f for f in rows if f["gt_status"] == "LABELED"]
        frame_summary[det_name] = {
            "frames_sampled": len(rows),
            "frames_with_detection": sum(1 for f in rows if f["n_boxes"] > 0),
            "verified_frames": len(labeled),
            "verified_frames_exact": sum(1 for f in labeled if f["best_exact"]),
            "verified_frame_exact_accuracy": round(
                sum(1 for f in labeled if f["best_exact"]) / len(labeled), 4)
            if labeled else None,
            "median_boxes_per_frame": round(statistics.median(
                [f["n_boxes"] for f in rows]), 2),
        }

    # ---- threshold sweep -------------------------------------------------
    sweep_thresholds = [float(x) for x in args.sweep.split(",")]
    sweep_rows = []
    for conf in sweep_thresholds:
        dets = {"current_detector": make_production_detector(conf),
                "iranplate_vision": make_ipv_detector(conf)}
        for video, idx, frame in frames:
            ref = gt.get((video, idx))
            for det_name, fn in dets.items():
                if det_name == "iranplate_vision" and conf != sweep_thresholds[0]:
                    continue  # both swept below; kept symmetric via loop order
                boxes, det_ms, err = fn(frame)
                if err:
                    continue
                valid = exact = n_verified = 0
                widths = []
                clipped = 0
                for b in boxes:
                    crop = crop_of(frame, b["bbox"])
                    if crop is None:
                        continue
                    widths.append(crop.shape[1])
                    if clipping_flags(b["bbox"], frame.shape[1], frame.shape[0])["clipped_any"]:
                        clipped += 1
                    r = ocr.predict(crop)
                    if is_valid_iranian(r["raw_text"], r["confidence"] or 0.9):
                        valid += 1
                    if ref:
                        n_verified += 1
                        exact += int(score_pair(r["raw_text"], ref)["exact"])
                sweep_rows.append({
                    "threshold": conf, "detector": det_name, "camera": video,
                    "frame": idx, "n_boxes": len(boxes),
                    "mean_crop_width": round(statistics.fmean(widths), 1) if widths else None,
                    "clipping_rate": round(clipped / len(widths), 4) if widths else None,
                    "ocr_valid_count": valid,
                    "verified_count": n_verified,
                    "exact_count": exact,
                    "detector_latency_ms": round(det_ms, 2),
                })

    # re-run the second detector for every threshold (symmetric sweep)
    for conf in sweep_thresholds[1:]:
        fn = make_ipv_detector(conf)
        for video, idx, frame in frames:
            ref = gt.get((video, idx))
            boxes, det_ms, err = fn(frame)
            if err:
                continue
            widths, clipped, valid, exact = [], 0, 0, 0
            for b in boxes:
                crop = crop_of(frame, b["bbox"])
                if crop is None:
                    continue
                widths.append(crop.shape[1])
                if clipping_flags(b["bbox"], frame.shape[1], frame.shape[0])["clipped_any"]:
                    clipped += 1
                r = ocr.predict(crop)
                if is_valid_iranian(r["raw_text"], r["confidence"] or 0.9):
                    valid += 1
                if ref:
                    exact += int(score_pair(r["raw_text"], ref)["exact"])
            sweep_rows.append({
                "threshold": conf, "detector": "iranplate_vision",
                "camera": video, "frame": idx, "n_boxes": len(boxes),
                "mean_crop_width": round(statistics.fmean(widths), 1) if widths else None,
                "clipping_rate": round(clipped / len(widths), 4) if widths else None,
                "ocr_valid_count": valid,
                "verified_count": sum(1 for _ in boxes) if ref else 0,
                "exact_count": exact,
                "detector_latency_ms": round(det_ms, 2),
            })

    sweep_summary = {}
    for conf in sweep_thresholds:
        for det_name in DETECTORS:
            sub = [r for r in sweep_rows if r["threshold"] == conf
                   and r["detector"] == det_name]
            if not sub:
                continue
            vsub = [r for r in sub if r["verified_count"]]
            sweep_summary[f"{det_name}@{conf}"] = {
                "detections_per_frame": round(statistics.fmean(
                    [r["n_boxes"] for r in sub]), 3),
                "verified_exact": sum(r["exact_count"] for r in vsub),
                "verified_total": sum(r["verified_count"] for r in vsub),
                "valid_crops": sum(r["ocr_valid_count"] for r in sub),
                "total_crops": sum(r["n_boxes"] for r in sub),
                "median_detector_latency_ms": round(statistics.median(
                    [r["detector_latency_ms"] for r in sub]), 2),
            }

    # ---- crop expansion experiment --------------------------------------
    expand_factors = [float(x) for x in args.expand.split(",")]
    expand_rows = []
    for factor in expand_factors:
        for det_name in DETECTORS:
            fn = detectors[det_name]
            for video, idx, frame in frames:
                ref = gt.get((video, idx))
                boxes, _, _ = fn(frame)
                for b in boxes:
                    crop = crop_of(frame, b["bbox"], expand=factor)
                    if crop is None:
                        continue
                    r = ocr.predict(crop)
                    exact = None
                    if ref:
                        exact = score_pair(r["raw_text"], ref)["exact"]
                    expand_rows.append({
                        "expand": factor, "detector": det_name, "camera": video,
                        "frame": idx, "width": crop.shape[1],
                        "exact": exact,
                        "invalid": not is_valid_iranian(r["raw_text"], r["confidence"] or 0.9),
                        "ocr_valid": is_valid_iranian(r["raw_text"], r["confidence"] or 0.9),
                        # CORRECTION 2026-10-03: `failed` means EMPTY OCR output, not
                        # "not ocr_valid". Previously the record carried no such field and
                        # failed_rate reused the invalid_rate predicate (`not ocr_valid`),
                        # so failed_rate == invalid_rate in every crop_expansion cell.
                        # Verified against the primary records: failed == (not ocr_text).
                        "failed": not (r["raw_text"] or "").strip(),
                    })
    expand_summary = {}
    for factor in expand_factors:
        for det_name in DETECTORS:
            sub = [r for r in expand_rows if r["expand"] == factor
                   and r["detector"] == det_name]
            ver = [r for r in sub if r["exact"] is not None]
            expand_summary[f"{det_name}@{factor:.2f}"] = {
                "n_crops": len(sub),
                "median_width": round(statistics.median([r["width"] for r in sub]), 1),
                "exact_accuracy": round(sum(1 for r in ver if r["exact"]) / len(ver), 4)
                if ver else None,
                "verified_total": len(ver),
                "invalid_rate": round(sum(1 for r in sub if r["invalid"]) / len(sub), 4),
                "failed_rate": round(sum(1 for r in sub if r["failed"]) / len(sub), 4),
            }

    # ---- pairwise --------------------------------------------------------
    pairs = []
    per_frame = {}
    for r in records:
        if "ocr_text" in r:
            per_frame.setdefault((r["camera"], r["frame"], r["detector"]), []).append(r)
    for video in VIDEOS:
        for _, idx, _ in [f for f in frames if f[0] == video]:
            cur = [r for r in per_frame.get((video, idx, "current_detector"), [])]
            ipv = [r for r in per_frame.get((video, idx, "iranplate_vision"), [])]
            if not cur or not ipv:
                continue
            cur_boxes = [[r["x1"], r["y1"], r["x2"], r["y2"]] for r in cur]
            ipv_boxes = [[r["x1"], r["y1"], r["x2"], r["y2"]] for r in ipv]
            matched, cur_only, ipv_only = pair_boxes(cur_boxes, ipv_boxes)
            for cb, ib, iou in matched:
                c = next(r for r in cur if [r["x1"], r["y1"], r["x2"], r["y2"]] == cb)
                i = next(r for r in ipv if [r["x1"], r["y1"], r["x2"], r["y2"]] == ib)
                ref = gt.get((video, idx))
                outcome = classify_pair(
                    gt_available=bool(ref),
                    cur_exact=c.get("exact"), ipv_exact=i.get("exact"),
                    cur_valid=c["ocr_valid"], ipv_valid=i["ocr_valid"])
                pairs.append({
                    "camera": video, "frame": idx, "iou": iou,
                    "current_crop": [c["width"], c["height"]],
                    "iranplate_crop": [i["width"], i["height"]],
                    "width_delta": round(i["width"] - c["width"], 1),
                    "current_clipping": {k: c[k] for k in
                                         ("clipped_left", "clipped_right",
                                          "clipped_top", "clipped_bottom")},
                    "iranplate_clipping": {k: i[k] for k in
                                           ("clipped_left", "clipped_right",
                                            "clipped_top", "clipped_bottom")},
                    "current_ocr": c["ocr_text"],
                    "iranplate_ocr": i["ocr_text"],
                    "current_ocr_valid": c["ocr_valid"],
                    "iranplate_ocr_valid": i["ocr_valid"],
                    "current_conf": c["confidence"],
                    "iranplate_conf": i["confidence"],
                    "ground_truth": ref,
                    "gt_status": "LABELED" if ref else "UNLABELED",
                    "current_result": c.get("exact"),
                    "iranplate_result": i.get("exact"),
                    "outcome": outcome,
                })
            # unmatched detections are recorded but never used for superiority
            for b in cur_only:
                pairs.append({"camera": video, "frame": idx, "iou": 0.0,
                              "outcome": "INCOMPARABLE",
                              "note": "current detections unmatched by IranPlate-Vision"})
            for b in ipv_only:
                pairs.append({"camera": video, "frame": idx, "iou": 0.0,
                              "outcome": "INCOMPARABLE",
                              "note": "IranPlate-Vision detections unmatched by current"})

    pair_counts = {}
    for p in pairs:
        pair_counts[p["outcome"]] = pair_counts.get(p["outcome"], 0) + 1

    # ---- write machine-readable results ---------------------------------
    (RESULTS / "phase2b_detector_crop_results.json").write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "methodology": {
            "conf": args.conf, "interval": args.interval,
            "ocr": "current_production (identical for both detectors)",
            "note": "accuracy uses verified GT only; cam2 is UNLABELED",
        },
        "detector_summary": detector_summary,
        "frame_level": frame_summary,
        "records": records,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    (RESULTS / "phase2b_pairwise_results.json").write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "outcome_counts": pair_counts,
        "pairs": pairs,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    (RESULTS / "phase2b_bucket_results.json").write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "buckets": {
            det: {b[2]: detector_summary[det].get(f"bucket:{b[2]}")
                  for b in BUCKETS}
            for det in DETECTORS},
        "threshold_sweep": sweep_summary,
        "crop_expansion": expand_summary,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    with open(DIAG / "phase2b_crops.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- console summary -------------------------------------------------
    print(json.dumps({
        "detector_medians": {
            d: {k: detector_summary[d]["overall"][k] for k in
                ("n_crops", "exact_accuracy", "char_accuracy", "invalid_rate",
                 "clipping_rate", "median_crop_width", "total_latency_ms_p50")}
            for d in DETECTORS},
        "cam1_overall": {d: {
            "n_crops": detector_summary[d]["cam1.mp4"]["n_crops"],
            "n_verified": detector_summary[d]["cam1.mp4"]["n_verified"],
            "exact": detector_summary[d]["cam1.mp4"]["exact_accuracy"],
            "invalid": detector_summary[d]["cam1.mp4"]["invalid_rate"],
            "median_w": detector_summary[d]["cam1.mp4"]["median_crop_width"],
        } for d in DETECTORS},
        "cam2_diag": {d: {
            "n_crops": detector_summary[d]["cam2.mp4"]["n_crops"],
            "invalid": detector_summary[d]["cam2.mp4"]["invalid_rate"],
            "median_w": detector_summary[d]["cam2.mp4"]["median_crop_width"],
            "clipping": detector_summary[d]["cam2.mp4"]["clipping_rate"],
            "conf_mean": detector_summary[d]["cam2.mp4"]["detector_conf_mean"],
        } for d in DETECTORS},
        "frame_level_cam1": frame_summary,
        "pair_outcomes": pair_counts,
        "sweep": sweep_summary,
        "expansion": expand_summary,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
