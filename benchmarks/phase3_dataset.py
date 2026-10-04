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
    PERSIAN_DIGITS, PERSIAN_LETTERS,
    canonical_forms, extract_region_code)

DATASET_DIR = ROOT / "benchmarks" / "dataset" / "phase3"
GT_LABELS = ROOT / "benchmarks" / "dataset" / "gt_labels.json"

# Readability classes (Phase 3.5 §5) — exactly these six.
READABILITY_LEVELS = ("EXCELLENT", "GOOD", "FAIR", "POOR",
                      "UNREADABLE", "INVALID_SAMPLE")
# Transitional value on staged Phase 3 records. It stays
# accepted by validation so the existing dataset remains
# valid, but it is NOT one of the six annotation classes.
TRANSITIONAL_READABILITY = "PENDING_HUMAN_REVIEW"
# Definitions shown verbatim in the annotation UI (§5).
READABILITY_DEFINITIONS = {
    "EXCELLENT":
        "Plate is clearly readable with high confidence.",
    "GOOD":
        "Plate is readable with minor visual difficulty.",
    "FAIR": ("Plate is readable but one or more characters "
             "require careful inspection."),
    "POOR": ("Partially readable, transcription has "
             "meaningful uncertainty. POOR does NOT mean "
             "guess: leave plate_text empty and give an "
             "uncertainty_reason."),
    "UNREADABLE": ("Plate visible but no reliable "
                   "transcription can be established "
                   "(plate_text stays empty + reason)."),
    "INVALID_SAMPLE": ("Sample cannot legitimately be "
                       "annotated: plate missing, corrupted, "
                       "unusable, or frame invalid (reason "
                       "required)."),
}
# Annotation status (Phase 3.5 §26). UNLABELED is a
# queue-level state for frames WITHOUT a record (it is never
# stored on a record); records store one of the values below.
# Legacy Phase 3 staged statuses stay accepted so existing
# GT records remain valid untouched.
ANNOTATION_STATUSES = ("in_progress", "verified", "rejected",
                       "pending_human_review",
                       "provisional_programmatic")
# The four workflow statuses shown in the queue/UI (§26).
WORKFLOW_STATUSES = ("UNLABELED", "IN_PROGRESS", "VERIFIED",
                     "REJECTED")
# Stored status -> workflow label. Legacy staged statuses map
# to IN_PROGRESS (explicit values, never inferred from
# missing fields).
WORKFLOW_STATUS_MAP = {
    "in_progress": "IN_PROGRESS",
    "pending_human_review": "IN_PROGRESS",
    "provisional_programmatic": "IN_PROGRESS",
    "verified": "VERIFIED",
    "rejected": "REJECTED",
}
# Structured uncertainty reasons (Phase 3.5 §17).
UNCERTAINTY_REASONS = ("final_digit_ambiguous",
                       "letter_ambiguous",
                       "insufficient_resolution",
                       "motion_blur", "occlusion", "other")
# Occlusion type (Phase 3.5 §18). detector_crop records crop
# clipping and is explicitly NOT physical plate truncation.
OCCLUSION_TYPES = ("none", "vehicle_occlusion",
                   "object_occlusion", "frame_edge",
                   "detector_crop", "unknown")
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

    # readability vocabulary (six classes + transitional)
    rb = rec.get("readability")
    if rb is not None and rb not in READABILITY_LEVELS \
            and rb != TRANSITIONAL_READABILITY:
        errs.append(f"invalid readability: {rb!r}")

    # raw/normalized/ascii consistency (§20): derived forms
    # must be reproducible from the raw human transcription.
    raw = rec.get("plate_text_raw")
    forms = canonical_forms(raw)
    if rec.get("plate_text_normalized") != \
            forms["plate_text_normalized"]:
        errs.append("inconsistent raw/normalized text")
    if rec.get("plate_text_ascii") != \
            forms["plate_text_ascii"]:
        errs.append("inconsistent raw/ascii text")
    norm = forms["plate_text_normalized"]
    if (raw or "").strip() and not norm:
        errs.append("invalid normalized text (empty for "
                    "non-empty raw)")
    elif norm and not all(
            ch in PERSIAN_DIGITS or ch in PERSIAN_LETTERS
            or (ch.isascii() and ch.isalnum())
            for ch in norm):
        errs.append("invalid normalized text (unexpected "
                    "characters)")

    # plate type: valid whenever present (any status);
    # verified records must carry a valid type (checked above).
    if status != "verified":
        pt = rec.get("plate_type")
        if pt is not None and pt != "" \
                and pt not in PLATE_TYPES:
            errs.append(f"invalid plate_type: {pt!r}")

    # occlusion type vocabulary (§18)
    oct_ = rec.get("occlusion_type")
    if oct_ is not None and oct_ != "" \
            and oct_ not in OCCLUSION_TYPES:
        errs.append(f"invalid occlusion_type: {oct_!r}")

    ur = rec.get("uncertainty_reason")
    if ur is not None and not isinstance(ur, str):
        errs.append("uncertainty_reason must be text")

    # numeric field sanity
    fid = rec.get("frame_id")
    if fid is not None:
        if not isinstance(fid, int) or fid < 0:
            errs.append(f"invalid frame_id: {fid!r}")
    return errs


