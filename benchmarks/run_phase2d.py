"""Phase 2D — crop extraction determinism, quantization & expansion benchmark.

Answers (Phase 2D mission):
  * Step 4: reproduce the six Phase-2C discordant frames under
    A/trunc, B/trunc, B/round, B/ceil, B/trunc+1.05x.
  * Step 5: controlled crop-expansion sweep (1.00..1.10), CURRENT_PRODUCTION
    OCR only, cam1 verified + cam2 unlabeled (diagnostic-only metrics).
  * Step 6: quantization sweep (trunc/floor/round/ceil) against the SAME
    detector boxes — detector inference is run ONCE per frame per detector
    and never re-run per convention.
  * Step 8: clean paired dataset (append-only, every row retained).
  * Step 9: post-fix matrix A/B x baseline/candidate separating detector
    effect from crop effect.

Hard rules honored:
  * production code (alpr_engine.py, video_processor.py, api.py, db.py,
    camera_manager.py) is NEVER modified; the engine is only imported to
    reuse its loaded models, exactly as Phase 2C did.
  * detector weights and OCR weights are never swapped.
  * cam2 is diagnostic-only: no accuracy, no recall, no superiority claim.
  * the frozen baseline convention is trunc (alpr_engine.py:363).
"""
from __future__ import annotations

import argparse
import json
import math
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
from phase2d_crop import CONVENTIONS, EXPANSIONS, extract_crop  # noqa: E402

DS = ROOT / "benchmarks" / "dataset"
RESULTS = ROOT / "benchmarks" / "results"
VIDEOS = ("cam1.mp4", "cam2.mp4")
DETECTORS = ("detector_a_current", "detector_b_iranplate")

# Frozen protocol — identical to Phase 2C (both arms, all experiments).
PROTOCOL = {
    "conf": 0.50, "iou": 0.45, "max_det": 12, "imgsz": 640,
    "agnostic_nms": False, "half": False,
    "crop_convention": "trunc", "clip": True, "pad_x": 0, "pad_y": 0,
    "ocr": "CURRENT_PRODUCTION", "ground_truth_policy": "verified_only",
}

# The six Phase-2C discordant frames (cam1, plate 12d67413).
DISCORDANT_FRAMES = (180, 185, 210, 215, 330, 335)
DISCORDANT_PLATE = "۱۲د۶۷۴۱۳"

# Original Phase-2B cam2 sample frames (the "22 cam2 samples").
CAM2_PHASE2B_SAMPLES = (205, 210, 300, 305, 315, 320, 325, 330, 335, 340,
                        345, 350, 355, 485, 495, 500, 505, 510, 530, 540,
                        545, 555)


# --------------------------------------------------------------------- setup
def load_gt() -> dict:
    """(video, frame) -> verified plate text. UNLABELED rows never added."""
    labels = json.loads((DS / "gt_labels.json").read_text(encoding="utf-8"))
    out = {}
    for lab in labels["labels"].values():
        if not lab.get("verified"):
            continue
        for lo, hi in lab["applies_to"]["frame_ranges"]:
            for f in range(lo, hi + 1):
                out[(lab["applies_to"]["source_video"], f)] = lab["plate_text"]
    return out


def build_detectors():
    """Two detector callables driven with IDENTICAL inference parameters."""
    from api import _ensure_models
    engine = _ensure_models()
    a_model = engine._plate_model
    b = IranPlateDetectorAdapter()
    b.load()
    b_model = b.model

    def call(model, frame):
        res = model.predict(frame, conf=PROTOCOL["conf"], iou=PROTOCOL["iou"],
                            max_det=PROTOCOL["max_det"],
                            imgsz=PROTOCOL["imgsz"],
                            agnostic_nms=PROTOCOL["agnostic_nms"],
                            half=PROTOCOL["half"], verbose=False)[0]
        boxes = []
        if res.boxes is not None:
            for bx in res.boxes.data.tolist():
                x1, y1, x2, y2, c, cls = bx
                boxes.append({"bbox": [x1, y1, x2, y2],
                              "confidence": float(c), "class_id": int(cls)})
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


