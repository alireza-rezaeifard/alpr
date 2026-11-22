"""
routers/detection.py
Image / video / RTSP detection API.

The detection handlers and the proven `video_processor.py` pipeline (YOLOv8
detector + DTRB recognizer) are **preserved** from the original `api.py`
implementation and only *wrapped* with the security perimeter here (design.md:
"Detection Component (preserved + hooked)").

Authorization & licensing (design "Backend Request Pipeline"):
    * Every detection endpoint (image — Req 8, video — Req 9, RTSP — Req 10) is
      guarded by ``current_user()`` + ``require_permission("run_detection")``
      via the router-level dependency, so an unauthenticated or under-privileged
      request never reaches a handler (Requirements 8.1, 9.1, 10.1, 2.2, 2.3).
    * The *run/start* endpoints (image detect, video start, RTSP start) also
      depend on ``require_license()`` so detection runs require a valid,
      unexpired license (Requirement 3.3, 3.4). Status / stop / preview
      endpoints are control operations and are not license-gated.

Enforcement preserved from the original handlers:
    * Video / RTSP ``skip_frames`` is constrained to ``1..1000`` by the form
      field bounds; out-of-range values yield a validation error (Req 9.6).
    * An undecodable uploaded image yields a ``validation_error`` (Req 8.2).
    * Per-image persistence is atomic: if storing a detection record raises, the
      exception propagates and the whole request fails (Req 8.4).
    * Unknown video / RTSP task ids return ``404 not_found`` (Req 9.5, 10.2).

Shared process state (the lazily-loaded models, the background-task registry,
and the output directory) lives on the ``api`` module so it is shared with the
``CameraManager``. The handlers resolve it lazily at call time (``import api``
inside each handler) which keeps a single source of truth and avoids an
import-time cycle.

Requirements: 8.1, 8.2, 8.4, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3
"""
from __future__ import annotations

import base64
import logging
import os
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse

from auth.dependencies import (
    AuthenticatedUser,
    current_user,
    require_license,
    require_permission,
)
from db import end_session, save_detection, start_session
from schemas import ErrorCode

# Router-level guard: authentication + the run-detection permission apply to
# every endpoint below (Requirements 8.1, 9.1, 10.1, 2.2, 2.3). ``require_permission``
# itself depends on ``current_user``, so authentication always runs first.
router = APIRouter(
    prefix="/api/detect",
    tags=["detection"],
    dependencies=[Depends(require_permission("run_detection"))],
)


# ---------------------------------------------------------------------------
# Error helpers — every error uses the { error, code } envelope
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# Bounded wait for a cancelled video worker to terminate and complete its
# permitted final flush (F-3). The wait is backed by the processor's own
# processing/status flags, not by arbitrary ordering sleeps.
_VIDEO_CANCEL_TIMEOUT_S = 10.0
_VIDEO_CANCEL_POLL_S = 0.1


def _envelope(message: str, code: ErrorCode) -> dict:
    return {"error": message, "code": code.value}


def _not_found(message: str = "Task not found") -> JSONResponse:
    return JSONResponse(_envelope(message, ErrorCode.NOT_FOUND), status_code=404)


def _close_video_session(session_id, state, terminal_status):
    """Close one uploaded-video session idempotently with terminal status."""
    plate_log = state.get("plate_log", [])
    unique = len(set(e["dtrb_text"] for e in plate_log))
    end_session(
        session_id, state.get("total_frames", 0), len(plate_log), unique,
        status=terminal_status,
    )


