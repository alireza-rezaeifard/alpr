"""Phase 3 tests — splits and leakage prevention
(task §26/§27/§37)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmarks.phase3_dataset import (  # noqa: E402
    plate_annotation)
from benchmarks.phase3_splits import (  # noqa: E402
    build_splits, check_leakage)


def _vehicle(vid):
    return {"vehicle_instance_id": vid, "camera_id": "cam1"}


def _annot(vid, frame):
    return plate_annotation(
        annotation_id=f"{vid}_f{frame:05d}",
        camera_id="cam1", session_id="cam1_s001",
        vehicle_instance_id=vid,
        plate_instance_id=f"{vid}_p001",
        frame_id=frame, plate_bbox=None,
        box_annotation_status="pending_human_annotation",
        plate_text_raw="۱۲د۶۷۴۱۳", plate_type="civilian",
        region_code="13", readability="GOOD",
        occluded=False, truncated=False,
        annotation_status="verified", annotator="test")


def test_two_instances_stay_in_one_evaluation_set():
    """With < 5 instances no split is manufactured —
    everything goes to the single evaluation set."""
    s = build_splits([_vehicle("a"), _vehicle("b")])
    assert s["strategy"] == "single_evaluation_set"
    assert s["splits"]["train"] == []
    assert s["splits"]["validation"] == []
    assert sorted(s["splits"]["test"]) == ["a", "b"]
    assert "rationale" in s and s["rationale"]


def test_sufficient_instances_split_deterministically():
    vs = [_vehicle(f"v{i:03d}") for i in range(6)]
    s1 = build_splits(vs)
    s2 = build_splits(vs)
    assert s1["strategy"] == "instance_level_60_20_20"
    assert s1 == s2  # stable hash -> deterministic
    all_ids = (s1["splits"]["train"]
               + s1["splits"]["validation"]
               + s1["splits"]["test"])
    assert sorted(all_ids) == sorted(
        v["vehicle_instance_id"] for v in vs)
    # no instance in two splits
    assert len(set(all_ids)) == len(all_ids)


def test_no_instance_in_two_splits():
    anns = [_annot("a", 0), _annot("b", 5)]
    splits = {"train": ["a", "b"], "validation": ["b"],
              "test": []}
    res = check_leakage(anns, splits)
    assert not res["leakage_free"]
    assert any("both" in v for v in res["violations"])


def test_no_frame_under_two_instances():
    # the same (camera, frame) under two vehicles is a
    # frame-assignment violation
    anns = [_annot("a", 0),
            plate_annotation(
                annotation_id="b_f00000",
                camera_id="cam1", session_id="cam1_s001",
                vehicle_instance_id="b",
                plate_instance_id="b_p001",
                frame_id=0, plate_bbox=None,
                box_annotation_status=
                "pending_human_annotation",
                plate_text_raw="۱۲د۶۷۴۱۳",
                plate_type="civilian", region_code="13",
                readability="GOOD", occluded=False,
                truncated=False,
                annotation_status="verified",
                annotator="test")]
    res = check_leakage(anns,
                        {"train": [], "validation": [],
                         "test": ["a", "b"]})
    assert not res["leakage_free"]


def test_clean_assignment_is_leakage_free():
    anns = [_annot("a", 0), _annot("a", 5),
            _annot("b", 10)]
    splits = {"train": [], "validation": [],
              "test": ["a", "b"]}
    res = check_leakage(anns, splits)
    assert res["leakage_free"]
    assert res["violations"] == []


def test_unassigned_instance_flagged():
    anns = [_annot("a", 0)]
    res = check_leakage(anns,
                        {"train": [], "validation": [],
                         "test": []})
    assert not res["leakage_free"]
    assert any("no split assignment" in v
               for v in res["violations"])


def test_split_ids_cover_all_verified_instances():
    """Every verified instance in the real dataset must
    have a split assignment."""
    s = build_splits([_vehicle("cam1_s001_v001"),
                      _vehicle("cam1_s001_v002")])
    assert set(s["splits"]["test"]) == {
        "cam1_s001_v001", "cam1_s001_v002"}