# ------------------------------------------------------------------ scoring
def score_record(text, ref):
    if ref is None:
        return {"exact": None, "char_accuracy": None, "edit_distance": None,
                "pred_canonical": None, "ref_canonical": None}
    s = score_pair(text, ref)
    return {"exact": s["exact"], "char_accuracy": s["char_accuracy"],
            "edit_distance": s["edit_distance"],
            "pred_canonical": s["pred_canonical"],
            "ref_canonical": s["ref_canonical"]}


# --------------------------------------------------------------- one variant
def evaluate_variant(frame, box, ocr, convention, expansion):
    """Run ONE crop variant (crop + OCR) and return the measured record."""
    t0 = time.perf_counter()
    r = extract_crop(frame, box["bbox"], convention=convention,
                     expansion=expansion, clip=PROTOCOL["clip"])
    crop_ms = (time.perf_counter() - t0) * 1000.0
    rec = {
        "convention": convention, "expansion": expansion,
        "bbox_float": [round(float(v), 4) for v in box["bbox"]],
        "integer_bbox": list(r["integer_bbox"]),
        "raw_integer_bbox": list(r["raw_integer_bbox"]),
        "crop_width": r["effective_width"],
        "crop_height": r["effective_height"],
        "clipping": r["clipping_status"],
        "invalid_crop": r["invalid"],
        "crop_latency_ms": round(crop_ms, 4),
    }
    if r["invalid"] or r["crop"] is None:
        rec.update({"ocr_text": None, "ocr_confidence": None,
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
        "ocr_valid": bool(is_valid_iranian(text, out["confidence"] or 0.9)),
        "failed": not text.strip(),
        "ocr_latency_ms": round(ocr_ms, 4),
    })
    return rec


# -------------------------------------------------------------------- passes
def run_quantization_sweep(gt, detectors, ocr, frames):
    """Step 6: trunc/floor/round/ceil on the SAME cached detector boxes."""
    records = []
    boxes_cache = {}  # (video, frame, detector) -> [boxes]
    for video, idx, frame in frames:
        ref = gt.get((video, idx))
        for det_name, fn in detectors.items():
            t0 = time.perf_counter()
            boxes = fn(frame)
            det_ms = (time.perf_counter() - t0) * 1000.0
            boxes_cache[(video, idx, det_name)] = boxes
            for bx in boxes:
                for conv in CONVENTIONS:
                    rec = {"camera": video, "frame": idx, "detector": det_name,
                           "experiment": "quantization",
                           "confidence": round(bx["confidence"], 6),
                           "detector_latency_ms": round(det_ms, 4),
                           "ground_truth": ref,
                           "gt_status": "LABELED" if ref else "UNLABELED"}
                    rec.update(evaluate_variant(frame, bx, ocr, conv, 1.0))
                    rec.update(score_record(rec.get("ocr_text"), ref))
                    records.append(rec)
    return records, boxes_cache


def run_expansion_sweep(gt, detectors, ocr, frames, boxes_cache):
    """Step 5: expansion sweep on the SAME cached boxes (no re-inference)."""
    records = []
    for video, idx, frame in frames:
        ref = gt.get((video, idx))
        for det_name in DETECTORS:
            for bx in boxes_cache.get((video, idx, det_name), []):
                for expansion in EXPANSIONS:
                    rec = {"camera": video, "frame": idx, "detector": det_name,
                           "experiment": "expansion",
                           "confidence": round(bx["confidence"], 6),
                           "ground_truth": ref,
                           "gt_status": "LABELED" if ref else "UNLABELED"}
                    rec.update(evaluate_variant(frame, bx, ocr,
                                                PROTOCOL["crop_convention"],
                                                expansion))
                    rec.update(score_record(rec.get("ocr_text"), ref))
                    records.append(rec)
    return records


