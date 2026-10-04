"""Phase 3 — ALPR evaluation dataset + ground-truth +
localization benchmark runner.

One command regenerates the benchmark:

    python benchmarks/run_phase3.py [--skip-visuals]

Outputs (benchmarks/results/phase3/):
    dataset_summary.json      composition tables
    detector_evaluation.json  counts (diagnostic) + matching
                              infra status (NOT_AVAILABLE:
                              no box GT)
    ocr_evaluation.json       exact/char/edit/invalid/failed
                              with cam1 breakdowns
    crop_robustness.json      detector x convention x
                              expansion x size-bucket x
                              camera x instance
    temporal_consistency.json per-instance evidence rows
    performance.json          cold / warm-up / steady state
    hard_cases.json           curated difficult examples
    model_cards.json          A + B (usable weights only)
    diagnostics/              overlays, crop strips, OCR
                              examples + index

Hard rules honored: production source, weights, crop
convention, thresholds and API are NEVER touched. The
detector/OCR model objects are only *called*, exactly as
in Phases 2B/2C/2D.
"""
from __future__ import annotations

import argparse
import hashlib
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

from adapters.registry import ProductionOCRAdapter  # noqa: E402
from metrics import is_valid_iranian  # noqa: E402
from normalization import normalize_plate_text  # noqa: E402
from phase2d_crop import (  # noqa: E402
    CONVENTIONS as CROP_CONVENTIONS, extract_crop)
from phase3_build_dataset import (  # noqa: E402
    PROTOCOL, VIDEOS, build, build_detectors, sha256_file)
from phase3_dataset import (  # noqa: E402
    DATASET_DIR, SAMPLING_INTERVAL, quality_properties,
    width_bucket)
from phase3_metrics import (  # noqa: E402
    aggregate_detection, aggregate_ocr, group_by,
    mcnemar_exact, pct, ratio, score_ocr_record,
    temporal_consistency, wilson_ci)
from phase3_normalization import (  # noqa: E402
    normalize_to_ascii)

RESULTS = ROOT / "benchmarks" / "results" / "phase3"
AUDIT = ROOT / "benchmarks" / "audit" / "phase3"

EXPANSIONS = (1.00, 1.03, 1.05, 1.07, 1.10)
CONVENTIONS = ("trunc", "floor", "round", "ceil")


# ------------------------------------------------------------------ cards
def model_cards() -> dict:
    from api import _ensure_models
    from adapters.registry import IranPlateDetectorAdapter
    engine = _ensure_models()
    b = IranPlateDetectorAdapter()
    b.load()

    def names(m):
        try:
            return dict(m.names or {})
        except Exception:
            return {}

    return {
        "detector_a_current": {
            "role": "CURRENT_PRODUCTION baseline",
            "model_path":
                "weigths/plate_det_model.pt",
            "sha256": sha256_file(
                ROOT / "weigths" / "plate_det_model.pt"),
            "architecture": "ultralytics-YOLO plate "
                            "detector",
            "classes": names(engine._plate_model),
            "input_size": 640,
            "inference_parameters": PROTOCOL,
            "license": "repo LICENSE (production asset)",
            "source": "project weights (weigths/)",
            "benchmark_configuration": "protocol-frozen "
                "call site; no adapter defaults",
        },
        "detector_b_iranplate": {
            "role": "IranPlate-Vision candidate "
                    "(evaluation only)",
            "model_path": "bench/IranPlate-Vision-main/"
                "IranPlate-Vision-main/best.pt",
            "sha256": sha256_file(
                ROOT / "bench" / "IranPlate-Vision-main" /
                "IranPlate-Vision-main" / "best.pt"),
            "architecture": "ultralytics-YOLO plate "
                            "detector",
            "classes": names(b.model),
            "input_size": 640,
            "inference_parameters": PROTOCOL,
            "license": "unknown — no LICENSE file in the "
                       "bench checkout; evaluation-only "
                       "use in this benchmark; verify "
                       "before any other use",
            "source": "bench/IranPlate-Vision-main",
            "benchmark_configuration": "protocol-frozen "
                "call site; no adapter defaults",
        },
        "ocr_production": {
            "role": "CURRENT_PRODUCTION baseline "
                    "(AlprEngine._assemble_chars)",
            "model_path": "weigths/char_model.pt",
            "sha256": sha256_file(
                ROOT / "weigths" / "char_model.pt"),
            "architecture": "ultralytics-YOLO character "
                            "detector + x1-sort assembly",
            "input_size": "plate crop as-is (char YOLO "
                          "letterboxes internally)",
            "inference_parameters":
                {"conf": 0.3, "iou": 0.45},
            "license": "repo LICENSE (production asset)",
            "source": "project weights (weigths/)",
        },
    }