def _await_processor_termination(vp, timeout_s: float = _VIDEO_CANCEL_TIMEOUT_S,
                                 interval_s: float = _VIDEO_CANCEL_POLL_S) -> bool:
    """Wait until a VideoProcessor worker has terminated and completed its
    permitted final flush.

    The worker sets ``processing=False`` (under its lock) only after the
    end-of-video ``expire()`` flush and the terminal status update, so
    ``not processing`` + terminal status is the reliable shutdown-complete
    signal (F-3). Returns False on timeout: the shutdown is INCOMPLETE and
    callers must not close the session or discard the processor.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = vp.get_state()
        status = str(state.get("status", ""))
        if not state.get("processing", False) and (
                status in ("done", "error") or status.startswith("error:")):
            return True
        threading.Event().wait(interval_s)
    return False


def _finalize_video_session(entry: dict, state: dict, close_video_session
                            ) -> None:
    """Post-loop session triage for one uploaded-video task (F-3).

    An incomplete shutdown (cancellation wait timed out) deliberately leaves
    the session open and keeps the processor reference: a timeout never
    proves a safe shutdown. Otherwise the terminal status determines the
    session's closing status.
    """
    if entry.get("stop_incomplete"):
        return
    if state["status"] == "done":
        close_video_session(state, "done")
    elif state["status"].startswith("error"):
        # Terminal retention/shutdown failure: close the managed session so
        # it cannot remain running forever. The task state retains the
        # diagnostic reason (for example "error: retention blocked").
        close_video_session(state, "error")
    else:
        close_video_session(state, "cancelled")


def _cancel_video_task(task_id: str, vp,
                       timeout_s: float = _VIDEO_CANCEL_TIMEOUT_S) -> None:
    """Cancel a video task without racing its final flush (F-3).

    Signals cancellation, requests processor stop, then waits for verified
    worker termination. On timeout the session is deliberately LEFT OPEN and
    the processor reference retained: a timeout never proves a safe shutdown,
    and the incomplete state is surfaced through the task entry so a caller
    can observe and retry it.
    """
    import api

    vp.stop()
    completed = _await_processor_termination(vp, timeout_s=timeout_s)
    state = vp.get_state()
    with api._tasks_lock:
        entry = api._tasks.get(task_id)
        if entry is not None:
            # Preserve user-facing cancellation semantics.
            entry["status"] = "cancelled"
            if not completed:
                entry["stop_incomplete"] = True
    if not completed:
        logger.warning(
            "video task %s cancellation timed out: worker still active; "
            "session left open and processor retained for a later safe retry",
            task_id)
    return


def _stop_rtsp_task_entry(entry: dict) -> dict:
    """Stop an RTSP processor; close its session only after verified
    shutdown and final flush (F-2).

    Returns a status dict. When shutdown is incomplete, the session stays
    open, the processor reference is retained in the entry, and the
    incomplete state is observable to the caller so a later stop can retry.
    """
    processor = entry.get("processor")
    if not processor:
        return {"status": "stopped", "shutdown_completed": True}
    processor.stop()
    if not processor.shutdown_completed():
        # A timeout is not proof of termination: do not claim a flush that
        # never ran, do not close the session, do not discard the processor.
        logger.warning(
            "RTSP stop incomplete; session kept open and processor retained "
            "for a later safe retry")
        return {"status": "stop_incomplete", "shutdown_completed": False}
    state = processor.get_state()
    if entry.get("session_id"):
        history = state.get("history", [])
        end_session(
            entry["session_id"], 0, len(history),
            len({p["dtrb_text"] for p in history}),
        )
    return {"status": "stopped", "shutdown_completed": True}


# ---------------------------------------------------------------------------
# Image detection — POST /api/detect/image (Req 8.1, 8.2, 8.4, 8.5)
# ---------------------------------------------------------------------------
@router.post("/image", dependencies=[Depends(require_license())])
async def detect_image(file: UploadFile = File(...)):
    """Run plate detection on a single uploaded image.

    Decodes the image, runs the preserved detection pipeline, persists one
    detection per recognized plate under a fresh ``image`` session, and returns
    the annotated image plus the recognized plates. An undecodable image is a
    validation error (Req 8.2); a persistence failure aborts the whole request
    (Req 8.4).
    """
    import api

    engine = api._ensure_models()
    from video_processor import format_plate_persian, process_frame

    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return JSONResponse(
            _envelope("Invalid image: could not be decoded", ErrorCode.VALIDATION_ERROR),
            status_code=400,
        )

    annotated, plates, alpr_results = process_frame(img, engine)

    # Validate plates and derive metadata
    from plate_validator import validate_iranian_plate
    from video_processor import best_plate_text

    # Save to session
    sid = start_session("image", file.filename or "upload")
    plates_out = []
    for idx, plate in enumerate(plates):
        # alpr_results contains AlprResult objects; extract plate_text as dtrb_text
        plate_text = plate["plate_text"]
        plate_conf = float(plate["confidence"])

        # Try validation with plate text directly
        dtrb_text, best_conf = best_plate_text(
            plate_text, plate_conf,
            plate_text, plate_conf
        )

        persian = format_plate_persian(dtrb_text)
        # Convert numpy types to native Python for JSON serialization
        bbox = tuple(int(x) for x in plate["bbox"])

        # Validate and derive metadata
        validation = validate_iranian_plate(dtrb_text, best_conf)
        metadata_dict = None
        if validation.is_valid and validation.metadata is not None:
            md = validation.metadata
            metadata_dict = {
                "classified": md.classified,
                "category": md.category,
                "category_display": md.category_display,
                "color_scheme": md.color_scheme,
                "region_code": md.region_code,
                "region_name": md.region_name,
                "special_note": md.special_note,
            }

        plates_out.append({
            "plate_dtrb": dtrb_text,
            "plate_persian": persian,
            "confidence": best_conf,
            "bbox": bbox,
            "metadata": metadata_dict,
            "car_color": plate.get("car_color"),
            "car_type": plate.get("car_type"),
            "city": plate.get("city"),
        })
        # Atomic per-image persistence: a failure here propagates and fails the
        # whole request (Req 8.4).
        save_detection(sid, "image", dtrb_text, persian, best_conf, file.filename)
    end_session(sid, 0, len(plates), len(set(p["plate_dtrb"] for p in plates_out)))

    # Encode annotated image to base64
    _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64 = base64.b64encode(buf).decode("utf-8")

    return {
        "session_id": sid,
        "annotated": f"data:image/jpeg;base64,{b64}",
        "plates": plates_out,
    }


# ---------------------------------------------------------------------------
# Video detection — POST /api/detect/video (Req 9.1, 9.4, 9.6)
# ---------------------------------------------------------------------------
@router.post("/video", dependencies=[Depends(require_license())])
async def detect_video(
    file: UploadFile = File(...),
    skip_frames: int = Form(30, ge=1, le=1000),
    fast_mode: bool = Form(False),
):
    """Start background video processing and return its task and session ids.

    ``skip_frames`` is constrained to ``1..1000``; an out-of-range value is
    rejected as a validation error before the handler runs (Req 9.6). On
    completion the originating session is closed with final counts (Req 9.4).
    """
    import api

    engine = api._ensure_models()
    from video_processor import VideoProcessor, format_plate_persian

    # Save uploaded file
    ext = Path(file.filename or "video.mp4").suffix or ".mp4"
    input_path = os.path.join(api.OUTPUT_DIR, f"input_{uuid.uuid4().hex}{ext}")
    contents = await file.read()
    with open(input_path, "wb") as f:
        f.write(contents)

    task_id = uuid.uuid4().hex
    session_id = start_session("video", file.filename)

    def run_video(task_id, sid, inp, skip, fast):
        def on_det(src, text, conf, sf, frame, ftime):
            save_detection(sid, src, text, format_plate_persian(text), conf, sf, frame, ftime)
        # Uploaded video is an unmanaged source: no synthetic camera_id is
        # invented. The session id scopes the event key; source_file supplies
        # display context.
        vp = VideoProcessor(engine, on_detection=on_det,
                            session_id=sid, source_file=os.path.basename(inp))
        with api._tasks_lock:
            api._tasks[task_id]["processor"] = vp
        vp.process_video(inp, skip_frames=skip, fast_mode=fast)
        session_closed = False

        def close_video_session(state, terminal_status):
            nonlocal session_closed
            if session_closed:
                return
            _close_video_session(sid, state, terminal_status)
            session_closed = True

        # Wait for completion
        state = vp.get_state()
        while True:
            # Check if cancelled externally
            with api._tasks_lock:
                if api._tasks.get(task_id, {}).get("status") == "cancelled":
                    _cancel_video_task(task_id, vp)
                    state = vp.get_state()
                    break
            state = vp.get_state()
            with api._tasks_lock:
                if task_id in api._tasks:
                    api._tasks[task_id].update(state)
            if state["status"] in ("done", "error") or state["status"].startswith("error:"):
                break
            threading.Event().wait(0.5)
        with api._tasks_lock:
            entry = api._tasks.get(task_id) or {}
        _finalize_video_session(entry, state, close_video_session)

    with api._tasks_lock:
        api._tasks[task_id] = {"status": "queued", "session_id": session_id}

    threading.Thread(
        target=run_video,
        args=(task_id, session_id, input_path, skip_frames, fast_mode),
        daemon=True,
    ).start()

    return JSONResponse({"task_id": task_id, "session_id": session_id})


@router.get("/video/{task_id}")
def video_status(task_id: str):
    """Return current processing state for a video task (Req 9.2).

    Unknown task ids return ``404 not_found`` (Req 9.5).
    """
    import api

    with api._tasks_lock:
        state = api._tasks.get(task_id)
    if state is None:
        return _not_found()

    # Encode the latest annotated frame for live preview
    annotated_b64 = None
    current_frame = state.get("current_frame")
    if current_frame is not None:
        try:
            _, buf = cv2.imencode(".jpg", current_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            annotated_b64 = f"data:image/jpeg;base64,{base64.b64encode(buf).decode('utf-8')}"
        except Exception:
            pass

    return {
        "status": state.get("status", "unknown"),
        "frame_idx": state.get("frame_idx", 0),
        "total_frames": state.get("total_frames", 0),
        "plate_log": state.get("plate_log", []),
        "live_detections": state.get("live_detections", []),
        "error": state.get("error"),
        "output_path": state.get("output_path"),
        "annotated": annotated_b64,
    }


@router.post("/video/{task_id}/stop")
def stop_video_task(task_id: str):
    """Cancel a running video task (Req 9.3). Unknown ids return 404 (Req 9.5)."""
    import api

    with api._tasks_lock:
        state = api._tasks.get(task_id)
    if state is None:
        return _not_found()
    processor = state.get("processor")
    if processor:
        processor.stop()
    with api._tasks_lock:
        api._tasks[task_id]["status"] = "cancelled"
    return {"status": "stopped"}


# ---------------------------------------------------------------------------
# RTSP detection — POST /api/detect/rtsp (Req 10.1, 10.2, 10.3)
# ---------------------------------------------------------------------------
@router.post("/rtsp", dependencies=[Depends(require_license())])
def detect_rtsp(
    url: str = Form(...),
    fast_mode: bool = Form(False),
    skip_frames: int = Form(15, ge=1, le=1000),
):
    """Start an RTSP stream detection task and return its task/session ids.

    ``skip_frames`` is constrained to ``1..1000`` (Req 9.6 applied to streams).
    """
    import api

    engine = api._ensure_models()
    from video_processor import RTSPStreamProcessor, format_plate_persian

    task_id = uuid.uuid4().hex
    session_id = start_session("rtsp", url)

    def on_det(src, text, conf, sf, frame, ftime):
        save_detection(session_id, src, text, format_plate_persian(text), conf, sf, frame, ftime)

    # Ad-hoc RTSP has no managed camera row; do not invent a camera_id. The
    # session id is the source-instance identity and the URL is the display
    # context.
    processor = RTSPStreamProcessor(engine, url,
                                     fast_mode=fast_mode, skip_frames=skip_frames,
                                     on_detection=on_det,
                                     session_id=session_id, source_file=url)
    processor.start()

    with api._tasks_lock:
        api._tasks[task_id] = {"processor": processor, "session_id": session_id, "status": "running", "url": url}

    return JSONResponse({"task_id": task_id, "session_id": session_id})


@router.get("/rtsp/{task_id}", dependencies=[])
def rtsp_status(task_id: str):
    """Return RTSP processor state with detection history (Req 10.2).

    Unknown task ids return ``404 not_found`` (Req 10.2).
    """
    import api
    from video_processor import RTSPStreamProcessor

    with api._tasks_lock:
        entry = api._tasks.get(task_id)
    if entry is None:
        return _not_found()
    processor: RTSPStreamProcessor = entry.get("processor")
    if processor is None:
        return {"status": "error", "error": "Processor not found"}
    state = processor.get_state()

    # Phase 1 (additive): bounded-cardinality pipeline metrics when the event
    # pipeline is enabled. Legacy clients ignore unknown keys.
    pipeline_metrics = None
    if getattr(processor, "event_pipeline", None) is not None:
        try:
            pipeline_metrics = processor.event_pipeline.get_metrics()
        except Exception:
            pipeline_metrics = None

    return {
        "status": state.get("status", "unknown"),
        "history": state.get("history", []),
        "live_detections": state.get("live_detections", []),
        "pipeline": pipeline_metrics,
    }


@router.get("/rtsp/{task_id}/frame", dependencies=[])
def rtsp_frame_only(task_id: str):
    """Lightweight endpoint: returns only the latest pre-encoded frame + status.

    Optimized for fast polling (~300ms). Frame is pre-encoded by the processor
    thread. Unknown task ids return ``404 not_found`` (Req 10.2).
    """
    import api

    with api._tasks_lock:
        entry = api._tasks.get(task_id)
    if entry is None:
        return _not_found()
    processor = entry.get("processor")
    if processor is None:
        return {"status": "error"}

    # Get pre-encoded JPEG and recent data directly
    with processor.lock:
        proc_status = processor.status
        jpeg_bytes = processor.latest_jpeg
        recent_live = processor.live_detections[-3:] if processor.live_detections else []
        recent_history = processor.plate_history[-5:] if processor.plate_history else []

    # Use pre-encoded JPEG — no encoding needed here
    annotated_b64 = None
    if jpeg_bytes is not None:
        annotated_b64 = f"data:image/jpeg;base64,{base64.b64encode(jpeg_bytes).decode('utf-8')}"

    return {
        "status": proc_status,
        "annotated": annotated_b64,
        "live_detections": list(recent_live),
        "history": list(recent_history),
    }


@router.get("/rtsp/{task_id}/mjpeg", dependencies=[])
async def rtsp_mjpeg_stream(task_id: str):
    """MJPEG stream endpoint for smooth real-time video in the browser/app.

    Streams annotated frames as multipart JPEG at ~10 FPS. Unknown task ids
    return ``404 not_found`` (Req 10.2).
    """
    import time as _time

    import api

    with api._tasks_lock:
        entry = api._tasks.get(task_id)
    if entry is None:
        return _not_found()
    processor = entry.get("processor")
    if processor is None:
        return JSONResponse(
            _envelope("Processor not found", ErrorCode.NOT_FOUND), status_code=404
        )

    def generate_frames():
        while True:
            try:
                with processor.lock:
                    proc_status = processor.status
                    jpeg_bytes = processor.latest_jpeg
                if proc_status.startswith("error") or proc_status in ("done", "stopped"):
                    break
                if jpeg_bytes is not None:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpeg_bytes)).encode() + b"\r\n\r\n"
                        + jpeg_bytes + b"\r\n"
                    )
                _time.sleep(0.04)  # ~25 FPS for smooth native playback
            except Exception:
                break

    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("/rtsp/{task_id}/stop")
def stop_rtsp_task(task_id: str):
    """Stop an RTSP task: close its session and stop the processor (Req 10.3).

    Unknown task ids return ``404 not_found`` (Req 10.2).
    """
    import api

    with api._tasks_lock:
        entry = api._tasks.get(task_id)
    if entry is None:
        return _not_found()
    result = _stop_rtsp_task_entry(entry)
    if result["shutdown_completed"]:
        with api._tasks_lock:
            api._tasks[task_id]["status"] = "stopped"
    else:
        # Incomplete shutdown: keep the session open and the processor
        # reference; surface the incomplete state so a later stop can retry.
        with api._tasks_lock:
            api._tasks[task_id]["status"] = "stop_incomplete"
            api._tasks[task_id]["shutdown_completed"] = False
    return result