# ------------------------------------------------------------- Step 4 check
def discordant_reproduction(quant_records, gt):
    """Reproduce the six Phase-2C discordant frames and CHECK expectations.

    Expected (from Phase 2C, which must NOT be rewritten to pass):
      B/trunc        -> wrong on all six
      B/round        -> correct on all six
      B/ceil         -> correct on all six
      B/trunc+1.05x  -> correct on all six
      A/trunc        -> correct on all six
    Any deviation is reported as a STOP condition, never silently absorbed.
    """
    ref = gt.get(("cam1.mp4", DISCORDANT_FRAMES[0]))
    out = {"plate_ground_truth": ref, "frames": {}, "expectations": {},
           "all_as_expected": True}
    for f in DISCORDANT_FRAMES:
        frame_out = {}
        for det in DETECTORS:
            for conv in CONVENTIONS:
                rows = [r for r in quant_records
                        if r["camera"] == "cam1.mp4" and r["frame"] == f
                        and r["detector"] == det and r["convention"] == conv
                        and r["experiment"] == "quantization"]
                if rows:
                    frame_out[f"{det}|{conv}"] = rows
            rows = [r for r in quant_records
                    if r["camera"] == "cam1.mp4" and r["frame"] == f
                    and r["detector"] == det
                    and r["experiment"] == "expansion"
                    and r["expansion"] == 1.05]
            if rows:
                frame_out[f"{det}|trunc+1.05x"] = rows
        out["frames"][str(f)] = frame_out

    expectations = {
        "detector_a_current|trunc": True,
        "detector_b_iranplate|trunc": False,
        "detector_b_iranplate|round": True,
        "detector_b_iranplate|ceil": True,
        "detector_b_iranplate|trunc+1.05x": True,
    }
    for key, expected_correct in expectations.items():
        per_frame = []
        for f in DISCORDANT_FRAMES:
            rows = out["frames"][str(f)].get(key, [])
            if not rows:
                per_frame.append(None)
                continue
            # highest-confidence box, as in the Phase 2C pairing rule
            best = max(rows, key=lambda r: r["confidence"])
            per_frame.append(best["exact"])
        matches = all(v == expected_correct for v in per_frame if v is not None)
        complete = all(v is not None for v in per_frame)
        out["expectations"][key] = {
            "expected_correct": expected_correct,
            "per_frame_exact": per_frame,
            "matches_phase2c": bool(matches and complete),
        }
        if not (matches and complete):
            out["all_as_expected"] = False
    return out


# ---------------------------------------------------------------- aggregation
def pct(values, p):
    if not values:
        return None
    v = sorted(values)
    k = min(len(v) - 1, max(0, math.ceil(p / 100.0 * len(v)) - 1))
    return round(float(v[k]), 4)


def ratio(num, den):
    return {"numerator": num, "denominator": den,
            "value": round(num / den, 4) if den else None}


def summarize_scope(rows):
    """Aggregate one scope (detector x convention x experiment x camera).

    Accuracy fields exist ONLY where gt_status == LABELED. cam2 rows are
    UNLABELED by construction, so their accuracy fields stay null.
    """
    labeled = [r for r in rows if r["gt_status"] == "LABELED"]
    with_ocr = [r for r in rows if r.get("ocr_text") is not None]
    widths = [r["crop_width"] for r in rows if r["crop_width"] > 0]
    heights = [r["crop_height"] for r in rows if r["crop_height"] > 0]
    return {
        "n_crops": len(rows),
        "n_labeled": len(labeled),
        "n_unlabeled": len(rows) - len(labeled),
        "exact": ratio(sum(1 for r in labeled if r["exact"]), len(labeled)),
        "char_accuracy": ratio(
            round(sum(r["char_accuracy"] for r in labeled
                      if r["char_accuracy"] is not None), 6), len(labeled)),
        "mean_edit_distance": ratio(
            round(sum(r["edit_distance"] for r in labeled
                      if r["edit_distance"] is not None), 6), len(labeled)),
        "invalid_rate": ratio(sum(1 for r in with_ocr if not r["ocr_valid"]),
                              len(with_ocr)),
        "failed_rate": ratio(sum(1 for r in with_ocr if r["failed"]),
                             len(with_ocr)),
        "median_crop_width": pct(widths, 50),
        "median_crop_height": pct(heights, 50),
        "clipping_rate": ratio(sum(1 for r in rows if r["clipping"]["any"]),
                               len(rows)),
        "mean_confidence": round(statistics.fmean(
            [r["confidence"] for r in rows]), 4) if rows else None,
        "median_ocr_latency_ms": pct(
            [r["ocr_latency_ms"] for r in with_ocr], 50),
    }


