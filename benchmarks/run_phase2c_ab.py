"""Phase 2C â€” Detector A/B with crop extraction fully controlled.

Answers ONE question (task Â§5): on the same frames, with identical inference
parameters, identical box->pixel conversion, identical crop extraction,
identical OCR and verified ground truth, is there evidence either detector
produces better ALPR results?

Design constraints that differ from Phase 2B:
  * Detector B is driven with the SAME conf / iou / max_det as Detector A, so
    the NMS and candidate-budget asymmetry (2B finding D1) is eliminated.
  * ONE canonical crop extractor (phase2c_canonical) for both arms. The
    convention matrix is measured, not chosen by accuracy.
  * Frame-aligned: a frame where a detector fires nothing is recorded as
    NO_DETECTION and STAYS in the denominator (task Â§14/Â§16).
  * Every metric is stored as raw numerator/denominator.
  * Warm-up >= 20 calls before any latency is measured (task Â§25).
  * Run twice to prove repeatability (task Â§26).

Reads alpr_engine only to reuse the loaded production models. Never mutates it.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from adapters.registry import IranPlateDetectorAdapter, ProductionOCRAdapter  # noqa: E402
from metrics import is_valid_iranian, score_pair  # noqa: E402
from normalization import normalize_plate_text  # noqa: E402
from phase2c_canonical import (  # noqa: E402
    CONVENTIONS, bucket_for, convert_box, expand_box, extract_plate_crop,
    select_canonical,
)

DS = ROOT / "benchmarks" / "dataset"
RESULTS = ROOT / "benchmarks" / "results"
AUDIT = ROOT / "benchmarks" / "audit"
VIDEOS = ("cam1.mp4", "cam2.mp4")
DETECTORS = ("detector_a_current", "detector_b_iranplate")

# Frozen protocol (task Â§9). Both arms get EXACTLY these values.
PROTOCOL = {
    "conf": 0.50,
    "iou": 0.45,
    "max_det": 12,
    "imgsz": 640,
    "agnostic_nms": False,
    "half": False,
    "crop_convention": "trunc",
    "clip": True,
    "pad_x": 0,
    "pad_y": 0,
    "ocr": "CURRENT_PRODUCTION",
}

SWEEP_CONF = (0.30, 0.40, 0.50, 0.60, 0.70)
EXPAND_FACTORS = (1.00, 1.05, 1.10, 1.15, 1.20)
WARMUP_CALLS = 20
LATENCY_CALLS = 100
# --------------------------------------------------------------- ground truth
def load_gt() -> dict:
    """(video, frame) -> verified plate text. UNLABELED rows are never added."""
    labels = json.loads((DS / "gt_labels.json").read_text(encoding="utf-8"))
    out = {}
    for lab in labels["labels"].values():
        if not lab.get("verified"):
            continue
        for lo, hi in lab["applies_to"]["frame_ranges"]:
            for f in range(lo, hi + 1):
                out[(lab["applies_to"]["source_video"], f)] = lab["plate_text"]
    return out


def gt_frame_counts() -> dict:
    """Frames inside each verified range â€” the recall denominator."""
    labels = json.loads((DS / "gt_labels.json").read_text(encoding="utf-8"))
    counts = {}
    for lab in labels["labels"].values():
        if not lab.get("verified"):
            continue
        v = lab["applies_to"]["source_video"]
        counts[v] = counts.get(v, 0) + sum(hi - lo + 1 for lo, hi
                                          in lab["applies_to"]["frame_ranges"])
    return counts


# ------------------------------------------------------------------- detectors
def build_detectors(conf, iou, max_det, imgsz):
    """Two detector callables driven with IDENTICAL inference parameters."""
    from api import _ensure_models
    engine = _ensure_models()
    a_model = engine._plate_model
    b = IranPlateDetectorAdapter()
    b.load()
    b_model = b.model

    def call(model, frame):
        res = model.predict(frame, conf=conf, iou=iou, max_det=max_det, imgsz=imgsz,
                            agnostic_nms=PROTOCOL["agnostic_nms"],
                            half=PROTOCOL["half"], verbose=False)[0]
        boxes = []
        if res.boxes is not None:
            for b_ in res.boxes.data.tolist():
                x1, y1, x2, y2, c, cls = b_
                boxes.append({"bbox": [x1, y1, x2, y2], "confidence": float(c),
                              "class_id": int(cls)})
        return boxes

    return {"detector_a_current": lambda f: call(a_model, f),
            "detector_b_iranplate": lambda f: call(b_model, f)}


def read_frames(interval):
    frames = []
    for v in VIDEOS:
        cap = cv2.VideoCapture(str(ROOT / v))
        idx = 0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            if idx % interval == 0:
                frames.append((v, idx, fr))
            idx += 1
        cap.release()
    return frames


# ------------------------------------------------------------------- main pass
def run_pass(gt, detectors, ocr, frames, conventions, run_tag):
    """One full A/B pass. Returns (records, frame_rows).

    Frame-aligned: frames where a detector produces nothing are recorded with
    detection_status NO_DETECTION and remain in every denominator (task Â§14/Â§16).
    """
    records, frame_rows = [], []
    for video, idx, frame in frames:
        fh, fw = frame.shape[:2]
        ref = gt.get((video, idx))
        for det_name, fn in detectors.items():
            t0 = time.perf_counter()
            boxes = fn(frame)
            det_ms = (time.perf_counter() - t0) * 1000.0
            frame_rows.append({"run": run_tag, "camera": video, "frame": idx,
                           "detector": det_name, "detected": bool(boxes),
                           "n_boxes": len(boxes), "ground_truth": ref,
                           "gt_status": "LABELED" if ref else "UNLABELED"})
            if not boxes:
                for conv in conventions:
                    records.append({
                        "run": run_tag, "camera": video, "frame": idx,
                        "detector": det_name, "convention": conv,
                        "detection_status": "NO_DETECTION", "box_rank": None,
                        "confidence": None, "n_boxes_this_frame": 0,
                        "ocr_text": None, "ocr_confidence": None, "ocr_valid": None,
                        "failed": None, "ground_truth": ref,
                        "gt_status": "LABELED" if ref else "UNLABELED",
                        "exact": None, "char_accuracy": None, "edit_distance": None,
                        "detector_latency_ms": round(det_ms, 4),
                        "ocr_latency_ms": None, "total_latency_ms": None})
                continue

            for rank, bx in enumerate(boxes):
                for conv in conventions:
                    rec = {
                        "run": run_tag, "camera": video, "frame": idx,
                        "detector": det_name, "convention": conv,
                        "detection_status": "DETECTED", "box_rank": rank,
                        "confidence": round(bx["confidence"], 6),
                        "class_id": bx["class_id"],
                        "n_boxes_this_frame": len(boxes),
                        "bbox_float": [round(float(v), 4) for v in bx["bbox"]],
                        "aspect_ratio": round(bx["bbox"][2] / bx["bbox"][3], 4)
                        if bx["bbox"][3] > 0 else None,
                        "bbox_area_ratio": round(
                            ((bx["bbox"][2] - bx["bbox"][0]) * (bx["bbox"][3] - bx["bbox"][1]))
                            / float(fw * fh), 8),
                        "detector_latency_ms": round(det_ms, 4),
                        "ground_truth": ref,
                        "gt_status": "LABELED" if ref else "UNLABELED"}
                    crop, cr = extract_plate_crop(
                        frame, bx["bbox"], convention=conv,
                        clip=PROTOCOL["clip"], pad_x=PROTOCOL["pad_x"],
                        pad_y=PROTOCOL["pad_y"])
                    rec["crop"] = cr.as_dict()
                    rec.update(margins(cr, fw, fh))
                    if crop is None:
                        rec.update({"ocr_text": None, "ocr_confidence": None,
                                    "ocr_valid": None, "failed": True, "exact": None,
                                    "char_accuracy": None, "edit_distance": None,
                                    "ocr_latency_ms": None, "total_latency_ms": None})
                        records.append(rec)
                        continue
                    rec.update(crop_quality(crop))
                    t1 = time.perf_counter()
                    r = ocr.predict(crop)
                    ocr_ms = (time.perf_counter() - t1) * 1000.0
                    text = r["raw_text"] or ""
                    valid = bool(is_valid_iranian(r["raw_text"], r["confidence"] or 0.9))
                    rec.update({"ocr_text": text, "ocr_confidence": r["confidence"],
                                "ocr_valid": valid, "failed": not text.strip(),
                                "ocr_latency_ms": round(ocr_ms, 4),
                                "total_latency_ms": round(det_ms + ocr_ms, 4)})
                    rec.update(score_pair(text, ref) if ref
                               else {"exact": None, "char_accuracy": None,
                                     "edit_distance": None})
                    records.append(rec)
    return records, frame_rows


# ----------------------------------------------------------------- aggregation
def pct(values, p):
    """Nearest-rank percentile; returns None for an empty sample."""
    if not values:
        return None
    v = sorted(values)
    k = min(len(v) - 1, max(0, math.ceil(p / 100.0 * len(v)) - 1))
    return round(float(v[k]), 4)


def ratio(num, den):
    """Always returns numerator AND denominator so no metric hides a base."""
    return {"numerator": num, "denominator": den,
            "value": round(num / den, 4) if den else None}


def summarize(records, frame_rows, convention, run_tag):
    """Per detector Ã— camera. Denominators are explicit everywhere."""
    out = {}
    sel = [r for r in records if r["convention"] == convention and r["run"] == run_tag]
    for det in DETECTORS:
        det_rows = [r for r in sel if r["detector"] == det]
        for scope, pred in (("overall", lambda r: True),
                            ("cam1.mp4", lambda r: r["camera"] == "cam1.mp4"),
                            ("cam2.mp4", lambda r: r["camera"] == "cam2.mp4")):
            rows = [r for r in det_rows if pred(r)]
            fr = [f for f in frame_rows if f["detector"] == det and pred(f)
                  and f["run"] == run_tag]
            detected = [r for r in rows if r["detection_status"] == "DETECTED"]
            labeled = [r for r in rows if r["gt_status"] == "LABELED"]
            unlabeled = [r for r in rows if r["gt_status"] == "UNLABELED"]
            with_ocr = [r for r in detected if r.get("ocr_text") is not None]
            widths = [r["crop"]["crop_width"] for r in detected
                      if r["crop"]["crop_width"] > 0]
            heights = [r["crop"]["crop_height"] for r in detected
                       if r["crop"]["crop_height"] > 0]
            block = {
                "frames_total": len(fr),
                "frames_with_detection": sum(1 for f in fr if f["detected"]),
                "frames_without_detection": sum(1 for f in fr if not f["detected"]),
                "n_boxes": sum(f["n_boxes"] for f in fr),
                "multi_box_frames": sum(1 for f in fr if f["n_boxes"] > 1),
                "detected_crops": len(detected),
                "labeled_crops": len(labeled),
                "unlabeled_crops": len(unlabeled),
                "ocr_attempts": len(with_ocr),
                # --- OCR, verified crops ONLY -----------------------------
                "exact": ratio(sum(1 for r in labeled if r["exact"]), len(labeled)),
                "char_accuracy": ratio(
                    round(sum(r["char_accuracy"] for r in labeled
                              if r["char_accuracy"] is not None), 6), len(labeled)),
                "mean_edit_distance": ratio(
                    round(sum(r["edit_distance"] for r in labeled
                              if r["edit_distance"] is not None), 6), len(labeled)),
                # --- validity / failure, over ALL crops of this scope -----
                "invalid_rate_all_crops": ratio(
                    sum(1 for r in with_ocr if not r["ocr_valid"]), len(with_ocr)),
                "failed_rate_all_crops": ratio(
                    sum(1 for r in with_ocr if r["failed"]), len(with_ocr)),
                # --- geometry ---------------------------------------------
                "median_crop_width": pct(widths, 50),
                "median_crop_height": pct(heights, 50),
                "mean_crop_width": round(statistics.fmean(widths), 4) if widths else None,
                "mean_crop_height": round(statistics.fmean(heights), 4) if heights else None,
                "width_percentiles": {p: pct(widths, p)
                                      for p in (10, 25, 50, 75, 90)},
                "clipping_rate": ratio(
                    sum(1 for r in detected if r["crop"]["clipped_any"]), len(detected)),
                "confidence_mean": round(statistics.fmean(
                    [r["confidence"] for r in detected]), 4) if detected else None,
            }
            out[f"{det}|{scope}"] = block
    return out


def convention_scores(records, run_tag):
    """Non-accuracy evidence used to pick the canonical convention (task Â§31).

    Deliberately excludes GT accuracy so protocol selection cannot leak labels.
    """
    scores = {}
    for conv in CONVENTIONS:
        rows = [r for r in records if r["convention"] == conv and r["run"] == run_tag
                and r["detection_status"] == "DETECTED"]
        degenerate = sum(1 for r in rows if r["crop"]["crop_width"] <= 0
                         or r["crop"]["crop_height"] <= 0)
        # pixels the integer crop loses vs the float box extent (artificial shrink)
        shrinks = 0
        for r in rows:
            c = r["crop"]
            shrinks += max(0, math.ceil(c["x1_float"]) - c["x1_pixel"])
            shrinks += max(0, math.ceil(c["x2_float"]) - c["x2_pixel"])
            shrinks += max(0, math.ceil(c["y1_float"]) - c["y1_pixel"])
            shrinks += max(0, math.ceil(c["y2_float"]) - c["y2_pixel"])
        scores[conv] = {
            "production_equivalent": conv == "trunc",
            "degenerate_count": degenerate,
            "shrinks_box_count": shrinks,
            "n_crops": len(rows),
        }
    return scores


# ---------------------------------------------------------------- crop metrics
def crop_quality(crop):
    """Explanatory image metrics. NOT accuracy claims."""
    if crop is None or crop.size == 0:
        return None
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return {"blur_laplacian_var": round(float(cv2.Laplacian(g, cv2.CV_64F).var()), 3),
            "mean_brightness": round(float(g.mean()), 3),
            "contrast_std": round(float(g.std()), 3),
            "edge_density": round(float((cv2.Canny(g, 80, 160) > 0).mean()), 5)}


def margins(cr, frame_w, frame_h):
    """Pixel margin from the crop to each frame boundary."""
    return {"margin_left": cr.x1_pixel, "margin_top": cr.y1_pixel,
            "margin_right": frame_w - cr.x2_pixel,
            "margin_bottom": frame_h - cr.y2_pixel}


# ---------------------------------------------------------------- paired stats
def mcnemar_exact(b, c):
    """Exact two-sided McNemar (binomial) p-value for discordant pairs.

    b = A correct & B wrong, c = A wrong & B correct, n = b + c.
    No chi-square approximation, so it stays valid for tiny discordant counts.
    """
    n = b + c
    if n == 0:
        return None, n
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return round(min(1.0, 2 * tail), 6), n


def paired(records, convention, run_tag, camera=None):
    """Frame-aligned pairing on verified frames only (task Â§24)."""
    sel = [r for r in records if r["convention"] == convention and r["run"] == run_tag
           and r["gt_status"] == "LABELED"
           and (camera is None or r["camera"] == camera)]
    # best box per (frame, detector) by confidence; NO_DETECTION counts as wrong
    best = {}
    for r in sel:
        k = (r["camera"], r["frame"], r["detector"])
        if r["detection_status"] != "DETECTED":
            best.setdefault(k, {"exact": False, "ocr": None, "status": "NO_DETECTION"})
            continue
        cur = best.get(k)
        if cur is None or (r.get("confidence") or 0) > (cur.get("confidence") or 0):
            best[k] = {"exact": r["exact"], "ocr": r["ocr_text"],
                       "status": "DETECTED", "confidence": r.get("confidence"),
                       "width": r["crop"]["crop_width"]}
    keys = sorted({(c, f) for c, f, _ in best})
    table = {"both_correct": 0, "a_correct_b_wrong": 0, "a_wrong_b_correct": 0,
             "both_wrong": 0}
    ids = {"a_correct_b_wrong": [], "a_wrong_b_correct": [], "both_wrong": []}
    for cam, fr in keys:
        a = best.get((cam, fr, "detector_a_current"))
        b = best.get((cam, fr, "detector_b_iranplate"))
        ok_a = bool(a and a["exact"])
        ok_b = bool(b and b["exact"])
        if ok_a and ok_b:
            table["both_correct"] += 1
        elif ok_a and not ok_b:
            table["a_correct_b_wrong"] += 1
            ids["a_correct_b_wrong"].append(f"{cam}@{fr}")
        elif not ok_a and ok_b:
            table["a_wrong_b_correct"] += 1
            ids["a_wrong_b_correct"].append(f"{cam}@{fr}")
        else:
            table["both_wrong"] += 1
            ids["both_wrong"].append(f"{cam}@{fr}")
    p, n = mcnemar_exact(table["a_correct_b_wrong"], table["a_wrong_b_correct"])
    return {"camera": camera or "all", "table": table, "discordant_pairs": n,
            "mcnemar_exact_p": p, "discordant_ids": ids,
            "verified_frames": len(keys)}


# --------------------------------------------------------------------- buckets
def build_buckets(records, convention, run_tag="run0"):
    """Width-bucket table per detector. N/A where no ground truth exists."""
    out = {}
    for det in DETECTORS:
        rows = [r for r in records if r["run"] == run_tag and r["detector"] == det
                and r["convention"] == convention and r["detection_status"] == "DETECTED"]
        out[det] = {}
        for _, _, name in ((0, 80, "lt80"), (80, 100, "80-99"), (100, 150, "100-149"),
                           (150, 200, "150-199"), (200, 10 ** 9, "ge200")):
            sub = [r for r in rows if bucket_for(r["crop"]["crop_width"]) == name]
            lab = [r for r in sub if r["gt_status"] == "LABELED"]
            with_ocr = [r for r in sub if r.get("ocr_text") is not None]
            out[det][name] = {
                "N": len(sub), "labeled": len(lab),
                "exact": ratio(sum(1 for r in lab if r["exact"]), len(lab)),
                "char_accuracy": ratio(
                    round(sum(r["char_accuracy"] for r in lab
                              if r["char_accuracy"] is not None), 6), len(lab)),
                "invalid": ratio(sum(1 for r in with_ocr if not r["ocr_valid"]),
                                 len(with_ocr)),
                "failed": ratio(sum(1 for r in with_ocr if r["failed"]), len(with_ocr)),
                "median_width": pct([r["crop"]["crop_width"] for r in sub], 50),
                "median_height": pct([r["crop"]["crop_height"] for r in sub], 50),
                "median_ocr_latency_ms": pct([r["ocr_latency_ms"] for r in sub], 50),
                "median_detector_latency_ms": pct([r["detector_latency_ms"] for r in sub], 50),
                "clipping_rate": ratio(sum(1 for r in sub if r["crop"]["clipped_any"]),
                                       len(sub))}
    return out


# -------------------------------------------------------------------- latency
def measure_latency(detectors, ocr, frame, det_samples=100, ocr_samples=100):
    """Steady-state latency only: warm up, discard, then measure (task Â§25)."""
    det_ms = {k: [] for k in detectors}
    ocr_ms, crop_ms, total_ms = [], [], []
    box = None
    for k, fn in detectors.items():
        for _ in range(WARMUP_CALLS):          # >= 20 warm-up calls
            fn(frame)
    for _ in range(det_samples):
        for k, fn in detectors.items():
            t0 = time.perf_counter()
            b = fn(frame)
            det_ms[k].append((time.perf_counter() - t0) * 1000.0)
            if b and box is None:
                box = b[0]["bbox"]
    if box is None:
        return None
    for _ in range(WARMUP_CALLS):
        c, _ = extract_plate_crop(frame, box, convention=PROTOCOL["crop_convention"])
        if c is not None:
            ocr.predict(c)
    for _ in range(ocr_samples):
        t0 = time.perf_counter()
        c, _ = extract_plate_crop(frame, box, convention=PROTOCOL["crop_convention"])
        t1 = time.perf_counter()
        crop_ms.append((t1 - t0) * 1000.0)
        ocr.predict(c)
        t2 = time.perf_counter()
        ocr_ms.append((t2 - t1) * 1000.0)
        total_ms.append((t2 - t0) * 1000.0)

    def stats(v):
        return {"p50": pct(v, 50), "p95": pct(v, 95), "p99": pct(v, 99),
                "mean": round(statistics.fmean(v), 4), "max": round(max(v), 4),
                "n": len(v)}
    return {"detector": {k: stats(v) for k, v in det_ms.items()},
            "crop_extraction": stats(crop_ms), "ocr": stats(ocr_ms),
            "total": stats(total_ms), "warmup_calls": WARMUP_CALLS,
            "measured_calls": det_samples}


def environment():
    import torch
    import ultralytics
    return {"python": platform.python_version(), "torch": torch.__version__,
            "ultralytics": ultralytics.__version__, "opencv": cv2.__version__,
            "cuda_available": torch.cuda.is_available(),
            "platform": platform.platform(), "processor": platform.processor(),
            "cpu_count": __import__("os").cpu_count()}


def run_expansion(gt, detectors, ocr, frames, run_tag="expand"):
    """Crop-expansion experiment (task §22).

    Identical expansion for both arms. Answers: is any difference a detector
    localization problem, or simply a too-tight box?
    """
    rows = []
    for video, idx, frame in frames:
        ref = gt.get((video, idx))
        for det_name, fn in detectors.items():
            boxes = fn(frame)
            for bx in boxes:
                for factor in EXPAND_FACTORS:
                    ebox = expand_box(bx["bbox"], factor)
                    crop, cr = extract_plate_crop(
                        frame, ebox, convention=PROTOCOL["crop_convention"],
                        clip=PROTOCOL["clip"])
                    rec = {"run": run_tag, "camera": video, "frame": idx,
                           "detector": det_name, "expand": factor,
                           "crop_width": cr.crop_width, "crop_height": cr.crop_height,
                           "ground_truth": ref,
                           "gt_status": "LABELED" if ref else "UNLABELED"}
                    if crop is None:
                        rec.update({"ocr_text": None, "ocr_valid": None, "failed": True,
                                    "exact": None, "char_accuracy": None,
                                    "latency_ms": None})
                    else:
                        t0 = time.perf_counter()
                        r = ocr.predict(crop)
                        rec["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 4)
                        text = r["raw_text"] or ""
                        rec.update({
                            "ocr_text": text,
                            "ocr_valid": bool(is_valid_iranian(
                                r["raw_text"], r["confidence"] or 0.9)),
                            "failed": not text.strip()})
                        rec.update(score_pair(text, ref) if ref
                                   else {"exact": None, "char_accuracy": None})
                    rows.append(rec)
    return rows


def summarize_expansion(rows):
    out = {}
    for det in DETECTORS:
        out[det] = {}
        for factor in EXPAND_FACTORS:
            sub = [r for r in rows if r["detector"] == det and r["expand"] == factor]
            lab = [r for r in sub if r["gt_status"] == "LABELED"]
            with_ocr = [r for r in sub if r.get("ocr_text") is not None]
            out[det][f"{factor:.2f}"] = {
                "N": len(sub), "labeled": len(lab),
                "exact": ratio(sum(1 for r in lab if r["exact"]), len(lab)),
                "char_accuracy": ratio(
                    round(sum(r["char_accuracy"] for r in lab
                              if r["char_accuracy"] is not None), 6), len(lab)),
                "invalid": ratio(sum(1 for r in with_ocr if not r["ocr_valid"]),
                                 len(with_ocr)),
                "failed": ratio(sum(1 for r in with_ocr if r["failed"]), len(with_ocr)),
                "median_width": pct([r["crop_width"] for r in sub], 50),
                "median_height": pct([r["crop_height"] for r in sub], 50),
                "median_latency_ms": pct([r["latency_ms"] for r in sub], 50)}
    return out


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--conf", type=float, default=PROTOCOL["conf"])
    ap.add_argument("--max-det", type=int, default=PROTOCOL["max_det"])
    ap.add_argument("--iou", type=float, default=PROTOCOL["iou"])
    ap.add_argument("--latency", action="store_true")
    ap.add_argument("--expand", action="store_true", help="crop expansion sweep")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    AUDIT.mkdir(parents=True, exist_ok=True)

    gt = load_gt()
    frames = read_frames(args.interval)
    ocr = ProductionOCRAdapter()
    ocr.is_available()
    detectors = build_detectors(args.conf, args.iou, args.max_det, PROTOCOL["imgsz"])

    all_records, all_frame_rows = [], []
    for run_i in range(args.repeats):
        recs, frows = run_pass(gt, detectors, ocr, frames, CONVENTIONS, f"run{run_i}")
        all_records += recs
        all_frame_rows += frows
        print(f"  pass {run_i}: {len(recs)} records", flush=True)

    scores = convention_scores(all_records, "run0")
    canonical, canon_reasons = select_canonical(scores)
    PROTOCOL["crop_convention"] = canonical
    print(f"canonical convention = {canonical} :: {canon_reasons}", flush=True)

    # repeatability (task Â§26) â€” compares real outcomes, not just counts
    repeat = {"runs": args.repeats}
    if args.repeats > 1:
        for det in DETECTORS:
            sig = []
            for run_i in range(args.repeats):
                rows = [r for r in all_records if r["run"] == f"run{run_i}"
                        and r["detector"] == det and r["convention"] == canonical]
                detr = [r for r in rows if r["detection_status"] == "DETECTED"]
                lab = [r for r in rows if r["gt_status"] == "LABELED"]
                sig.append({"n_boxes": sum(r["n_boxes_this_frame"] for r in detr),
                            "n_detected": len(detr),
                            "n_exact": sum(1 for r in lab if r["exact"]),
                            "n_labeled": len(lab),
                            "n_invalid": sum(1 for r in detr
                                             if r.get("ocr_valid") is False)})
            repeat[det] = sig
        repeat["identical"] = all(
            len({json.dumps(s, sort_keys=True) for s in repeat[d]}) == 1
            for d in DETECTORS)

    summary = {f"run{i}": summarize(all_records, all_frame_rows, canonical, f"run{i}")
               for i in range(args.repeats)}
    paired_all = paired(all_records, canonical, "run0")
    paired_cam1 = paired(all_records, canonical, "run0", camera="cam1.mp4")
    buckets = build_buckets(all_records, canonical)

    out_raw = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "protocol": PROTOCOL, "environment": environment(),
               "interval": args.interval, "gt_frame_counts": gt_frame_counts(),
               "records": all_records, "frame_rows": all_frame_rows}
    (RESULTS / "phase2c_raw_results.json").write_text(
        json.dumps(out_raw, ensure_ascii=False, indent=1), encoding="utf-8")

    out_sum = {"generated_at": out_raw["generated_at"], "protocol": PROTOCOL,
               "environment": environment(),
               "canonical_convention": canonical,
               "canonical_selection_reasons": canon_reasons,
               "convention_scores_non_accuracy": scores,
               "repeatability": repeat,
               "per_run_summary": summary,
               "paired_statistics": {"all": paired_all, "cam1": paired_cam1},
               "buckets": buckets,
               "ground_truth": {
                   "policy": "verified_only", "verified_plate_instances": 2,
                   "cam1_frames_in_verified_ranges": gt_frame_counts().get("cam1.mp4"),
                   "cam2_frames_in_verified_ranges": gt_frame_counts().get("cam2.mp4", 0),
                   "cam2_status": "UNLABELED",
                   "box_ground_truth": "NO_BOX_GROUND_TRUTH"}}
    (RESULTS / "phase2c_summary.json").write_text(
        json.dumps(out_sum, ensure_ascii=False, indent=1), encoding="utf-8")

    (RESULTS / "phase2c_bucket_results.json").write_text(
        json.dumps({"generated_at": out_raw["generated_at"],
                    "canonical_convention": canonical, "buckets": buckets},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    lat = None
    if args.latency:
        lat = measure_latency(detectors, ocr, frames[0][2])
        (RESULTS / "phase2c_latency.json").write_text(
            json.dumps({"generated_at": out_raw["generated_at"],
                        "environment": environment(), "latency": lat},
                       ensure_ascii=False, indent=1), encoding="utf-8")

    if args.expand:
        exp_rows = run_expansion(gt, detectors, ocr, frames)
        exp_sum = summarize_expansion(exp_rows)
        (RESULTS / "phase2c_crop_results.json").write_text(
            json.dumps({"generated_at": out_raw["generated_at"],
                        "canonical_convention": canonical,
                        "expand_factors": list(EXPAND_FACTORS),
                        "summary": exp_sum, "rows": exp_rows},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        print("expansion written", flush=True)

    print(json.dumps({"canonical": canonical, "reasons": canon_reasons,
                      "repeatable": repeat.get("identical"),
                      "paired_all": paired_all["table"],
                      "discordant": paired_all["discordant_pairs"],
                      "mcnemar_p": paired_all["mcnemar_exact_p"],
                      "a_cam1": summary["run0"]["detector_a_current|cam1.mp4"],
                      "b_cam1": summary["run0"]["detector_b_iranplate|cam1.mp4"]},
                     ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()
