"""
routers/scanner.py
Network camera discovery API: scan an IPv4 range for RTSP-responsive hosts,
report progress, stop a running scan, and test whether a frame can be retrieved
from an RTSP URL.

The probing logic (socket connect to common RTSP ports + an RTSP ``OPTIONS``
request for brand detection, run in a background thread with running-state /
progress tracking and a cooperative stop flag) is preserved from the original
``api.py`` implementation and only protected with auth here (design.md:
"Network scanner — Preserve; protect with auth").

Authorization (design "Backend Request Pipeline", Requirement 2.6):
    * Mutating scan operations — start, stop, and test-URL — are an Operator
      capability and are guarded with ``require_permission("manage_cameras")``.
    * Read-only scan status is guarded with ``current_user`` (any authenticated
      role may observe progress).

Endpoints (prefix ``/api/scanner``):
    * ``POST /api/scanner/scan``   — start a scan over an IP range; reports
      progress as completed/total (Requirement 7.1). Rejected with
      ``409 conflict`` if a scan is already running (Requirement 7.5).
    * ``GET  /api/scanner/status`` — running state, discovered hosts, and
      progress (Requirements 7.2, 7.3).
    * ``POST /api/scanner/stop``   — halt further probing and report stopped
      (Requirement 7.4).
    * ``POST /api/scanner/test``   — report whether a frame can be retrieved
      from an RTSP URL (Requirement 7.6).

All errors use the standard ``{ error, code }`` envelope (schemas.ErrorResponse /
schemas.ErrorCode).

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
"""
from __future__ import annotations

import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, Depends, HTTPException, status

from auth.dependencies import AuthenticatedUser, current_user, require_permission
from schemas import (
    ErrorCode,
    ScanHost,
    ScanStart,
    ScanStartResult,
    ScanStatus,
    ScanStopResult,
    TestUrlRequest,
    TestUrlResult,
)

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


# ---------------------------------------------------------------------------
# Error helpers — every error uses the { error, code } envelope
# ---------------------------------------------------------------------------
def _envelope(message: str, code: ErrorCode) -> dict:
    return {"error": message, "code": code.value}


def _http_error(status_code: int, message: str, code: ErrorCode) -> HTTPException:
    return HTTPException(status_code=status_code, detail=_envelope(message, code))


# ---------------------------------------------------------------------------
# Scan state (preserved from api.py)
# ---------------------------------------------------------------------------
# A single process-wide scan runs at a time. ``running`` doubles as the
# cooperative stop flag: the background worker checks it and halts when cleared
# (Requirement 7.4). ``results`` holds the discovered hosts, ``progress`` the
# number of completed checks, and ``total`` the planned number of checks.
_scan_lock = threading.Lock()
_scan_state: dict = {"running": False, "results": [], "progress": 0, "total": 0}

# Common RTSP ports probed for each address in the range.
_RTSP_PORTS = [554, 8554, 1554, 5554, 80, 8080]


def _ip_to_int(ip: str) -> int:
    parts = [int(p) for p in ip.split(".")]
    return (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]


def _int_to_ip(n: int) -> str:
    return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"


