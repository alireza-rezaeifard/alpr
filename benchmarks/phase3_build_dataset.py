"""Phase 3 dataset population.

Builds benchmarks/dataset/phase3/ from:

  * cam1.mp4 / cam2.mp4 (interval-5 sampling, single
    detector-inference pass per frame per detector),
  * benchmarks/dataset/gt_labels.json (Phase 2B
    human/agent visual-review provenance for the two
    cam1 plate instances),
  * detector measurements recorded as MEASUREMENTS,
    never copied into GT fields.

Instance identities:
  cam1_s001_v001 — plate A (28Y68923 / ۲۸ی۶۸۹۲۳)
  cam1_s001_v002 — plate B (12D67413 / ۱۲د۶۷۴۱۳)
  cam2_s001_v00K — PROVISIONAL clusters from
                   spatiotemporal detection grouping
                   (pending human confirmation).
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmarks.phase3_dataset import (  # noqa: E402
    DATASET_DIR, GT_LABELS, SAMPLING_INTERVAL,
    camera_record, cluster_detections,
    derived_quality_bucket, plate_annotation,
    quality_properties, read_video_frames,
    sample_frames, validate_dataset,
    vehicle_record, width_bucket)
from benchmarks.phase3_normalization import (  # noqa: E402
    canonical_forms, extract_region_code)
from benchmarks.phase3_splits import (  # noqa: E402
    build_splits, check_leakage, write_splits)
from benchmarks.phase3_dataset import (  # noqa: E402
    read_video_frames as _rvf)  # noqa: F401

VIDEOS = {"cam1": ROOT / "cam1.mp4", "cam2": ROOT / "cam2.mp4"}
DETECTORS = ("detector_a_current", "detector_b_iranplate")
PROTOCOL = {"conf": 0.50, "iou": 0.45, "max_det": 12,
            "imgsz": 640, "agnostic_nms": False,
            "half": False}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def build_detectors():
    from api import _ensure_models
    from adapters.registry import IranPlateDetectorAdapter
    engine = _ensure_models()
    a_model = engine._plate_model
    b = IranPlateDetectorAdapter()
    b.load()

    def call(model, frame):
        res = model.predict(
            frame, conf=PROTOCOL["conf"], iou=PROTOCOL["iou"],
            max_det=PROTOCOL["max_det"],
            imgsz=PROTOCOL["imgsz"],
            agnostic_nms=PROTOCOL["agnostic_nms"],
            half=PROTOCOL["half"], verbose=False)[0]
        boxes = []
        if res.boxes is not None:
            for bx in res.boxes.data.tolist():
                x1, y1, x2, y2, c, cls = bx
                boxes.append({"bbox": [x1, y1, x2, y2],
                              "confidence": float(c),
                              "class_id": int(cls)})
        return boxes
    return {"detector_a_current": lambda f: call(a_model, f),
            "detector_b_iranplate": lambda f: call(
                b.model, f)}


def run_detectors() -> dict:
    """Single inference pass per frame per detector.
    Returns {(camera, frame): {detector: [boxes]}}."""
    detectors = build_detectors()
    out = {}
    for cam, video in VIDEOS.items():
        cap = cv2.VideoCapture(str(video))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        idx = 0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            if idx % SAMPLING_INTERVAL == 0:
                per_det = {}
                for name, fn in detectors.items():
                    per_det[name] = [
                        {"bbox": [round(float(v), 4)
                                  for v in b["bbox"]],
                         "confidence": round(
                             b["confidence"], 6),
                         "class_id": b["class_id"]}
                        for b in fn(fr)]
                out[(cam, idx)] = per_det
            idx += 1
        cap.release()
    return out


def load_verified_labels() -> dict:
    return json.loads(GT_LABELS.read_text(
        encoding="utf-8"))["labels"]


def build() -> dict:
    """Populate the whole dataset tree. Returns the
    in-memory dataset plus paths written."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    for sub in ("cameras", "sessions", "gt", "splits"):
        (DATASET_DIR / sub).mkdir(parents=True,
                                  exist_ok=True)

    # ---- cameras + sessions ------------------------------
    cameras = {}
    sessions = {}
    frames_meta = {}
    for cam, video in VIDEOS.items():
        rec = camera_record(cam, video)
        rec["sha256"] = sha256_file(video)
        cameras[cam] = rec
        (DATASET_DIR / "cameras" / f"{cam}.json").write_text(
            json.dumps(rec, indent=1), encoding="utf-8")
        sid = f"{cam}_s001"
        sessions[sid] = {
            "session_id": sid, "camera_id": cam,
            "source": video.name,
            "frame_count": rec["frame_count"],
            "sampled_frames": sample_frames(
                rec["frame_count"], SAMPLING_INTERVAL),
            "sampling": f"interval_{SAMPLING_INTERVAL}"}
        (DATASET_DIR / "sessions" /
         f"{sid}.json").write_text(
            json.dumps(sessions[sid], indent=1),
            encoding="utf-8")
        frames_meta[cam] = {f: None for f in
                            sessions[sid]["sampled_frames"]}

    # ---- detector measurements ---------------------------
    print("detector pass (A+B, single inference per "
          "frame/detector)...", flush=True)
    detections = run_detectors()
    print(f"  {len(detections)} sampled frames measured",
          flush=True)

    labels = load_verified_labels()

    # ---- cam1 verified instances -------------------------
    vehicles = []
    annotations = []
    frame_rows = []

    cam1_map = {"cam1_plate_A": ("cam1_s001_v001",
                                 "cam1_s001_v001_p001"),
                "cam1_plate_B": ("cam1_s001_v002",
                                 "cam1_s001_v002_p001")}
    for label_name, (vid, pid) in cam1_map.items():
        lab = labels[label_name]
        forms = canonical_forms(lab["plate_text"])
        ranges = lab["applies_to"]["frame_ranges"]
        in_range = set()
        for lo, hi in ranges:
            in_range |= {f for f in range(lo, hi + 1)
                         if f % SAMPLING_INTERVAL == 0}
        vehicles.append(vehicle_record(
            vid, "cam1", "cam1_s001",
            min(r[0] for r in ranges),
            max(r[1] for r in ranges), [pid],
            "verified_text_pending_box", split="test"))
        # frames for measurements
        frames = read_video_frames(
            VIDEOS["cam1"], sorted(in_range))
        for f in sorted(in_range):
            det = detections.get(("cam1", f), {})
            best_a = max(det.get("detector_a_current",
                                 []),
                         key=lambda b: b["confidence"],
                         default=None)
            meas = {}
            if best_a is not None:
                ib = [int(best_a["bbox"][0]),
                      int(best_a["bbox"][1]),
                      int(best_a["bbox"][2]),
                      int(best_a["bbox"][3])]
                props = quality_properties(frames[f],
                                           tuple(ib))
                meas = {
                    "detector_a_current": {
                        "bbox": best_a["bbox"],
                        "confidence":
                            best_a["confidence"]},
                    **props,
                    "width_bucket":
                        width_bucket(
                            props.get("plate_width_px")),
                    "quality_bucket":
                        derived_quality_bucket(props),
                }
            annotations.append(plate_annotation(
                annotation_id=f"{pid}_f{f:05d}",
                camera_id="cam1",
                session_id="cam1_s001",
                vehicle_instance_id=vid,
                plate_instance_id=pid, frame_id=f,
                plate_bbox=None,
                box_annotation_status=
                "pending_human_annotation",
                plate_text_raw=lab["plate_text"],
                plate_type=lab.get("plate_type",
                                   "civilian"),
                region_code=extract_region_code(
                    forms["plate_text_ascii"]),
                readability="PENDING_HUMAN_REVIEW",
                occluded=False, truncated=False,
                annotation_status="verified",
                annotator=
                "phase2b_human_visual_review",
                notes=lab.get("evidence", ""),
                measurements=meas))

    # frame rows for cam1 (all sampled frames)
    for f in sessions["cam1_s001"]["sampled_frames"]:
        det = detections.get(("cam1", f), {})
        verified = next(
            (a for a in annotations
             if a["camera_id"] == "cam1"
             and a["frame_id"] == f), None)
        frame_rows.append({
            "camera_id": "cam1",
            "session_id": "cam1_s001", "frame_id": f,
            "sampling": f"interval_{SAMPLING_INTERVAL}",
            "in_verified_range": verified is not None,
            "vehicle_instance_id":
                verified["vehicle_instance_id"]
                if verified else None,
            "detections": det})

    # ---- cam2 provisional instances ----------------------
    cam2_dets = []
    for (cam, f), per_det in detections.items():
        if cam != "cam2":
            continue
        for b in per_det.get("detector_a_current", []):
            cam2_dets.append({
                "frame": f,
                "bbox": [int(b["bbox"][0]),
                         int(b["bbox"][1]),
                         int(b["bbox"][2]),
                         int(b["bbox"][3])],
                "confidence": b["confidence"]})
    clusters = cluster_detections(cam2_dets)
    print(f"cam2 provisional clusters: {len(clusters)}",
          flush=True)
    cam2_frames = read_video_frames(
        VIDEOS["cam2"],
        sorted({d["frame"] for d in cam2_dets}))
    for k, c in enumerate(clusters, 1):
        vid = f"cam2_s001_v{k:03d}"
        pid = f"{vid}_p001"
        vehicles.append(vehicle_record(
            vid, "cam2", "cam2_s001",
            c["frame_min"], c["frame_max"], [pid],
            "provisional_programmatic", split="test"))
        for det in c["detections"]:
            f = det["frame"]
            props = quality_properties(
                cam2_frames[f], tuple(det["bbox"]))
            annotations.append(plate_annotation(
                annotation_id=f"{pid}_f{f:05d}",
                camera_id="cam2",
                session_id="cam2_s001",
                vehicle_instance_id=vid,
                plate_instance_id=pid, frame_id=f,
                plate_bbox=None,
                box_annotation_status=
                "pending_human_annotation",
                plate_text_raw=None,
                plate_type="unknown",
                region_code=None,
                readability="PENDING_HUMAN_REVIEW",
                occluded=False, truncated=False,
                annotation_status=
                "pending_human_review",
                annotator="phase3_provisional_clustering",
                notes="spatiotemporal detection cluster; "
                      "plate text NOT verified; "
                      "phase2b_sample="
                      + str(f in (205, 210, 300, 305,
                                  315, 320, 325, 330, 335,
                                  340, 345, 350, 355, 485,
                                  495, 500, 505, 510, 530,
                                  540, 545, 555)),
                measurements={
                    "detector_a_current": {
                        "bbox": det["bbox"],
                        "confidence":
                            det["confidence"]},
                    **props,
                    "width_bucket":
                        width_bucket(
                            props.get("plate_width_px")),
                    "quality_bucket":
                        derived_quality_bucket(props),
                }))
    for f in sessions["cam2_s001"]["sampled_frames"]:
        det = detections.get(("cam2", f), {})
        owner = next(
            (a["vehicle_instance_id"]
             for a in annotations
             if a["camera_id"] == "cam2"
             and a["frame_id"] == f), None)
        frame_rows.append({
            "camera_id": "cam2",
            "session_id": "cam2_s001", "frame_id": f,
            "sampling": f"interval_{SAMPLING_INTERVAL}",
            "in_verified_range": False,
            "vehicle_instance_id": owner,
            "detections": det,
            "phase2b_sample": f in (
                205, 210, 300, 305, 315, 320, 325, 330,
                335, 340, 345, 350, 355, 485, 495, 500,
                505, 510, 530, 540, 545, 555)})

    # ---- splits (instance level) -------------------------
    # Verified instances use the documented policy (all
    # verified -> single evaluation split while n < 5).
    # Provisional (unverified) instances are LISTED in
    # the test split as evaluation CONTEXT only: they
    # are measured diagnostically and never enter any
    # accuracy metric (every scorer requires the
    # verified flag).
    verified_vehicles = [
        v for v in vehicles
        if v["annotation_status"] ==
        "verified_text_pending_box"]
    provisional_ids = [
        v["vehicle_instance_id"] for v in vehicles
        if v["annotation_status"] !=
        "verified_text_pending_box"]
    splits = build_splits(verified_vehicles)
    splits["splits"]["test"] = sorted(
        set(splits["splits"]["test"]) |
        set(provisional_ids))
    splits["rationale"] += (
        " Provisional (unverified) instances are listed "
        "in the test split as evaluation context only; "
        "they never enter accuracy metrics.")
    wrote = write_splits(splits, DATASET_DIR / "splits")

    # ---- write GT files ----------------------------------
    def dump_jsonl(name, rows):
        p = DATASET_DIR / "gt" / name
        p.write_text("\n".join(
            json.dumps(r, ensure_ascii=False)
            for r in rows) + "\n", encoding="utf-8")

    dump_jsonl("vehicles.jsonl", vehicles)
    dump_jsonl("plates.jsonl", annotations)
    dump_jsonl("frames.jsonl", frame_rows)

    # ---- validation + leakage ----------------------------
    val = validate_dataset(annotations)
    leak = check_leakage(
        annotations,
        {k: v for k, v in
         [("train", splits["splits"]["train"]),
          ("validation",
           splits["splits"]["validation"]),
          ("test", splits["splits"]["test"])]})
    manifest = {
        "dataset": "phase3",
        "dataset_version": "3.0.0",
        "created_at": stamp,
        "sampling": f"interval_{SAMPLING_INTERVAL}",
        "cameras": list(cameras),
        "n_cameras": len(cameras),
        "sessions": list(sessions),
        "n_sessions": len(sessions),
        "n_vehicle_instances": len(vehicles),
        "n_verified_vehicle_instances":
            len(verified_vehicles),
        "n_annotations": len(annotations),
        "n_verified_text_annotations": sum(
            1 for a in annotations
            if a["annotation_status"] == "verified"),
        "n_verified_box_annotations": sum(
            1 for a in annotations
            if a["box_annotation_status"] ==
            "annotated"),
        "n_frames": len(frame_rows),
        "splits_strategy": splits["strategy"],
        "splits_rationale": splits["rationale"],
        "validation": {
            "valid": val["valid"],
            "n_records_with_errors":
                val["n_records_with_errors"]},
        "leakage": leak,
        "gt_version": "phase2b_labels_v1+phase3_build_v1",
        "box_gt_status": "PENDING_HUMAN_ANNOTATION",
        "cam2_status": "STAGED_PENDING_HUMAN_REVIEW",
    }
    (DATASET_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    (ROOT / "benchmarks" / "dataset" /
     "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")

    print(f"dataset: {len(vehicles)} vehicles "
          f"({len(verified_vehicles)} verified), "
          f"{len(annotations)} annotations, "
          f"{len(frame_rows)} frames", flush=True)
    print(f"validation valid={val['valid']} "
          f"leakage_free={leak['leakage_free']}",
          flush=True)
    return {"cameras": cameras, "sessions": sessions,
            "vehicles": vehicles,
            "annotations": annotations,
            "frame_rows": frame_rows,
            "splits": splits, "manifest": manifest,
            "detections": detections}


if __name__ == "__main__":
    build()
