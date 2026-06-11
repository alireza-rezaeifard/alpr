import os, sys, io, uuid, base64, json, threading
import asyncio
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
from fastapi import FastAPI, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from db import *
from schemas import (
    CameraCreate, CameraUpdate, CameraView, StartResult, StopResult,
    ConcurrencyConfig, ConcurrencyView, PlateMetadataResponse,
)
from camera_manager import CameraManager
from plate_metadata import derive_metadata

# Import all routers
from routers import auth, users, licenses, cameras, detection, scanner, watchlists, alerts, reports, export, audit, retention

# Import bootstrap and pruning functions
from routers.auth import bootstrap_default_admin
from routers.cameras import restore_cameras, set_camera_manager
from retention.service import prune_detections

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

    MODEL_DIR = os.environ.get("MODEL_DIR", "weigths")
    DETECTOR_PATH = os.path.join(MODEL_DIR, "..", "plate_detector.pt") if MODEL_DIR != "weigths" else "plate_detector.pt"
    RECOGNIZER_PATH = os.path.join(MODEL_DIR, "dtrb-recoginzer", "dtrb-None-VGG-BiLSTM-CTC-license-plate-recognizer.pth")

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


# ── Background task state ──
_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


# ── Camera Manager (process-wide singleton) ──
_camera_manager = CameraManager(ensure_models_fn=_ensure_models, tasks_registry=_tasks, tasks_lock=_tasks_lock)

# ── Retention pruning background task ──
_pruning_task = None
_pruning_interval = 24 * 60 * 60  # 24 hours in seconds


