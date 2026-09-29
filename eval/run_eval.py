"""Evaluation harness entry point (design Phase 0 exit gate).

Phase 0 contract: this script must run and print a clear "dataset missing"
message instead of crashing or fabricating numbers. Accuracy evaluation
starts once the held-out set from design §6.3 exists.

Usage:
  python eval/run_eval.py --split heldout-manifest
  python eval/run_eval.py --self-test          # metric sanity checks only
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from eval import datasets, metrics  # noqa: E402  (path set above)


def _self_test() -> int:
    """Deterministic metric checks that need no dataset."""
    checks = [
        (metrics.plate_exact_match("12b34567", "12b34567"), True),
        (metrics.plate_exact_match("12B34567", "12b34567"), True),
        (metrics.plate_exact_match("۱۲ب۳۴۵۶۷", "12b34567"), True),
        (metrics.plate_exact_match("12b34587", "12b34567"), False),
        (metrics.plate_exact_match("", "12b34567"), False),
        (metrics.character_error_rate("12b34567", "12b34567"), 0.0),
        (round(metrics.character_error_rate("12b34587", "12b34567"), 4), 0.125),
        (metrics.percentile([1, 2, 3, 4, 5], 50), 3),
    ]
    failed = [(got, want) for got, want in checks if got != want]
    summary = metrics.summarize_events([
        {"plate_number": "12b34567", "truth": "12b34567", "confidence": 0.9,
         "agreement_ratio": 0.8},
        {"plate_number": "12b34587", "truth": "12b34567", "confidence": 0.5,
         "agreement_ratio": 0.4, "needs_review": True},
    ])
    print(json.dumps({"self_test_failures": failed, "event_summary": summary},
                     indent=2))
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ALPR evaluation harness")
    parser.add_argument("--split", default="heldout-manifest")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if args.self_test:
        return _self_test()

    try:
        manifest = datasets.load_manifest()
        visits = datasets.load_visits()
    except datasets.DatasetMissing as exc:
        print(f"[eval] dataset missing: {exc}")
        print("[eval] accuracy evaluation is NOT run; no numbers are produced.")
        print("[eval] latency baselines are available: eval/baselines/")
        return 0                                  # Phase 0 exit gate: no crash

    print(json.dumps({"manifest": manifest, "visits": len(visits)}, indent=2))
    print("[eval] model evaluation is Phase 1+ work (see design §6.1).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
