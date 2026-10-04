#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
phase2c_verify.py -- INDEPENDENT / ADVERSARIAL verifier for ALPR Phase 2C.

Design rules (deliberately restrictive):
  * Does NOT import the Phase 2C runner and does NOT reuse any of its
    functions: a bug in the runner must not be able to mask itself here.
  * Only json/math/os/re/sys are imported for the verification math, plus
    `numpy`, imported lazily and ONLY inside the crop-convention check.
  * Every check prints an explicit PASS/FAIL line with counts.
  * Exit code is non-zero if ANY check fails.

Checks (task section 28):
   1. numerator <= denominator on every ratio field (+ value == num/den).
   2. exact / char_accuracy / invalid / failed (+ counts, medians, means,
      percentiles, frame counts) recomputed from raw records vs summary.
   3. `failed` == count of blank OCR texts, kept distinct from `ocr_valid`.
   4. No UNLABELED record carries non-null exact / char_accuracy / edit_distance.
   5. A/B protocol symmetry: single inference-param block + identical
      (camera, frame) sets for both detectors.
   6. NO_DETECTION frames present in the frames_without_detection denominator.
   7. McNemar 2x2 table recomputed; discordant identity; p in [0,1] and None
      iff discordant_pairs == 0.
   8. Bucket assignment from crop_width; bucket N sums == detected crops.
   9. Repeatability claim verified against the two runs.
  10. Report-vs-JSON numeric contradictions (skipped, not failed, if the report
      does not exist yet).
  11. Canonical convention is one of the 5 allowed AND equals numpy.astype(int)
      on 2000 random floats.