async def _retention_pruning_loop():
    """Background task that prunes old detections every 24 hours."""
    while True:
        try:
            await asyncio.sleep(_pruning_interval)
            now = datetime.now()
            deleted = prune_detections(now)
            if deleted > 0:
                print(f"Retention pruning: deleted {deleted} old detection(s)")
        except Exception as e:
            print(f"Error in retention pruning task: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logic.
    
    On startup (Requirement 1.9, 4.6, 16.2):
    - Initialize database tables
    - Bootstrap default admin account if no users exist
    - Inject camera manager into cameras router
    - Restore persisted cameras to their last known status
    - Schedule retention pruning background task
    
    On shutdown:
    - Cancel the pruning task
    """
    global _pruning_task
    
    # Startup
    print("Starting ANPR backend...")
    
    # 1. Initialize database
    init_db()
    
    # 2. Bootstrap default admin (Requirement 1.9)
    bootstrap_default_admin()
    
    # 3. Inject camera manager into cameras router
    set_camera_manager(_camera_manager)
    
    # 4. Restore cameras (Requirement 4.6)
    restore_cameras(_camera_manager)
    
    # 5. Schedule retention pruning background task (Requirement 16.2)
    _pruning_task = asyncio.create_task(_retention_pruning_loop())
    
    print("ANPR backend started successfully")
    
    yield
    
    # Shutdown
    print("Shutting down ANPR backend...")
    if _pruning_task:
        _pruning_task.cancel()
        try:
            await _pruning_task
        except asyncio.CancelledError:
            pass
    print("ANPR backend shutdown complete")


app = FastAPI(
    title="Persian License Plate API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global exception handler — catches unhandled errors, logs them to the
# centralized error store, and returns a clean JSON envelope.
# ---------------------------------------------------------------------------
from error_handler import report_exception, ErrorCategory

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Catch any unhandled exception across the API layer."""
    from fastapi.responses import JSONResponse as _JSONResp
    report_exception(exc, ErrorCategory.SYSTEM, source=f"api:{request.url.path}")
    return _JSONResp(
        status_code=500,
        content={
            "error": "An internal server error occurred.",
            "code": "internal_error",
            "detail": str(exc) if os.environ.get("DEBUG") else None,
        },
    )

# Include all routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(licenses.router)
app.include_router(cameras.router)
app.include_router(detection.router)
app.include_router(scanner.router)
app.include_router(watchlists.router)
app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(export.router)
app.include_router(audit.router)
app.include_router(retention.router)


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


# ── Detection endpoints ──
# Image (Req 8), video (Req 9), and RTSP (Req 10) detection now live in
# ``routers/detection.py`` behind ``current_user()`` + ``run_detection`` (and
# ``require_license()`` for the run/start paths). The handler functions are
# re-exported here so they remain importable as ``api.detect_image`` etc. for
# direct-call integration tests; they operate on this module's shared
# ``_ensure_models`` / ``_tasks`` / ``_tasks_lock`` / ``OUTPUT_DIR`` state.
from routers.detection import (  # noqa: E402
    detect_image,
    detect_rtsp,
    detect_video,
    rtsp_frame_only,
    rtsp_mjpeg_stream,
    rtsp_status,
    stop_rtsp_task,
    stop_video_task,
    video_status,
)


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


# ── Network Camera Scanner ──

_scan_lock = threading.Lock()
_scan_state: dict = {"running": False, "results": [], "progress": 0, "total": 0}


def _ip_to_int(ip: str) -> int:
    parts = [int(p) for p in ip.split(".")]
    return (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]


def _int_to_ip(n: int) -> str:
    return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"


def _is_rtsp_camera(ip: str, port: int = 554, timeout: float = 2.0) -> dict | None:
    """Check if host is an actual RTSP IP camera by attempting an RTSP OPTIONS request."""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        # Send RTSP OPTIONS to identify camera
        sock.sendall(f"OPTIONS rtsp://{ip}:{port}/ RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
        response = sock.recv(2048).decode(errors="ignore")
        sock.close()
        if "RTSP" in response:
            brand = "Unknown"
            server_info = ""
            resp_lower = response.lower()

            # Extract Server header for detailed info
            for line in response.split("\r\n"):
                if line.lower().startswith("server:"):
                    server_info = line.split(":", 1)[1].strip()
                    break

            # Brand detection from response content
            if "hikvision" in resp_lower or "hikvis" in resp_lower:
                brand = "Hikvision"
            elif "dahua" in resp_lower or "dh-" in resp_lower:
                brand = "Dahua"
            elif "axis" in resp_lower:
                brand = "Axis"
            elif "uniview" in resp_lower or "unv" in resp_lower:
                brand = "Uniview"
            elif "reolink" in resp_lower:
                brand = "Reolink"
            elif "amcrest" in resp_lower:
                brand = "Amcrest"
            elif "foscam" in resp_lower:
                brand = "Foscam"
            elif "onvif" in resp_lower:
                brand = "ONVIF Camera"
            elif "hanwha" in resp_lower or "samsung" in resp_lower or "wisenet" in resp_lower:
                brand = "Hanwha/Samsung"
            elif "vivotek" in resp_lower:
                brand = "Vivotek"
            elif "bosch" in resp_lower:
                brand = "Bosch"
            elif "panasonic" in resp_lower or "i-pro" in resp_lower:
                brand = "Panasonic"
            elif "geovision" in resp_lower or "gv-" in resp_lower:
                brand = "GeoVision"
            elif "tiandy" in resp_lower:
                brand = "Tiandy"
            elif "sunell" in resp_lower:
                brand = "Sunell"
            elif "tp-link" in resp_lower or "tplink" in resp_lower:
                brand = "TP-Link"
            elif "imou" in resp_lower:
                brand = "Imou"
            elif "ezviz" in resp_lower:
                brand = "EZVIZ"

            # If brand still unknown, try to get it from server header
            if brand == "Unknown" and server_info:
                brand = f"RTSP ({server_info[:30]})"

            return {"ip": ip, "port": port, "brand": brand, "server": server_info}
        return None
    except Exception:
        return None


# Common RTSP ports to scan
_RTSP_PORTS = [554, 8554, 1554, 5554, 80, 8080]


def _scan_network_for_cameras(start_ip: str, end_ip: str, timeout: float = 0.8):
    """Scan IP range for hosts with open RTSP port using concurrent threads."""
    import socket
    from concurrent.futures import ThreadPoolExecutor, as_completed

    start = _ip_to_int(start_ip)
    end = _ip_to_int(end_ip)
    ip_count = end - start + 1
    # Total = IPs × ports
    total = ip_count * len(_RTSP_PORTS)

    with _scan_lock:
        _scan_state["running"] = True
        _scan_state["results"] = []
        _scan_state["progress"] = 0
        _scan_state["total"] = total

    def _check_single_ip_port(ip_int: int, port: int) -> dict | None:
        ip = _int_to_ip(ip_int)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            if sock.connect_ex((ip, port)) == 0:
                sock.close()
                return _is_rtsp_camera(ip, port, timeout=2.0)
            else:
                sock.close()
        except Exception:
            pass
        return None

    # Use thread pool for concurrent scanning (50 threads max)
    max_workers = min(50, total)
    progress_counter = 0

    # Track which IPs already found (to avoid duplicate entries per IP if multiple ports respond)
    found_ip_ports = set()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for ip_int in range(start, end + 1):
            with _scan_lock:
                if not _scan_state["running"]:
                    break
            for port in _RTSP_PORTS:
                future = executor.submit(_check_single_ip_port, ip_int, port)
                futures[future] = (ip_int, port)

        for future in as_completed(futures):
            with _scan_lock:
                if not _scan_state["running"]:
                    # Cancel remaining futures
                    for f in futures:
                        f.cancel()
                    break
                progress_counter += 1
                _scan_state["progress"] = progress_counter
            result = future.result()
            if result:
                key = (result["ip"], result["port"])
                if key not in found_ip_ports:
                    found_ip_ports.add(key)
                    with _scan_lock:
                        _scan_state["results"].append(result)

    with _scan_lock:
        _scan_state["running"] = False


@app.post("/api/scanner/scan")
def start_scan(start_ip: str = Form(""), end_ip: str = Form(""), timeout: float = Form(0.8)):
    with _scan_lock:
        if _scan_state["running"]:
            return JSONResponse({"error": "Scan already running"}, status_code=409)
    s_ip = start_ip.strip() or "192.168.1.1"
    e_ip = end_ip.strip() or "192.168.1.254"
    threading.Thread(target=_scan_network_for_cameras, args=(s_ip, e_ip, timeout), daemon=True).start()
    return {"status": "scanning", "start_ip": s_ip, "end_ip": e_ip}


@app.get("/api/scanner/status")
def scan_status():
    with _scan_lock:
        return {
            "running": _scan_state["running"],
            "results": list(_scan_state["results"]),
            "progress": _scan_state["progress"],
            "total": _scan_state["total"],
        }


@app.post("/api/scanner/stop")
def stop_scan():
    with _scan_lock:
        _scan_state["running"] = False
    return {"status": "stopped"}


@app.post("/api/scanner/test")
def test_rtsp_connection(url: str = Form(...)):
    """Test if an RTSP URL is reachable and returns frames."""
    cap = cv2.VideoCapture(url)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    try:
        if not cap.isOpened():
            return {"success": False, "error": "Cannot connect"}
        ret, _ = cap.read()
        if not ret:
            return {"success": False, "error": "Connected but no frames received"}
        return {"success": True}
    finally:
        cap.release()


# Common RTSP stream paths by brand
_BRAND_STREAMS: dict[str, list[dict]] = {
    "Hikvision": [
        {"path": "/Streaming/Channels/101", "label": "Main Stream (Ch1)"},
        {"path": "/Streaming/Channels/102", "label": "Sub Stream (Ch1)"},
        {"path": "/Streaming/Channels/103", "label": "Third Stream (Ch1)"},
        {"path": "/Streaming/Channels/201", "label": "Main Stream (Ch2)"},
        {"path": "/ISAPI/Streaming/Channels/101", "label": "ISAPI Main"},
        {"path": "/h264/ch1/main/av_stream", "label": "H264 Main"},
        {"path": "/h264/ch1/sub/av_stream", "label": "H264 Sub"},
    ],
    "Dahua": [
        {"path": "/cam/realmonitor?channel=1&subtype=0", "label": "Main Stream (Ch1)"},
        {"path": "/cam/realmonitor?channel=1&subtype=1", "label": "Sub Stream (Ch1)"},
        {"path": "/cam/realmonitor?channel=1&subtype=2", "label": "Third Stream (Ch1)"},
        {"path": "/cam/realmonitor?channel=2&subtype=0", "label": "Main Stream (Ch2)"},
        {"path": "/live", "label": "Live"},
    ],
    "Axis": [
        {"path": "/axis-media/media.amp", "label": "Main Stream"},
        {"path": "/axis-media/media.amp?videocodec=h264", "label": "H264 Stream"},
        {"path": "/axis-media/media.amp?resolution=640x480", "label": "Low Res"},
        {"path": "/mpeg4/media.amp", "label": "MPEG4"},
    ],
    "Uniview": [
        {"path": "/media/video1", "label": "Main Stream"},
        {"path": "/media/video2", "label": "Sub Stream"},
        {"path": "/media/video3", "label": "Third Stream"},
        {"path": "/unicast/c1/s0/live", "label": "Unicast Main"},
        {"path": "/unicast/c1/s1/live", "label": "Unicast Sub"},
    ],
    "Reolink": [
        {"path": "/h264Preview_01_main", "label": "Main Stream"},
        {"path": "/h264Preview_01_sub", "label": "Sub Stream"},
        {"path": "/Preview_01_main", "label": "Preview Main"},
        {"path": "/Preview_01_sub", "label": "Preview Sub"},
    ],
    "Amcrest": [
        {"path": "/cam/realmonitor?channel=1&subtype=0", "label": "Main Stream"},
        {"path": "/cam/realmonitor?channel=1&subtype=1", "label": "Sub Stream"},
    ],
    "Foscam": [
        {"path": "/videoMain", "label": "Main Stream"},
        {"path": "/videoSub", "label": "Sub Stream"},
        {"path": "/video1", "label": "Video 1"},
        {"path": "/video2", "label": "Video 2"},
    ],
    "Hanwha/Samsung": [
        {"path": "/profile1/media.smp", "label": "Profile 1"},
        {"path": "/profile2/media.smp", "label": "Profile 2"},
        {"path": "/profile3/media.smp", "label": "Profile 3"},
    ],
    "Vivotek": [
        {"path": "/live.sdp", "label": "Main Stream"},
        {"path": "/live2.sdp", "label": "Sub Stream"},
        {"path": "/video.mp4", "label": "MP4 Stream"},
    ],
    "Bosch": [
        {"path": "/rtsp_tunnel", "label": "RTSP Tunnel"},
        {"path": "/video", "label": "Video"},
    ],
    "Panasonic": [
        {"path": "/MediaInput/h264", "label": "H264 Main"},
        {"path": "/MediaInput/h264/stream_1", "label": "Stream 1"},
        {"path": "/MediaInput/h264/stream_2", "label": "Stream 2"},
        {"path": "/nphMpeg4/nil-320x240", "label": "MPEG4 Low"},
    ],
    "GeoVision": [
        {"path": "/CH001.sdp", "label": "Channel 1"},
        {"path": "/CH002.sdp", "label": "Channel 2"},
        {"path": "/media/video1", "label": "Video 1"},
    ],
    "TP-Link": [
        {"path": "/stream1", "label": "Main Stream"},
        {"path": "/stream2", "label": "Sub Stream"},
    ],
    "Imou": [
        {"path": "/cam/realmonitor?channel=1&subtype=0", "label": "Main Stream"},
        {"path": "/cam/realmonitor?channel=1&subtype=1", "label": "Sub Stream"},
    ],
    "EZVIZ": [
        {"path": "/h264_stream", "label": "H264 Main"},
        {"path": "/Streaming/Channels/101", "label": "Channel 101"},
    ],
    "Tiandy": [
        {"path": "/Streaming/Channels/101", "label": "Main Stream"},
        {"path": "/Streaming/Channels/102", "label": "Sub Stream"},
    ],
    "Sunell": [
        {"path": "/media/video1", "label": "Main Stream"},
        {"path": "/media/video2", "label": "Sub Stream"},
    ],
}

# Generic paths tried for all unknown brands
_GENERIC_STREAMS: list[dict] = [
    {"path": "/stream1", "label": "Stream 1"},
    {"path": "/stream2", "label": "Stream 2"},
    {"path": "/live", "label": "Live"},
    {"path": "/h264", "label": "H264"},
    {"path": "/media/video1", "label": "Media Video 1"},
    {"path": "/Streaming/Channels/101", "label": "Channel 101"},
    {"path": "/cam/realmonitor?channel=1&subtype=0", "label": "Realmonitor Main"},
    {"path": "/video1", "label": "Video 1"},
    {"path": "/1", "label": "Path /1"},
    {"path": "/0", "label": "Path /0"},
    {"path": "/ch0_0.h264", "label": "CH0 H264"},
]


def _probe_rtsp_stream(ip: str, port: int, path: str, username: str, password: str, timeout: float = 3.0) -> bool:
    """Try opening an RTSP stream path and check if it returns frames.
    
    Uses a quick RTSP DESCRIBE check first to avoid the 30s FFmpeg default timeout
    on paths that don't exist.
    """
    import socket

    # Step 1: Quick RTSP DESCRIBE to check if the path is valid (avoids 30s FFmpeg timeout)
    cred_rtsp = ""
    if username:
        import base64
        cred_rtsp = base64.b64encode(f"{username}:{password}".encode()).decode()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        # Send DESCRIBE request to check if path exists
        describe = f"DESCRIBE rtsp://{ip}:{port}{path} RTSP/1.0\r\nCSeq: 2\r\n"
        if cred_rtsp:
            describe += f"Authorization: Basic {cred_rtsp}\r\n"
        describe += "\r\n"
        sock.sendall(describe.encode())
        response = sock.recv(1024).decode(errors="ignore")
        sock.close()

        # If we get 404, 453, 451, or no RTSP response, path doesn't exist
        if "404" in response or "453" in response or "451" in response:
            return False
        if "RTSP" not in response:
            return False
        # 401 means path exists but needs auth (or wrong auth) - still valid path
        # 200 means path exists and is accessible
        if "200" not in response and "401" not in response:
            return False
    except Exception:
        return False

    # Step 2: Only if DESCRIBE succeeded, do the actual OpenCV check
    cred = f"{username}:{password}@" if username else ""
    url = f"rtsp://{cred}{ip}:{port}{path}"
    # Set FFmpeg timeout via options string
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(timeout * 1000),
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(timeout * 1000),
    ])
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    try:
        if not cap.isOpened():
            return False
        ret, _ = cap.read()
        return ret
    except Exception:
        return False
    finally:
        cap.release()


