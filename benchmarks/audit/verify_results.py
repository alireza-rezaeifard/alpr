"""Independent re-computation of Phase 2B stored results (READ-ONLY).

Recomputes every published aggregate from the raw `records` array in
benchmarks/results/phase2b_detector_crop_results.json and compares against the
stored summaries. Also audits UNLABELED handling, bucket boundaries, pairwise
classification, threshold sweep and crop-expansion coverage.

Run: python benchmarks/audit/verify_results.py
"""
from __future__ import annotations

import collections
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from ab_helpers import BUCKETS, bucket_for, classify_pair  # noqa: E402

RES = ROOT / "benchmarks" / "results"
DETECTORS = ("current_detector", "iranplate_vision")
VIDEOS = ("cam1.mp4", "cam2.mp4")

issues: list[str] = []
notes: list[str] = []


def flag(msg: str) -> None:
    issues.append(msg)


def note(msg: str) -> None:
    notes.append(msg)


def pct(values, p):
    """Nearest-rank percentile, re-derived independently (not imported)."""
    if not values:
        return None
    vs = sorted(values)
    idx = min(len(vs) - 1, max(0, int(round((p / 100.0) * (len(vs) - 1)))))
    return vs[idx]


def eq(a, b, tol=1e-6):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    return a == b


def cmp_field(scope, field, stored, recomputed):
    tol = 5e-4 if isinstance(stored, float) else 1e-9
    if not eq(stored, recomputed, tol):
        flag(f"[{scope}] {field}: stored={stored!r} recomputed={recomputed!r}")


def recompute_stats(rows):
    widths = [r["width"] for r in rows]
    heights = [r["height"] for r in rows]
    confs = [r["confidence"] for r in rows]
    ver = [r for r in rows if r.get("exact") is not None]
    return {
        "n_crops": len(rows),
        "n_verified": len(ver),
        "n_exact": sum(1 for r in ver if r["exact"]),
        "exact_accuracy": round(sum(1 for r in ver if r["exact"]) / len(ver), 4) if ver else None,
        "char_accuracy": round(sum(r["char_accuracy"] for r in ver) / len(ver), 4) if ver else None,
        "mean_edit_distance": round(sum(r["edit_distance"] for r in ver) / len(ver), 4) if ver else None,
        "invalid_rate": round(sum(1 for r in rows if not r["ocr_valid"]) / len(rows), 4),
        "failed_rate": round(sum(1 for r in rows if not r["ocr_text"]) / len(rows), 4),
        "mean_crop_width": round(statistics.fmean(widths), 1),
        "median_crop_width": round(statistics.median(widths), 1),
        "p10_crop_width": pct(widths, 10),
        "p25_crop_width": pct(widths, 25),
        "p50_crop_width": pct(widths, 50),
        "p75_crop_width": pct(widths, 75),
        "p90_crop_width": pct(widths, 90),
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
        "detector_conf_p10": pct(confs, 10),
        "detector_conf_p90": pct(confs, 90),
        "detector_latency_ms_p50": round(statistics.median([r["detector_latency_ms"] for r in rows]), 2),
        "detector_latency_ms_p95": pct([r["detector_latency_ms"] for r in rows], 95),
        "ocr_latency_ms_p50": round(statistics.median([r["ocr_latency_ms"] for r in rows]), 2),
        "ocr_latency_ms_p95": pct([r["ocr_latency_ms"] for r in rows], 95),
        "total_latency_ms_p50": round(statistics.median([r["total_latency_ms"] for r in rows]), 2),
    }