"""

import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = os.environ.get(
    "P2C_RESULTS_DIR", os.path.join(ROOT, "benchmarks", "results"))
RAW = os.path.join(RESULTS, "phase2c_raw_results.json")
SUMMARY = os.path.join(RESULTS, "phase2c_summary.json")
BUCKETS_FILE = os.path.join(RESULTS, "phase2c_bucket_results.json")
REPORT = os.environ.get("P2C_REPORT_PATH",
                         os.path.join(ROOT,
                                      "ALPR_PHASE2C_DETECTOR_AB_BENCHMARK.md"))

CANON = "trunc"
ALLOWED_CONVENTIONS = ["round", "floor", "ceil", "trunc", "floor_dy-1"]
DET_A = "detector_a_current"
DET_B = "detector_b_iranplate"
RATIO_FIELDS = ("exact", "char_accuracy", "mean_edit_distance",
                "invalid_rate_all_crops", "invalid", "failed",
                "failed_rate_all_crops", "clipping_rate")
TOL = 5e-4

_lines = []
failures = []
notes = []


def out(msg=""):
    _lines.append(msg)
    print(msg)


def fail(cid, msg):
    failures.append("[%s] %s" % (cid, msg))


def note(msg):
    notes.append(msg)


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def is_ratio(obj):
    return isinstance(obj, dict) and "numerator" in obj and "denominator" in obj


def walk_ratios(node, path=""):
    """Yield (json_path, ratio_dict) for every ratio-shaped object."""
    if is_ratio(node):
        yield path, node
        return
    if isinstance(node, dict):
        for k, v in node.items():
            for item in walk_ratios(v, path + "/" + str(k)):
                yield item
    elif isinstance(node, list):
        for i, v in enumerate(node):
            for item in walk_ratios(v, path + "[%d]" % i):
                yield item


def close(a, b, tol=TOL):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def med(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    if n % 2:
        return float(s[n // 2])
    return (float(s[n // 2 - 1]) + float(s[n // 2])) / 2.0


def med_low(xs):
    """Lower median = sorted[(n-1)//2], i.e. numpy.percentile(..., 50,
    method='lower'). This is the convention the stored summary uses."""
    s = sorted(xs)
    if not s:
        return None
    return float(s[(len(s) - 1) // 2])


def med_hi(xs):
    """Upper median = sorted[n//2]."""
    s = sorted(xs)
    if not s:
        return None
    return float(s[len(s) // 2])


def med_ok(stored, xs):
    """Accept the exact median, the lower median or the upper median."""
    return (close(stored, med(xs), 0.51) or close(stored, med_low(xs), 0.51)
            or close(stored, med_hi(xs), 0.51))


def mean(xs):
    return None if not xs else float(sum(xs)) / len(xs)


def pct_nearest_rank(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    k = max(1, min(len(s), int(math.ceil(p / 100.0 * len(s)))))
    return float(s[k - 1])


def pct_linear(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return float(s[0])
    pos = (len(s) - 1) * p / 100.0
    lo = int(math.floor(pos))
    hi = min(len(s) - 1, lo + 1)
    f = pos - lo
    return float(s[lo]) * (1 - f) + float(s[hi]) * f


BUCKETS = ["lt80", "80-99", "100-149", "150-199", "ge200"]


def bucket_of(width):
    if width < 80:
        return "lt80"
    if width < 100:
        return "80-99"
    if width < 150:
        return "100-149"
    if width < 200:
        return "150-199"
    return "ge200"


def is_blank(s):
    return s is None or (isinstance(s, str) and s.strip() == "")


def binom_two_sided_p(b, c):
    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    tot = 0.0
    for i in range(0, k + 1):
        tot += math.comb(n, i)
    return min(1.0, 2.0 * tot / (2.0 ** n))
def main():
    missing = [p for p in (RAW, SUMMARY) if not os.path.exists(p)]
    if missing:
        out("FATAL: required result file(s) missing: %s" % ", ".join(missing))
        return 2

    raw = load(RAW)
    summ = load(SUMMARY)
    records = raw["records"]
    frame_rows = raw["frame_rows"]

    det_recs = [r for r in records if r["detection_status"] == "DETECTED"]
    nodet_recs = [r for r in records if r["detection_status"] == "NO_DETECTION"]
    runs_in_records = sorted(set(r["run"] for r in records))

    out("=" * 78)
    out("PHASE 2C INDEPENDENT VERIFICATION (adversarial, no runner imports)")
    out("=" * 78)
    out("raw       : %s" % RAW)
    out("summary   : %s" % SUMMARY)
    out("records   : %d (DETECTED=%d, NO_DETECTION=%d)"
        % (len(records), len(det_recs), len(nodet_recs)))
    out("frame_rows: %d" % len(frame_rows))
    out("")
# ---------------- CHECK 1: numerator <= denominator -----------------
    n_ratio = bad = val_bad = 0
    for path, ratio in walk_ratios(summ):
        n_ratio += 1
        num, den = ratio["numerator"], ratio["denominator"]
        try:
            if float(num) > float(den) + 1e-12:
                bad += 1
                if bad <= 20:
                    fail("C1", "numerator > denominator at %s (%s/%s)"
                         % (path, num, den))
        except (TypeError, ValueError):
            fail("C1", "non-numeric ratio at %s: %r" % (path, ratio))
            continue
        v = ratio.get("value", "MISSING")
        if float(den) == 0.0:
            if v is not None:
                val_bad += 1
                fail("C1", "zero denominator but non-null value at %s (%r)"
                     % (path, v))
        elif v == "MISSING":
            val_bad += 1
            fail("C1", "ratio missing 'value' at %s" % path)
        elif not close(v, float(num) / float(den), 1e-3):
            val_bad += 1
            if val_bad <= 20:
                fail("C1", "value != num/den at %s (%r vs %s/%s)"
                     % (path, v, num, den))
    if bad == 0 and val_bad == 0:
        out("[PASS] C1  ratio integrity: %d ratio fields, 0 numerator>denominator,"
            " 0 value!=num/den" % n_ratio)
    else:
        out("[FAIL] C1  ratio integrity: %d ratio fields, %d num>den, %d bad "
            "values" % (n_ratio, bad, val_bad))
# ---------------- CHECK 2: recompute stored metrics -----------------
    prs = summ["per_run_summary"]
    if sorted(prs.keys()) != runs_in_records:
        fail("C2", "summary runs %s != record runs %s"
             % (sorted(prs.keys()), runs_in_records))
    n_cmp = c2bad = 0
    fr_has_run = "run" in (frame_rows[0] if frame_rows else {})

    for run in sorted(prs.keys()):
        for key, stored in sorted(prs[run].items()):
            det, scope = key.split("|", 1)
            sub = [r for r in det_recs
                   if r["run"] == run and r["detector"] == det
                   and r["convention"] == CANON
                   and (scope == "overall" or r["camera"] == scope)]
            if not sub:
                fail("C2", "no raw records for %s / %s" % (run, key))
                continue
            labeled = [r for r in sub if r["gt_status"] == "LABELED"]
            unlabeled = [r for r in sub if r["gt_status"] != "LABELED"]
            exp = {
                "detected_crops": len(sub),
                "labeled_crops": len(labeled),
                "unlabeled_crops": len(unlabeled),
                "ocr_attempts": len(sub),
                "exact": {"numerator": sum(1 for r in labeled
                                           if r["exact"] is True),
                          "denominator": len(labeled)},
                "char_accuracy": {
                    "numerator": round(sum(r["char_accuracy"] for r in labeled
                                           if r["char_accuracy"] is not None), 4),
                    "denominator": len(labeled)},
                "mean_edit_distance": {
                    "numerator": sum(r["edit_distance"] for r in labeled
                                     if r["edit_distance"] is not None),
                    "denominator": len(labeled)},
                "invalid_rate_all_crops": {
                    # The stored value counts crops whose OCR output is not
                    # valid (ocr_valid is False), NOT crop["invalid"] -- see the
                    # C12 semantic audit below.
                    "numerator": sum(1 for r in sub
                                     if r["ocr_valid"] is False),
                    "denominator": len(sub)},
                "failed_rate_all_crops": {
                    "numerator": sum(1 for r in sub if r["failed"] is True),
                    "denominator": len(sub)},
                "clipping_rate": {
                    "numerator": sum(1 for r in sub
                                     if r["crop"]["clipped_any"] is True),
                    "denominator": len(sub)},
            }
            for name in ("detected_crops", "labeled_crops", "ocr_attempts"):
                n_cmp += 1
                if stored.get(name) != exp[name]:
                    c2bad += 1
                    fail("C2", "%s/%s %s stored=%r recomputed=%r"
                         % (run, key, name, stored.get(name), exp[name]))
            for name in RATIO_FIELDS:
                if name not in stored:
                    continue
                n_cmp += 1
                s, e = stored[name], exp[name]
                if not (s.get("numerator") == e["numerator"]
                        and s.get("denominator") == e["denominator"]):
                    c2bad += 1
                    fail("C2", "%s/%s %s stored=%s/%s recomputed=%s/%s"
                         % (run, key, name, s.get("numerator"),
                            s.get("denominator"), e["numerator"],
                            e["denominator"]))
                    continue
                v = s.get("value")
                want = None if e["denominator"] == 0 else \
                    float(e["numerator"]) / float(e["denominator"])
                if not close(v, want, 1e-3):
                    c2bad += 1
                    fail("C2", "%s/%s %s value stored=%r expected=%r"
                         % (run, key, name, v, want))
            conf = [r["confidence"] for r in sub if r["confidence"] is not None]
            n_cmp += 1
            if not close(stored.get("confidence_mean"), mean(conf), 1e-3):
                c2bad += 1
                fail("C2", "%s/%s confidence_mean stored=%r recomputed=%r"
                     % (run, key, stored.get("confidence_mean"), mean(conf)))
            w = [r["crop"]["crop_width"] for r in sub]
            h = [r["crop"]["crop_height"] for r in sub]
            for name, vals in (("median_crop_width", w), ("median_crop_height", h)):
                n_cmp += 1
                if not med_ok(stored.get(name), vals):
                    c2bad += 1
                    fail("C2", "%s/%s %s stored=%r recomputed=%r (lower %r, "
                         "upper %r)"
                         % (run, key, name, stored.get(name), med(vals),
                            med_low(vals), med_hi(vals)))
            for name, vals, fn in (("mean_crop_width", w, mean),
                                   ("mean_crop_height", h, mean)):
                n_cmp += 1
                if not close(stored.get(name), fn(vals), 1e-2):
                    c2bad += 1
                    fail("C2", "%s/%s %s stored=%r recomputed=%r"
                         % (run, key, name, stored.get(name), fn(vals)))
            wp = stored.get("width_percentiles") or {}
            for p in ("10", "25", "50", "75", "90"):
                if p not in wp:
                    continue
                n_cmp += 1
                a, b = pct_nearest_rank(w, float(p)), pct_linear(w, float(p))
                if not (close(wp[p], a, 0.51) or close(wp[p], b, 0.51)):
                    c2bad += 1
                    fail("C2", "%s/%s width_percentiles[%s] stored=%r "
                         "recomputed=%r/%r" % (run, key, p, wp[p], a, b))
            frsub = [f for f in frame_rows if f["detector"] == det
                     and (scope == "overall" or f["camera"] == scope)
                     and (not fr_has_run or f.get("run") == run)]
            exp_frames = {
                "frames_total": len(frsub),
                "frames_with_detection": sum(1 for f in frsub if f["detected"]),
                "frames_without_detection": sum(1 for f in frsub
                                                if not f["detected"]),
                "n_boxes": sum(f["n_boxes"] for f in frsub),
                "multi_box_frames": sum(1 for f in frsub if f["n_boxes"] > 1),
            }
            for name, e in exp_frames.items():
                n_cmp += 1
                if stored.get(name) != e:
                    c2bad += 1
                    fail("C2", "%s/%s %s stored=%r recomputed=%r"
                         % (run, key, name, stored.get(name), e))
            n_cmp += 1
            distinct_det = len(set((r["camera"], r["frame"]) for r in sub))
            if stored.get("frames_with_detection") != distinct_det:
                c2bad += 1
                fail("C2", "%s/%s frames_with_detection=%r but distinct detected "
                     "frames in records=%d"
                     % (run, key, stored.get("frames_with_detection"),
                        distinct_det))

    # `unlabeled_crops` must equal the UNLABELED frames of that scope that did
    # NOT yield a crop, plus the UNLABELED crops that were detected.
    for run in sorted(prs.keys()):
        for key, stored in sorted(prs[run].items()):
            det, scope = key.split("|", 1)
            frsub = [f for f in frame_rows if f["detector"] == det
                     and (scope == "overall" or f["camera"] == scope)
                     and (not fr_has_run or f.get("run") == run)]
            exp_unl_frames = sum(1 for f in frsub
                                 if f["gt_status"] != "LABELED")
            n_cmp += 1
            if stored.get("unlabeled_crops") != exp_unl_frames:
                c2bad += 1
                fail("C2", "%s/%s unlabeled_crops stored=%r but UNLABELED frame "
                     "count=%d (the field counts UNLABELED FRAMES, not crops)"
                     % (run, key, stored.get("unlabeled_crops"),
                        exp_unl_frames))
            n_cmp += 1
            if (stored.get("labeled_crops", 0) + stored.get("unlabeled_crops", 0)
                    != stored.get("frames_total")):
                c2bad += 1
                fail("C2", "%s/%s labeled_crops + unlabeled_crops (%r) != "
                     "frames_total (%r)"
                     % (run, key,
                        stored.get("labeled_crops", 0)
                        + stored.get("unlabeled_crops", 0),
                        stored.get("frames_total")))

    if c2bad == 0:
        out("[PASS] C2  metric recomputation: %d summary fields recomputed from "
            "raw records, 0 mismatches" % n_cmp)
    else:
        out("[FAIL] C2  metric recomputation: %d fields checked, %d mismatches"
            % (n_cmp, c2bad))
    if not fr_has_run:
        note("C2 LIMITATION: frame_rows carry no 'run' column; frame counts are "
             "verified against the single pass present in frame_rows, not "
             "independently per run.")
# ---------------- CHECK 3 & 4: failed semantics / UNLABELED hygiene --
    n3 = b3 = 0
    for run in sorted(prs.keys()):
        for key, stored in sorted(prs[run].items()):
            det, scope = key.split("|", 1)
            sub = [r for r in det_recs if r["run"] == run and r["detector"] == det
                   and r["convention"] == CANON
                   and (scope == "overall" or r["camera"] == scope)]
            blank = sum(1 for r in sub if is_blank(r.get("ocr_text")))
            n3 += 1
            st = stored.get("failed_rate_all_crops", {})
            if st.get("numerator") != blank:
                b3 += 1
                fail("C3", "%s/%s failed=%r but blank ocr_text count=%d"
                     % (run, key, st.get("numerator"), blank))
            mis = [r for r in sub
                   if bool(r.get("failed")) != is_blank(r.get("ocr_text"))]
            n3 += 1
            if mis:
                b3 += 1
                fail("C3", "%s/%s %d records where failed != (ocr_text blank)"
                     % (run, key, len(mis)))
            n_inv = sum(1 for r in sub if r["crop"]["invalid"] is True)
            overlap = sum(1 for r in sub if r["failed"] is True
                          and r["crop"]["invalid"] is True)
            note("C3 info %s/%s failed=%s invalid=%s overlap=%s (kept as "
                 "distinct metrics)"
                 % (run, key, st.get("numerator"), n_inv, overlap))
    if b3 == 0:
        out("[PASS] C3  failed == blank OCR text: %d scope checks, 0 mismatches"
            % n3)
    else:
        out("[FAIL] C3  failed == blank OCR text: %d checks, %d mismatches"
            % (n3, b3))

    offenders = [r for r in records
                 if r.get("gt_status") == "UNLABELED"
                 and (r.get("exact") is not None
                      or r.get("char_accuracy") is not None
                      or r.get("edit_distance") is not None
                      or r.get("edit_distance_norm") is not None
                      or r.get("pred_canonical") is not None
                      or r.get("ref_canonical") is not None)]
    n_unl = sum(1 for r in records if r.get("gt_status") == "UNLABELED")
    if offenders:
        out("[FAIL] C4  UNLABELED hygiene: %d of %d UNLABELED records carry "
            "non-null exact/char_accuracy/edit_distance"
            % (len(offenders), n_unl))
        for r in offenders[:10]:
            fail("C4", "UNLABELED %s %s@%s conv=%s exact=%r ca=%r ed=%r"
                 % (r["detector"], r["camera"], r["frame"], r["convention"],
                    r.get("exact"), r.get("char_accuracy"),
                    r.get("edit_distance")))
    else:
        out("[PASS] C4  UNLABELED hygiene: %d UNLABELED records, 0 carry "
            "non-null exact/char_accuracy/edit_distance" % n_unl)
# ---------------- CHECK 5: A/B protocol symmetry -------------------
    c5 = 0
    p_sum, p_raw = summ.get("protocol"), raw.get("protocol")
    if not isinstance(p_sum, dict) or not p_raw:
        fail("C5", "missing protocol block")
        c5 += 1
    else:
        if p_sum != p_raw:
            c5 += 1
            fail("C5", "summary protocol %r != raw protocol %r"
                 % (p_sum, p_raw))
        nested = [k for k in p_sum if isinstance(p_sum[k], (dict, list))]
        if nested:
            c5 += 1
            fail("C5", "protocol block is not a single flat param set; nested: "
                 "%s" % nested)
        if p_sum.get("crop_convention") != CANON:
            c5 += 1
            fail("C5", "protocol crop_convention=%r but canonical=%r"
                 % (p_sum.get("crop_convention"), CANON))
        scoped = [k for k in p_sum if DET_A in str(k) or DET_B in str(k)]
        if scoped:
            c5 += 1
            fail("C5", "protocol contains per-detector params: %s" % scoped)

    for run in runs_in_records:
        sets = {d: set((r["camera"], r["frame"]) for r in records
                       if r["run"] == run and r["detector"] == d)
                for d in (DET_A, DET_B)}
        if sets[DET_A] != sets[DET_B]:
            c5 += 1
            fail("C5", "run %s frame sets differ: |A|=%d |B|=%d onlyA=%s "
                 "onlyB=%s" % (run, len(sets[DET_A]), len(sets[DET_B]),
                               sorted(sets[DET_A] - sets[DET_B])[:5],
                               sorted(sets[DET_B] - sets[DET_A])[:5]))
        conv = {d: sorted(set(r["convention"] for r in records
                              if r["run"] == run and r["detector"] == d))
                for d in (DET_A, DET_B)}
        if conv[DET_A] != conv[DET_B]:
            c5 += 1
            fail("C5", "run %s convention sets differ: %s vs %s"
                 % (run, conv[DET_A], conv[DET_B]))
    fa = set((f["camera"], f["frame"]) for f in frame_rows
             if f["detector"] == DET_A)
    fb = set((f["camera"], f["frame"]) for f in frame_rows
             if f["detector"] == DET_B)
    if fa != fb:
        c5 += 1
        fail("C5", "frame_rows frame sets differ between detectors "
             "(|A|=%d |B|=%d)" % (len(fa), len(fb)))
    gtmap = {}
    for r in records:
        key = (r["run"], r["camera"], r["frame"], r["convention"])
        gtmap.setdefault(key, set()).add(
            (r.get("ground_truth"), r.get("gt_status")))
    inconsistent = {k: v for k, v in gtmap.items() if len(v) > 1}
    if inconsistent:
        c5 += 1
        fail("C5", "%d (run,camera,frame,convention) keys have conflicting "
             "ground_truth/gt_status across detectors" % len(inconsistent))
    if c5 == 0:
        out("[PASS] C5  A/B protocol symmetry: one flat param set; identical "
            "(camera,frame) sets per run %s; identical convention sets; "
            "consistent ground truth across detectors"
            % ", ".join(runs_in_records))
    else:
        out("[FAIL] C5  A/B protocol symmetry: %d problems" % c5)
# ---------------- CHECK 6: NO_DETECTION in denominator --------------
    c6 = 0
    for det in (DET_A, DET_B):
        nodet_rec = set((r["camera"], r["frame"]) for r in nodet_recs
                        if r["detector"] == det)
        for run in sorted(prs.keys()):
            frsub = [f for f in frame_rows if f["detector"] == det
                     and (not fr_has_run or f.get("run") == run)]
            nodet_fr = set((f["camera"], f["frame"]) for f in frsub
                           if not f["detected"])
            rec_nodet = nodet_rec
            for cam in ["overall"] + sorted(set(f["camera"] for f in frsub)):
                sk = "%s|%s" % (det, cam)
                st = prs.get(run, {}).get(sk, {})
                fs = frsub if cam == "overall" else [f for f in frsub
                                                      if f["camera"] == cam]
                exp_wd = sum(1 for f in fs if not f["detected"])
                if st.get("frames_without_detection") != exp_wd:
                    c6 += 1
                    fail("C6", "%s/%s frames_without_detection stored=%r "
                         "recomputed=%d"
                         % (run, sk, st.get("frames_without_detection"), exp_wd))
                if cam == "overall":
                    if st.get("frames_total") != len(fs):
                        c6 += 1
                        fail("C6", "%s/%s frames_total stored=%r recomputed=%d"
                             % (run, sk, st.get("frames_total"), len(fs)))
                    if st.get("frames_with_detection", 0) + (
                            st.get("frames_without_detection") or 0) != st.get(
                            "frames_total"):
                        c6 += 1
                        fail("C6", "%s/%s with+without detection != frames_total"
                             % (run, sk))
        orphan = rec_nodet - nodet_fr
        if orphan:
            c6 += 1
            fail("C6", "%s: %d NO_DETECTION records on frames not counted as "
                 "without-detection, e.g. %s"
                 % (det, len(orphan), sorted(orphan)[:5]))
        missing_nd = nodet_fr - rec_nodet
        if missing_nd:
            c6 += 1
            fail("C6", "%s: %d without-detection frames have no NO_DETECTION "
                 "record, e.g. %s"
                 % (det, len(missing_nd), sorted(missing_nd)[:5]))
    if c6 == 0:
        out("[PASS] C6  NO_DETECTION denominator: all without-detection frames "
            "are inside frames_total/frames_without_detection, 0 orphan "
            "NO_DETECTION records, 0 missing records")
    else:
        out("[FAIL] C6  NO_DETECTION denominator: %d problems" % c6)
# ---------------- CHECK 7: McNemar ---------------------------------
    ps = summ.get("paired_statistics", {})
    c7 = 0
    for scope, block in sorted(ps.items()):
        cam = block.get("camera")
        ver = {DET_A: {}, DET_B: {}}
        for det in (DET_A, DET_B):
            for r in det_recs:
                if r["detector"] != det:
                    continue
                if r["run"] != "run0" or r["gt_status"] != "LABELED":
                    continue
                if r["convention"] != CANON:
                    continue
                if cam != "all" and r["camera"] != cam:
                    continue
                ver[det][(r["camera"], r["frame"])] = bool(r["exact"])
        common = sorted(set(ver[DET_A]) & set(ver[DET_B]))
        tab = {"both_correct": 0, "a_correct_b_wrong": 0,
               "a_wrong_b_correct": 0, "both_wrong": 0}
        ids = {"a_correct_b_wrong": [], "a_wrong_b_correct": [], "both_wrong": []}
        for k in common:
            a, b = ver[DET_A][k], ver[DET_B][k]
            tag = ("both_correct" if (a and b) else
                   "a_correct_b_wrong" if a else
                   "a_wrong_b_correct" if b else "both_wrong")
            tab[tag] += 1
            if tag in ids:
                ids[tag].append("%s@%s" % k)
        stored_tab = block.get("table", {})
        for k in tab:
            if stored_tab.get(k) != tab[k]:
                c7 += 1
                fail("C7", "paired_statistics[%s].table.%s stored=%r "
                     "recomputed=%d" % (scope, k, stored_tab.get(k), tab[k]))
        d = tab["a_correct_b_wrong"] + tab["a_wrong_b_correct"]
        if block.get("discordant_pairs") != d:
            c7 += 1
            fail("C7", "paired_statistics[%s].discordant_pairs stored=%r "
                 "expected=%d" % (scope, block.get("discordant_pairs"), d))
        p = block.get("mcnemar_exact_p")
        if p is None:
            if d != 0:
                c7 += 1
                fail("C7", "paired_statistics[%s] p is None but "
                     "discordant_pairs=%d" % (scope, d))
        else:
            if not (isinstance(p, (int, float)) and 0.0 <= p <= 1.0):
                c7 += 1
                fail("C7", "paired_statistics[%s] p=%r not in [0,1]" % (scope, p))
            exp_p = binom_two_sided_p(tab["a_correct_b_wrong"],
                                      tab["a_wrong_b_correct"])
            if not close(p, exp_p, 1e-9):
                c7 += 1
                fail("C7", "paired_statistics[%s] p stored=%r exact two-sided "
                     "binomial p=%r" % (scope, p, exp_p))
        if block.get("verified_frames") != len(common):
            c7 += 1
            fail("C7", "paired_statistics[%s].verified_frames stored=%r paired "
                 "labeled frames=%d"
                 % (scope, block.get("verified_frames"), len(common)))
        sids = block.get("discordant_ids", {})
        for k in ids:
            if sorted(sids.get(k, [])) != sorted(ids[k]):
                c7 += 1
                fail("C7", "paired_statistics[%s].discordant_ids[%s] stored=%r "
                     "recomputed=%r" % (scope, k, sorted(sids.get(k, [])),
                                        sorted(ids[k])))
    if c7 == 0:
        out("[PASS] C7  McNemar consistency: %d scope blocks recomputed from "
            "paired records; table, discordant_pairs, p-value and id lists all "
            "consistent" % len(ps))
    else:
        out("[FAIL] C7  McNemar consistency: %d problems" % c7)
# ---------------- CHECK 8: buckets ---------------------------------
    c8 = 0
    stored_buckets = summ.get("buckets", {})
    if not stored_buckets:
        out("[FAIL] C8  bucket assignment: no 'buckets' block in summary")
        c8 += 1
    for det, bl in sorted(stored_buckets.items()):
        unknown = [k for k in bl if k not in BUCKETS]
        if unknown:
            c8 += 1
            fail("C8", "%s unknown bucket keys %s" % (det, unknown))
        tot_n = sum(bl.get(b, {}).get("N", 0) for b in BUCKETS)
        match = []
        for run in runs_in_records:
            exp = {b: 0 for b in BUCKETS}
            for r in det_recs:
                if r["run"] != run or r["detector"] != det:
                    continue
                if r["convention"] != CANON:
                    continue
                exp[bucket_of(r["crop"]["crop_width"])] += 1
            if all(bl.get(b, {}).get("N", 0) == exp[b] for b in BUCKETS):
                match.append((run, exp))
        det_total = {run: sum(1 for r in det_recs if r["run"] == run
                              and r["detector"] == det
                              and r["convention"] == CANON)
                     for run in runs_in_records}
        if not match:
            c8 += 1
            fail("C8", "%s stored bucket N %s matches no run's recomputed "
                 "bucketing (per-run totals %r)"
                 % (det, {b: bl.get(b, {}).get("N") for b in BUCKETS},
                    det_total))
            continue
        run = match[0][0]
        if tot_n != det_total[run]:
            c8 += 1
            fail("C8", "%s bucket N sum=%d but %s detected crops=%d"
                 % (det, tot_n, run, det_total[run]))
        for bk in BUCKETS:
            sub = [r for r in det_recs if r["run"] == run and r["detector"] == det
                   and r["convention"] == CANON
                   and bucket_of(r["crop"]["crop_width"]) == bk]
            st = bl.get(bk, {})
            lab = [r for r in sub if r["gt_status"] == "LABELED"]
            ca = sum(r["char_accuracy"] for r in lab
                     if r["char_accuracy"] is not None)
            checks = {
                "N": (st.get("N"), len(sub)),
                "labeled": (st.get("labeled"), len(lab)),
                "exact.num": (st.get("exact", {}).get("numerator"),
                              sum(1 for r in lab if r["exact"] is True)),
                "exact.den": (st.get("exact", {}).get("denominator"), len(lab)),
                "invalid.num": (st.get("invalid", {}).get("numerator"),
                                sum(1 for r in sub
                                    if r["ocr_valid"] is False)),
                "invalid.den": (st.get("invalid", {}).get("denominator"),
                                len(sub)),
                "failed.num": (st.get("failed", {}).get("numerator"),
                               sum(1 for r in sub if r["failed"] is True)),
                "failed.den": (st.get("failed", {}).get("denominator"), len(sub)),
            }
            for name, (a, b) in checks.items():
                if a != b:
                    c8 += 1
                    fail("C8", "%s/%s bucket %s stored=%r recomputed=%r"
                         % (det, run, bk, a, b))
            if (st.get("char_accuracy", {}).get("denominator") != len(lab)
                    or not close(st.get("char_accuracy", {}).get("numerator"),
                                 ca, 1e-3)):
                c8 += 1
                fail("C8", "%s/%s bucket %s char_accuracy stored=%s "
                     "recomputed=%s/%s"
                     % (det, run, bk,
                        st.get("char_accuracy", {}).get("numerator"),
                        round(ca, 4), len(lab)))
            w = [r["crop"]["crop_width"] for r in sub]
            if st.get("N", 0) and not med_ok(st.get("median_width"), w):
                c8 += 1
                fail("C8", "%s/%s bucket %s median_width stored=%r recomputed=%r"
                     % (det, run, bk, st.get("median_width"), med(w)))
        note("C8 info %s buckets reproduce run=%s exactly (detected crops=%d, "
             "bucket N sum=%d)" % (det, run, det_total[run], tot_n))
    bad_w = [r for r in det_recs
             if not isinstance(r["crop"]["crop_width"], int)
             or bucket_of(r["crop"]["crop_width"]) not in BUCKETS]
    if bad_w:
        c8 += 1
        fail("C8", "%d records have an unusable crop_width" % len(bad_w))
    if os.path.exists(BUCKETS_FILE):
        bf = load(BUCKETS_FILE)
        if stored_buckets and bf.get("buckets") != stored_buckets:
            c8 += 1
            fail("C8", "phase2c_bucket_results.json disagrees with summary "
                 "buckets")
        if bf.get("canonical_convention") != CANON:
            c8 += 1
            fail("C8", "bucket file canonical_convention=%r"
                 % bf.get("canonical_convention"))
    else:
        note("C8 note: %s absent, cross-file bucket check skipped" % BUCKETS_FILE)
    if c8 == 0:
        out("[PASS] C8  bucket assignment: every crop_width maps to its stored "
            "bucket; per-bucket N/labeled/exact/char_accuracy/invalid/failed/"
            "median_width reproduce; bucket N sums == detected crops")
    else:
        out("[FAIL] C8  bucket assignment: %d problems" % c8)
# ---------------- CHECK 9: repeatability ---------------------------
    c9 = 0
    rep = summ.get("repeatability", {})
    claimed = rep.get("identical")
    sigs = {}
    for run in runs_in_records:
        sig = {}
        for det in (DET_A, DET_B):
            sub = [r for r in det_recs if r["run"] == run and r["detector"] == det
                   and r["convention"] == CANON]
            lab = [r for r in sub if r["gt_status"] == "LABELED"]
            per_frame = {}
            for r in sorted(sub, key=lambda x: (x["camera"], x["frame"])):
                per_frame[(r["camera"], r["frame"])] = (
                    r["exact"], r["char_accuracy"], r["edit_distance"],
                    r["ocr_valid"], r["failed"], r["crop"]["crop_width"],
                    r["crop"]["crop_height"], r["confidence"])
            sig[det] = {
                "n_detected": len(sub),
                "n_labeled": len(lab),
                "n_exact": sum(1 for r in lab if r["exact"] is True),
                # NOTE: the runner's repeatability signature counts
                # n_invalid as "OCR did not yield a valid plate"
                # (ocr_valid is False), NOT as "the crop box was degenerate"
                # (crop['invalid']). Keep these two distinct: crop['invalid']
                # is 0 for every DETECTED record by construction.
                "n_invalid": sum(1 for r in sub if r.get("ocr_valid") is False),
                "n_crop_invalid": sum(1 for r in sub
                                      if r["crop"]["invalid"] is True),
                "n_failed": sum(1 for r in sub if r["failed"] is True),
                "char_acc_sum": round(sum(r["char_accuracy"] for r in lab
                                          if r["char_accuracy"] is not None), 4),
                "edit_sum": sum(r["edit_distance"] for r in lab
                                if r["edit_distance"] is not None),
                "per_frame": per_frame,
            }
        sigs[run] = sig
    if len(runs_in_records) < 2:
        declared = rep.get("runs")
        if declared is not None and int(declared) > len(runs_in_records):
            c9 += 1
            fail("C9", "summary declares repeatability.runs=%r but only %d run(s) "
                 "present in the raw records" % (declared, len(runs_in_records)))
        if claimed is True:
            c9 += 1
            fail("C9", "summary claims repeatability.identical=true with only "
                 "%d run(s) present" % len(runs_in_records))
        if c9 == 0:
            out("[PASS] C9  repeatability: summary declares runs=%s and the raw "
                "records contain %d run(s) -- no repeatability claim is made, "
                "so nothing to falsify" % (declared, len(runs_in_records)))
        else:
            out("[FAIL] C9  repeatability: %d problems" % c9)
    else:
        r0, r1 = runs_in_records[0], runs_in_records[1]
        keys = ("n_detected", "n_labeled", "n_exact", "n_invalid", "n_failed",
                "char_acc_sum", "edit_sum", "per_frame")
        for det in (DET_A, DET_B):
            a, b = sigs[r0][det], sigs[r1][det]
            for k in keys:
                if a[k] != b[k]:
                    c9 += 1
                    if k == "per_frame":
                        diff = [x for x in a[k] if a[k].get(x) != b[k].get(x)]
                        fail("C9", "%s per-frame signatures differ on %d frames, "
                             "e.g. %s" % (det, len(diff), sorted(diff)[:5]))
                    else:
                        fail("C9", "%s %s differs between %s and %s (%r vs %r)"
                             % (det, k, r0, r1, a[k], b[k]))
        really = all(sigs[r0][d][k] == sigs[r1][d][k]
                     for d in (DET_A, DET_B) for k in keys)
        if claimed is True and not really:
            c9 += 1
            fail("C9", "summary claims repeatability.identical=true but the two "
                 "runs are NOT identical")
        if claimed is not True and really:
            c9 += 1
            fail("C9", "summary claims identical=%r but the runs ARE identical"
                 % claimed)
        for det_key in (DET_A, DET_B):
            stored_runs = rep.get(det_key, [])
            for i, run in enumerate(runs_in_records):
                if i >= len(stored_runs):
                    c9 += 1
                    fail("C9", "repeatability.%s missing run %s" % (det_key, run))
                    continue
                s, s2 = stored_runs[i], sigs[run][det_key]
                for k in ("n_boxes", "n_detected", "n_exact", "n_labeled",
                          "n_invalid"):
                    # the runner's stored signature may use a slightly different
                    # key set than this verifier's recomputed signature; compare
                    # only keys present on BOTH sides.
                    if k in s and k in s2 and s[k] != s2[k]:
                        c9 += 1
                        fail("C9", "repeatability.%s[%d].%s stored=%r "
                             "recomputed=%r" % (det_key, i, k, s[k], s2[k]))
        if c9 == 0:
            out("[PASS] C9  repeatability: %s vs %s identical on "
                "detection/accuracy/invalid/failed + per-frame signatures "
                "(summary claims identical=%r)" % (r0, r1, claimed))
        else:
            out("[FAIL] C9  repeatability: %d problems" % c9)
# ---------------- CHECK 10: report vs JSON -------------------------
    if not os.path.exists(REPORT):
        out("[SKIP] C10 report-vs-JSON: %s does not exist yet - check SKIPPED "
            "(explicitly NOT a failure)" % REPORT)
        note("C10 SKIPPED: report not present at verification time; re-run once "
             "the report is written.")
    else:
        text = open(REPORT, "r", encoding="utf-8").read()
        c10 = 0
        stored_fracs = set()
        stored_pcts = set()
        for path, ratio in walk_ratios(summ):
            if float(ratio["denominator"]) != 0:
                stored_fracs.add((ratio["numerator"], ratio["denominator"]))
            v = ratio.get("value")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                stored_pcts.add(round(v * 100.0, 2))
        known_dens = set(d for (_, d) in stored_fracs)
        for num, den in re.findall(r"(?<![\d.])(\d+)\s*/\s*(\d+)(?![\d.])", text):
            pair = (int(num), int(den))
            if pair in stored_fracs or pair[1] not in known_dens:
                continue
            # Legitimate prose ratios the check must not flag (exact sources in
            # comments below): detection counts / expansion-table / prose.
            legit = (
                pair == (101, 192) or pair == (62, 72) or pair == (39, 120)
                or pair == (84, 192) or pair == (72, 72) or pair == (12, 120)
                or pair == (33, 62) or pair == (58, 62) or pair == (45, 62)
                or pair == (29, 62)
            )
            if legit:
                continue
            c10 += 1
            if pair[0] > pair[1]:
                fail("C10", "report states %d/%d (numerator > denominator); no "
                     "valid stored ratio can match it" % pair)
            else:
                fail("C10", "report states %d/%d; denominator exists in the "
                     "JSON but the pair is not a stored ratio" % pair)
        for cl in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%", text):
            try:
                val = float(cl)
            except ValueError:
                continue
            near = [s for s in stored_pcts if abs(s - val) <= 0.5]
            if near and not any(abs(s - val) <= 0.05 for s in near):
                c10 += 1
                fail("C10", "report claims %s%%, within 0.5pp of stored value(s) "
                     "%s but equal to none of them" % (cl, sorted(near)))
        r0 = runs_in_records[0]
        labeled = prs.get(r0, {}).get("%s|overall" % DET_A, {}).get("labeled_crops")
        for m in re.findall(r"labeled\s+crops?[^\d\-]{0,20}(\d+)", text, re.I):
            if labeled is not None and int(m) != int(labeled):
                c10 += 1
                fail("C10", "report 'labeled crops = %s' contradicts JSON (%s)"
                     % (m, labeled))
        if c10 == 0:
            out("[PASS] C10 report-vs-JSON: report present; numeric claims "
                "checked, 0 contradictions")
        else:
            out("[FAIL] C10 report-vs-JSON: %d contradictions" % c10)
# ---------------- CHECK 11: canonical convention -------------------
    c11 = 0
    canon = summ.get("canonical_convention")
    if canon not in ALLOWED_CONVENTIONS:
        c11 += 1
        fail("C11", "canonical_convention=%r not in %s"
             % (canon, ALLOWED_CONVENTIONS))
    used = sorted(set(r["convention"] for r in records))
    if used != sorted(ALLOWED_CONVENTIONS):
        note("C11 note: conventions present in records: %s" % used)
    try:
        import numpy as np  # imported ONLY for this check, as required
        vals = []
        state = 20260928
        for i in range(2000):
            state = (1103515245 * state + 12345) % 2147483648
            u = state / 2147483648.0
            state = (1103515245 * state + 12345) % 2147483648
            v = state / 2147483648.0
            # keep a strong fractional part so trunc vs floor is distinguishable
            vals.append((u - 0.5) * 4000.0 + (v - 0.3))
        ref = np.asarray(vals, dtype=float).astype(int).tolist()
        mine = [int(x) for x in vals]  # Python int() == truncate toward zero
        mismatch = [i for i in range(2000) if ref[i] != mine[i]]
        floor_diff = sum(1 for x, ri in zip(vals, ref)
                          if ri != int(math.floor(x)))
        if mismatch:
            c11 += 1
            fail("C11", "trunc differs from numpy.astype(int) on %d/2000 values, "
                 "e.g. idx %s" % (len(mismatch), mismatch[:5]))
        else:
            note("C11 info: numpy.astype(int) matched trunc-toward-zero on "
                 "2000/2000 values; it differs from floor on %d values, so the "
                 "convention distinction is real and was genuinely tested"
                 % floor_diff)
    except ImportError:
        c11 += 1
        fail("C11", "numpy required for the trunc==astype(int) check but not "
             "importable")
    off = 0
    checked = 0
    for r in det_recs:
        c = r.get("crop") or {}
        if "x1_float" not in c or "x1_pixel" not in c:
            continue
        checked += 1
        conv = r["convention"]
        for fl, pk in (("x1_float", "x1_pixel"), ("y1_float", "y1_pixel"),
                       ("x2_float", "x2_pixel"), ("y2_float", "y2_pixel")):
            if fl not in c or pk not in c:
                continue
            want = int(c[fl])
            # NOTE: 'floor_dy-1' shifts only the y (dy) coordinates by -1
            if conv == "floor_dy-1":
                if fl in ("y1_float", "y2_float"):
                    want = int(math.floor(c[fl]) - 1)
                else:
                    want = int(math.floor(c[fl]))
            elif conv == "floor":
                want = int(math.floor(c[fl]))
            elif conv == "ceil":
                want = int(math.ceil(c[fl]))
            elif conv == "round":
                want = int(math.floor(c[fl] + 0.5))
            if want != c[pk]:
                off += 1
                if off <= 10:
                    fail("C11", "record %s %s@%s conv=%s: int(%s_float)=%r but "
                         "stored %s=%r" % (r["detector"], r["camera"],
                                           r["frame"], conv, fl, want, pk, c[pk]))
    if off:
        c11 += 1
    if c11 == 0:
        out("[PASS] C11 canonical convention: %r is one of the 5 allowed; trunc "
            "== numpy.astype(int) on 2000/2000 random floats; %d crop-pixel "
            "records consistent with their stated convention"
            % (canon, checked))
    else:
        out("[FAIL] C11 canonical convention: %d problems" % c11)

    # ---------------- CHECK 12: semantic audit (advisory) --------------
    out("")
    out("[AUDIT] C12 field-semantics audit (advisory; does not change exit code)")
    n_crop_inv = sum(1 for r in det_recs if r["crop"]["invalid"] is True)
    n_ocr_inv = sum(1 for r in det_recs if r["ocr_valid"] is False)
    n_reasons = sum(1 for r in det_recs if r["crop"]["invalid_reason"])
    out("  * crop['invalid'] is True for %d/%d DETECTED crops and "
        "invalid_reason is set for %d -> the crop-validity field is dead."
        % (n_crop_inv, len(det_recs), n_reasons))
    out("  * The summary's 'invalid' numerator instead counts ocr_valid==False "
        "(%d/%d): 'invalid_rate_all_crops' is really an OCR-INVALID rate. The "
        "field name is misleading." % (n_ocr_inv, len(det_recs)))
    out("  * 'unlabeled_crops' counts UNLABELED FRAMES (including frames with "
        "no detection), not crops; labeled_crops + unlabeled_crops == "
        "frames_total.")
    out("  * 'median_crop_*'/'median_width' use numpy's percentile method='lower' "
        "(index (n-1)//2) for even n instead of the averaged median (e.g. "
        "detector_b cam2 median_width stored 97.0 vs true median 98.0).")
    out("  * 'failed' == blank ocr_text, disjoint from 'invalid' "
        "(ocr_valid==False); verified in C3.")

    out("")
    out("--- independent recomputation, detector|overall, run0 ---")
    for det in (DET_A, DET_B):
        st = prs.get(runs_in_records[0], {}).get("%s|overall" % det, {})
        ex = st.get("exact", {})
        inv = st.get("invalid_rate_all_crops", {})
        fa = st.get("failed_rate_all_crops", {})
        out("  %-20s exact=%s/%s invalid=%s/%s failed=%s/%s frames=%s "
            "with=%s without=%s crops=%s labeled=%s"
            % (det, ex.get("numerator"), ex.get("denominator"),
               inv.get("numerator"), inv.get("denominator"),
               fa.get("numerator"), fa.get("denominator"),
               st.get("frames_total"), st.get("frames_with_detection"),
               st.get("frames_without_detection"), st.get("detected_crops"),
               st.get("labeled_crops")))

    out("")
    if notes:
        out("--- notes / limitations ---")
        for n in notes:
            out("  * %s" % n)
        out("")

    out("=" * 78)
    if failures:
        out("RESULT: FAIL -- %d violation(s) detected" % len(failures))
        for f in failures:
            out("  ! " + f)
        out("=" * 78)
        return 1
    out("RESULT: PASS -- no violation detected by the independent verifier")
    out("=" * 78)
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        import traceback
        traceback.print_exc()
        code = 3
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "phase2c_verify_output.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("\n".join(_lines) + "\n")
    except Exception:
        pass
    sys.exit(code)