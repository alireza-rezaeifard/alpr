"""Benchmark preprocessing variants independently (task §6/§7).

Every OCR model sees the SAME preprocessed image for a given (crop, variant).
Metrics are split by video and by crop-width bucket; accuracy uses only
verified ground-truth samples.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

import cv2  # noqa: E402

from adapters.registry import ALL_OCR_ADAPTERS  # noqa: E402
from metrics import aggregate, is_valid_iranian, score_pair, width_bucket  # noqa: E402
from preprocessing import VARIANTS, apply_variant  # noqa: E402

DS = ROOT / "benchmarks" / "dataset"
RESULTS = ROOT / "benchmarks" / "results"


def load_verified_gt() -> dict:
    gt = {}
    p = DS / "ground_truth.jsonl"
    for line in open(p, encoding="utf-8"):
        rec = json.loads(line)
        if rec.get("verified") and rec.get("plate_text"):
            gt[rec["sample_id"]] = rec["plate_text"]
    return gt


def main() -> None:
    meta = [json.loads(l) for l in open(DS / "metadata.jsonl", encoding="utf-8")]
    gt = load_verified_gt()
    adapters = [c() for c in ALL_OCR_ADAPTERS]
    for a in adapters:
        a.is_available()

    records = []
    skipped = defaultdict(int)
    for m in meta:
        crop = cv2.imread(str(DS / m["crop_path"]))
        if crop is None:
            continue
        ref = gt.get(m["id"])
        for variant in VARIANTS:
            proc = apply_variant(crop, variant)
            if proc is None:
                skipped[(m["source_video"], variant)] += 1
                continue
            for a in adapters:
                r = a.predict(proc)
                rec = {
                    "sample_id": m["id"],
                    "video": m["source_video"],
                    "frame": m["frame"],
                    "variant": variant,
                    "model": a.id,
                    "width": m["quality"]["width"],
                    "bucket": width_bucket(m["quality"]["width"]),
                    "raw_text": r["raw_text"],
                    "text": r["text"],
                    "latency_ms": r["latency_ms"],
                    "error": r["error"],
                    "invalid": not is_valid_iranian(r["raw_text"], r["confidence"] or 0.9),
                    "failed": not r["text"],
                }
                if ref:
                    rec.update(score_pair(r["raw_text"], ref))
                else:
                    rec.update({"exact": None, "char_accuracy": None,
                                "edit_distance": None, "failed": not r["text"]})
                records.append(rec)

    def dump(recs, label):
        out = {}
        for model in sorted({r["model"] for r in recs}):
            for variant in VARIANTS:
                sub = [r for r in recs if r["model"] == model and r["variant"] == variant]
                if not sub:
                    continue
                agg = aggregate(sub)[ "all"]
                out[f"{model}|{variant}"] = agg
        return out

    cam1 = [r for r in records if r["video"] == "cam1.mp4"]
    cam2 = [r for r in records if r["video"] == "cam2.mp4"]

    by_bucket = {}
    for bucket in ("lt100", "100-150", "ge150"):
        sub = [r for r in records if r["bucket"] == bucket]
        if sub:
            by_bucket[bucket] = aggregate(sub)

    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "variants": VARIANTS,
        "n_records": len(records),
        "skipped_perspective": {f"{v}|{var}": n for (v, var), n in skipped.items()},
        "all": dump(records, "all"),
        "cam1": dump(cam1, "cam1"),
        "cam2": dump(cam2, "cam2"),
        "by_width_bucket": {k: v["all"] for k, v in by_bucket.items()},
        "records": records,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    with open(RESULTS / "preprocess_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"records={len(records)} skipped_persp={dict(skipped)}")
    for key in sorted(out["all"]):
        a = out["all"][key]
        print("%-38s n=%-4s exact=%-6s char_acc=%-6s invalid=%-6s failed=%-6s" % (
            key, a["n_samples"], a["exact_accuracy"], a["char_accuracy"],
            a["invalid_rate"], a["failed_rate"]))


if __name__ == "__main__":
    main()