# -------------------------------------------------------------- OCR matrix
def evaluate_crop(frame, box, ocr, convention,
                  expansion) -> dict:
    t0 = time.perf_counter()
    r = extract_crop(frame, box["bbox"],
                     convention=convention,
                     expansion=expansion, clip=True)
    crop_ms = (time.perf_counter() - t0) * 1000.0
    rec = {"convention": convention, "expansion": expansion,
           "bbox_float": [round(float(v), 4)
                          for v in box["bbox"]],
           "integer_bbox": list(r["integer_bbox"]),
           "crop_width": r["effective_width"],
           "crop_height": r["effective_height"],
           "clipping": r["clipping_status"],
           "invalid_crop": r["invalid"],
           "crop_latency_ms": round(crop_ms, 4)}
    if r["invalid"] or r["crop"] is None:
        rec.update({"ocr_text": None,
                    "ocr_confidence": None,
                    "ocr_valid": None, "failed": True,
                    "ocr_latency_ms": None})
        return rec
    t1 = time.perf_counter()
    out = ocr.predict(r["crop"])
    ocr_ms = (time.perf_counter() - t1) * 1000.0
    text = out["raw_text"] or ""
    rec.update({
        "ocr_text": text,
        "ocr_normalized": normalize_plate_text(text),
        "ocr_confidence": out["confidence"],
        "ocr_valid": bool(is_valid_iranian(
            text, out["confidence"] or 0.9)),
        "failed": not text.strip(),
        "ocr_latency_ms": round(ocr_ms, 4)})
    return rec