def validate_dataset(annotations: list[dict], *,
                     frames=None, cameras=None,
                     sessions=None, vehicles=None,
                     splits=None) -> dict:
    """Whole-dataset validation: per-record checks plus
    global uniqueness constraints.

    Returns {"valid": bool, "errors": [...],
             "dataset_errors": [...],
             "n_records": int, "n_records_with_errors": int}.

    Optional cross-file checks (Phase 3.5 §20): pass
    `frames` (frame records), `cameras` / `sessions` /
    `vehicles` (id iterables or dicts) and the split dict
    {train:[], validation:[], test:[]} to enable duplicate
    frame-id, missing camera/session/instance, duplicate
    physical instance and split-leakage checks. All optional
    so existing callers keep their behaviour.
    """
    errors = []
    dataset_errors = []
    seen_ids = set()
    seen_frame_instance = {}
    bad = 0
    cam_ids = set(cameras) if cameras is not None else None
    sess_ids = set(sessions) if sessions is not None else None
    veh_ids = set(vehicles) if vehicles is not None else None
    plate_owner: dict = {}
    vehicle_cam: dict = {}
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
        if cam_ids is not None and \
                rec.get("camera_id") not in cam_ids:
            rec_errs.append(
                f"missing camera: {rec.get('camera_id')!r}")
        if sess_ids is not None and \
                rec.get("session_id") not in sess_ids:
            rec_errs.append(
                f"missing session: {rec.get('session_id')!r}")
        if veh_ids is not None and \
                rec.get("vehicle_instance_id") not in veh_ids:
            rec_errs.append(
                "missing vehicle instance: "
                f"{rec.get('vehicle_instance_id')!r}")
        # duplicate physical instances: one plate instance may
        # never belong to two vehicles; one vehicle instance
        # may never span two cameras.
        pid = rec.get("plate_instance_id")
        vid = rec.get("vehicle_instance_id")
        if pid is not None and vid is not None:
            if pid in plate_owner and plate_owner[pid] != vid:
                dataset_errors.append(
                    "duplicate physical plate instance: "
                    f"{pid} under {plate_owner[pid]} and {vid}")
            plate_owner.setdefault(pid, vid)
        if vid is not None:
            cam = rec.get("camera_id")
            if vid in vehicle_cam and vehicle_cam[vid] != cam:
                dataset_errors.append(
                    "duplicate physical vehicle instance: "
                    f"{vid} under cameras {vehicle_cam[vid]} "
                    f"and {cam}")
            vehicle_cam.setdefault(vid, cam)
        if rec_errs:
            bad += 1
            errors.append({"annotation_id": aid,
                           "errors": rec_errs})
    if frames is not None:
        seen_frames = set()
        for f in frames:
            fk = (f.get("camera_id"), f.get("frame_id"))
            if fk in seen_frames:
                dataset_errors.append(
                    f"duplicate frame id: {fk}")
            seen_frames.add(fk)
    if splits is not None:
        from benchmarks.phase3_splits import check_leakage
        leak = check_leakage(annotations, splits)
        dataset_errors.extend(
            f"split leakage: {v}"
            for v in leak["violations"])
    return {
        "valid": not errors and not dataset_errors,
        "errors": errors,
        "dataset_errors": dataset_errors,
        "n_records": len(annotations),
        "n_records_with_errors": bad,
    }


