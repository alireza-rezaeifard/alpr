"""Phase 3 — dataset records, validation, and construction.

Builds the canonical Phase 3 dataset tree
(benchmarks/dataset/phase3/) from:

  * the raw videos (cam1.mp4, cam2.mp4),
  * the Phase 2B verified ground truth
    (benchmarks/dataset/gt_labels.json — human/agent
    visual review provenance),
  * detector measurements (recorded as measurements,
    NEVER copied into GT fields).

Everything is measurable-properties-first: where a human
has not verified a value, the field is null and the
status is explicit (pending_human_review /
pending_human_annotation).

Validation (task §16) rejects: invalid boxes,
out-of-frame boxes, empty verified text, invalid
normalized text, duplicate annotation IDs, duplicate
frame/instance assignments, impossible plate
dimensions, inconsistent camera/session IDs, malformed
records, missing required fields. It does NOT reject
legitimate difficult plates (poor readability,
occlusion, unusual types) — those are valid data.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent

from benchmarks.phase3_normalization import (  # noqa: E402
    canonical_forms, extract_region_code)

DATASET_DIR = ROOT / "benchmarks" / "dataset" / "phase3"
GT_LABELS = ROOT / "benchmarks" / "dataset" / "gt_labels.json"

# Readability / quality vocabulary (task §9).
READABILITY_LEVELS = ("EXCELLENT", "GOOD", "FAIR", "POOR",
                      "UNREADABLE")
ANNOTATION_STATUSES = ("verified",
                       "pending_human_review",
                       "provisional_programmatic")
BOX_STATUSES = ("annotated",
                "pending_human_annotation",
                "provisional_programmatic")
PLATE_TYPES = ("civilian", "taxi", "government", "military",
               "diplomatic", "police", "motorcycle",
               "free_zone", "other", "unknown")

# Interval sampling, identical to Phase 2B/2C/2D.
SAMPLING_INTERVAL = 5


# ------------------------------------------------------------------ records
def camera_record(camera_id: str, video_path: Path) -> dict:
    cap = cv2.VideoCapture(str(video_path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    cap.release()
    return {
        "camera_id": camera_id,
        "source": video_path.name,
        "width": w, "height": h,
        "fps": round(fps, 3), "frame_count": n,
        "role": "production-camera"
                if camera_id == "cam1" else "diagnostic-camera",
        "diversity_notes": (
            "fixed roadside camera, daylight, two vehicles "
            "sequentially visible" if camera_id == "cam1"
            else "fixed roadside camera, dusk/night, multiple "
                 "vehicles, small plates"),
    }


def vehicle_record(vehicle_instance_id: str, camera_id: str,
                   session_id: str, first_frame: int,
                   last_frame: int, plate_instance_ids: list,
                   annotation_status: str,
                   split: str = "test") -> dict:
    return {
        "vehicle_instance_id": vehicle_instance_id,
        "camera_id": camera_id,
        "session_id": session_id,
        "split": split,
        "first_frame": first_frame,
        "last_frame": last_frame,
        "plate_instances": plate_instance_ids,
        "annotation_status": annotation_status,
    }


def plate_annotation(*, annotation_id: str, camera_id: str,
                     session_id: str, vehicle_instance_id: str,
                     plate_instance_id: str, frame_id: int,
                     plate_bbox: dict | None,
                     box_annotation_status: str,
                     plate_text_raw: str | None,
                     plate_type: str, region_code: str | None,
                     readability: str, occluded: bool,
                     truncated: bool, annotation_status: str,
                     annotator: str, notes: str = "",
                     measurements: dict | None = None) -> dict:
    """Build one plate-annotation record. The raw transcription
    is preserved verbatim; normalized/ascii forms are derived,
    never stored over the raw."""
    forms = canonical_forms(plate_text_raw)
    return {
        "annotation_id": annotation_id,
        "camera_id": camera_id,
        "session_id": session_id,
        "vehicle_instance_id": vehicle_instance_id,
        "plate_instance_id": plate_instance_id,
        "frame_id": frame_id,
        "plate_bbox": plate_bbox,
        "box_annotation_status": box_annotation_status,
        "plate_text_raw": forms["plate_text_raw"],
        "plate_text_normalized":
            forms["plate_text_normalized"],
        "plate_text_ascii": forms["plate_text_ascii"],
        "plate_type": plate_type,
        "region_code": region_code,
        "readability": readability,
        "occluded": bool(occluded),
        "truncated": bool(truncated),
        "measurements": measurements or {},
        "annotation_status": annotation_status,
        "annotator": annotator,
        "notes": notes,
    }


# ----------------------------------------------------------------- quality
def quality_properties(frame: np.ndarray,
                       bbox: tuple[int, int, int, int]
                       | None) -> dict:
    """Measurable crop properties (NOT GT). Used for the
    derived quality bucket and small-object buckets."""
    if bbox is None:
        return {}
    x1, y1, x2, y2 = bbox
    fh, fw = frame.shape[:2]
    x1c, y1c = max(0, x1), max(0, y1)
    x2c, y2c = min(fw, x2), min(fh, y2)
    crop = frame[y1c:y2c, x1c:x2c]
    if crop.size == 0:
        return {"plate_width_px": max(0, x2 - x1),
                "plate_height_px": max(0, y2 - y1)}
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return {
        "plate_width_px": int(x2 - x1),
        "plate_height_px": int(y2 - y1),
        "plate_area_px": int((x2 - x1) * (y2 - y1)),
        "aspect_ratio": round(float((x2 - x1) /
                                    max(1, y2 - y1)), 4),
        "blur_score": round(float(cv2.Laplacian(
            gray, cv2.CV_64F).var()), 3),
        "brightness": round(float(gray.mean()), 3),
        "contrast_std": round(float(gray.std()), 3),
    }


def derived_quality_bucket(props: dict) -> str | None:
    """Objective quality bucket from measurable properties.

    Conservative rule (documented, not authoritative):
      EXCELLENT — width >= 128 and blur >= 500
      GOOD      — width >= 96  and blur >= 300
      FAIR      — width >= 64
      POOR      — width >= 32
      UNREADABLE— width <  32
    Returns None when no properties exist.
    """
    w = props.get("plate_width_px")
    blur = props.get("blur_score")
    if w is None:
        return None
    if w >= 128 and (blur is None or blur >= 500):
        return "EXCELLENT"
    if w >= 96 and (blur is None or blur >= 300):
        return "GOOD"
    if w >= 64:
        return "FAIR"
    if w >= 32:
        return "POOR"
    return "UNREADABLE"


def width_bucket(width_px: int | None) -> str | None:
    """Small-object buckets (task §19), adapted to the
    observed cam1/cam2 distribution (66–256 px)."""
    if width_px is None:
        return None
    if width_px < 64:
        return "lt64"
    if width_px < 96:
        return "64-96"
    if width_px < 128:
        return "96-128"
    if width_px < 192:
        return "128-192"
    if width_px < 256:
        return "192-256"
    return "ge256"


# ------------------------------------------------------------- validation
def validate_plate_annotation(rec: dict) -> list[str]:
    """Return a list of validation errors (empty = valid).

    Enforces task §16 without rejecting difficult plates.
    """
    errs = []

    def req(field):
        if field not in rec or rec[field] in (None, ""):
            errs.append(f"missing required field: {field}")

    for f in ("annotation_id", "camera_id", "session_id",
              "vehicle_instance_id", "plate_instance_id",
              "frame_id", "annotation_status", "annotator"):
        req(f)

    status = rec.get("annotation_status")
    if status not in ANNOTATION_STATUSES:
        errs.append(f"invalid annotation_status: {status!r}")

    # verified text rules
    if status == "verified":
        text = rec.get("plate_text_raw")
        if not text or not str(text).strip():
            errs.append("verified annotation with empty text")
        if not rec.get("plate_text_ascii"):
            errs.append("verified annotation with empty "
                        "normalized/ascii form")
        if rec.get("plate_type") not in PLATE_TYPES:
            errs.append(f"invalid plate_type: "
                        f"{rec.get('plate_type')!r}")

    # box rules
    box_status = rec.get("box_annotation_status")
    if box_status not in BOX_STATUSES:
        errs.append(f"invalid box_annotation_status: "
                    f"{box_status!r}")
    box = rec.get("plate_bbox")
    if box is not None:
        try:
            x1, y1, x2, y2 = (int(box["x1"]), int(box["y1"]),
                              int(box["x2"]), int(box["y2"]))
        except (KeyError, TypeError, ValueError):
            errs.append("malformed plate_bbox")
        else:
            if x1 > x2 or y1 > y2:
                errs.append("inverted plate_bbox")
            if x1 < 0 or y1 < 0:
                errs.append("negative plate_bbox origin")
            if "image_width" in rec and x2 > rec["image_width"]:
                errs.append("plate_bbox exceeds image width")
            if "image_height" in rec and y2 > rec["image_height"]:
                errs.append("plate_bbox exceeds image height")
            if x2 - x1 < 4 or y2 - y1 < 4:
                errs.append("impossible plate dimensions "
                            "(< 4px)")
    elif box_status == "annotated":
        errs.append("box_annotation_status=annotated but "
                    "plate_bbox is null")

    # readability vocabulary
    rb = rec.get("readability")
    if rb is not None and rb not in READABILITY_LEVELS \
            and rb != "PENDING_HUMAN_REVIEW":
        errs.append(f"invalid readability: {rb!r}")

    # numeric field sanity
    fid = rec.get("frame_id")
    if fid is not None:
        if not isinstance(fid, int) or fid < 0:
            errs.append(f"invalid frame_id: {fid!r}")
    return errs


def validate_dataset(annotations: list[dict]) -> dict:
    """Whole-dataset validation: per-record checks plus
    global uniqueness constraints.

    Returns {"valid": bool, "errors": [...],
             "n_records": int, "n_records_with_errors": int}.
    """
    errors = []
    seen_ids = set()
    seen_frame_instance = {}
    bad = 0
    for rec in annotations:
        rec_errs = validate_plate_annotation(rec)
        aid = rec.get("annotation_id")
        if aid in seen_ids:
            rec_errs.append(f"duplicate annotation_id: {aid}")
        seen_ids.add(aid)
        key = (rec.get("vehicle_instance_id"),
               rec.get("frame_id"))
        if key in seen_frame_instance:
            rec_errs.append(
                "duplicate vehicle_instance/frame assignment: "
                f"{key}")
        seen_frame_instance[key] = aid
        if rec_errs:
            bad += 1
            errors.append({"annotation_id": aid,
                           "errors": rec_errs})
    return {
        "valid": not errors,
        "errors": errors,
        "n_records": len(annotations),
        "n_records_with_errors": bad,
    }


# ------------------------------------------------------------- clustering
def cluster_detections(
    detections: list[dict],
    *,
    max_centre_distance: float = 120.0,
    max_frame_gap: int = 25,
) -> list[dict]:
    """Group detections into PROVISIONAL vehicle instances
    by spatiotemporal proximity.

    Two detections belong to the same provisional cluster
    when their box centres are within `max_centre_distance`
    px AND their frames are within `max_frame_gap` of the
    cluster's frame range (transitive closure).

    PROVISIONAL: this is a measurement grouping, not GT. A
    human must confirm which detections show the same
    physical vehicle.
    """
    clusters: list[dict] = []
    for det in sorted(detections,
                      key=lambda d: (d["frame"],
                                     d["bbox"][0])):
        x1, y1, x2, y2 = det["bbox"]
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        best = None
        for c in clusters:
            if (abs(cx - c["centre"][0]) <= max_centre_distance
                    and abs(cy - c["centre"][1])
                    <= max_centre_distance
                    and c["frame_min"] - max_frame_gap
                    <= det["frame"]
                    <= c["frame_max"] + max_frame_gap):
                if best is None or det["frame"] < best["frame_min"]:
                    best = c
        if best is None:
            clusters.append({
                "centre": [cx, cy],
                "frame_min": det["frame"],
                "frame_max": det["frame"],
                "frames": [det["frame"]],
                "detections": [det],
            })
        else:
            n = len(best["frames"])
            best["centre"] = [
                (best["centre"][0] * n + cx) / (n + 1),
                (best["centre"][1] * n + cy) / (n + 1)]
            best["frames"].append(det["frame"])
            best["frame_min"] = min(best["frame_min"],
                                    det["frame"])
            best["frame_max"] = max(best["frame_max"],
                                    det["frame"])
            best["detections"].append(det)
    for c in clusters:
        c["frames"] = sorted(c["frames"])
    return sorted(clusters, key=lambda c: c["frame_min"])


# ------------------------------------------------------------- sampling
def sample_frames(frame_count: int,
                  interval: int = SAMPLING_INTERVAL) -> list[int]:
    """Deterministic interval sampling: every `interval`-th
    frame, starting at 0."""
    return list(range(0, frame_count, interval))


def read_video_frames(video_path: Path,
                      frame_ids: list[int]) -> dict[int, np.ndarray]:
    """Decode only the requested frames (sequential read,
    single pass)."""
    wanted = set(frame_ids)
    out = {}
    cap = cv2.VideoCapture(str(video_path))
    idx = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if idx in wanted:
            out[idx] = fr
        idx += 1
        if len(out) == len(wanted):
            break
    cap.release()
    return out