def environment() -> dict:
    import os

    import torch
    import ultralytics
    try:
        import psutil
        ram = round(psutil.virtual_memory().total
                    / (1024 ** 3), 2)
    except Exception:
        ram = None
    return {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "ultralytics": ultralytics.__version__,
        "opencv": cv2.__version__,
        "cuda_available": torch.cuda.is_available(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "ram_gb": ram,
    }


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-visuals", action="store_true")
    ap.add_argument("--skip-slow-ocr", action="store_true",
                    help="currently unused; reserved")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    AUDIT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")

    # ---- 1. dataset -----------------------------------------
    ds = build()

    # ---- 2. model cards + cold start ------------------------
    # Cold start MUST be measured in a FRESH process:
    # _ensure_models is a singleton, so any in-process
    # timing after the first call measures the cache.
    cold = measure_cold_start()
    cards = model_cards()

    ocr = ProductionOCRAdapter()
    ocr.is_available()
    detectors = build_detectors()

    # ---- 3. crop x OCR matrix --------------------------------
    # unique configs: 4 conventions @1.00 + 4 expansions
    # @trunc (1.00x-trunc == trunc-convention duplicate
    # removed)
    configs = [("trunc", 1.00), ("floor", 1.00),
               ("round", 1.00), ("ceil", 1.00),
               ("trunc", 1.03), ("trunc", 1.05),
               ("trunc", 1.07), ("trunc", 1.10)]

    # decode sampled frames once
    frames = {}
    for cam, video in VIDEOS.items():
        cap = cv2.VideoCapture(str(video))
        idx = 0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            if idx % SAMPLING_INTERVAL == 0:
                frames[(cam, idx)] = fr
            idx += 1
        cap.release()

    # annotation index: (camera, frame) -> GT record
    gt_index = {(a["camera_id"], a["frame_id"]): a
                for a in ds["annotations"]}

    records = []
    for (cam, f), frame in sorted(frames.items()):
        gt = gt_index.get((cam, f))
        per_det = ds["detections"].get((cam, f), {})
        for det in ("detector_a_current",
                    "detector_b_iranplate"):
            for bx in per_det.get(det, []):
                for conv, exp in configs:
                    rec = {
                        "camera": cam, "frame": f,
                        "detector": det,
                        "convention": conv,
                        "expansion": exp,
                        "confidence": bx["confidence"],
                        "ground_truth":
                            gt["plate_text_ascii"]
                            if gt and gt[
                                "annotation_status"]
                            == "verified" else None,
                        "verified":
                            gt is not None and gt[
                                "annotation_status"]
                            == "verified",
                        "vehicle_instance_id":
                            gt["vehicle_instance_id"]
                            if gt else None,
                        "plate_instance_id":
                            gt["plate_instance_id"]
                            if gt else None,
                    }
                    rec.update(evaluate_crop(
                        frame, bx, ocr, conv, exp))
                    rec.update(score_ocr_record(
                        rec.get("ocr_text"),
                        rec.get("ocr_confidence"),
                        rec.get("ground_truth")))
                    w = rec["crop_width"]
                    rec["width_bucket"] = width_bucket(
                        w if w > 0 else None)
                    records.append(rec)

    # ---- 4. OCR evaluation + breakdowns ----------------------
    ocr_eval = {}
    for det in ("detector_a_current",
                "detector_b_iranplate"):
        for conv, exp in configs:
            key = f"{det}|{conv}|{exp:.2f}"
            rows = [r for r in records
                    if r["detector"] == det
                    and r["convention"] == conv
                    and r["expansion"] == exp]
            verified = [r for r in rows if r["verified"]]
            ocr_eval[key] = {
                "overall_cam1_verified":
                    aggregate_ocr(
                        verified,
                        label=key + "|cam1_verified"),
                "n_crops": len(rows),
                "n_verified_crops": len(verified),
                "n_unlabeled_crops":
                    len(rows) - len(verified),
            }
            for dim, fn in (
                    ("by_camera", lambda r: r["camera"]),
                    ("by_instance",
                     lambda r: r["vehicle_instance_id"]),
                    ("by_width",
                     lambda r: r["width_bucket"]),
                    ("by_detector",
                     lambda r: r["detector"])):
                groups = group_by(verified, fn)
                ocr_eval[key][dim] = {
                    k: aggregate_ocr(v, label=f"{key}|{k}")
                    for k, v in sorted(groups.items())
                    if k != "None"}

    # ---- 5. detector evaluation ------------------------------
    det_eval = {}
    for det in ("detector_a_current",
                "detector_b_iranplate"):
        for cam in ("cam1", "cam2"):
            n_frames = sum(
                1 for (c, _f) in frames if c == cam)
            with_det = sum(
                1 for (c, f) in frames if c == cam
                and ds["detections"].get(
                    (c, f), {}).get(det))
            det_eval[f"{det}|{cam}"] = {
                **aggregate_detection(
                    None, label=f"{det}|{cam}"),
                "frames_sampled": n_frames,
                "frames_with_detection": with_det,
                "frames_without_detection":
                    n_frames - with_det,
                "diagnostic_note": "counts only, not "
                    "recall: no box GT exists",
            }

    # paired A/B on verified frames (production OCR,
    # trunc convention)
    paired_rows = [r for r in records
                   if r["convention"] == "trunc"
                   and r["expansion"] == 1.00
                   and r["verified"]]
    best = {}
    for r in paired_rows:
        k = (r["camera"], r["frame"], r["detector"])
        cur = best.get(k)
        if cur is None or (r["confidence"] or 0) > (
                cur.get("confidence") or 0):
            best[k] = r
    tbl = {"both_correct": 0,
           "a_correct_b_wrong": 0,
           "a_wrong_b_correct": 0, "both_wrong": 0}
    ids = {"a_correct_b_wrong": [],
           "a_wrong_b_correct": [], "both_wrong": []}
    for cam, f in sorted({(c, fr) for c, fr, _ in best}):
        a = best.get((cam, f, "detector_a_current"))
        b = best.get((cam, f, "detector_b_iranplate"))
        oka = bool(a and a["exact"])
        okb = bool(b and b["exact"])
        if oka and okb:
            tbl["both_correct"] += 1
        elif oka and not okb:
            tbl["a_correct_b_wrong"] += 1
            ids["a_correct_b_wrong"].append(f"{cam}@{f}")
        elif not oka and okb:
            tbl["a_wrong_b_correct"] += 1
            ids["a_wrong_b_correct"].append(f"{cam}@{f}")
        else:
            tbl["both_wrong"] += 1
            ids["both_wrong"].append(f"{cam}@{f}")
    mc = mcnemar_exact(tbl["a_correct_b_wrong"],
                       tbl["a_wrong_b_correct"])
    det_eval["paired_AB_verified_trunc"] = {
        "table": tbl, "discordant_ids": ids,
        "mcnemar": mc,
        "verified_frames": len(
            {(c, fr) for c, fr, _ in best})}

    # ---- 6. temporal consistency -----------------------------
    temporal = {}
    for v in ds["vehicles"]:
        vid = v["vehicle_instance_id"]
        obs = []
        for r in records:
            if r["vehicle_instance_id"] == vid \
                    and r["detector"] == "detector_a_current" \
                    and r["convention"] == "trunc" \
                    and r["expansion"] == 1.00:
                obs.append({
                    "frame_id": r["frame"],
                    "ocr_text": r.get("ocr_text"),
                    "ocr_normalized":
                        r.get("ocr_normalized"),
                    "ocr_valid": r.get("ocr_valid"),
                    "failed": r.get("failed"),
                    "exact": r.get("exact"),
                    "confidence":
                        r.get("confidence")})
        obs.sort(key=lambda s: s["frame_id"])
        temporal[vid] = {
            "camera": v["camera_id"],
            "verified": v["annotation_status"] ==
            "verified_text_pending_box",
            **temporal_consistency(obs)}

    # ---- 7. performance --------------------------------------
    perf = measure_performance(detectors, ocr, frames)

    # ---- 8. hard cases ---------------------------------------
    hard = build_hard_cases(records, ds, frames)

    # ---- 9. visuals ------------------------------------------
    visuals_index = []
    if not args.skip_visuals:
        from benchmarks import phase3_visuals as vis
        vis.ensure_dirs()
        visuals_index = build_visuals(
            vis, records, ds, frames)

    # ---- 10. dataset summary ---------------------------------
    ds_summary = dataset_summary(ds)

    payloads = {
        "dataset_summary": {
            "generated_at": stamp, **ds_summary},
        "detector_evaluation": {
            "generated_at": stamp,
            "protocol": PROTOCOL,
            "evaluation": det_eval},
        "ocr_evaluation": {
            "generated_at": stamp,
            "protocol": PROTOCOL,
            "evaluation": ocr_eval},
        "crop_robustness": {
            "generated_at": stamp,
            "protocol": PROTOCOL,
            "configs": [
                {"convention": c, "expansion": e}
                for c, e in configs],
            "note": "per-cell exact/invalid/failed are in "
                    "ocr_evaluation; this file carries the "
                    "cell inventory and clipping"},
        "temporal_consistency": {
            "generated_at": stamp, **temporal},
        "performance": {
            "generated_at": stamp,
            "environment": environment(),
            "cold_start": cold,
            **perf},
        "hard_cases": hard,
        "model_cards": {
            "generated_at": stamp, **cards},
    }
    for name, payload in payloads.items():
        (RESULTS / f"phase3_{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False,
                       indent=1), encoding="utf-8")

    (RESULTS / "phase3_crop_cells.json").write_text(
        json.dumps({"generated_at": stamp,
                    "cells": crop_cell_summary(records)},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")

    # hard cases also live in the dataset tree (§32)
    (DATASET_DIR / "hard_cases.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False)
                   for c in hard["cases"]) + "\n",
        encoding="utf-8")

    print(f"records: {len(records)}", flush=True)
    print(f"verified OCR exact (A|trunc|1.00, cam1): "
          f"{ocr_eval['detector_a_current|trunc|1.00']}"
          f"['overall_cam1_verified']['exact']",
          flush=True)
    print(f"visual artifacts: {len(visuals_index)} "
          f"sections", flush=True)
    return {"records": records, "dataset": ds,
            "payloads": payloads,
            "visuals_index": visuals_index}


# ------------------------------------------------------------ helpers
def measure_cold_start() -> dict:
    """Cold start in a FRESH subprocess (the model loader
    is a singleton, so in-process timing would measure
    the cache). Reports process start + import +
    model-load wall time, and model-load-only time."""
    import subprocess
    code = (
        "import sys, time; "
        "sys.path.insert(0, '.'); "
        "t0 = time.perf_counter(); "
        "from api import _ensure_models; "
        "t1 = time.perf_counter(); "
        "engine = _ensure_models(); "
        "t2 = time.perf_counter(); "
        "print(f'{t1 - t0:.3f} {t2 - t1:.3f} "
        "{t2 - t0:.3f}')")
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True,
        text=True, cwd=str(ROOT), timeout=600)
    wall = round(time.perf_counter() - t0, 3)
    out = {"subprocess_ok": proc.returncode == 0,
           "subprocess_wall_s": wall,
           "note": "fresh process; singleton cache "
                   "cannot leak in"}
    if proc.returncode == 0:
        try:
            imp, load, total = proc.stdout.strip(
                ).split()[-3:]
            out.update({
                "import_api_s": float(imp),
                "model_load_s": float(load),
                "process_total_s": float(total)})
        except Exception as exc:  # noqa: BLE001
            out["parse_error"] = str(exc)
            out["stdout_tail"] = proc.stdout[-500:]
    else:
        out["stderr_tail"] = proc.stderr[-1000:]
    return out