# ------------------------------------------------- save-gate rules (§19)
def validate_annotation_workflow(rec: dict) -> list[str]:
    """Phase 3.5 §19 — rules enforced BEFORE saving a record
    as verified, keyed on the readability class:

      EXCELLENT/GOOD/FAIR — plate bbox + valid plate text
      POOR                — uncertainty_reason (text optional;
                            never guess; bbox required only if
                            the plate is visible — a human
                            judgment the UI documents)
      UNREADABLE          — plate_text empty + reason
      INVALID_SAMPLE      — reason

    Applied to `verified` records only, so in-progress work
    is never blocked and legacy staged records (transitional
    readability) stay valid. Returns [] when the record does
    not need the gate.
    """
    if rec.get("annotation_status") != "verified":
        return []
    errs = []
    rb = rec.get("readability")
    text = str(rec.get("plate_text_raw") or "").strip()
    reason = str(rec.get("uncertainty_reason") or "").strip()
    box = rec.get("plate_bbox")
    if rb in ("EXCELLENT", "GOOD", "FAIR"):
        if box is None:
            errs.append(
                f"{rb} verified annotation requires plate bbox")
        if not text:
            errs.append(
                f"{rb} verified annotation requires plate text")
    elif rb == "POOR":
        if not reason:
            errs.append(
                "POOR verified annotation requires "
                "uncertainty_reason")
    elif rb == "UNREADABLE":
        if text:
            errs.append(
                "UNREADABLE verified annotation must keep "
                "plate_text empty (do not guess)")
        if not reason:
            errs.append(
                "UNREADABLE verified annotation requires "
                "uncertainty_reason")
    elif rb == "INVALID_SAMPLE":
        if not reason:
            errs.append(
                "INVALID_SAMPLE verified annotation requires "
                "uncertainty_reason")
    elif rb == TRANSITIONAL_READABILITY or not rb:
        # Transitional readability: legacy staged records
        # (no human revision) are NOT re-gated so existing GT
        # stays valid untouched. A record saved through the
        # human tool (revision present) must pick a class.
        if rec.get("revision") is not None:
            errs.append(
                "human-saved verified annotation must use one "
                "of the six readability classes (not "
                f"{rb or 'unset'})")
    return errs


# ------------------------------------------------- queue (§21/§26)
def annotation_status_label(records: list[dict]) -> str:
    """Workflow label for the records of one frame.

    no records -> UNLABELED; all verified -> VERIFIED;
    any rejected -> REJECTED; otherwise IN_PROGRESS.
    Status is always read from the explicit stored value,
    never inferred from missing fields.
    """
    if not records:
        return "UNLABELED"
    labels = {WORKFLOW_STATUS_MAP.get(
        r.get("annotation_status"), "IN_PROGRESS")
        for r in records}
    if labels and labels <= {"VERIFIED"}:
        return "VERIFIED"
    if "REJECTED" in labels:
        return "REJECTED"
    return "IN_PROGRESS"


def build_annotation_queue(annotations: list[dict],
                           frame_ids,
                           camera: str | None = None
                           ) -> list[dict]:
    """Ordered per-frame annotation queue (Phase 3.5 §21).

    Priority: 1 unannotated (UNLABELED), 2 partially
    annotated (IN_PROGRESS), 3 invalid/inconsistent,
    4 REJECTED, 5 VERIFIED. Within a priority class, staged
    Phase 2B cam2 samples come first, then frame id.
    """
    by_frame: dict = {}
    for a in annotations:
        if camera is None or a.get("camera_id") == camera:
            by_frame.setdefault(a.get("frame_id"),
                                []).append(a)
    entries = []
    for fid in sorted({int(f) for f in frame_ids}):
        recs = by_frame.get(fid, [])
        invalid = any(
            validate_plate_annotation(r)
            or validate_annotation_workflow(r)
            for r in recs)
        label = annotation_status_label(recs)
        if not recs:
            prio = 0
        elif invalid:
            prio = 2
        elif label == "IN_PROGRESS":
            prio = 1
        elif label == "REJECTED":
            prio = 3
        else:
            prio = 4
        staged = any("phase2b_sample=True"
                     in (r.get("notes") or "")
                     for r in recs)
        entries.append({
            "frame_id": fid, "status": label,
            "valid": not invalid,
            "n_annotations": len(recs),
            "phase2b_sample": staged,
            "priority": prio})
    entries.sort(key=lambda e: (
        e["priority"],
        0 if e["phase2b_sample"] else 1,
        e["frame_id"]))
    return entries


def queue_summary(entries: list[dict]) -> dict:
    """Counts per workflow status plus #invalid (§21)."""
    out = {s: 0 for s in WORKFLOW_STATUSES}
    out["invalid"] = 0
    for e in entries:
        out[e["status"]] += 1
        if not e["valid"]:
            out["invalid"] += 1
    return out


# ------------------------------------- camera-3 sampler prep (§24)
def sample_instance_frames(frame_ids, k: int) -> list[int]:
    """Deterministic, temporally-SPREAD selection of up to `k`
    frames from one instance's candidate frames.

    Frames are picked at evenly spaced indices over the sorted
    candidate list (endpoints included), so a single continuous
    burst is never selected. Pure function of the input: same
    frames in -> same frames out, every time. Meant for a third
    camera's sampling manifest (>= 5 frames per instance,
    10-20 instances).
    """
    ids = sorted({int(f) for f in frame_ids})
    if k <= 0 or not ids:
        return []
    if len(ids) <= k:
        return ids
    if k == 1:
        return [ids[0]]
    n = len(ids)
    idx = sorted({round(i * (n - 1) / (k - 1))
                  for i in range(k)})
    return [ids[i] for i in idx]


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
