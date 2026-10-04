"""Phase 3 tests — GT schema validation and dataset
construction (task §16/§37)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmarks.phase3_dataset import (  # noqa: E402
    PLATE_TYPES, cluster_detections,
    derived_quality_bucket, plate_annotation,
    quality_properties, sample_frames,
    validate_dataset, validate_plate_annotation,
    width_bucket)


def _valid_record(**overrides) -> dict:
    rec = plate_annotation(
        annotation_id="cam1_s001_v001_p001_f000180",
        camera_id="cam1", session_id="cam1_s001",
        vehicle_instance_id="cam1_s001_v001",
        plate_instance_id="cam1_s001_v001_p001",
        frame_id=180,
        plate_bbox=None,
        box_annotation_status="pending_human_annotation",
        plate_text_raw="۱۲د۶۷۴۱۳",
        plate_type="civilian", region_code="13",
        readability="GOOD", occluded=False,
        truncated=False, annotation_status="verified",
        annotator="test")
    rec.update(overrides)
    return rec


def test_valid_record_passes():
    assert validate_plate_annotation(
        _valid_record()) == []


def test_missing_required_fields_rejected():
    rec = _valid_record()
    del rec["annotation_id"]
    errs = validate_plate_annotation(rec)
    assert any("annotation_id" in e for e in errs)


def test_verified_annotation_requires_text():
    rec = _valid_record(plate_text_raw=None)
    errs = validate_plate_annotation(rec)
    assert any("empty text" in e for e in errs)


def test_verified_annotation_requires_valid_type():
    rec = _valid_record(plate_type="civilian???")
    errs = validate_plate_annotation(rec)
    assert any("plate_type" in e for e in errs)


@pytest.mark.parametrize("ptype", PLATE_TYPES)
def test_all_taxonomy_types_accepted(ptype):
    rec = _valid_record(plate_type=ptype)
    assert validate_plate_annotation(rec) == []


def test_unknown_plate_type_not_forced_civilian():
    """unknown is a legitimate value and must pass."""
    rec = _valid_record(plate_type="unknown",
                        plate_text_raw="۱۲د۶۷۴۱۳")
    assert validate_plate_annotation(rec) == []


def test_inverted_box_rejected():
    rec = _valid_record(
        plate_bbox={"x1": 100, "y1": 50,
                    "x2": 90, "y2": 90},
        box_annotation_status="annotated")
    errs = validate_plate_annotation(rec)
    assert any("inverted" in e for e in errs)


def test_negative_box_rejected():
    rec = _valid_record(
        plate_bbox={"x1": -5, "y1": 0,
                    "x2": 90, "y2": 90},
        box_annotation_status="annotated")
    errs = validate_plate_annotation(rec)
    assert any("negative" in e for e in errs)


def test_out_of_frame_box_rejected():
    rec = _valid_record(
        plate_bbox={"x1": 0, "y1": 0,
                    "x2": 9999, "y2": 90},
        box_annotation_status="annotated",
        image_width=1920)
    errs = validate_plate_annotation(rec)
    assert any("exceeds image width" in e
               for e in errs)


def test_impossible_dimensions_rejected():
    rec = _valid_record(
        plate_bbox={"x1": 0, "y1": 0,
                    "x2": 2, "y2": 2},
        box_annotation_status="annotated")
    errs = validate_plate_annotation(rec)
    assert any("impossible plate dimensions" in e
               for e in errs)


def test_annotated_status_requires_box():
    rec = _valid_record(
        plate_bbox=None,
        box_annotation_status="annotated")
    errs = validate_plate_annotation(rec)
    assert any("plate_bbox is null" in e
               for e in errs)


def test_pending_box_status_allows_null_box():
    rec = _valid_record(
        plate_bbox=None,
        box_annotation_status="pending_human_annotation")
    assert validate_plate_annotation(rec) == []


def test_difficult_plates_not_rejected():
    """Poor readability, occlusion, truncation and
    unusual types are legitimate data."""
    rec = _valid_record(
        readability="POOR", occluded=True,
        truncated=True, plate_type="motorcycle",
        annotation_status="verified",
        plate_text_raw="۱۲د۶۷۴۱۳")
    assert validate_plate_annotation(rec) == []


def test_duplicate_annotation_id_detected():
    a = _valid_record()
    b = _valid_record(frame_id=185)
    res = validate_dataset([a, b])
    assert not res["valid"]
    assert any("duplicate annotation_id" in " ".join(
        e["errors"]) for e in res["errors"])


def test_duplicate_frame_instance_assignment_detected():
    a = _valid_record()
    b = _valid_record(
        annotation_id="...different")
    res = validate_dataset([a, b])
    assert not res["valid"]
    assert any("duplicate vehicle_instance/frame"
               in " ".join(e["errors"])
               for e in res["errors"])


def test_valid_dataset_passes():
    a = _valid_record()
    b = _valid_record(
        annotation_id="cam1_s001_v001_p001_f000185",
        frame_id=185)
    res = validate_dataset([a, b])
    assert res["valid"]
    assert res["n_records"] == 2


def test_malformed_box_handled():
    rec = _valid_record(
        plate_bbox="not-a-box",
        box_annotation_status="annotated")
    errs = validate_plate_annotation(rec)
    assert any("malformed plate_bbox" in e
               for e in errs)


def test_quality_properties():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    props = quality_properties(frame, (10, 10, 110, 50))
    assert props["plate_width_px"] == 100
    assert props["plate_height_px"] == 40
    assert props["aspect_ratio"] == 2.5


def test_quality_properties_empty_crop():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    props = quality_properties(frame, (300, 300, 400, 400))
    assert props["plate_width_px"] == 100
    assert "blur_score" not in props


def test_derived_quality_bucket():
    assert derived_quality_bucket(
        {"plate_width_px": 200, "blur_score": 900}) \
        == "EXCELLENT"
    assert derived_quality_bucket(
        {"plate_width_px": 100, "blur_score": 400}) \
        == "GOOD"
    assert derived_quality_bucket(
        {"plate_width_px": 70}) == "FAIR"
    assert derived_quality_bucket(
        {"plate_width_px": 40}) == "POOR"
    assert derived_quality_bucket(
        {"plate_width_px": 20}) == "UNREADABLE"
    assert derived_quality_bucket({}) is None


def test_width_bucket():
    assert width_bucket(63) == "lt64"
    assert width_bucket(64) == "64-96"
    assert width_bucket(96) == "96-128"
    assert width_bucket(128) == "128-192"
    assert width_bucket(192) == "192-256"
    assert width_bucket(256) == "ge256"
    assert width_bucket(None) is None


def test_sample_frames_deterministic():
    assert sample_frames(100, 5) == list(range(0, 100, 5))
    assert sample_frames(7, 5) == [0, 5]


def test_cluster_detections_groups_nearby():
    dets = [
        {"frame": 100, "bbox": (100, 100, 200, 140)},
        {"frame": 105, "bbox": (102, 101, 202, 141)},
        {"frame": 110, "bbox": (101, 99, 201, 139)},
        {"frame": 100, "bbox": (900, 900, 1000, 940)},
    ]
    clusters = cluster_detections(dets)
    assert len(clusters) == 2
    big = max(clusters, key=lambda c: len(c["frames"]))
    assert len(big["frames"]) == 3


def test_cluster_detections_separates_distant():
    dets = [
        {"frame": 100, "bbox": (0, 0, 100, 40)},
        {"frame": 100, "bbox": (1500, 900, 1600, 940)},
    ]
    assert len(cluster_detections(dets)) == 2


def test_cluster_detections_respects_time_gap():
    dets = [
        {"frame": 100, "bbox": (100, 100, 200, 140)},
        {"frame": 200, "bbox": (100, 100, 200, 140)},
    ]
    # same location but 100 frames apart (> max_frame_gap
    # of 25) -> separate provisional instances
    assert len(cluster_detections(dets)) == 2