def _is_rtsp_camera(ip: str, port: int = 554, timeout: float = 2.0) -> dict | None:
    """Check if host is an actual RTSP IP camera via an RTSP ``OPTIONS`` request.

    On success returns the host address, port, detected brand, and server header
    (Requirement 7.2); returns ``None`` otherwise.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.sendall(f"OPTIONS rtsp://{ip}:{port}/ RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
        response = sock.recv(2048).decode(errors="ignore")
        sock.close()
        if "RTSP" not in response:
            return None

        brand = "Unknown"
        server_info = ""
        resp_lower = response.lower()

        # Extract Server header for detailed info.
        for line in response.split("\r\n"):
            if line.lower().startswith("server:"):
                server_info = line.split(":", 1)[1].strip()
                break

        # Brand detection from response content.
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

        # If brand still unknown, derive it from the server header.
        if brand == "Unknown" and server_info:
            brand = f"RTSP ({server_info[:30]})"

        return {"ip": ip, "port": port, "brand": brand, "server": server_info}
    except Exception:
        return None


def _scan_network_for_cameras(start_ip: str, end_ip: str, timeout: float = 0.8) -> None:
    """Scan an inclusive IP range for RTSP-responsive hosts using a thread pool.

    Updates ``_scan_state`` progress as checks complete and records discovered
    hosts (Requirements 7.1, 7.2). Honours the cooperative stop flag so a stop
    request halts further probing promptly (Requirement 7.4).
    """
    start = _ip_to_int(start_ip)
    end = _ip_to_int(end_ip)
    ip_count = end - start + 1
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
            sock.close()
        except Exception:
            pass
        return None

    max_workers = max(1, min(50, total))
    progress_counter = 0
    found_ip_ports: set = set()

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


# ---------------------------------------------------------------------------
# POST /api/scanner/scan — start a scan (Requirements 7.1, 7.5)
# ---------------------------------------------------------------------------
@router.post("/scan", response_model=ScanStartResult)
def start_scan(
    body: ScanStart,
    _user: AuthenticatedUser = Depends(require_permission("manage_cameras")),
) -> ScanStartResult:
    """Start a background network scan over the given IP range.

    Reports progress as a count of completed checks over a total via the status
    endpoint (Requirement 7.1). Rejects the request with ``409 conflict`` when a
    scan is already running (Requirement 7.5).
    """
    with _scan_lock:
        if _scan_state["running"]:
            raise _http_error(
                status.HTTP_409_CONFLICT,
                "a scan is already running",
                ErrorCode.CONFLICT,
            )

    s_ip = body.start_ip.strip() or "192.168.1.1"
    e_ip = body.end_ip.strip() or "192.168.1.254"
    threading.Thread(
        target=_scan_network_for_cameras,
        args=(s_ip, e_ip, body.timeout),
        daemon=True,
    ).start()
    return ScanStartResult(status="scanning", start_ip=s_ip, end_ip=e_ip)


# ---------------------------------------------------------------------------
# GET /api/scanner/status — running state, hosts, progress (Req 7.2, 7.3)
# ---------------------------------------------------------------------------
@router.get("/status", response_model=ScanStatus)
def scan_status(
    _user: AuthenticatedUser = Depends(current_user),
) -> ScanStatus:
    """Return the scan running state, discovered hosts, and current progress."""
    with _scan_lock:
        return ScanStatus(
            running=_scan_state["running"],
            hosts=[ScanHost(**h) for h in _scan_state["results"]],
            completed=_scan_state["progress"],
            total=_scan_state["total"],
        )


# ---------------------------------------------------------------------------
# POST /api/scanner/stop — halt probing (Requirement 7.4)
# ---------------------------------------------------------------------------
@router.post("/stop", response_model=ScanStopResult)
def stop_scan(
    _user: AuthenticatedUser = Depends(require_permission("manage_cameras")),
) -> ScanStopResult:
    """Clear the running flag so the background worker halts further probing."""
    with _scan_lock:
        _scan_state["running"] = False
    return ScanStopResult(status="stopped")


# ---------------------------------------------------------------------------
# POST /api/scanner/test — test whether a frame can be retrieved (Req 7.6)
# ---------------------------------------------------------------------------
@router.post("/test", response_model=TestUrlResult)
def test_rtsp_connection(
    body: TestUrlRequest,
    _user: AuthenticatedUser = Depends(require_permission("manage_cameras")),
) -> TestUrlResult:
    """Report whether a frame can be retrieved from the given RTSP URL.

    Opens the URL and attempts to read a single frame (Requirement 7.6). ``cv2``
    is imported lazily so importing this router does not require OpenCV.
    """
    import cv2

    cap = cv2.VideoCapture(body.url)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    try:
        if not cap.isOpened():
            return TestUrlResult(success=False, error="Cannot connect")
        ret, _ = cap.read()
        if not ret:
            return TestUrlResult(success=False, error="Connected but no frames received")
        return TestUrlResult(success=True)
    finally:
        cap.release()
