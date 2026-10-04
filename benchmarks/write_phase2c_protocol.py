"""Write benchmarks/phase2c_protocol.json from the stored frozen protocol.

Task §8: the protocol must be machine-readable and must state explicitly which
inputs were allowed to select the canonical crop convention.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
s = json.loads((ROOT / "benchmarks" / "results" / "phase2c_summary.json")
               .read_text(encoding="utf-8"))
p = s["protocol"]

out = {
    "frozen_at": s["generated_at"],
    "detector_conf": p["conf"],
    "detector_iou": p["iou"],
    "detector_max_det": p["max_det"],
    "imgsz": p["imgsz"],
    "agnostic_nms": p["agnostic_nms"],
    "half": p["half"],
    "crop_rounding": p["crop_convention"],
    "crop_rounding_definition":
        "truncation toward zero, identical to numpy.astype(int) used at "
        "alpr_engine.py:363",
    "clip": p["clip"],
    "padding": {"pad_x": p["pad_x"], "pad_y": p["pad_y"]},
    "crop_operation_order": "convert -> pad -> clip -> validate",
    "conventions_measured": ["round", "floor", "ceil", "trunc", "floor_dy-1"],
    "canonical_selection_inputs":
        ["production_equivalent", "degenerate_count", "shrinks_box_count"],
    "canonical_selection_excluded": ["ground_truth_accuracy"],
    "ocr": p["ocr"],
    "normalization": "benchmarks/normalization.normalize_plate_text",
    "dataset": "benchmarks/dataset/gt_labels.json (verified ranges only)",
    "ground_truth_policy": "verified_only",
    "box_ground_truth": "NO_BOX_GROUND_TRUTH",
    "applied_identically_to_both_detectors": True,
    "environment": s["environment"],
    "detectors": {
        "A_current_production": {
            "weights": "weigths/plate_det_model.pt",
            "sha256": "C70A91B5D695C2B8302BBE4F8AB6112DDC7845159F2FCC91CD50072D401ED00C"},
        "B_iranplate_vision": {
            "weights": "bench/IranPlate-Vision-main/IranPlate-Vision-main/best.pt",
            "sha256": "308C24643EAF49FC38930CEBFC46CA7455E7472F1D83FE98A2AE24443043DE40"},
    },
}
dest = ROOT / "benchmarks" / "phase2c_protocol.json"
dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("wrote", dest)