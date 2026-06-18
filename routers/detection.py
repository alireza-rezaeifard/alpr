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
import os
import threading
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
def _envelope(message: str, code: ErrorCode) -> dict:
    return {"error": message, "code": code.value}


def _not_found(message: str = "Task not found") -> JSONResponse:
    return JSONResponse(_envelope(message, ErrorCode.NOT_FOUND), status_code=404)


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
        vp = VideoProcessor(engine, on_detection=on_det)
        with api._tasks_lock:
            api._tasks[task_id]["processor"] = vp
        vp.process_video(inp, skip_frames=skip, fast_mode=fast)
        # Wait for completion
        while True:
            # Check if cancelled externally
            with api._tasks_lock:
                if api._tasks.get(task_id, {}).get("status") == "cancelled":
                    vp.stop()
                    break
            state = vp.get_state()
            with api._tasks_lock:
                api._tasks[task_id].update(state)
            if state["status"] in ("done", "error"):
                break
            threading.Event().wait(0.5)
        if state["status"] == "done":
            unique = len(set(e["dtrb_text"] for e in state["plate_log"]))
            end_session(sid, state["total_frames"], len(state["plate_log"]), unique)

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

    processor = RTSPStreamProcessor(engine, url,
                                     fast_mode=fast_mode, skip_frames=skip_frames,
                                     on_detection=on_det)
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

    return {
        "status": state.get("status", "unknown"),
        "history": state.get("history", []),
        "live_detections": state.get("live_detections", []),
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
    processor = entry.get("processor")
    if processor:
        state = processor.get_state()
        if entry.get("session_id"):
            end_session(entry["session_id"], 0, len(state.get("history", [])),
                        len(set(p["dtrb_text"] for p in state.get("history", []))))
        processor.stop()
    with api._tasks_lock:
        api._tasks[task_id]["status"] = "stopped"
    return {"status": "stopped"}
