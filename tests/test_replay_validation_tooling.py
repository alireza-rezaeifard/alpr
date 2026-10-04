"""Phase 1.5 — replay validation smoke tests.

These tests exercise ONLY the validation tooling (analyze_events
classification and replay_runner helpers), never the production pipeline.
No model weights are loaded and no real video is required.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "validation"))

from analyze_events import analyze, print_report  # noqa: E402


def _write_outputs(out_dir: Path, events, metrics_extra=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "raw_events.jsonl", "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    summary = {
        "run_at": "2026-09-30T09:00:00",
        "video": {"file": "fake.mp4", "fps": 30.0, "frame_count": 300,
                  "width": 1920, "height": 1080, "duration_s": 10.0},
        "configuration": {"event_pipeline_enabled": True},
        "metrics": {
            "frames_processed": 300,
            "ocr_observations": 50,
            "observations_accepted": 50,
            "observations_rejected": 0,
            "tracks_created": 3,
            "tracks_rejected_new": 0,
            "tracks_expired": 2,
            "duplicate_finalizations_suppressed": 0,
            "finalization_reasons": {"consensus_confirm": len(events)},
        },
        "counts": {"observation_lines": 50, "raw_events": len(events)},
    }
    if metrics_extra:
        summary["metrics"].update(metrics_extra)
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False)


def _event(key, track, plate, first, last, **kw):
    base = {
        "event_key": key, "track_id": track, "track_kind": "vehicle",
        "plate_number": plate, "plate_norm": plate,
        "confidence": kw.get("confidence", 0.9),
        "agreement_ratio": kw.get("agreement", 0.9),
        "quality_score": 0.5, "frame_count": 10, "observation_count": 10,
        "duration_ms": 500, "status": "confirmed", "needs_review": False,
        "finalize_reason": "consensus_confirm", "plate_valid": True,
        "camera_id": "camX", "camera_name": None, "session_id": None,
        "source_type": "video", "source_file": None,
        "first_seen": first, "last_seen": last,
    }
    base.update(kw)
    return base


def test_case_a_single_event_per_track(tmp_path):
    out = tmp_path / "a"
    _write_outputs(out, [
        _event("camX:0:1", "camX:0:1", "12d67413",
               "2026-09-30T09:00:00", "2026-09-30T09:00:05"),
    ])
    r = analyze(out)
    assert r["case_a_same_track_singletons"] == 1
    assert r["case_b_possible_duplicates"] == []
    assert r["case_c_possible_false_merges"] == []
    assert r["metrics"]["final_events"] == 1
    assert r["metrics"]["OCR_per_event"] == 50.0


def test_case_b_same_plate_two_tracks_close(tmp_path):
    out = tmp_path / "b"
    _write_outputs(out, [
        _event("camX:0:1", "camX:0:1", "28y68923",
               "2026-09-30T09:00:00", "2026-09-30T09:00:05"),
        _event("camX:0:3", "camX:0:3", "28y68923",
               "2026-09-30T09:00:20", "2026-09-30T09:00:25"),
    ])
    r = analyze(out)
    assert r["case_b_possible_duplicates"], "expected Case B pair"
    pair = r["case_b_possible_duplicates"][0]
    assert pair["event_1"] == "camX:0:1"
    assert pair["event_2"] == "camX:0:3"
    assert 0 <= pair["gap_s"] < 30.0


def test_case_b_far_apart_not_flagged(tmp_path):
    out = tmp_path / "b2"
    _write_outputs(out, [
        _event("camX:0:1", "camX:0:1", "28y68923",
               "2026-09-30T09:00:00", "2026-09-30T09:00:05"),
        _event("camX:0:3", "camX:0:3", "28y68923",
               "2026-09-30T09:20:00", "2026-09-30T09:20:05"),
    ])
    r = analyze(out)
    assert r["case_b_possible_duplicates"] == []


def test_case_c_overlapping_tracks_different_plates(tmp_path):
    out = tmp_path / "c"
    _write_outputs(out, [
        _event("camX:0:1", "camX:0:1", "aaa11111",
               "2026-09-30T09:00:00", "2026-09-30T09:00:10"),
        _event("camX:0:2", "camX:0:2", "bbb22222",
               "2026-09-30T09:00:05", "2026-09-30T09:00:15"),
    ])
    r = analyze(out)
    assert r["case_c_possible_false_merges"], "expected Case C pair"
    c = r["case_c_possible_false_merges"][0]
    assert c["overlap_s"] == 5.0


def test_metrics_ratios_present(tmp_path):
    out = tmp_path / "m"
    _write_outputs(out, [
        _event("camX:0:1", "camX:0:1", "12d67413",
               "2026-09-30T09:00:00", "2026-09-30T09:00:05"),
    ], metrics_extra={"tracks_created": 4, "observations_accepted": 20})
    r = analyze(out)
    assert r["metrics"]["detections_per_event"] == 4.0
    assert r["metrics"]["OCR_per_event"] == 20.0


def test_print_report_is_plain_text(capsys, tmp_path):
    out = tmp_path / "p"
    _write_outputs(out, [
        _event("camX:0:1", "camX:0:1", "12d67413",
               "2026-09-30T09:00:00", "2026-09-30T09:00:05"),
    ])
    r = analyze(out)
    print_report(r)
    captured = capsys.readouterr()
    assert "final_events" in captured.out