def measure_performance(detectors, ocr, frames):
    from phase2d_crop import extract_crop  # noqa: E402
    (cam, f), frame = sorted(frames.items())[0]
    boxes = detectors["detector_a_current"](frame)
    box = max(boxes,
              key=lambda b: b["confidence"])["bbox"]
    warm, measured = 20, 100
    det_ms = {k: [] for k in detectors}
    for fn in detectors.values():
        for _ in range(warm):
            fn(frame)
    for _ in range(measured):
        for name, fn in detectors.items():
            t0 = time.perf_counter()
            fn(frame)
            det_ms[name].append(
                (time.perf_counter() - t0) * 1000.0)
    crop_ms, ocr_ms, total_ms = [], [], []
    for _ in range(warm):
        c = extract_crop(frame, box, "trunc", 1.0)
        ocr.predict(c["crop"])
    for _ in range(measured):
        t0 = time.perf_counter()
        c = extract_crop(frame, box, "trunc", 1.0)
        t1 = time.perf_counter()
        ocr.predict(c["crop"])
        t2 = time.perf_counter()
        crop_ms.append((t1 - t0) * 1000.0)
        ocr_ms.append((t2 - t1) * 1000.0)
        total_ms.append((t2 - t0) * 1000.0)

    def stats(v):
        return {"p50": pct(v, 50), "p95": pct(v, 95),
                "max": round(float(max(v)), 4), "n": len(v)}
    return {"warmup_calls": warm,
            "measured_calls": measured,
            "detector": {k: stats(v)
                         for k, v in det_ms.items()},
            "crop_extraction_trunc": stats(crop_ms),
            "ocr": stats(ocr_ms),
            "total_crop_plus_ocr": stats(total_ms),
            "note": "steady-state only; model load "
                    "reported separately as "
                    "cold_model_load_s; warm-up "
                    "excluded (20 calls)"}


