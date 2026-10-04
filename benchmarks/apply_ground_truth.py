"""Applies reviewed labels (benchmarks/dataset/gt_labels.json) to
benchmarks/dataset/ground_truth.jsonl.

Every sample gets exactly one record. Samples not covered by a verified label
are written as status=UNLABELED, verified=false — they are EXCLUDED from all
accuracy metrics by the benchmark runners.

Usage:
    python benchmarks/apply_ground_truth.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DS = ROOT / "benchmarks" / "dataset"


def main() -> None:
    labels = json.loads((DS / "gt_labels.json").read_text(encoding="utf-8"))
    meta = [json.loads(l) for l in open(DS / "metadata.jsonl", encoding="utf-8")]

    def match(sample) -> dict | None:
        for key, lab in labels["labels"].items():
            applies = lab.get("applies_to", {})
            if applies.get("source_video") != sample["source_video"]:
                continue
            for lo, hi in applies.get("frame_ranges", []):
                if lo <= sample["frame"] <= hi:
                    return lab
        return None

    rows = []
    n_verified = 0
    for m in meta:
        lab = match(m)
        if lab and lab.get("verified"):
            n_verified += 1
            rows.append({
                "sample_id": m["id"],
                "plate_text": lab["plate_text"],
                "plate_text_ascii": lab.get("plate_text_ascii"),
                "plate_type": lab.get("plate_type", "unknown"),
                "verified": True,
                "status": "LABELED",
                "evidence": lab.get("evidence"),
            })
        else:
            rows.append({
                "sample_id": m["id"],
                "plate_text": None,
                "plate_type": "unknown",
                "verified": False,
                "status": "UNLABELED",
                "reason": (lab or {}).get("evidence", "no verified label"),
            })

    with open(DS / "ground_truth.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"ground_truth.jsonl written: {len(rows)} samples, "
          f"{n_verified} verified, {len(rows) - n_verified} UNLABELED")


if __name__ == "__main__":
    main()