@app.post("/api/scanner/probe")
def probe_camera_streams(
    ip: str = Form(...),
    port: int = Form(554),
    brand: str = Form("Unknown"),
    username: str = Form(""),
    password: str = Form(""),
):
    """Probe a discovered camera for available RTSP stream paths across all RTSP ports.
    
    Tries brand-specific paths first, then generic paths. Each path is tested on
    the detected port AND all other common RTSP ports. Returns list of working
    streams with the port each works on.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Build candidate list: brand-specific first, then generic
    candidates = []
    brand_clean = brand.strip()
    if brand_clean in _BRAND_STREAMS:
        candidates.extend(_BRAND_STREAMS[brand_clean])
    # Always add generic paths (skip duplicates)
    seen_paths = {c["path"] for c in candidates}
    for g in _GENERIC_STREAMS:
        if g["path"] not in seen_paths:
            candidates.append(g)
            seen_paths.add(g["path"])

    # Ports to try: detected port first, then other common ports
    ports_to_try = [port] + [p for p in _RTSP_PORTS if p != port]

    working_streams = []

    def _test_path_port(candidate: dict, test_port: int) -> dict | None:
        import socket
        # Quick check: is the port even open?
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            if sock.connect_ex((ip, test_port)) != 0:
                sock.close()
                return None
            sock.close()
        except Exception:
            return None

        path = candidate["path"]
        if _probe_rtsp_stream(ip, test_port, path, username, password, timeout=3.0):
            return {"path": path, "label": candidate["label"], "port": test_port}
        return None

    # Probe concurrently (up to 10 at a time to avoid overwhelming the camera)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {}
        for candidate in candidates:
            for test_port in ports_to_try:
                future = executor.submit(_test_path_port, candidate, test_port)
                futures[future] = (candidate["path"], test_port)

        # Track found path+port combos to avoid duplicates
        found = set()
        for future in as_completed(futures):
            result = future.result()
            if result:
                key = (result["path"], result["port"])
                if key not in found:
                    found.add(key)
                    working_streams.append(result)

    # Sort by port, then path
    working_streams.sort(key=lambda s: (s["port"], s["path"]))

    return {
        "ip": ip,
        "port": port,
        "brand": brand_clean,
        "streams": working_streams,
        "total_tried": len(candidates) * len(ports_to_try),
    }


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
    # Launch via the import string (not the app object) so the served app lives
    # in the importable ``api`` module. The detection router and camera manager
    # share the live task registry via ``import api``; running the app object
    # directly under ``__main__`` would give them a second, empty ``api._tasks``
    # copy, so camera frames would 404 ("connecting" forever).
    uvicorn.run("api:app", host="127.0.0.1", port=port)