def crop_cell_summary(records):
    cells = {}
    for r in records:
        key = (r["detector"], r["convention"],
               f"{r['expansion']:.2f}",
               r["camera"],
               r["vehicle_instance_id"] or "UNLABELED",
               r["width_bucket"] or "unknown")
        c = cells.setdefault(
            "|".join(str(x) for x in key),
            {"n_crops": 0, "n_verified": 0,
             "n_exact": 0, "n_invalid": 0,
             "n_failed": 0, "n_clipped": 0,
             "widths": []})
        c["n_crops"] += 1
        if r["verified"]:
            c["n_verified"] += 1
            if r["exact"]:
                c["n_exact"] += 1
        if r.get("ocr_text") is not None:
            if not r.get("ocr_valid"):
                c["n_invalid"] += 1
            if r.get("failed"):
                c["n_failed"] += 1
        if r["clipping"]["any"]:
            c["n_clipped"] += 1
        c["widths"].append(r["crop_width"])
    out = {}
    for k, c in sorted(cells.items()):
        out[k] = {
            "n_crops": c["n_crops"],
            "n_verified": c["n_verified"],
            "exact": ratio(c["n_exact"], c["n_verified"])
            if c["n_verified"] else None,
            "invalid": ratio(c["n_invalid"],
                             c["n_crops"]),
            "failed": ratio(c["n_failed"],
                            c["n_crops"]),
            "clipped": ratio(c["n_clipped"],
                             c["n_crops"]),
            "median_crop_width": pct(c["widths"], 50)}
    return out


