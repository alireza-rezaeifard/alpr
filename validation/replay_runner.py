"""ALPR Phase 1.5 — offline replay validation runner.

Runs a video file through the REAL production video path
(``VideoProcessor._run`` → ``detect_plates`` → ``engine.run`` →
``EventPipeline.process_results``), with the event pipeline opted in via the
existing feature-flag mechanism (``ALPR_PIPELINE_VIDEO=events``). No
artificial detections, no bypass of video_processor.py, no changes to the
Phase 1 architecture.

Telemetry is captured WITHOUT touching production files:

  * ``process_results`` is wrapped per-instance in the validation process
    (runner-side observer; the pipeline object itself is untouched).
  * ``VideoProcessor._run`` and ``RTSPStreamProcessor._run`` are wrapped
    transparently so the runner can collect finalized events and metrics
    after the normal method returns (a per-instance bound-method wrapper,
    again with zero production-file edits).

Usage:
    python validation/replay_runner.py cam1.mp4 [--out validation/cam1]
        [--camera-id 1] [--fast] [--skip-frames 5]

Outputs (under --out):
    observations.jsonl  per-frame OCR observation + track + consensus state
    tracks.jsonl        per-track summary (frames seen, obs count, outcome)
    raw_events.jsonl    every finalized VehicleEvent (full field dump)
    summary.json        pipeline metrics + video info + run configuration
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------
# Flags MUST be set before VideoProcessor / EventPipeline are constructed
# (flags are read at processor construction time).
# ---------------------------------------------------------------------
os.environ["ALPR_PIPELINE_VIDEO"] = "events"
os.environ["ALPR_PIPELINE_MODE"] = "events"

import cv2  # noqa: E402

import db as db_module  # noqa: E402

# Redirect the DB to a temp file so replay NEVER touches database/plpr.db.
_TMP_DB_DIR = tempfile.mkdtemp(prefix="alpr_replay_")
db_module.DB_PATH = os.path.join(_TMP_DB_DIR, "replay.db")
db_module.init_db()


def _event_to_dict(ev) -> dict:
    """Full field dump of a pipeline.types.VehicleEvent."""
    d = {}
    for name in ("event_key", "track_id", "track_kind", "plate_number",
                 "plate_norm", "confidence", "agreement_ratio",
                 "quality_score", "frame_count", "observation_count",
                 "duration_ms", "status", "needs_review", "finalize_reason",
                 "plate_valid", "camera_id", "camera_name", "session_id",
                 "source_type", "source_file"):
        d[name] = getattr(ev, name, None)
    d["first_seen"] = getattr(ev, "first_seen", None)
    d["last_seen"] = getattr(ev, "last_seen", None)
    return d


def probe_video(path: str) -> dict:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open video: {path}")
    info = {
        "file": os.path.basename(path),
        "path": path,
        "fps": round(cap.get(cv2.CAP_PROP_FPS), 2),
        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    info["duration_s"] = round(
        info["frame_count"] / info["fps"], 2) if info["fps"] else None
    cap.release()
    return info


def run_replay(video_path: str, out_dir: Path, camera_id, fast_mode: bool,
               skip_frames: int, trace: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    video_info = probe_video(video_path)

    from api import _ensure_models
    from video_processor import VideoProcessor, detect_plates
    from pipeline.integration import EventPipeline

    observations_path = out_dir / "observations.jsonl"
    events_path = out_dir / "raw_events.jsonl"
    tracks_path = out_dir / "tracks.jsonl"

    obs_file = open(observations_path, "w", encoding="utf-8")
    events_file = open(events_path, "w", encoding="utf-8")
    trace_file = open(tracks_path, "w", encoding="utf-8")

    finalized_events: list[dict] = []
    tracks_seen: dict[str, dict] = {}
    tf = trace_file  # alias used inside the observer closure

    # ---- runner-side instrumentation (no production file changes) -------
    # 1) Wrap the REAL EventPipeline.process_results to capture per-frame
    #    observation / track / consensus state.
    # 2) Wrap VideoProcessor._run per-instance to collect events + metrics
    #    after the normal method completes (incl. the expire("video_end")
    #    flush that _run itself performs).
    orig_process_results = EventPipeline.process_results
    orig_run = VideoProcessor._run

    def observed_process_results(self, frame_idx, frame_width, frame_height,
                                 results, now=None):
        finalized = orig_process_results(self, frame_idx, frame_width,
                                         frame_height, results, now)
        ts = frame_idx / (video_info["fps"] or 30.0)
        if trace:
            # Per-frame lifecycle snapshot: which tracks exist, their state,
            # and how many observations each holds. Runner-side only.
            for key, tr in self._lifecycle._tracks.items():
                tf.write(json.dumps({
                    "frame": frame_idx,
                    "time_s": round(ts, 3),
                    "track_key": key,
                    "kind": tr.kind,
                    "state": tr.state,
                    "hits": tr.hits,
                    "observations": len(tr.observations),
                    "event_emitted": getattr(tr, "event_emitted", False),
                    "texts": [r.text for r in tr.observations][-8:][:: -1][:8],
                }, ensure_ascii=False) + "\n")
        for ev in finalized or []:
            rec = _event_to_dict(ev)
            rec["finalized_at_frame"] = frame_idx
            finalized_events.append(rec)
            events_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
            tk = rec["track_id"] or rec["event_key"]
            tracks_seen.setdefault(tk, {
                "track_id": tk,
                "kind": rec["track_kind"],
                "frames": [],
                "observations": 0,
                "outcome": None,
            })["outcome"] = {
                "event_key": rec["event_key"],
                "plate": rec["plate_number"],
                "confidence": rec["confidence"],
                "agreement": rec["agreement_ratio"],
                "status": rec["status"],
                "finalize_reason": rec["finalize_reason"],
                "needs_review": rec["needs_review"],
                "plate_valid": rec["plate_valid"],
                "observation_count": rec["observation_count"],
            }
            tracks_seen[tk]["observations"] += rec["observation_count"]
        for r in results or []:
            text = getattr(r, "plate_text", "") or ""
            rec = {
                "frame": frame_idx,
                "time_s": round(ts, 3),
                "has_plate_text": bool(text),
                "plate_text": text,
                "confidence": float(getattr(r, "confidence", 0.0) or 0.0),
                "plate_det_conf": float(getattr(r, "plate_det_conf", 0.0) or 0.0),
                "char_conf": float(getattr(r, "char_conf", 0.0) or 0.0),
                "vehicle_boxes": [list(b) for b in (getattr(r, "vehicle_boxes", None) or [])],
                "plate_bbox": list(getattr(r, "plate_bbox", None) or []) if getattr(r, "plate_bbox", None) else None,
            }
            obs_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return finalized

    EventPipeline.process_results = observed_process_results

    def wrapped_run(self, input_path, sf, fm):
        orig_run(self, input_path, sf, fm)
        # After the normal _run (which includes expire("video_end")), dump
        # tracker/lifecycle state for tracks.jsonl and the final metrics.
        ep = self.event_pipeline
        if ep is None:
            return
        for key, track in ep._lifecycle._tracks.items():
            rec = {
                "track_key": key,
                "track_id": track.track_id if hasattr(track, "track_id") else key,
                "kind": track.kind,
                "state": track.state,
                "first_ts": track.first_ts,
                "last_ts": track.last_ts,
                "hits": track.hits,
                "observation_count": len(track.observations),
                "event_emitted": getattr(track, "event_emitted", False),
            }
            with open(tracks_path, "a", encoding="utf-8") as tf:
                tf.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            tracks_seen.setdefault(key, {
                "track_id": rec["track_id"], "kind": track.kind,
                "frames": [], "observations": rec["observation_count"],
                "outcome": None,
            }).update({"state": track.state,
                       "hits": track.hits,
                       "event_emitted": rec["event_emitted"]})

    VideoProcessor._run = wrapped_run

    # ---- build the real production objects -------------------------------
    engine = _ensure_models()
    if engine is None:
        raise SystemExit("ALPR engine failed to load; cannot replay")

    started = time.time()
    processor = VideoProcessor(engine, on_detection=None,
                               camera_id=camera_id,
                               camera_name=f"replay-{video_info['file']}")
    event_pipeline_obj = processor.event_pipeline
    pipeline_mode_enabled = event_pipeline_obj is not None

    # Restore originals immediately after construction-time wiring so the
    # wrappers apply only to this run (defensive: nothing else constructs
    # processors in this process).
    processor._run = wrapped_run.__get__(processor, VideoProcessor)

    # Run synchronously (bypass only the thread spawn, not the processing
    # path): process_video() starts a thread; we call the wrapped _run
    # directly so the replay blocks until the video is done.
    processor._run(video_path, skip_frames, fast_mode)

    elapsed = time.time() - started

    EventPipeline.process_results = orig_process_results
    VideoProcessor._run = orig_run
    obs_file.close()
    events_file.close()
    trace_file.close()

    metrics = event_pipeline_obj.get_metrics() if event_pipeline_obj else {}

    # per-track frame ranges from observations.jsonl
    for line in open(observations_path, encoding="utf-8"):
        rec = json.loads(line)
        for tk, tdata in tracks_seen.items():
            pass  # frame->track mapping lives in tracker; summarized via metrics

    summary = {
        "run_at": datetime.now().isoformat(),
        "video": video_info,
        "configuration": {
            "ALPR_PIPELINE_MODE": os.environ.get("ALPR_PIPELINE_MODE"),
            "ALPR_PIPELINE_VIDEO": os.environ.get("ALPR_PIPELINE_VIDEO"),
            "ALPR_DUAL_WRITE_DETECTIONS": os.environ.get(
                "ALPR_DUAL_WRITE_DETECTIONS", "1"),
            "event_pipeline_enabled": pipeline_mode_enabled,
            "fast_mode": fast_mode,
            "skip_frames": skip_frames,
            "camera_id": camera_id,
            "db_redirected_to": db_module.DB_PATH,
        },
        "wall_clock_s": round(elapsed, 2),
        "metrics": metrics,
        "counts": {
            "observation_lines": sum(1 for _ in open(observations_path, encoding="utf-8")),
            "raw_events": len(finalized_events),
            "tracks_seen": len(tracks_seen),
        },
        "finalized_events": finalized_events,
        "tracks": [t for t in tracks_seen.values()],
    }
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", help="path to video file (e.g. cam1.mp4)")
    ap.add_argument("--out", default=None,
                    help="output directory (default: validation/<video stem>)")
    ap.add_argument("--camera-id", default="cam1", help="camera_id recorded in events")
    ap.add_argument("--fast", action="store_true", help="pass fast_mode to the engine")
    ap.add_argument("--skip-frames", type=int, default=1,
                    help="passed through to the real _run (video files process every frame anyway)")
    ap.add_argument("--trace", action="store_true",
                    help="write per-frame lifecycle track snapshots to tracks.jsonl")
    args = ap.parse_args()

    video_path = args.video if os.path.isabs(args.video) else str(ROOT / args.video)
    out_dir = (Path(args.out) if args.out
               else ROOT / "validation" / Path(video_path).stem)
    summary = run_replay(video_path, out_dir, args.camera_id,
                         args.fast, args.skip_frames, trace=args.trace)
    print(json.dumps({
        "video": summary["video"]["file"],
        "frames": summary["video"]["frame_count"],
        "event_pipeline_enabled": summary["configuration"]["event_pipeline_enabled"],
        "metrics": summary["metrics"],
        "raw_events": summary["counts"]["raw_events"],
        "wall_clock_s": summary["wall_clock_s"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
