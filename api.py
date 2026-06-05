import os, sys, io, uuid, base64, json, threading
from pathlib import Path
import cv2
import numpy as np
from fastapi import FastAPI, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from db import *
from schemas import (
    CameraCreate, CameraUpdate, CameraView, StartResult, StopResult,
    ConcurrencyConfig, ConcurrencyView, PlateMetadataResponse,
)
from camera_manager import CameraManager
from plate_metadata import derive_metadata

app = FastAPI(title="Persian License Plate API", version="1.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

init_db()

# ── Detection model loading (lazy) ──
_detector = None
_recognizer = None
_opt = None


def _load_models():
    global _detector, _recognizer, _opt
    if _detector is not None:
        return
    from ultralytics import YOLO
    from deep_text_recognition_benchmark.dtrb import DTRB
    import argparse

    DETECTOR_PATH = "plate_detector.pt"
    RECOGNIZER_PATH = "weigths/dtrb-recoginzer/dtrb-None-VGG-BiLSTM-CTC-license-plate-recognizer.pth"

    _opt = argparse.Namespace(
        workers=0, batch_size=192, batch_max_length=25,
        imgH=32, imgW=100, rgb=False,
        character='0123456789abcdefghijklmnopqrstuvwxyz',
        sensitive=False, PAD=False,
        Transformation="TPS", FeatureExtraction="ResNet",
        SequenceModeling="BiLSTM", Prediction="Attn",
        num_fiducial=20, input_channel=1, output_channel=512,
        hidden_size=256, threshold=0.6,
    )
    print("Loading detector...")
    _detector = YOLO(DETECTOR_PATH)
    print("Loading recognizer...")
    _recognizer = DTRB(RECOGNIZER_PATH, _opt)
    print("Models loaded.")


def _ensure_models():
    if _detector is None:
        _load_models()
    return _detector, _recognizer, _opt


# ── Camera Manager (process-wide singleton) ──
_camera_manager = CameraManager(ensure_models_fn=_ensure_models)

from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app):
    _camera_manager.restore_on_startup()
    yield

app.router.lifespan_context = _lifespan


# ── Background task state ──
_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()

OUTPUT_DIR = "io/output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── REST endpoints ──

@app.get("/api/stats")
def get_stats_api():
    return get_stats()


@app.get("/api/detections")
def get_detections_api(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    source_type: str = Query("all"),
    search: str = Query(""),
):
    dets, total = get_all_detections(limit=limit, offset=offset, source_type=source_type, search=search)
    return {"data": dets, "total": total, "limit": limit, "offset": offset}


@app.get("/api/detections/timeline")
def get_timeline_api(days: int = Query(14, ge=1, le=90)):
    data = get_detections_timeline(days=days)
    return {"data": data}


@app.get("/api/detections/letters")
def get_letters_api():
    data = get_letter_frequency()
    return {"data": data}


@app.get("/api/detections/sources")
def get_sources_api():
    data = get_source_distribution()
    return {"data": data}


@app.get("/api/detections/confidence")
def get_confidence_api():
    data = get_confidence_distribution()
    return {"data": data}


@app.get("/api/sessions")
def get_sessions_api(limit: int = Query(20, ge=1, le=100)):
    data = get_sessions_history(limit=limit)
    return {"data": data}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── Image detection ──

@app.post("/api/detect/image")
async def detect_image(file: UploadFile = File(...)):
    detector, recognizer, opt = _ensure_models()
    from video_processor import process_frame, format_plate_persian

    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return JSONResponse({"error": "Invalid image"}, status_code=400)

    annotated, plates, dtrb_results = process_frame(img, detector, recognizer, opt)

    # Save to session
    sid = start_session("image", file.filename or "upload")
    plates_out = []
    for idx, plate in enumerate(plates):
        dtrb_text = dtrb_results[idx] if idx < len(dtrb_results) else "-"
        persian = format_plate_persian(dtrb_text)
        # Convert numpy types to native Python for JSON serialization
        bbox = tuple(int(x) for x in plate["bbox"])
        plates_out.append({
            "plate_dtrb": dtrb_text,
            "plate_persian": persian,
            "confidence": float(plate["confidence"]),
            "bbox": bbox,
        })
        save_detection(sid, "image", dtrb_text, persian, plate["confidence"], file.filename)
    end_session(sid, 0, len(plates), len(set(p["plate_dtrb"] for p in plates_out)))

    # Encode annotated image to base64
    _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64 = base64.b64encode(buf).decode("utf-8")

    return {
        "session_id": sid,
        "annotated": f"data:image/jpeg;base64,{b64}",
        "plates": plates_out,
    }