def dataset_summary(ds):
    anns = ds["annotations"]
    verified = [a for a in anns
                if a["annotation_status"] == "verified"]
    prov = [a for a in anns
            if a["annotation_status"] != "verified"]
    widths = [a["measurements"].get("plate_width_px")
              for a in anns
              if a["measurements"].get(
                  "plate_width_px")]
    return {
        "cameras": list(ds["cameras"]),
        "n_cameras": len(ds["cameras"]),
        "n_sessions": len(ds["sessions"]),
        "n_vehicle_instances": len(ds["vehicles"]),
        "n_verified_vehicle_instances": sum(
            1 for v in ds["vehicles"]
            if v["annotation_status"] ==
            "verified_text_pending_box"),
        "n_annotations": len(anns),
        "n_verified_text": len(verified),
        "n_provisional_or_pending": len(prov),
        "n_verified_boxes": sum(
            1 for a in anns
            if a["box_annotation_status"] ==
            "annotated"),
        "n_readable": sum(
            1 for a in anns
            if a["readability"] in ("EXCELLENT", "GOOD",
                                    "FAIR", "POOR")),
        "n_unreadable": sum(
            1 for a in anns
            if a["readability"] == "UNREADABLE"),
        "n_pending_review": sum(
            1 for a in anns
            if a["readability"] ==
            "PENDING_HUMAN_REVIEW"),
        "n_frames": len(ds["frame_rows"]),
        "n_sampled_frames_cam1": sum(
            1 for f in ds["frame_rows"]
            if f["camera_id"] == "cam1"),
        "n_sampled_frames_cam2": sum(
            1 for f in ds["frame_rows"]
            if f["camera_id"] == "cam2"),
        "splits": {k: len(v) for k, v in
                   ds["splits"]["splits"].items()},
        "n_readable": sum(
            1 for a in anns
            if a["readability"] in ("EXCELLENT", "GOOD",
                                    "FAIR", "POOR")),
        "n_unreadable": sum(
            1 for a in anns
            if a["readability"] == "UNREADABLE"),
        "n_pending_review": sum(
            1 for a in anns
            if a["readability"] ==
            "PENDING_HUMAN_REVIEW"),
        "plate_width": {
            "min": min(widths) if widths else None,
            "p25": pct(widths, 25),
            "median": pct(widths, 50),
            "p75": pct(widths, 75),
            "max": max(widths) if widths else None,
        },
    }