def main() -> None:
    det = json.loads((RES / "phase2b_detector_crop_results.json").read_text(encoding="utf-8"))
    pw = json.loads((RES / "phase2b_pairwise_results.json").read_text(encoding="utf-8"))
    bk = json.loads((RES / "phase2b_bucket_results.json").read_text(encoding="utf-8"))
    records = det["records"]

    # ---- 1. recompute every published aggregate --------------------------
    for d in DETECTORS:
        rows = [r for r in records if r.get("detector") == d and "ocr_text" in r]
        stored_all = det["detector_summary"][d]
        scopes = {"overall": rows}
        for v in VIDEOS:
            scopes[v] = [r for r in rows if r["camera"] == v]
        for _, _, name in BUCKETS:
            scopes[f"bucket:{name}"] = [r for r in rows if r["bucket"] == name]
        for scope, srows in scopes.items():
            st = stored_all.get(scope)
            rc = recompute_stats(srows)
            if st is None:
                flag(f"[{d}/{scope}] stored block null but {len(srows)} records exist")
                continue
            for k, v in rc.items():
                cmp_field(f"{d}/{scope}", k, st.get(k, "<MISSING>"), v)
        ver = [r for r in rows if r.get("exact") is not None]
        cvc = stored_all.get("confidence_vs_correctness", {})
        for key, sel in (("mean_conf_correct", lambda r: r["exact"]),
                         ("mean_conf_incorrect", lambda r: not r["exact"])):
            sub = [r["confidence"] for r in ver if sel(r)]

    # ---- 2. UNLABELED rule ------------------------------------------------
    cam2 = [r for r in records if r.get("camera") == "cam2.mp4" and "ocr_text" in r]
    for r in cam2:
        for f in ("exact", "char_accuracy", "edit_distance", "edit_distance_norm"):
            if r.get(f) is not None:
                flag(f"[UNLABELED] cam2 {r['detector']}@{r['frame']} {f}={r[f]!r} (must be null)")
        if r.get("ground_truth") is not None:
            flag(f"[UNLABELED] cam2 record carries ground_truth={r['ground_truth']!r}")
    for d in DETECTORS:
        s = det["detector_summary"][d]["cam2.mp4"]
        if s["n_verified"] != 0 or s["exact_accuracy"] is not None or s["char_accuracy"] is not None:
            flag(f"[UNLABELED] cam2 summary {d}: n_verified={s['n_verified']} exact={s['exact_accuracy']}")
    for d in DETECTORS:
        for name, blk in det["detector_summary"][d].items():
            if not isinstance(blk, dict) or blk.get("n_verified") != 0:
                continue
            if any(blk.get(k) is not None for k in ("exact_accuracy", "char_accuracy", "mean_edit_distance")):
                flag(f"[UNLABELED] {d}/{name}: n_verified=0 but accuracy not null")
    note(f"cam2 records inspected: {len(cam2)} (exact/char_accuracy all null)")

    # ---- 3. bucket boundaries ---------------------------------------------
    expect = {0: "lt80", 79: "lt80", 80: "80-99", 99: "80-99", 100: "100-149",
              149: "100-149", 150: "150-199", 199: "150-199", 200: "ge200", 100000: "ge200"}
    for w, want in expect.items():
        if bucket_for(w) != want:
            flag(f"[BUCKET] bucket_for({w})={bucket_for(w)!r} expected {want!r}")
    if [(b[0], b[1], b[2]) for b in BUCKETS] != [(0, 80, "lt80"), (80, 100, "80-99"),
                                                  (100, 150, "100-149"), (150, 200, "150-199"),
                                                  (200, 10 ** 9, "ge200")]:
        flag("[BUCKET] BUCKETS table != task 8 boundaries")
    for r in records:
        if "width" not in r:
            continue
        want = bucket_for(int(r["width"]))
        if r.get("bucket") != want:
            flag(f"[BUCKET] {r['detector']}/{r['camera']}@{r['frame']} w={r['width']} "
                 f"stored={r.get('bucket')!r} recomputed={want!r}")
    for d in DETECTORS:
        rows = [r for r in records if r.get("detector") == d and "ocr_text" in r]

    # ---- 4. pairwise ------------------------------------------------------
    pairs = pw["pairs"]
    allowed = {"CURRENT_BETTER", "IRANPLATE_BETTER", "BOTH_CORRECT", "BOTH_WRONG",
               "CURRENT_ONLY_VALID", "IRANPLATE_ONLY_VALID", "NEITHER_VALID", "INCOMPARABLE"}
    superior = {"CURRENT_BETTER", "IRANPLATE_BETTER", "CURRENT_ONLY_VALID", "IRANPLATE_ONLY_VALID"}
    counts: dict[str, int] = {}
    stubs: list = []
    for p in pairs:
        o = p["outcome"]
        counts[o] = counts.get(o, 0) + 1
        if o not in allowed:
            flag(f"[PAIRWISE] unknown outcome {o!r}")
        if o in superior and p.get("iou", 1.0) <= 0:
            flag(f"[PAIRWISE] superiority class {o} on unmatched/iou=0 pair @{p['frame']}")
        if o == "CURRENT_BETTER" and p.get("iranplate_result") is True:
            flag(f"[PAIRWISE] CURRENT_BETTER but iranplate_result True @{p['frame']}")
        if o == "IRANPLATE_BETTER" and p.get("current_result") is True:
            flag(f"[PAIRWISE] IRANPLATE_BETTER but current_result True @{p['frame']}")
        if "current_ocr_valid" not in p:
            # unmatched-detection stub: no OCR/GT fields at all
            stubs.append((p["camera"], p["frame"], o))
            if o != "INCOMPARABLE":
                flag(f"[PAIRWISE] unmatched stub @{p['frame']} has outcome {o}")
            continue
        want = classify_pair(bool(p.get("ground_truth")), p.get("current_result"),
                             p.get("iranplate_result"), p.get("current_ocr_valid", False),
                             p.get("iranplate_ocr_valid", False))
        if want != o:
            flag(f"[PAIRWISE] {p['camera']}@{p['frame']} stored={o} recomputed={want}")
    if counts != pw.get("outcome_counts"):
        flag(f"[PAIRWISE] outcome_counts stored={pw.get('outcome_counts')} recomputed={counts}")
    note(f"pairwise n={len(pairs)} counts={counts}")
    note(f"unmatched INCOMPARABLE stubs: {stubs}")
    for p in pairs:
        if "gt_status" not in p:
            flag(f"[PAIRWISE] stub record @{p['frame']} omits gt_status (schema inconsistency)")
            continue
        want = "LABELED" if p.get("ground_truth") else "UNLABELED"
        if p.get("gt_status") != want:
            flag(f"[PAIRWISE] gt_status mismatch @{p['frame']}")
        if want == "UNLABELED" and p.get("current_result") is not None:
            flag(f"[PAIRWISE] UNLABELED pair carries accuracy @{p['frame']}")

    # ---- 5. threshold sweep ----------------------------------------------
    sweep = bk["threshold_sweep"]
    want_th = {"0.2", "0.3", "0.4", "0.5", "0.6"}
    for d in DETECTORS:
        got = {k.split("@")[1] for k in sweep if k.startswith(d + "@")}
        if got != want_th:
            flag(f"[SWEEP] {d} thresholds stored={sorted(got)} expected={sorted(want_th)}")
    for k, v in sweep.items():
        if not v.get("verified_total"):
            flag(f"[SWEEP] {k} verified_total=0 - no accuracy produced")

    # ---- 6. crop expansion -------------------------------------------------
    exp = bk["crop_expansion"]
    want_f = {"1.00", "1.05", "1.10", "1.15", "1.20"}
    for d in DETECTORS:
        got = {k.split("@")[1] for k in exp if k.startswith(d + "@")}
        if got != want_f:
            flag(f"[EXPAND] {d} factors stored={sorted(got)} expected={sorted(want_f)}")
    dup = [k for k, v in exp.items() if v.get("failed_rate") == v.get("invalid_rate")]
    if dup:
        note(f"[EXPAND] failed_rate == invalid_rate in {len(dup)}/{len(exp)} cells (same predicate)")
    c2p = RES / "phase2b_cam2_expansion.json"
    if c2p.exists():
        c2 = json.loads(c2p.read_text(encoding="utf-8"))
        facs = sorted({k.split("@")[1] for k in c2})
        if set(facs) != want_f:
            flag(f"[EXPAND] phase2b_cam2_expansion.json factors={facs} != required {sorted(want_f)}")
        for d in DETECTORS:
            got = {k.split("@")[1] for k in c2 if k.startswith(d + "@")}
            if got != want_f:
                flag(f"[EXPAND] cam2_expansion {d} factors={sorted(got)} != {sorted(want_f)}")

    # ---- bucket-file consistency ------------------------------------------
    for d in DETECTORS:
        for b in BUCKETS:
            a = det["detector_summary"][d].get(f"bucket:{b[2]}")
            c = bk["buckets"][d][b[2]]
            if not eq(a, c, tol=1e-9):
                diffs = [k for k in (a or {}) if not eq((a or {}).get(k), c.get(k))]
                flag(f"[BUCKETFILE] {d}/{b[2]} differs from detector_summary on {diffs}")

    # ---- 8. report (markdown) vs stored JSON spot-checks ------------------
    rep_path = ROOT / "ALPR_PHASE2B_DETECTOR_CROP_BENCHMARK.md"
    if rep_path.exists():
        rep = rep_path.read_text(encoding="utf-8")
        cur = det["detector_summary"]["current_detector"]["overall"]
        ipv = det["detector_summary"]["iranplate_vision"]["overall"]
        claims = [
            ("detector p95 current", "25.8", cur["detector_latency_ms_p95"]),
            ("detector p95 iranplate", "25.4", ipv["detector_latency_ms_p95"]),
            ("ocr p95 current", "13.2", cur["ocr_latency_ms_p95"]),
            ("ocr p95 iranplate", "12.6", ipv["ocr_latency_ms_p95"]),
        ]
        for name, claimed, stored in claims:
            if claimed in rep and abs(float(claimed) - float(stored)) > 0.051:
                flag(f"[REPORT] {name}: report says {claimed}, stored value is {stored}")

    # ---- pairwise coverage / exhaustiveness over raw detections ----------
    pair_frames = {(p["camera"], p["frame"]) for p in pairs if "current_ocr" in p}
    dropped = [r for r in records if "ocr_text" in r and (r["camera"], r["frame"]) not in pair_frames]
    note(f"detections never entering the pairwise set: {len(dropped)} of "
         f"{len([r for r in records if 'ocr_text' in r])}")
    if dropped:
        dcam = collections.Counter(r["camera"] for r in dropped)
        note(f"dropped detections by camera: {dict(dcam)}")
        bydet = collections.Counter(r["detector"] for r in dropped)
        note(f"dropped detections by detector: {dict(bydet)}")
        flag(f"[PAIRWISE-COVERAGE] {len(dropped)} detections are excluded from the pairwise "
             f"analysis because their frame has no detection from the other detector; they are "
             f"NOT reported as INCOMPARABLE (per camera: {dict(dcam)}). Pairwise outcomes are "
             f"therefore not exhaustive over the detection set.")

    # ---- report ------------------------------------------------------------
    out = ["# verify_results.py output", "", f"records={len(records)} issues={len(issues)}", ""]
    out += [f"NOTE  {n}" for n in notes]
    out += ["", "## ISSUES", ""] + ([f"- {i}" for i in issues] or ["- none"])
    text = "\n".join(out)
    (Path(__file__).parent / "verify_output.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