# ── Video detection ──

@app.post("/api/detect/video")
async def detect_video(
    file: UploadFile = File(...),
    skip_frames: int = Form(30, ge=1, le=1000),
    fast_mode: bool = Form(False),
):
    detector, recognizer, opt = _ensure_models()
    from video_processor import VideoProcessor, format_plate_persian

    # Save uploaded file
    ext = Path(file.filename or "video.mp4").suffix or ".mp4"
    input_path = os.path.join(OUTPUT_DIR, f"input_{uuid.uuid4().hex}{ext}")
    contents = await file.read()
    with open(input_path, "wb") as f:
        f.write(contents)

    task_id = uuid.uuid4().hex
    session_id = start_session("video", file.filename)

    def run_video(task_id, sid, inp, skip, fast):
        def on_det(src, text, conf, sf, frame, ftime):
            save_detection(sid, src, text, format_plate_persian(text), conf, sf, frame, ftime)
        vp = VideoProcessor(detector, recognizer, opt, on_detection=on_det)
        vp.process_video(inp, skip_frames=skip, fast_mode=fast)
        # Wait for completion
        while True:
            state = vp.get_state()
            with _tasks_lock:
                _tasks[task_id] = state
            if state["status"] in ("done", "error"):
                break
            threading.Event().wait(0.5)
        if state["status"] == "done":
            unique = len(set(e["dtrb_text"] for e in state["plate_log"]))
            end_session(sid, state["total_frames"], len(state["plate_log"]), unique)

    threading.Thread(target=run_video, args=(task_id, session_id, input_path, skip_frames, fast_mode), daemon=True).start()

    with _tasks_lock:
        _tasks[task_id] = {"status": "queued", "session_id": session_id}

    return JSONResponse({"task_id": task_id, "session_id": session_id})


@app.get("/api/detect/video/{task_id}")
def video_status(task_id: str):
    with _tasks_lock:
        state = _tasks.get(task_id)
    if state is None:
        return JSONResponse({"error": "Task not found"}, status_code=404)

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


@app.post("/api/detect/video/{task_id}/stop")
def stop_video_task(task_id: str):
    with _tasks_lock:
        state = _tasks.get(task_id)
    if state is None:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    if state.get("status") == "processing":
        from video_processor import VideoProcessor
        # The processor stores running flag; we set it to false via the task state approach
        # For simplicity, we mark it cancelled
        with _tasks_lock:
            _tasks[task_id] = {**_tasks[task_id], "status": "cancelled"}
    return {"status": "stopped"}


# ── RTSP detection ──

@app.post("/api/detect/rtsp")
def detect_rtsp(
    url: str = Form(...),
    fast_mode: bool = Form(False),
    skip_frames: int = Form(15, ge=1, le=1000),
):
    detector, recognizer, opt = _ensure_models()
    from video_processor import RTSPStreamProcessor, format_plate_persian

    task_id = uuid.uuid4().hex
    session_id = start_session("rtsp", url)

    def on_det(src, text, conf, sf, frame, ftime):
        save_detection(session_id, src, text, format_plate_persian(text), conf, sf, frame, ftime)

    processor = RTSPStreamProcessor(detector, recognizer, opt, url,
                                     fast_mode=fast_mode, skip_frames=skip_frames,
                                     on_detection=on_det)
    processor.start()

    with _tasks_lock:
        _tasks[task_id] = {"processor": processor, "session_id": session_id, "status": "running", "url": url}

    return JSONResponse({"task_id": task_id, "session_id": session_id})


@app.get("/api/detect/rtsp/{task_id}")
def rtsp_status(task_id: str):
    with _tasks_lock:
        entry = _tasks.get(task_id)
    if entry is None:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    processor: RTSPStreamProcessor = entry.get("processor")
    if processor is None:
        return {"status": "error", "error": "Processor not found"}
    state = processor.get_state()

    # Encode latest annotated frame
    annotated_b64 = None
    if state.get("annotated") is not None:
        _, buf = cv2.imencode(".jpg", state["annotated"], [cv2.IMWRITE_JPEG_QUALITY, 80])
        annotated_b64 = f"data:image/jpeg;base64,{base64.b64encode(buf).decode('utf-8')}"

    return {
        "status": state.get("status", "unknown"),
        "history": state.get("history", []),
        "live_detections": state.get("live_detections", []),
        "annotated": annotated_b64,
    }