def build_hard_cases(records, ds, frames):
    """Curated difficult examples for future Imajev-4B
    evaluation. Every entry carries its evidence; none
    carries a verdict."""
    cases = []

    def add(kind, recs, reason):
        for r in recs:
            cases.append({
                "kind": kind, "reason": reason,
                "camera": r["camera"], "frame": r["frame"],
                "detector": r["detector"],
                "convention": r["convention"],
                "expansion": r["expansion"],
                "integer_bbox": r["integer_bbox"],
                "crop_width": r["crop_width"],
                "ocr_text": r.get("ocr_text"),
                "ground_truth":
                    r.get("ground_truth"),
                "verified": r.get("verified"),
            })

    trunc_a = [r for r in records
               if r["convention"] == "trunc"
               and r["expansion"] == 1.00]
    # tiny plates
    tiny = [r for r in trunc_a
            if r["crop_width"] < 96
            and r["detector"] ==
            "detector_a_current"][:25]
    add("tiny_plate", tiny,
        "plate width < 96px (small-object regime)")
    # wrong verified reads
    wrong = [r for r in trunc_a
             if r["verified"] and r["exact"] is False]
    add("verified_wrong_read", wrong,
        "OCR disagrees with verified GT")
    # invalid plausible reads (grammar violations)
    inv = [r for r in trunc_a
           if r.get("ocr_text") and not r.get(
               "ocr_valid")]
    add("invalid_output", inv[:25],
        "output violates Iranian plate grammar")
    # ambiguous transcription (plate A letter)
    amb = [r for r in trunc_a
           if r.get("vehicle_instance_id")
           == "cam1_s001_v001"][:5]
    add("confusing_characters", amb,
        "instance carries a documented ی/ع glyph "
        "ambiguity")
    # detector misses: verified cam1 frames with no
    # detection by B (diagnostic, not recall)
    misses = []
    for a in ds["annotations"]:
        if a["annotation_status"] != "verified":
            continue
        det_b = [r for r in trunc_a
                 if r["camera"] == a["camera_id"]
                 and r["frame"] == a["frame_id"]
                 and r["detector"] ==
                 "detector_b_iranplate"]
        if not det_b:
            misses.append({
                "camera": a["camera_id"],
                "frame": a["frame_id"],
                "detector": "detector_b_iranplate",
                "convention": "trunc",
                "expansion": 1.00,
                "integer_bbox": None,
                "crop_width": 0,
                "ocr_text": None,
                "ground_truth":
                    a["plate_text_ascii"],
                "verified": True})
    cases.extend({"kind": "detector_miss",
                  "reason": "verified frame with no "
                            "Detector B crop (count, "
                            "not recall)",
                  **m} for m in misses)
    # cam2 pending-review samples (Phase-2B 22)
    pending = [r for r in trunc_a
               if r["camera"] == "cam2"
               and r["detector"] ==
               "detector_a_current"
               and r["verified"] is False][:22]
    add("unverified_cam2_sample", pending,
        "cam2 crop pending human verification")
    return {"n_hard_cases": len(cases),
            "cases": cases}


