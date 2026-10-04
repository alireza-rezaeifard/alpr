"""ALPR Phase 1.5 — offline replay analysis.

Reads the JSONL outputs produced by ``replay_runner.py`` and produces:

  * headline metrics (OCR emissions, tracks created, final events, ratios),
  * duplicate classification:
      Case A — same track -> same event (expected, OK)
      Case B — same plate_norm on 2+ events with close timestamps
               (possible duplicate; reported, never auto-fixed)
      Case C — different tracks with overlapping lifetimes but conflicting
               plate candidates (possible false merge; reported only)
  * low-confidence / needs-review listing.

Usage:
    python validation/analyze_events.py validation/cam1
    python validation/analyze_events.py validation/cam1 validation/cam2
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Two events on the same plate_norm are "close" when their wall-clock
# windows are nearer than this many seconds (report-only heuristic).
CASE_B_WINDOW_S = 30.0


def _parse_iso(ts: str | None) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return 0.0


def analyze(out_dir: Path) -> dict:
    events = [json.loads(l) for l in open(out_dir / "raw_events.jsonl",
                                          encoding="utf-8")]
    summary = json.load(open(out_dir / "summary.json", encoding="utf-8"))
    metrics = summary["metrics"]
    video = summary["video"]

    n_events = len(events)
    accepted = metrics.get("observations_accepted", 0)
    tracks_created = metrics.get("tracks_created", 0)

    by_plate: dict[str, list[dict]] = {}
    for e in events:
        if e.get("plate_norm"):
            by_plate.setdefault(e["plate_norm"], []).append(e)

    case_a = 0          # confirmed same-track singletons (the expected path)
    case_b = []         # possible duplicates
    for plate, group in by_plate.items():
        if len(group) == 1:
            case_a += 1
            continue
        group = sorted(group, key=lambda e: _parse_iso(e["first_seen"]))
        for i in range(len(group) - 1):
            a, b = group[i], group[i + 1]
            gap = _parse_iso(b["first_seen"]) - _parse_iso(a["last_seen"])
            if 0 <= gap < CASE_B_WINDOW_S:
                case_b.append({
                    "plate_norm": plate,
                    "event_1": a["event_key"],
                    "event_2": b["event_key"],
                    "track_1": a["track_id"],
                    "track_2": b["track_id"],
                    "gap_s": round(gap, 2),
                    "conf_1": round(a["confidence"], 3),
                    "conf_2": round(b["confidence"], 3),
                })

    # Case C: events on different tracks whose [first_seen, last_seen]
    # windows overlap, with conflicting plate texts (report only).
    case_c = []
    for i in range(n_events):
        for j in range(i + 1, n_events):
            a, b = events[i], events[j]
            if a["track_id"] == b["track_id"]:
                continue
            a0, a1 = _parse_iso(a["first_seen"]), _parse_iso(a["last_seen"])
            b0, b1 = _parse_iso(b["first_seen"]), _parse_iso(b["last_seen"])
            overlap = min(a1, b1) - max(a0, b0)
            if overlap > 0 and a["plate_norm"] != b["plate_norm"]:
                case_c.append({
                    "event_1": a["event_key"], "plate_1": a["plate_number"],
                    "event_2": b["event_key"], "plate_2": b["plate_number"],
                    "overlap_s": round(overlap, 2),
                })

    # A plate-visibility segment in the observations that never produced an
    # event at all = possible false split / missed visit.
    import itertools
    obs_path = out_dir / "observations.jsonl"
    missed_segments = []
    if obs_path.exists():
        obs = [json.loads(l) for l in open(obs_path, encoding="utf-8")]
        wt = [o for o in obs if o.get("has_plate_text")]
        fps = video.get("fps") or 30.0
        covered = set()
        for e in events:
            fs, ls = _parse_iso(e["first_seen"]), _parse_iso(e["last_seen"])
            covered.add((round(fs), round(ls)))
        # group consecutive OCR frames into segments
        seg = []
        segments = []
        for o in wt:
            if seg and o["frame"] - seg[-1]["frame"] > int(fps * 1.0):
                segments.append(seg)
                seg = []
            seg.append(o)
        if seg:
            segments.append(seg)
        for s in segments:
            t0 = s[0]["time_s"]
            t1 = s[-1]["time_s"]
            has_event = any(
                abs(_parse_iso(e["first_seen"]) - (summary["run_at"] and 0)) >= 0
                for e in events  # placeholder; refined below via time overlap
            )
            # time_s -> approximate wall-clock overlap with event windows is
            # not directly available (replay runs faster than real time), so
            # instead flag segments longer than 2s with no event whose plate
            # appears in any event.
            texts = {o["plate_text"] for o in s}
            matched = any(e["plate_number"] in texts for e in events)
            if not matched and (t1 - t0) >= 2.0:
                missed_segments.append({
                    "frames": f"{s[0]['frame']}-{s[-1]['frame']}",
                    "duration_s": round(t1 - t0, 1),
                    "dominant_text": max((o["plate_text"] for o in s),
                                         key=lambda t: sum(
                                             1 for o in s if o["plate_text"] == t)),
                })

    report = {
        "video": video,
        "metrics": {
            "frames_processed": metrics.get("frames_processed", 0),
            "ocr_observations": metrics.get("ocr_observations", 0),
            "observations_accepted": accepted,
            "observations_rejected": metrics.get("observations_rejected", 0),
            "tracks_created": tracks_created,
            "tracks_rejected_new": metrics.get("tracks_rejected_new", 0),
            "tracks_expired": metrics.get("tracks_expired", 0),
            "final_events": n_events,
            "duplicate_finalizations_suppressed":
                metrics.get("duplicate_finalizations_suppressed", 0),
            "finalization_reasons": metrics.get("finalization_reasons", {}),
            "detections_per_event": round(
                tracks_created / n_events, 2) if n_events else None,
            "OCR_per_event": round(
                accepted / n_events, 2) if n_events else None,
            "tracks_per_event": round(
                tracks_created / n_events, 2) if n_events else None,
            "needs_review_events": sum(1 for e in events if e.get("needs_review")),
            "invalid_plate_events": sum(1 for e in events if not e.get("plate_valid")),
        },
        "case_a_same_track_singletons": case_a,
        "case_b_possible_duplicates": case_b,
        "case_c_possible_false_merges": case_c,
        "possible_false_splits": missed_segments,
        "events": [
            {
                "event_id": e["event_key"],
                "camera_id": e.get("camera_id"),
                "track_id": e["track_id"],
                "plate": e["plate_number"],
                "confidence": round(e["confidence"], 3),
                "agreement": round(e["agreement_ratio"], 3),
                "observation_count": e["observation_count"],
                "finalization_reason": e["finalize_reason"],
                "first_seen": e["first_seen"],
                "last_seen": e["last_seen"],
                "status": e["status"],
                "needs_review": e["needs_review"],
                "plate_valid": e["plate_valid"],
            }
            for e in events
        ],
    }
    out = out_dir / "analysis.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


def print_report(r: dict) -> None:
    m = r["metrics"]
    print(f"== {r['video']['file']} ==")
    for k in ("frames_processed", "ocr_observations", "observations_accepted",
              "observations_rejected", "tracks_created", "tracks_rejected_new",
              "final_events", "duplicate_finalizations_suppressed",
              "detections_per_event", "OCR_per_event", "tracks_per_event",
              "needs_review_events", "invalid_plate_events"):
        print(f"  {k}: {m.get(k)}")
    print(f"  finalization_reasons: {m.get('finalization_reasons')}")
    print(f"  Case A (same track -> single event, OK): {r['case_a_same_track_singletons']}")
    print(f"  Case B (possible duplicates): {len(r['case_b_possible_duplicates'])}")
    for b in r["case_b_possible_duplicates"]:
        print("   ", json.dumps(b, ensure_ascii=False))
    print(f"  Case C (possible false merges): {len(r['case_c_possible_false_merges'])}")
    for c in r["case_c_possible_false_merges"]:
        print("   ", json.dumps(c, ensure_ascii=False))
    print(f"  Possible false splits (OCR segment, no event): "
          f"{len(r['possible_false_splits'])}")
    for s in r["possible_false_splits"]:
        print("   ", json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for arg in sys.argv[1:]:
        r = analyze(Path(arg))
        print_report(r)
        print()
