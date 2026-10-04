"""Phase 3.5 tests — annotation workflow rules (§19),
dataset-level validation extensions (§20), annotation queue
prioritisation (§21/§26) and the deterministic instance
sampler (§24)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmarks.phase3_dataset import (  # noqa: E402
    ANNOTATION_STATUSES, OCCLUSION_TYPES,
    READABILITY_LEVELS, WORKFLOW_STATUSES,
    annotation_status_label, build_annotation_queue,
    plate_annotation, queue_summary,
    sample_instance_frames, validate_annotation_workflow,
    validate_dataset, validate_plate_annotation)

BOX = {"x1": 100, "y1": 200, "x2": 300, "y2": 260}

# Keys plate_annotation() does not take as constructor kwargs;
# they are applied to the record after construction.
_DIRECT_KEYS = ("image_width", "image_height",
                "uncertainty_reason", "occlusion_type",
                "revision", "created_at", "updated_at",
                "plate_text_normalized", "plate_text_ascii",
                "notes")


def _record(**overrides) -> dict:
    """Build a record via the canonical constructor, then apply
    overrides (including raw key tampering)."""
    fields = dict(
        annotation_id="cam2_s001_v001_p001_f00205",
        camera_id="cam2", session_id="cam2_s001",
        vehicle_instance_id="cam2_s001_v001",
        plate_instance_id="cam2_s001_v001_p001",
        frame_id=205, plate_bbox=BOX,
        box_annotation_status="annotated",
        plate_text_raw="۱۲د۶۷۴۱۳",
        plate_type="civilian", region_code="13",
        readability="GOOD", occluded=False,
        truncated=False, annotation_status="verified",
        annotator="test")
    direct = {}
    for k, v in overrides.items():
        if k in _DIRECT_KEYS:
            direct[k] = v
        else:
            fields[k] = v
    rec = plate_annotation(**fields)
    rec.update(direct)
    return rec


# ------------------------------------------------------- §19 save gate
def test_readability_vocabulary_is_exactly_six():
    assert READABILITY_LEVELS == (
        "EXCELLENT", "GOOD", "FAIR", "POOR",
        "UNREADABLE", "INVALID_SAMPLE")


def test_workflow_status_vocabulary():
    assert WORKFLOW_STATUSES == (
        "UNLABELED", "IN_PROGRESS", "VERIFIED", "REJECTED")
    # UNLABELED is queue-only: never stored on a record.
    assert "unlabeled" not in ANNOTATION_STATUSES
    assert "in_progress" in ANNOTATION_STATUSES
    assert "rejected" in ANNOTATION_STATUSES


@pytest.mark.parametrize("rb", ["EXCELLENT", "GOOD", "FAIR"])
def test_sfa_verified_requires_bbox_and_text(rb):
    rec = _record(readability=rb, plate_bbox=None,
                  box_annotation_status=
                  "pending_human_annotation")
    errs = validate_annotation_workflow(rec)
    assert any("requires plate bbox" in e for e in errs)
    rec2 = _record(readability=rb, plate_bbox=BOX,
                   plate_text_raw="")
    errs2 = validate_annotation_workflow(rec2)
    assert any("requires plate text" in e for e in errs2)
    assert validate_annotation_workflow(
        _record(readability=rb)) == []


def test_poor_verified_requires_reason_not_guessing():
    rec = _record(readability="POOR", plate_text_raw="")
    errs = validate_annotation_workflow(rec)
    assert any("uncertainty_reason" in e for e in errs)
    rec["uncertainty_reason"] = "final_digit_ambiguous"
    assert validate_annotation_workflow(rec) == []


def test_unreadable_requires_empty_text_and_reason():
    rec = _record(readability="UNREADABLE")
    errs = validate_annotation_workflow(rec)
    assert any("plate_text empty" in e for e in errs)
    rec = _record(readability="UNREADABLE",
                  plate_text_raw="")
    errs = validate_annotation_workflow(rec)
    assert any("uncertainty_reason" in e for e in errs)
    rec["uncertainty_reason"] = "insufficient_resolution"
    assert validate_annotation_workflow(rec) == []


def test_invalid_sample_requires_reason():
    rec = _record(readability="INVALID_SAMPLE",
                  plate_text_raw="",
                  plate_bbox=None,
                  box_annotation_status=
                  "pending_human_annotation")
    errs = validate_annotation_workflow(rec)
    assert any("uncertainty_reason" in e for e in errs)
    rec["uncertainty_reason"] = "frame corrupt"
    assert validate_annotation_workflow(rec) == []


def test_gate_applies_only_to_verified():
    rec = _record(readability="GOOD", plate_bbox=None,
                  box_annotation_status=
                  "pending_human_annotation",
                  annotation_status="in_progress")
    assert validate_annotation_workflow(rec) == []
    rec["annotation_status"] = "rejected"
    assert validate_annotation_workflow(rec) == []


def test_legacy_transitional_verified_not_regated():
    """Existing staged GT (transitional readability, no
    human revision) must stay valid untouched."""
    rec = _record(readability="PENDING_HUMAN_REVIEW",
                  plate_bbox=None,
                  box_annotation_status=
                  "pending_human_annotation")
    assert validate_annotation_workflow(rec) == []
    assert validate_plate_annotation(rec) == []


def test_human_saved_verified_must_pick_a_class():
    """A record saved through the human tool (revision set)
    may not stay on the transitional readability."""
    rec = _record(readability="PENDING_HUMAN_REVIEW",
                  plate_bbox=None,
                  box_annotation_status=
                  "pending_human_annotation",
                  revision=1)
    errs = validate_annotation_workflow(rec)
    assert any("readability class" in e for e in errs)


# ---------------------------------------------------------- §20 checks
def test_inconsistent_normalized_text_rejected():
    rec = _record()
    rec["plate_text_normalized"] = "tampered"
    errs = validate_plate_annotation(rec)
    assert any("inconsistent raw/normalized" in e
               for e in errs)


def test_unnormalizable_raw_text_rejected():
    rec = _record(plate_text_raw="###")
    errs = validate_plate_annotation(rec)
    assert any("invalid normalized text" in e for e in errs)


def test_invalid_occlusion_type_rejected():
    rec = _record(occlusion_type="meteor_strike")
    errs = validate_plate_annotation(rec)
    assert any("occlusion_type" in e for e in errs)


@pytest.mark.parametrize("oct_", OCCLUSION_TYPES)
def test_valid_occlusion_types_accepted(oct_):
    rec = _record(occlusion_type=oct_)
    assert validate_plate_annotation(rec) == []


def test_in_progress_and_rejected_statuses_valid():
    for st in ("in_progress", "rejected"):
        rec = _record(annotation_status=st)
        assert validate_plate_annotation(rec) == []


def test_dataset_missing_reference_checks():
    rec = _record()
    res = validate_dataset([rec], cameras={"other_cam"},
                           sessions={"other_s"},
                           vehicles={"other_v"})
    assert not res["valid"]
    joined = " ".join(x for e in res["errors"]
                      for x in e["errors"])
    assert "missing camera" in joined
    assert "missing session" in joined
    assert "missing vehicle instance" in joined


def test_dataset_duplicate_frame_id_detected():
    res = validate_dataset(
        [_record()],
        frames=[{"camera_id": "cam2", "frame_id": 205},
                {"camera_id": "cam2", "frame_id": 205}])
    assert not res["valid"]
    assert any("duplicate frame id" in e
               for e in res["dataset_errors"])


def test_dataset_duplicate_physical_instance_detected():
    a = _record()
    b = _record(
        annotation_id="cam2_s001_v002_p001_f00210",
        vehicle_instance_id="cam2_s001_v002",
        frame_id=210)
    # same plate_instance_id under two vehicles
    b["plate_instance_id"] = a["plate_instance_id"]
    res = validate_dataset([a, b])
    assert not res["valid"]
    assert any("duplicate physical plate instance" in e
               for e in res["dataset_errors"])


def test_dataset_split_leakage_detected():
    rec = _record()
    res = validate_dataset(
        [rec],
        splits={"train": ["cam2_s001_v001"],
                "validation": ["cam2_s001_v001"],
                "test": []})
    assert not res["valid"]
    assert any("split leakage" in e
               for e in res["dataset_errors"])


# ------------------------------------------------------ §21/§26 queue
def _entry(**kw):
    defaults = dict(frame_id=0, status="UNLABELED", valid=True,
                    n_annotations=0, phase2b_sample=False,
                    priority=0)
    defaults.update(kw)
    return defaults


def test_queue_priority_order():
    verified = _record()  # GOOD w/ bbox+text -> VERIFIED
    inprog = _record(
        annotation_id="cam2_s001_v001_p001_f00210",
        frame_id=210, annotation_status="in_progress")
    rejected = _record(
        annotation_id="cam2_s001_v001_p001_f00215",
        frame_id=215, annotation_status="rejected")
    tampered = _record(
        annotation_id="cam2_s001_v001_p001_f00220",
        frame_id=220, annotation_status="verified")
    tampered["plate_text_normalized"] = "tampered"
    q = build_annotation_queue(
        [verified, inprog, rejected, tampered],
        [205, 210, 215, 220, 300, 305], camera="cam2")
    labels = [(e["frame_id"], e["status"], e["valid"])
              for e in q]
    # unannotated frames first, then in-progress, then the
    # invalid record, then rejected, then verified.
    assert [f for f, _, _ in labels][:2] == [300, 305]
    assert labels[2] == (210, "IN_PROGRESS", True)
    assert labels[3] == (220, "VERIFIED", False)  # invalid
    assert labels[4] == (215, "REJECTED", True)
    assert labels[5] == (205, "VERIFIED", True)
    assert [e["priority"] for e in q] == sorted(
        e["priority"] for e in q)


def test_queue_staged_samples_first_within_class():
    staged = _record(
        annotation_id="cam2_s001_v001_p001_f00300",
        frame_id=300, annotation_status="in_progress",
        notes="spatiotemporal cluster; phase2b_sample=True")
    plain = _record(
        annotation_id="cam2_s001_v001_p001_f00210",
        frame_id=210, annotation_status="in_progress")
    q = build_annotation_queue([staged, plain],
                               [300, 210], camera="cam2")
    assert [e["frame_id"] for e in q] == [300, 210]
    assert q[0]["phase2b_sample"] is True


def test_queue_camera_filter():
    cam1 = _record()
    cam2 = _record(
        annotation_id="cam2_s001_v001_p001_f00210",
        frame_id=210)
    q = build_annotation_queue([cam1, cam2],
                               [0, 210], camera="cam2")
    by_frame = {e["frame_id"]: e for e in q}
    # frame 0 has only a cam1 record: filtered out -> UNLABELED
    assert by_frame[0]["status"] == "UNLABELED"
    assert by_frame[210]["status"] == "VERIFIED"


def test_status_label_mapping():
    assert annotation_status_label([]) == "UNLABELED"
    assert annotation_status_label(
        [_record()]) == "VERIFIED"
    assert annotation_status_label(
        [_record(annotation_status="pending_human_review")]
    ) == "IN_PROGRESS"
    assert annotation_status_label(
        [_record(annotation_status="in_progress")]
    ) == "IN_PROGRESS"
    assert annotation_status_label(
        [_record(annotation_status="rejected")]
    ) == "REJECTED"


def test_queue_summary_counts():
    entries = [
        _entry(status="UNLABELED", priority=0),
        _entry(status="IN_PROGRESS", priority=1),
        _entry(status="IN_PROGRESS", priority=2,
               valid=False),
        _entry(status="VERIFIED", priority=4),
    ]
    s = queue_summary(entries)
    assert s == {"UNLABELED": 1, "IN_PROGRESS": 2,
                 "VERIFIED": 1, "REJECTED": 0,
                 "invalid": 1}


# ---------------------------------------------------------- §24 sampler
def test_sampler_deterministic():
    ids = list(range(0, 500, 5))
    assert sample_instance_frames(ids, 8) == \
        sample_instance_frames(ids, 8)


def test_sampler_spreads_frames_over_instance():
    ids = list(range(100, 200))  # one continuous burst
    picked = sample_instance_frames(ids, 5)
    assert len(picked) == 5
    assert picked[0] == 100 and picked[-1] == 199
    # not a burst: spans the full range
    assert picked[-1] - picked[0] > 0.8 * (
        ids[-1] - ids[0])
    gaps = [b - a for a, b in zip(picked, picked[1:])]
    assert min(gaps) > 5


def test_sampler_returns_all_when_enough():
    ids = [0, 5, 10]
    assert sample_instance_frames(ids, 5) == ids


def test_sampler_edge_cases():
    assert sample_instance_frames([], 5) == []
    assert sample_instance_frames([1, 2, 3], 0) == []
    assert sample_instance_frames([9, 1, 5], 1) == [1]
    assert sample_instance_frames(
        [3, 1, 2, 1], 10) == [1, 2, 3]
