"""Phase 2C — damage inventory after the workspace sync event.

Reports which benchmark inputs/outputs are present so the final status report
can state exactly what remains verifiable and what cannot be re-run.
"""
from pathlib import Path
import json

ROOT = Path(r"D:\alpr")

CHECKS = [
    ("cam1.mp4 (source video)", ROOT / "cam1.mp4"),
    ("cam2.mp4 (source video)", ROOT / "cam2.mp4"),
    ("detector A weights", ROOT / "weigths" / "plate_det_model.pt"),
    ("detector B weights", ROOT / "bench" / "IranPlate-Vision-main" /
     "IranPlate-Vision-main" / "best.pt"),
    ("gt_labels.json", ROOT / "benchmarks" / "dataset" / "gt_labels.json"),
    ("ground_truth.jsonl", ROOT / "benchmarks" / "dataset" / "ground_truth.jsonl"),
    ("metadata.jsonl", ROOT / "benchmarks" / "dataset" / "metadata.jsonl"),
    ("dataset/crops (84 png)", ROOT / "benchmarks" / "dataset" / "crops"),
    ("phase2c_protocol.json", ROOT / "benchmarks" / "phase2c_protocol.json"),
    ("phase2c_raw_results.json", ROOT / "benchmarks" / "results" / "phase2c_raw_results.json"),
    ("phase2c_summary.json", ROOT / "benchmarks" / "results" / "phase2c_summary.json"),
    ("phase2c_bucket_results.json", ROOT / "benchmarks" / "results" / "phase2c_bucket_results.json"),
    ("phase2c_latency.json", ROOT / "benchmarks" / "results" / "phase2c_latency.json"),
    ("phase2c_crop_results.json", ROOT / "benchmarks" / "results" / "phase2c_crop_results.json"),
    ("phase2c_verify.py", ROOT / "benchmarks" / "audit" / "phase2c_verify.py"),
    ("crop fidelity html", ROOT / "benchmarks" / "audit" / "phase2c_crop_fidelity.html"),
    ("report", ROOT / "ALPR_PHASE2C_DETECTOR_AB_BENCHMARK.md"),
    ("cam2 GT labels (2C)", ROOT / "benchmarks" / "dataset" / "2c" / "phase2c_cam2_gt_labels.json"),
    ("cam2 GT findings (2C)", ROOT / "benchmarks" / "audit" / "phase2c_cam2_gt_findings.md"),
    ("cam2 frames extract", ROOT / "benchmarks" / "audit" / "cam2_frames"),
]

print(f"{'asset':34s} {'present':8s} size / note")
print("-" * 78)
for name, p in CHECKS:
    if p.is_file():
        print(f"{name:34s} YES      {p.stat().st_size:,} bytes")
    elif p.is_dir():
        n = len(list(p.glob("*")))
        print(f"{name:34s} YES      {n} entries")
    else:
        print(f"{name:34s} MISSING")

print()
# repeatability + headline numbers, so they are quotable without the videos
s = json.loads((ROOT / "benchmarks" / "results" / "phase2c_summary.json")
               .read_text(encoding="utf-8"))
print("headline (still verifiable from JSON):")
r0 = s["per_run_summary"]["run0"]
for k in ("detector_a_current|cam1.mp4", "detector_b_iranplate|cam1.mp4"):
    v = r0[k]
    print(f"  {k:36s} exact {v['exact']['numerator']}/{v['exact']['denominator']}")
print("  paired:", s["paired_statistics"]["all"]["table"],
      "p =", s["paired_statistics"]["all"]["mcnemar_exact_p"])
print("  repeatability:", s["repeatability"]["runs"], "runs, identical =",
      s["repeatability"].get("identical"))