def ocr_stability(rows):
    """Diagnostic-only: how often OCR text changes across variants of the
    SAME (frame, detector, box). cam2 only — never an accuracy metric."""
    by_key = {}
    for r in rows:
        by_key.setdefault((r["camera"], r["frame"], r["detector"]), set()).add(
            r.get("ocr_text") or "")
    changes = sum(1 for texts in by_key.values() if len(texts) > 1)
    return {"frames_with_multiple_ocr_outputs": changes,
            "frames_total": len(by_key),
            "instability_rate": ratio(changes, len(by_key))}


# ----------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--out", type=str, default="phase2d")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    gt = load_gt()
    frames = read_frames(args.interval)
    print(f"frames: {len(frames)} "
          f"({sum(1 for v, _, _ in frames if v == 'cam1.mp4')} cam1, "
          f"{sum(1 for v, _, _ in frames if v == 'cam2.mp4')} cam2)", flush=True)

    ocr = ProductionOCRAdapter()
    ocr.is_available()
    detectors = build_detectors()

    print("quantization sweep (single inference pass per frame/detector)...",
          flush=True)
    quant_records, boxes_cache = run_quantization_sweep(gt, detectors, ocr,
                                                        frames)
    print(f"  {len(quant_records)} records", flush=True)

    print("expansion sweep (cached boxes, no re-inference)...", flush=True)
    exp_records = run_expansion_sweep(gt, detectors, ocr, frames, boxes_cache)
    print(f"  {len(exp_records)} records", flush=True)

    print("discordant-frame reproduction check...", flush=True)
    discordant = discordant_reproduction(quant_records + exp_records, gt)
    print(f"  all_as_expected={discordant['all_as_expected']}", flush=True)
    for key, exp in discordant["expectations"].items():
        print(f"  {key}: matches_phase2c={exp['matches_phase2c']} "
              f"per_frame={exp['per_frame_exact']}", flush=True)

    # ---- summaries -------------------------------------------------------
    quant_summary = {}
    for det in DETECTORS:
        for conv in CONVENTIONS:
            for scope, pred in (("overall", lambda r: True),
                                ("cam1", lambda r: r["camera"] == "cam1.mp4"),
                                ("cam2", lambda r: r["camera"] == "cam2.mp4")):
                rows = [r for r in quant_records if r["detector"] == det
                        and r["convention"] == conv and pred(r)]
                quant_summary[f"{det}|{conv}|{scope}"] = summarize_scope(rows)

    exp_summary = {}
    for det in DETECTORS:
        for e in EXPANSIONS:
            for scope, pred in (("overall", lambda r: True),
                                ("cam1", lambda r: r["camera"] == "cam1.mp4"),
                                ("cam2", lambda r: r["camera"] == "cam2.mp4")):
                rows = [r for r in exp_records if r["detector"] == det
                        and r["expansion"] == e and pred(r)]
                exp_summary[f"{det}|{e:.2f}|{scope}"] = summarize_scope(rows)

    cam2_stability_quant = {}
    for det in DETECTORS:
        rows = [r for r in quant_records if r["camera"] == "cam2.mp4"
                and r["detector"] == det]
        cam2_stability_quant[f"{det}|quantization"] = ocr_stability(rows)
    cam2_stability_exp = {}
    for det in DETECTORS:
        rows = [r for r in exp_records if r["camera"] == "cam2.mp4"
                and r["detector"] == det]
        cam2_stability_exp[f"{det}|expansion"] = ocr_stability(rows)

    # ---- Step 8: clean paired dataset ------------------------------------
    dataset_rows = []
    for r in quant_records + exp_records:
        dataset_rows.append({
            "sample_id": f"{r['camera'].replace('.mp4', '')}_f{r['frame']:05d}",
            "video": r["camera"], "frame": r["frame"],
            "detector": r["detector"], "experiment": r["experiment"],
            "bbox": r["bbox_float"], "crop_convention": r["convention"],
            "expansion": r["expansion"],
            "integer_bbox": r["integer_bbox"],
            "crop_width": r["crop_width"], "crop_height": r["crop_height"],
            "ocr_output": r.get("ocr_text"),
            "normalized_output": r.get("ocr_normalized"),
            "ocr_valid": r.get("ocr_valid"), "failed": r.get("failed"),
            "confidence": r.get("confidence"),
            "ground_truth": r.get("ground_truth"),
            "verified": r.get("gt_status") == "LABELED",
            "exact": r.get("exact"), "char_accuracy": r.get("char_accuracy"),
            "edit_distance": r.get("edit_distance"),
        })

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    base = args.out
    (RESULTS / f"{base}_records.json").write_text(json.dumps(
        {"generated_at": stamp, "protocol": PROTOCOL,
         "interval": args.interval,
         "discordant_frames": list(DISCORDANT_FRAMES),
         "quantization_records": quant_records,
         "expansion_records": exp_records},
        ensure_ascii=False, indent=1), encoding="utf-8")
    (RESULTS / f"{base}_summary.json").write_text(json.dumps(
        {"generated_at": stamp, "protocol": PROTOCOL,
         "discordant_reproduction": discordant,
         "quantization_summary": quant_summary,
         "expansion_summary": exp_summary,
         "cam2_ocr_stability_quantization": cam2_stability_quant,
         "cam2_ocr_stability_expansion": cam2_stability_exp},
        ensure_ascii=False, indent=1), encoding="utf-8")
    (RESULTS / f"{base}_dataset.json").write_text(json.dumps(
        {"generated_at": stamp, "protocol": PROTOCOL,
         "n_rows": len(dataset_rows), "rows": dataset_rows},
        ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- console digest ---------------------------------------------------
    def dig(key):
        s = quant_summary.get(key) or {}
        e = s.get("exact") or {}
        return (f"{e.get('numerator')}/{e.get('denominator')}"
                if e.get("denominator") else "n/a")

    print("\n=== cam1 verified exact (quantization sweep) ===", flush=True)
    for det in DETECTORS:
        for conv in CONVENTIONS:
            print(f"  {det:24s} {conv:6s} cam1 exact: "
                  f"{dig(f'{det}|{conv}|cam1')}", flush=True)
    print("\n=== cam1 verified exact (expansion sweep) ===", flush=True)
    for det in DETECTORS:
        for e in EXPANSIONS:
            s = exp_summary.get(f"{det}|{e:.2f}|cam1") or {}
            ex = s.get("exact") or {}
            print(f"  {det:24s} {e:.2f}  cam1 exact: "
                  f"{ex.get('numerator')}/{ex.get('denominator')}", flush=True)

    out = {"discordant_all_as_expected": discordant["all_as_expected"],
           "quantization": {f"{d}|{c}": dig(f"{d}|{c}|cam1")
                            for d in DETECTORS for c in CONVENTIONS}}
    (RESULTS / f"{base}_digest.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    print("\nwrote:", *[p.name for p in RESULTS.glob(f"{base}_*")], flush=True)


if __name__ == "__main__":
    main()