@app.post("/api/detect/rtsp/{task_id}/stop")
def stop_rtsp_task(task_id: str):
    with _tasks_lock:
        entry = _tasks.get(task_id)
    if entry is None:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    processor = entry.get("processor")
    if processor:
        state = processor.get_state()
        if entry.get("session_id"):
            end_session(entry["session_id"], 0, len(state.get("history", [])),
                        len(set(p["dtrb_text"] for p in state.get("history", []))))
        processor.stop()
    with _tasks_lock:
        _tasks[task_id]["status"] = "stopped"
    return {"status": "stopped"}


# ── Camera CRUD endpoints ──

@app.post("/api/cameras", response_model=CameraView)
def create_camera_api(body: CameraCreate):
    view = _camera_manager.add_camera(
        name=body.name,
        url=body.url,
        skip_frames=body.skip_frames,
    )
    return view


@app.get("/api/cameras")
def list_cameras_api():
    return {"data": _camera_manager.list_cameras_view()}


@app.patch("/api/cameras/{camera_id}", response_model=CameraView)
def update_camera_api(camera_id: int, body: CameraUpdate):
    view = _camera_manager.update_camera_info(
        camera_id=camera_id,
        name=body.name,
        url=body.url,
        skip_frames=body.skip_frames,
    )
    if view is None:
        return JSONResponse({"error": "Camera not found"}, status_code=404)
    return view


@app.delete("/api/cameras/{camera_id}")
def delete_camera_api(camera_id: int):
    removed = _camera_manager.remove_camera(camera_id)
    if not removed:
        return JSONResponse({"error": "Camera not found"}, status_code=404)
    return {"status": "deleted"}


@app.post("/api/cameras/{camera_id}/start")
def start_camera_api(camera_id: int):
    result = _camera_manager.start_camera(camera_id)
    if result.get("status") == "error":
        return JSONResponse({"error": "Camera not found"}, status_code=404)
    return result


@app.post("/api/cameras/{camera_id}/stop")
def stop_camera_api(camera_id: int):
    result = _camera_manager.stop_camera(camera_id)
    if result.get("status") == "not_found":
        return JSONResponse({"error": "Camera not found"}, status_code=404)
    return result


@app.post("/api/cameras/start-all")
def start_all_cameras_api():
    results = _camera_manager.start_all()
    return {"data": results}


@app.post("/api/cameras/stop-all")
def stop_all_cameras_api():
    _camera_manager.stop_all()
    return {"status": "stopped"}


# ── Concurrency config endpoints ──

@app.get("/api/config/concurrency")
def get_concurrency_api():
    return {"concurrency_limit": _camera_manager.get_limit()}


@app.put("/api/config/concurrency")
def set_concurrency_api(body: ConcurrencyConfig):
    try:
        _camera_manager.set_concurrency_limit(body.value)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    return {"concurrency_limit": _camera_manager.get_limit()}


# ── Plate metadata endpoint ──

@app.get("/api/plate/metadata")
def plate_metadata_api(plate: str = ""):
    if not plate.strip():
        return PlateMetadataResponse(
            classified=False,
            reason="Plate parameter is required and must not be empty",
        ).model_dump()
    result = derive_metadata(plate)
    return PlateMetadataResponse(
        classified=result.classified,
        category=result.category,
        category_display=result.category_display,
        color_scheme=result.color_scheme,
        region_code=result.region_code,
        region_name=result.region_name,
        special_note=result.special_note,
        reason=result.reason,
    ).model_dump()


# ── Static file serving ──
OUTPUT_DIR_ABS = os.path.abspath(OUTPUT_DIR)
if os.path.isdir(OUTPUT_DIR_ABS):
    app.mount("/media", StaticFiles(directory=OUTPUT_DIR_ABS), name="media")

BUILT_FRONTEND = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(BUILT_FRONTEND):
    app.mount("/", StaticFiles(directory=BUILT_FRONTEND, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"API server running at http://127.0.0.1:{port}")
    print(f"API docs at http://127.0.0.1:{port}/docs")
    uvicorn.run(app, host="127.0.0.1", port=port)