def build_visuals(vis, records, ds, frames):
    sections = []
    dirs = {"overlays": AUDIT / "overlays",
            "crop_strips": AUDIT / "crop_strips",
            "ocr_examples": AUDIT / "ocr_examples"}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    # ---- overlays: one per verified cam1 frame (A+B) ---
    items = []
    for (cam, f), frame in sorted(frames.items()):
        if cam != "cam1":
            continue
        gt = next((a for a in ds["annotations"]
                   if a["camera_id"] == cam
                   and a["frame_id"] == f), None)
        if gt is None or gt["annotation_status"] != \
                "verified":
            continue
        preds = []
        for r in records:
            if r["camera"] == cam and r["frame"] == f \
                    and r["convention"] == "trunc" \
                    and r["expansion"] == 1.00:
                preds.append(r)
        img = vis.detection_overlay(
            frame, None, preds,
            title=f"{cam} frame {f} "
                  f"GT={gt['plate_text_ascii']} "
                  f"(box GT pending)")
        name = f"{cam}_f{f:05d}.png"
        cv2.imwrite(str(dirs["overlays"] / name), img)
        items.append(vis.manifest_entry(
            "overlay", f"overlays/{name}",
            f"{cam}@{f}",
            f"GT text {gt['plate_text_ascii']}; "
            f"{len(preds)} detector crops"))
    sections.append({
        "title": "Detector overlays (cam1 verified "
                 "frames)",
        "description": "Blue=A, orange=B. No GT box is "
                       "drawn because box GT is pending "
                       "human annotation.",
        "items": items})

    # ---- crop strips: discordant + wrong reads ----------
    strip_items = []
    trunc_rows = [r for r in records
                  if r["expansion"] == 1.00]
    chosen = [r for r in trunc_rows
              if r["verified"] and r["exact"] is False]
    # add one correct-read example per instance
    for vid in ("cam1_s001_v001", "cam1_s001_v002"):
        ok = [r for r in trunc_rows
              if r.get("vehicle_instance_id") == vid
              and r["exact"] is True
              and r["detector"] ==
              "detector_a_current"
              and r["convention"] == "trunc"]
        if ok:
            chosen.append(ok[0])
    for r in chosen[:12]:
        frame = frames[(r["camera"], r["frame"])]
        crops = {}
        for c in CONVENTIONS:
            rr = extract_crop_crop(
                frame, r["bbox_float"], c, 1.00)
            crops[c] = rr
        for e in (1.03, 1.05, 1.10):
            rr = extract_crop_crop(
                frame, r["bbox_float"], "trunc", e)
            crops[f"trunc@{e:.2f}x"] = rr
        strip = vis.crop_strip(
            crops, ["trunc", "floor", "round", "ceil",
                    "trunc@1.03x", "trunc@1.05x",
                    "trunc@1.10x"])
        name = (f"{r['camera']}_f{r['frame']:05d}_"
                f"{r['detector'][-1]}.png")
        cv2.imwrite(str(dirs["crop_strips"] / name),
                    strip)
        strip_items.append(vis.manifest_entry(
            "crop_strip", f"crop_strips/{name}",
            f"{r['camera']}@{r['frame']} "
            f"{r['detector']} OCR={r.get('ocr_text')!r}",
            f"GT={r.get('ground_truth')}"))
    sections.append({
        "title": "Crop strips (wrong reads + one "
                 "correct example per instance)",
        "description": "Same detector box under each "
                       "convention and expansion. Review "
                       "status: pending.",
        "items": strip_items})

    # ---- OCR examples ------------------------------------
    ocr_items = []
    for r in chosen[:12]:
        frame = frames[(r["camera"], r["frame"])]
        rr = extract_crop_crop(
            frame, r["bbox_float"], r["convention"],
            r["expansion"])
        name = (f"ocr_{r['camera']}_f{r['frame']:05d}_"
                f"{r['detector'][-1]}_{r['convention']}.png")
        cv2.imwrite(str(dirs["ocr_examples"] / name),
                    vis.zoom4x(rr))
        ocr_items.append(vis.manifest_entry(
            "ocr_example", f"ocr_examples/{name}",
            f"OCR={r.get('ocr_text')!r} "
            f"(GT={r.get('ground_truth')})",
            f"conf={r.get('ocr_confidence')} "
            f"valid={r.get('ocr_valid')}"))
    sections.append({
        "title": "OCR examples",
        "description": "4x nearest-neighbor crops behind "
                       "selected reads. Review pending.",
        "items": ocr_items})

    vis.write_diagnostics_index(
        sections, AUDIT / "diagnostics.html")
    return sections


def extract_crop_crop(frame, bbox, convention,
                      expansion):
    from phase2d_crop import extract_crop  # noqa: E402
    r = extract_crop(frame, bbox,
                     convention=convention,
                     expansion=expansion, clip=True)
    return r["crop"]


if __name__ == "__main__":
    main()
