"""Independent recompute of Phase 2C denominators from phase2c_raw_results.json.

READ-ONLY with respect to the benchmark. Recomputes every headline number from
the raw records array WITHOUT calling run_phase2c_ab.summarize(), so an
aggregator bug cannot hide. Writes benchmarks/audit/phase2c_recomputed.json.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "benchmarks" / "results" / "phase2c_raw_results.json"
SUM = ROOT / "benchmarks" / "results" / "phase2c_summary.json"
OUT = ROOT / "benchmarks" / "audit" / "phase2c_recomputed.json"

WIDTH_BUCKETS = ((0, 80, "lt80"), (80, 100, "80-99"), (100, 150, "100-149"),
                 (150, 200, "150-199"), (200, 10 ** 9, "ge200"))
CONVENTIONS = ("round", "floor", "ceil", "trunc", "floor_dy-1")
DETS = ("detector_a_current", "detector_b_iranplate")


def bucket_for(w):
    for lo, hi, n in WIDTH_BUCKETS:
        if lo <= w < hi:
            return n
    return "unknown"


def pct(values, p):
    if not values:
        return None
    v = sorted(values)
    k = min(len(v) - 1, max(0, math.ceil(p / 100.0 * len(v)) - 1))
    return round(float(v[k]), 4)


def ratio(n, d):
    return {"numerator": n, "denominator": d,
            "value": round(n / d, 4) if d else None}


d = json.loads(RES.read_text(encoding="utf-8"))
summary = json.loads(SUM.read_text(encoding="utf-8"))
recs = d["records"]
frows = d["frame_rows"]
CANON = summary["canonical_convention"]

runs = sorted({r["run"] for r in recs})
run0 = runs[0]
convs = sorted({r["convention"] for r in recs})

rep = {
    "raw_file": str(RES),
    "raw_generated_at": d["generated_at"],
    "summary_generated_at": summary["generated_at"],
    "protocol_stored_in_json": d["protocol"],
    "interval": d["interval"],
    "gt_frame_counts": d["gt_frame_counts"],
    "canonical_convention": CANON,
    "n_records": len(recs),
    "n_frame_rows": len(frows),
    "structure": {
        "runs": runs,
        "detectors": sorted({r["detector"] for r in recs}),
        "conventions_present": convs,
        "convention_matrix_complete": set(CONVENTIONS) == set(convs),
        "detection_statuses": sorted({r["detection_status"] for r in recs}),
        "gt_statuses": sorted({r["gt_status"] for r in recs}),
        "frame_rows_total": len(frows),
        "distinct_frame_rows": len({(f["camera"], f["frame"], f["detector"])
                                    for f in frows}),
        "frame_rows_per_run": len(frows) // max(1, len(runs)),
    },
}

# ---------------------------------------------------------------- 1. NO_DETECTION
nd = [r for r in recs if r["detection_status"] == "NO_DETECTION"]
nd_keys = {(r["run"], r["detector"], r["camera"], r["frame"]) for r in nd}
fr_nodet = {(f["detector"], f["camera"], f["frame"]) for f in frows if not f["detected"]}
fr_det = {(f["detector"], f["camera"], f["frame"]) for f in frows if f["detected"]}
nd_run0 = {(r["detector"], r["camera"], r["frame"]) for r in nd if r["run"] == run0}
rows_per_key = {}
for r in recs:
    rows_per_key.setdefault((r["run"], r["detector"], r["camera"], r["frame"]),
                           []).append(r)
rep["no_detection"] = {
    "n_records": len(nd),
    "n_conv_rows_per_nodetection_key": sorted({len(v) for k, v in rows_per_key.items()
                                               if k[0] == run0
                                               and v[0]["detection_status"]
                                               == "NO_DETECTION"}),
    "distinct_frame_detector_keys": len(nd_keys),
    "frame_rows_marked_undetected": len(fr_nodet),
    "run0_nodetection_keys": len(nd_run0),
    "run0_keys_match_frame_rows": nd_run0 == fr_nodet,
    "all_exact_none": all(r["exact"] is None for r in nd),
    "all_char_none": all(r["char_accuracy"] is None for r in nd),
    "all_edit_none": all(r["edit_distance"] is None for r in nd),
    "all_failed_none": all(r["failed"] is None for r in nd),
    "all_ocr_text_none": all(r["ocr_text"] is None for r in nd),
}
# every DETECTED frame key must have a record too
det_keys = {(r["run"], r["detector"], r["camera"], r["frame"]) for r in recs
            if r["detection_status"] == "DETECTED"}
rep["no_detection"]["distinct_detected_keys"] = len(det_keys)
rep["no_detection"]["all_frame_rows_have_records"] = (
    len(nd_keys) + len({(run0, a, b, c) for a, b, c in fr_det}) * len(runs)
) == len(rows_per_key) * 1 or None
rep["no_detection"]["n_distinct_frame_detector_keys_total"] = len(
    {(a, b, c) for _, a, b, c in rows_per_key})

# ------------------------------------------------------- 2. UNLABELED safety
unl = [r for r in recs if r["gt_status"] == "UNLABELED"]
lab = [r for r in recs if r["gt_status"] == "LABELED"]
rep["unlabeled"] = {
    "n_records": len(unl),
    "cameras": sorted({r["camera"] for r in unl}),
    "n_exact_not_none": sum(1 for r in unl if r["exact"] is not None),
    "n_exact_false": sum(1 for r in unl if r["exact"] is False),
    "n_char_not_none": sum(1 for r in unl if r["char_accuracy"] is not None),
    "n_edit_not_none": sum(1 for r in unl if r["edit_distance"] is not None),
    "n_ground_truth_none": sum(1 for r in unl if r["ground_truth"] is None),
    "any_ground_truth_value": sorted({str(r["ground_truth"]) for r in unl})[:5],
}
rep["labeled"] = {
    "n_records": len(lab),
    "cameras": sorted({r["camera"] for r in lab}),
    "distinct_ground_truth": sorted({r["ground_truth"] for r in lab}),
    "n_exact_true": sum(1 for r in lab if r["exact"] is True),
    "n_exact_false": sum(1 for r in lab if r["exact"] is False),
    "n_exact_none": sum(1 for r in lab if r["exact"] is None),
    "n_char_none": sum(1 for r in lab if r["char_accuracy"] is None),
    "n_edit_none": sum(1 for r in lab if r["edit_distance"] is None),
}

# ------------------------------------------------- 3. failed predicate check
with_ocr = [r for r in recs if r.get("ocr_text") is not None]
viol = [r for r in with_ocr
        if bool(r["failed"]) != (not str(r["ocr_text"]).strip())]
nullcrop = [r for r in recs if r["detection_status"] == "DETECTED"
            and r.get("ocr_text") is None]
rep["failed_predicate"] = {
    "n_records_with_ocr_text": len(with_ocr),
    "n_violations_failed_eq_blank_text": len(viol),
    "violation_examples": viol[:3],
    "n_failed_true": sum(1 for r in with_ocr if r["failed"]),
    "n_ocr_valid_false": sum(1 for r in with_ocr if r["ocr_valid"] is False),
    "n_failed_and_invalid": sum(1 for r in with_ocr if r["failed"]
                                and r["ocr_valid"] is False),
    "n_failed_but_ocr_valid_true": sum(1 for r in with_ocr if r["failed"]
                                       and r["ocr_valid"] is True),
    "n_invalid_but_failed_false": sum(1 for r in with_ocr
                                      if r["ocr_valid"] is False
                                      and not r["failed"]),
    "n_detected_but_null_crop": len(nullcrop),
    "n_detected_null_crop_failed_true": sum(1 for r in nullcrop if r["failed"]),
    "n_detected_null_crop_ocr_valid_null": sum(1 for r in nullcrop
                                               if r["ocr_valid"] is None),
    "null_crop_cameras": sorted({r["camera"] for r in nullcrop}),
}
# --------------------------------------- 4. per detector x scope, run0 recompute
sel = [r for r in recs if r["convention"] == CANON and r["run"] == run0]
blocks = {}
for det in DETS:
    det_rows = [r for r in sel if r["detector"] == det]
    for scope, pred in (("overall", lambda r: True),
                        ("cam1.mp4", lambda r: r["camera"] == "cam1.mp4"),
                        ("cam2.mp4", lambda r: r["camera"] == "cam2.mp4")):
        rows = [r for r in det_rows if pred(r)]
        fr = [f for f in frows if f["detector"] == det and pred(f)]
        detected = [r for r in rows if r["detection_status"] == "DETECTED"]
        labeled = [r for r in rows if r["gt_status"] == "LABELED"]
        unlab = [r for r in rows if r["gt_status"] == "UNLABELED"]
        wo = [r for r in detected if r.get("ocr_text") is not None]
        widths = [r["crop"]["crop_width"] for r in detected
                  if r["crop"]["crop_width"] > 0]
        heights = [r["crop"]["crop_height"] for r in detected
                   if r["crop"]["crop_height"] > 0]
        blocks[f"{det}|{scope}"] = {
            "frames_total": len(fr),
            "frames_with_detection": sum(1 for f in fr if f["detected"]),
            "frames_without_detection": sum(1 for f in fr if not f["detected"]),
            "n_boxes": sum(f["n_boxes"] for f in fr),
            "multi_box_frames": sum(1 for f in fr if f["n_boxes"] > 1),
            "detected_crops": len(detected),
            "labeled_crops": len(labeled),
            "labeled_no_detection_rows": sum(
                1 for r in labeled if r["detection_status"] == "NO_DETECTION"),
            "unlabeled_crops": len(unlab),
            "ocr_attempts": len(wo),
            "exact": ratio(sum(1 for r in labeled if r["exact"] is True),
                           len(labeled)),
            "char_accuracy": ratio(round(sum(r["char_accuracy"] for r in labeled
                                             if r["char_accuracy"] is not None), 6),
                                   len(labeled)),
            "mean_edit_distance": ratio(round(sum(r["edit_distance"] for r in labeled
                                                  if r["edit_distance"] is not None),
                                              6), len(labeled)),
            "invalid_rate_all_crops": ratio(sum(1 for r in wo
                                                if r["ocr_valid"] is False), len(wo)),
            "failed_rate_all_crops": ratio(sum(1 for r in wo if r["failed"]),
                                           len(wo)),
            "median_crop_width": pct(widths, 50),
            "median_crop_height": pct(heights, 50),
            "mean_crop_width": (round(statistics.fmean(widths), 4)
                                if widths else None),
            "mean_crop_height": (round(statistics.fmean(heights), 4)
                                 if heights else None),
            "clipping_rate": ratio(sum(1 for r in detected
                                       if r["crop"]["clipped_any"]), len(detected)),
            "confidence_mean": (round(statistics.fmean(
                [r["confidence"] for r in detected]), 4) if detected else None),
        }
rep["recomputed_summary_run0"] = blocks
stored = summary["per_run_summary"][run0]
mismatch = {}
for k, v in blocks.items():
    sv = stored.get(k, {})
    diffs = {f: [sv.get(f), v.get(f)] for f in v if sv.get(f) != v.get(f)}
    if diffs:
        mismatch[k] = diffs
rep["stored_vs_recomputed_diff"] = mismatch
rep["stored_summary_keys"] = sorted(stored)

rep["labeled_frame_denominator"] = {
    "gt_frames_in_verified_ranges": d["gt_frame_counts"],
    "labeled_frame_keys_run0": {
        det: len({(r["camera"], r["frame"]) for r in sel
                  if r["detector"] == det and r["gt_status"] == "LABELED"})
        for det in DETS},
    "labeled_crop_rows_run0": {
        det: len([r for r in sel if r["detector"] == det
                  and r["gt_status"] == "LABELED"]) for det in DETS},
}

# ------------------------------------------------------ 5. buckets recomputed
bk = {}
for det in DETS:
    rows = [r for r in sel if r["detector"] == det
            and r["detection_status"] == "DETECTED"]
    bk[det] = {}
    for _, _, name in WIDTH_BUCKETS:
        sub = [r for r in rows if bucket_for(r["crop"]["crop_width"]) == name]
        lb = [r for r in sub if r["gt_status"] == "LABELED"]
        wo = [r for r in sub if r.get("ocr_text") is not None]
        bk[det][name] = {
            "N": len(sub), "labeled": len(lb),
            "exact": ratio(sum(1 for r in lb if r["exact"] is True), len(lb)),
            "char_accuracy": ratio(round(sum(r["char_accuracy"] for r in lb
                                             if r["char_accuracy"] is not None), 6),
                                   len(lb)),
            "invalid": ratio(sum(1 for r in wo if r["ocr_valid"] is False), len(wo)),
            "failed": ratio(sum(1 for r in wo if r["failed"]), len(wo)),
            "median_width": pct([r["crop"]["crop_width"] for r in sub], 50),
            "median_height": pct([r["crop"]["crop_height"] for r in sub], 50),
            "clipping_rate": ratio(sum(1 for r in sub
                                       if r["crop"]["clipped_any"]), len(sub)),
        }
    bk[det]["_N_total"] = sum(bk[det][n]["N"] for _, _, n in WIDTH_BUCKETS)
rep["recomputed_buckets_run0"] = bk
stored_bk = summary["buckets"]
bdiff = {}
for det in DETS:
    for name in [n for _, _, n in WIDTH_BUCKETS]:
        s = stored_bk.get(det, {}).get(name, {})
        r = bk[det][name]
        df = {f: [s.get(f), r.get(f)] for f in r if s.get(f) != r.get(f)}
        if df:
            bdiff[f"{det}|{name}"] = df
rep["stored_vs_recomputed_bucket_diff"] = bdiff

# ------------------------------------- 6. repeatability, full record compare
def sig(run, det):
    rows = [r for r in recs if r["run"] == run and r["detector"] == det
            and r["convention"] == CANON]
    det_rows = [r for r in rows if r["detection_status"] == "DETECTED"]
    lb = [r for r in rows if r["gt_status"] == "LABELED"]
    wo = [r for r in det_rows if r.get("ocr_text") is not None]
    texts = {(r["camera"], r["frame"]): (r["ocr_text"], r["exact"],
                                         r["char_accuracy"], r["edit_distance"],
                                         r["ocr_valid"], r["failed"],
                                         (r.get("crop") or {}).get("crop_width"),
                                         (r.get("crop") or {}).get("crop_height"),
                                         r.get("bbox_float"),
                                         r["detection_status"])
             for r in rows}
    return {"n_rows": len(rows),
            "n_boxes": sum(r["n_boxes_this_frame"] for r in det_rows),
            "n_detected": len(det_rows), "n_labeled": len(lb),
            "n_exact": sum(1 for r in lb if r["exact"] is True),
            "n_invalid": sum(1 for r in wo if r["ocr_valid"] is False),
            "n_failed": sum(1 for r in wo if r["failed"]),
            "n_texts": texts}


rep["repeatability_full"] = {"runs_available": runs,
                             "summary_repeatability": summary["repeatability"]}
if len(runs) > 1:
    for det in DETS:
        a, b = sig(runs[0], det), sig(runs[1], det)
        keys = set(a["n_texts"]) | set(b["n_texts"])
        diff = [k for k in sorted(keys)
                if a["n_texts"].get(k) != b["n_texts"].get(k)]
        rep["repeatability_full"][det] = {
            "run0_counts": {k: v for k, v in a.items() if k != "n_texts"},
            "run1_counts": {k: v for k, v in b.items() if k != "n_texts"},
            "counts_identical": all(a[k] == b[k]
                                    for k in a if k != "n_texts"),
            "n_keys": len(a["n_texts"]),
            "n_per_record_diffs": len(diff),
            "diff_examples": diff[:5],
        }

# ------------------------------------------------ 7. paired / McNemar recompute
def paired(camera=None):
    s = [r for r in sel if r["gt_status"] == "LABELED"
         and (camera is None or r["camera"] == camera)]
    best = {}
    for r in s:
        k = (r["camera"], r["frame"], r["detector"])
        if r["detection_status"] != "DETECTED":
            best.setdefault(k, {"exact": False})
            continue
        cur = best.get(k)
        if cur is None or (r.get("confidence") or 0) > (cur.get("confidence") or 0):
            best[k] = {"exact": r["exact"], "confidence": r.get("confidence")}
    keys = sorted({(c, f) for c, f, _ in best})
    t = {"both_correct": 0, "a_correct_b_wrong": 0, "a_wrong_b_correct": 0,
         "both_wrong": 0}
    for cam, fr in keys:
        oa = bool(best.get((cam, fr, "detector_a_current"), {}).get("exact"))
        ob = bool(best.get((cam, fr, "detector_b_iranplate"), {}).get("exact"))
        t["both_correct" if oa and ob else
          "a_correct_b_wrong" if oa else
          "a_wrong_b_correct" if ob else "both_wrong"] += 1
    n = t["a_correct_b_wrong"] + t["a_wrong_b_correct"]
    k = min(t["a_correct_b_wrong"], t["a_wrong_b_correct"])
    p = None if n == 0 else round(min(1.0, 2 * sum(
        math.comb(n, i) for i in range(k + 1)) / (2 ** n)), 6)
    return {"table": t, "discordant_pairs": n, "mcnemar_exact_p": p,
            "verified_frames": len(keys)}


rep["paired_recomputed"] = {"all": paired(), "cam1": paired("cam1.mp4"),
                            "cam2": paired("cam2.mp4")}
rep["paired_stored"] = summary["paired_statistics"]

# ---------------------------------------- 8. convention matrix per convention
rep["convention_matrix"] = {}
for conv in CONVENTIONS:
    rows = [r for r in recs if r["convention"] == conv and r["run"] == run0]
    per = {}
    for det in DETS:
        dr = [r for r in rows if r["detector"] == det]
        detd = [r for r in dr if r["detection_status"] == "DETECTED"]
        lb = [r for r in dr if r["gt_status"] == "LABELED"]
        wo = [r for r in detd if r.get("ocr_text") is not None]
        per[det] = {"rows": len(dr), "detected": len(detd), "labeled": len(lb),
                    "exact": ratio(sum(1 for r in lb if r["exact"] is True),
                                   len(lb)),
                    "char_accuracy": ratio(round(sum(r["char_accuracy"] for r in lb
                                                     if r["char_accuracy"] is not None),
                                                 6), len(lb)),
                    "invalid": ratio(sum(1 for r in wo if r["ocr_valid"] is False),
                                     len(wo)),
                    "failed": ratio(sum(1 for r in wo if r["failed"]), len(wo)),
                    "degenerate": sum(1 for r in detd if r["crop"]["crop_width"] <= 0
                                      or r["crop"]["crop_height"] <= 0),
                    "sum_crop_width": sum(r["crop"]["crop_width"] for r in detd),
                    "n_crops_with_ocr": len(wo)}
    rep["convention_matrix"][conv] = per
rep["convention_scores_stored"] = summary["convention_scores_non_accuracy"]

OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
print("wrote", OUT)


def dump(key, limit=6000):
    print("==", key)
    print(json.dumps(rep[key], ensure_ascii=True, indent=1)[:limit])


for k in ("structure", "no_detection", "unlabeled", "labeled", "failed_predicate",
          "stored_vs_recomputed_diff", "stored_vs_recomputed_bucket_diff",
          "recomputed_summary_run0", "labeled_frame_denominator",
          "repeatability_full", "paired_recomputed", "paired_stored",
          "recomputed_buckets_run0", "convention_scores_stored"):
    dump(k)

# ------------------------------------------- 9. trunc vs numpy astype(int)
import numpy as np  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "benchmarks"))
from phase2c_canonical import convert_coord  # noqa: E402

rng = random.Random(20261003)
mismatches = 0
tested = 0
edge_vals = [0.0, -0.0, 0.5, -0.5, 1.0, -1.0, 1e-9, -1e-9, 1e9, -1e9,
             0.4999999999, -0.4999999999]
samples = edge_vals + [rng.uniform(-5000, 5000) for _ in range(200000)]
for v in samples:
    tested += 1
    npv = int(np.array([v]).astype(int)[0])
    mine = convert_coord(v, "trunc")
    if npv != mine:
        mismatches += 1
rep["trunc_vs_numpy_astype_int"] = {
    "tested": tested,
    "mismatches": mismatches,
    "examples_tested": edge_vals,
}

# also verify floor vs trunc differ on negatives only (documented divergence)
neg = [v for v in samples if v < 0]
rep["trunc_vs_numpy_astype_int"]["n_negative"] = len(neg)
rep["trunc_vs_numpy_astype_int"]["n_negative_floor_differs"] = sum(
    1 for v in neg if math.floor(v) != convert_coord(v, "trunc"))

with open(ROOT / "benchmarks" / "audit" / "_rc.txt", "w", encoding="utf-8") as fh:
    json.dump(rep, fh, ensure_ascii=False, indent=1)
OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

# ------------------------------------------- 10. frame_rows are NOT run-scoped
fr_run0_det = {}
for f in frows:
    if f["detector"] == "detector_a_current":
        fr_run0_det.setdefault(f["camera"], [0, 0])
        fr_run0_det[f["camera"]][0 if f["detected"] else 1] += 1
rep["frame_row_double_count"] = {
    "frame_row_fields": sorted(frows[0]),
    "frame_rows_have_run_field": "run" in frows[0],
    "per_detector_frame_rows_all_runs": {
        d: sum(1 for f in frows if f["detector"] == d) for d in DETS},
    "true_frames_per_detector_per_run": {
        d: len({(f["camera"], f["frame"]) for f in frows
                if f["detector"] == d}) for d in DETS},
    "summary_reported_frames_total_overall": {
        d: blocks[f"{d}|overall"]["frames_total"] for d in DETS},
    "summary_reported_frames_with_detection": {
        d: blocks[f"{d}|overall"]["frames_with_detection"] for d in DETS},
    "true_detected_frames_per_run": {
        d: sum(1 for f in frows if f["detector"] == d and f["detected"]) // len(runs)
        for d in DETS},
    "stored_summary_frames_total": {
        d: stored[f"{d}|overall"]["frames_total"] for d in DETS},
    "stored_summary_frames_with_detection": {
        d: stored[f"{d}|overall"]["frames_with_detection"] for d in DETS},
    "stored_n_boxes": {d: stored[f"{d}|overall"]["n_boxes"] for d in DETS},
}

# ------------------------- 11. labelled / UNLABELED row composition per scope
comp = {}
for det in DETS:
    for scope in ("overall", "cam1.mp4", "cam2.mp4"):
        rows = [r for r in sel if r["detector"] == det
                and (scope == "overall" or r["camera"] == scope)]
        nd_ = sum(1 for r in rows if r["detection_status"] == "NO_DETECTION")
        detd = sum(1 for r in rows if r["detection_status"] == "DETECTED")
        comp[f"{det}|{scope}"] = {
            "rows_total": len(rows), "detected_rows": detd,
            "no_detection_rows": nd_,
            "labeled_rows": sum(1 for r in rows if r["gt_status"] == "LABELED"),
            "labeled_detected": sum(1 for r in rows if r["gt_status"] == "LABELED"
                                    and r["detection_status"] == "DETECTED"),
            "labeled_no_detection": sum(1 for r in rows
                                        if r["gt_status"] == "LABELED"
                                        and r["detection_status"] == "NO_DETECTION"),
            "unlabeled_rows": sum(1 for r in rows if r["gt_status"] == "UNLABELED"),
        }
rep["row_composition_run0_canonical"] = comp

# ------------------------- 12. GT instance diversity / independence caveat
gt_counts = {}
for r in sel:
    if r["gt_status"] == "LABELED":
        gt_counts[r["ground_truth"]] = gt_counts.get(r["ground_truth"], 0) + 1
rep["gt_structure"] = {
    "distinct_verified_plate_texts": len(gt_counts),
    "frames_per_text_run0": gt_counts,
    "verified_frames_in_ranges": d["gt_frame_counts"],
    "sampled_labeled_frames_run0": len({(r["camera"], r["frame"]) for r in sel
                                         if r["gt_status"] == "LABELED"}),
    "sample_interval": d["interval"],
}

# ------------------------- 13. discordant frame detail (A vs B)
disc = []
for cam in sorted({r["camera"] for r in sel}):
    frames = sorted({r["frame"] for r in sel if r["camera"] == cam
                     and r["gt_status"] == "LABELED"})
    for fr in frames:
        a = [r for r in sel if r["camera"] == cam and r["frame"] == fr
             and r["detector"] == "detector_a_current"]
        b = [r for r in sel if r["camera"] == cam and r["frame"] == fr
             and r["detector"] == "detector_b_iranplate"]
        if not a or not b:
            continue
        if bool(a[0]["exact"]) != bool(b[0]["exact"]):
            disc.append({"camera": cam, "frame": fr,
                         "gt": a[0]["ground_truth"],
                         "a_text": a[0]["ocr_text"], "a_exact": a[0]["exact"],
                         "a_w": a[0]["crop"]["crop_width"],
                         "b_text": b[0]["ocr_text"], "b_exact": b[0]["exact"],
                         "b_w": b[0]["crop"]["crop_width"]})
rep["discordant_detail"] = disc
OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
for k in ("frame_row_double_count", "row_composition_run0_canonical",
          "gt_structure", "discordant_detail"):
    dump(k)

# ------------- 14. dual `failed` predicate: score_pair() overwrites rec["failed"]
sys.path.insert(0, str(ROOT / "benchmarks"))
from metrics import canonical  # noqa: E402

lab_ocr = [r for r in with_ocr if r["gt_status"] == "LABELED"]
unl_ocr = [r for r in with_ocr if r["gt_status"] == "UNLABELED"]
rep["failed_dual_predicate"] = {
    "labeled_with_ocr": len(lab_ocr),
    "unlabeled_with_ocr": len(unl_ocr),
    "labeled_rows_carry_score_pair_keys": sum(
        1 for r in lab_ocr if "pred_canonical" in r),
    "unlabeled_rows_carry_score_pair_keys": sum(
        1 for r in unl_ocr if "pred_canonical" in r),
    "labeled_failed_ne_blank_text": sum(
        1 for r in lab_ocr if bool(r["failed"]) != (not str(r["ocr_text"]).strip())),
    "labeled_failed_ne_canonical_empty": sum(
        1 for r in lab_ocr
        if bool(r["failed"]) != (canonical(r["ocr_text"]) == "")),
    "unlabeled_failed_ne_blank_text": sum(
        1 for r in unl_ocr if bool(r["failed"]) != (not str(r["ocr_text"]).strip())),
    "n_nonblank_text_that_canonicalizes_empty": sum(
        1 for r in with_ocr if str(r["ocr_text"]).strip()
        and canonical(r["ocr_text"]) == ""),
}
OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
dump("failed_dual_predicate")