import json, math, collections, random
from pathlib import Path
R = Path(__file__).resolve().parent.parent / "results"
raw = json.loads((R / "phase2c_raw_results.json").read_text(encoding="utf-8"))
summ = json.loads((R / "phase2c_summary.json").read_text(encoding="utf-8"))
recs = raw["records"]
CANON = summ["canonical_convention"]
print("CANON", CANON, "protocol", json.dumps(raw["protocol"]))
print("CONVS_SEEN", sorted({r["convention"] for r in recs}))
print("RUNS_SEEN", sorted({r["run"] for r in recs}))

out = {}
for run in ("run0", "run1"):
    for det in ("detector_a_current", "detector_b_iranplate"):
        for scope in ("all", "cam1.mp4", "cam2.mp4"):
            fr = [f for f in raw["frame_rows"] if f["run" if "run" in f else "detector"] == det] if False else None
rows = {}
# frame_rows have no run tag -> check
print("FRAME_ROW_KEYS", sorted(raw["frame_rows"][0].keys()))
fr = raw["frame_rows"]
def agg(run, det, cam):
    S = [r for r in recs if r["run"] == run and r["detector"] == det
         and r["convention"] == CANON and (cam is None or r["camera"] == cam)]
    F = [f for f in fr if f["detector"] == det and (cam is None or f["camera"] == cam)]
    det_rows = [r for r in S if r["detection_status"] == "DETECTED"]
    nodet = [r for r in S if r["detection_status"] == "NO_DETECTION"]
    lab = [r for r in S if r["gt_status"] == "LABELED"]
    unl = [r for r in S if r["gt_status"] == "UNLABELED"]
    withocr = [r for r in S if r.get("ocr_text") is not None]
    return {
     "frames_total": len(F),
     "frames_with_detection": sum(1 for f in F if f["detected"]),
     "frames_without_detection": sum(1 for f in F if not f["detected"]),
     "records_total": len(S), "detected": len(det_rows), "no_detection": len(nodet),
     "labeled": len(lab), "unlabeled": len(unl),
     "exact": (sum(1 for r in lab if r["exact"]), len(lab)),
     "char_acc_sum": (round(sum(r["char_accuracy"] for r in lab if r["char_accuracy"] is not None), 6), len(lab)),
     "invalid": (sum(1 for r in withocr if not r["ocr_valid"]), len(withocr)),
     "failed": (sum(1 for r in withocr if r["failed"]), len(withocr)),
     "clipping": (sum(1 for r in det_rows if r["crop"]["clipped_any"]), len(det_rows)),
     "unlabeled_nonnull_acc": sum(1 for r in unl if r["exact"] is not None or r["char_accuracy"] is not None or r.get("edit_distance") is not None),
     "median_w": sorted(r["crop"]["crop_width"] for r in det_rows if r["crop"]["crop_width"] > 0)[
         min(len([r for r in det_rows if r["crop"]["crop_width"]>0])-1, math.ceil(0.5*len([r for r in det_rows if r["crop"]["crop_width"]>0]))-1)] if det_rows else None,
     "crop_none": sum(1 for r in S if r["detection_status"]=="DETECTED" and r.get("ocr_text") is None),
    }
for run in ("run0", "run1"):
    for det in ("detector_a_current", "detector_b_iranplate"):
        for cam in (None, "cam1.mp4", "cam2.mp4"):
            out[f"{run}|{det}|{cam}"] = agg(run, det, cam)
            print(f"{run}|{det}|{cam or 'all'}", json.dumps(out[f"{run}|{det}|{cam}"]))

# failed vs invalid disjointness
S = [r for r in recs if r["convention"] == CANON]
print("failed_and_invalid", sum(1 for r in S if r.get("failed") and r.get("ocr_valid") is False))
print("failed_blank_blank", sum(1 for r in S if r.get("failed") and not (r.get("ocr_text") or "").strip()))
print("invalid_but_text_nonblank", sum(1 for r in S if r.get("ocr_valid") is False and (r.get("ocr_text") or "").strip()))
print("failed_nonblank", sum(1 for r in S if r.get("failed") and (r.get("ocr_text") or "").strip()))
print("nonempty_ocr_not_invalid", sum(1 for r in S if r.get("ocr_valid") is True))
print("failed_None_and_no_ocr", sum(1 for r in S if r.get("failed") is None))

# convention selection inputs
print("CONV_SCORES", json.dumps(summ["convention_scores_non_accuracy"]))
print("REASONS", summ["canonical_selection_reasons"])
print("REPEAT", json.dumps(summ["repeatability"]))
print("PAIRED_ALL", json.dumps(summ["paired_statistics"]["all"]["table"]), summ["paired_statistics"]["all"]["discordant_pairs"], summ["paired_statistics"]["all"]["mcnemar_exact_p"], summ["paired_statistics"]["all"]["verified_frames"])
print("PAIRED_CAM1", json.dumps(summ["paired_statistics"]["cam1"]["table"]), summ["paired_statistics"]["cam1"]["discordant_pairs"], summ["paired_statistics"]["cam1"]["mcnemar_exact_p"], summ["paired_statistics"]["cam1"]["verified_frames"])
# stored summary check
print("STORED_RUN0", json.dumps(summ["per_run_summary"]["run0"]["detector_a_current|overall"]))
print("STORED_RUN0_B", json.dumps(summ["per_run_summary"]["run0"]["detector_b_iranplate|overall"]))
print("STORED_RUN0_A_CAM1", json.dumps(summ["per_run_summary"]["run0"]["detector_a_current|cam1.mp4"]))
print("STORED_RUN0_B_CAM1", json.dumps(summ["per_run_summary"]["run0"]["detector_b_iranplate|cam1.mp4"]))
try:
    print("STORED_RUN1_A", json.dumps(summ["per_run_summary"]["run1"]["detector_a_current|overall"]))
except KeyError:
    print("STORED_RUNS", sorted(summ["per_run_summary"].keys()), "repeatability", json.dumps(summ["repeatability"]))
print("GT", json.dumps(summ["ground_truth"]), json.dumps(raw["gt_frame_counts"]))
# trunc check
import numpy as np
bad = 0
random.seed(7)
for _ in range(20000):
    v = random.uniform(-1000, 1000)
    if int(v) != int(np.float64(v).astype(int)):
        bad += 1
print("trunc_mismatch", bad)