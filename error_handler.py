"""
error_handler.py
Centralized error handling for the ALPR application.

Provides:
- Typed error classes for different failure modes
- Error severity levels (info, warning, error, critical)
- Thread-safe error log with bounded size
- User-friendly error messages (supports Persian/English)
- Error formatting for UI display
"""
from __future__ import annotations

import logging
import threading
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    STREAM = "stream"          # RTSP/video stream errors
    DETECTION = "detection"    # ML model errors
    DATABASE = "database"      # DB read/write errors
    CAMERA = "camera"          # Camera management errors
    FILE_IO = "file_io"        # File read/write errors
    NETWORK = "network"        # Network connectivity errors
    VALIDATION = "validation"  # Input validation errors
    SYSTEM = "system"          # System-level errors (memory, GPU, etc.)


@dataclass
class AppError:
    """Structured error record."""
    message: str
    category: ErrorCategory
    severity: ErrorSeverity
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    details: Optional[str] = None      # Technical details / traceback
    source: Optional[str] = None       # Which component raised it
    recoverable: bool = True           # Can the system continue?
    user_message: Optional[str] = None  # Simplified message for UI

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "timestamp": self.timestamp,
            "details": self.details,
            "source": self.source,
            "recoverable": self.recoverable,
            "user_message": self.user_message or self.message,
        }


# ---------------------------------------------------------------------------
# User-friendly message templates
# ---------------------------------------------------------------------------

_USER_MESSAGES = {
    # Stream errors
    "stream_connect_failed": "Cannot connect to camera stream. Check the URL and network connection.",
    "stream_ended": "Camera stream ended unexpectedly. The camera may have disconnected.",
    "stream_timeout": "Stream connection timed out. The camera may be offline.",
    "stream_decode_error": "Failed to decode video frame. Stream may be corrupted.",

    # Detection errors
    "model_load_failed": "Failed to load the detection model. Check that model files exist.",
    "detection_failed": "Plate detection failed on current frame.",
    "recognition_failed": "Plate text recognition failed.",

    # Database errors
    "db_write_failed": "Failed to save detection to database.",
    "db_read_failed": "Failed to read from database.",
    "db_init_failed": "Failed to initialize database.",

    # Camera errors
    "camera_not_found": "Camera not found.",
    "camera_limit_reached": "Maximum concurrent camera limit reached.",
    "camera_already_running": "Camera is already running.",

    # File errors
    "file_not_found": "File not found.",
    "file_write_failed": "Failed to write output file.",
    "video_open_failed": "Cannot open video file. Format may be unsupported.",

    # Network
    "network_unreachable": "Network unreachable. Check your connection.",

    # System
    "gpu_memory": "GPU memory exhausted. Try reducing concurrent streams or resolution.",
    "system_memory": "System memory low. Close other applications.",
}


# ---------------------------------------------------------------------------
# Global Error Store (thread-safe, bounded)
# ---------------------------------------------------------------------------

class ErrorStore:
    """Thread-safe bounded error log with subscription support."""

    _MAX_ERRORS = 200

    def __init__(self):
        self._lock = threading.Lock()
        self._errors: deque[AppError] = deque(maxlen=self._MAX_ERRORS)
        self._subscribers: list[Callable[[AppError], None]] = []
        self._unread_count = 0

    def add(self, error: AppError) -> None:
        """Add an error and notify subscribers."""
        with self._lock:
            self._errors.append(error)
            self._unread_count += 1

        # Log based on severity
        log_msg = f"[{error.category.value}] {error.message}"
        if error.severity == ErrorSeverity.CRITICAL:
            logger.critical(log_msg)
        elif error.severity == ErrorSeverity.ERROR:
            logger.error(log_msg)
        elif error.severity == ErrorSeverity.WARNING:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        # Notify subscribers (non-blocking)
        for sub in self._subscribers:
            try:
                sub(error)
            except Exception:
                pass

    def get_recent(self, count: int = 20) -> list[dict]:
        """Return the N most recent errors as dicts."""
        with self._lock:
            errors = list(self._errors)[-count:]
            return [e.to_dict() for e in reversed(errors)]

    def get_unread_count(self) -> int:
        with self._lock:
            return self._unread_count

    def mark_read(self) -> None:
        with self._lock:
            self._unread_count = 0

    def clear(self) -> None:
        with self._lock:
            self._errors.clear()
            self._unread_count = 0

    def subscribe(self, callback: Callable[[AppError], None]) -> None:
        """Register a callback for new errors."""
        self._subscribers.append(callback)

    def get_by_category(self, category: ErrorCategory, count: int = 10) -> list[dict]:
        with self._lock:
            filtered = [e for e in self._errors if e.category == category]
            return [e.to_dict() for e in filtered[-count:]]


# Singleton instance
error_store = ErrorStore()


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def report_error(
    message: str,
    category: ErrorCategory,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
    source: Optional[str] = None,
    details: Optional[str] = None,
    user_key: Optional[str] = None,
    recoverable: bool = True,
) -> AppError:
    """Create, store, and return a structured error."""
    user_msg = _USER_MESSAGES.get(user_key) if user_key else None
    error = AppError(
        message=message,
        category=category,
        severity=severity,
        source=source,
        details=details,
        recoverable=recoverable,
        user_message=user_msg,
    )
    error_store.add(error)
    return error


def report_exception(
    exc: Exception,
    category: ErrorCategory,
    source: Optional[str] = None,
    user_key: Optional[str] = None,
    recoverable: bool = True,
) -> AppError:
    """Report an exception with full traceback."""
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return report_error(
        message=str(exc),
        category=category,
        severity=ErrorSeverity.ERROR,
        source=source,
        details="".join(tb),
        user_key=user_key,
        recoverable=recoverable,
    )


def report_stream_error(message: str, source: str = "rtsp", user_key: Optional[str] = None) -> AppError:
    """Shortcut for stream-related errors."""
    return report_error(message, ErrorCategory.STREAM, source=source, user_key=user_key)


def report_detection_error(exc: Exception, source: str = "detection") -> AppError:
    """Shortcut for ML detection errors."""
    return report_exception(exc, ErrorCategory.DETECTION, source=source, user_key="detection_failed")


def report_db_error(exc: Exception, operation: str = "write") -> AppError:
    """Shortcut for database errors."""
    key = "db_write_failed" if "write" in operation or "save" in operation else "db_read_failed"
    return report_exception(exc, ErrorCategory.DATABASE, source=f"db.{operation}", user_key=key)


# ---------------------------------------------------------------------------
# UI formatting helpers
# ---------------------------------------------------------------------------

_SEVERITY_ICONS = {
    ErrorSeverity.INFO: "ℹ️",
    ErrorSeverity.WARNING: "⚠️",
    ErrorSeverity.ERROR: "❌",
    ErrorSeverity.CRITICAL: "🔴",
}

_SEVERITY_COLORS = {
    ErrorSeverity.INFO: "var(--primary-light)",
    ErrorSeverity.WARNING: "var(--warning)",
    ErrorSeverity.ERROR: "var(--danger)",
    ErrorSeverity.CRITICAL: "#dc2626",
}


def format_errors_html(count: int = 10) -> str:
    """Render recent errors as an HTML panel for Gradio."""
    errors = error_store.get_recent(count)
    if not errors:
        return '<div style="padding:12px;color:var(--text-muted);font-size:13px">No errors recorded.</div>'

    rows = []
    for e in errors:
        sev = ErrorSeverity(e["severity"])
        icon = _SEVERITY_ICONS.get(sev, "")
        color = _SEVERITY_COLORS.get(sev, "var(--text)")
        time_str = e["timestamp"][11:19] if len(e["timestamp"]) > 19 else e["timestamp"]
        msg = e["user_message"] or e["message"]
        cat = e["category"]
        rows.append(
            f'<div style="padding:8px 12px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px">'
            f'<span style="font-size:14px">{icon}</span>'
            f'<span style="color:var(--text-muted);font-size:11px;min-width:55px">{time_str}</span>'
            f'<span style="color:{color};font-size:12px;min-width:70px;font-weight:500">[{cat}]</span>'
            f'<span style="color:var(--text);font-size:13px">{msg}</span>'
            f'</div>'
        )
    return f'<div style="max-height:300px;overflow-y:auto;border:1px solid var(--border);border-radius:8px;background:var(--surface)">{"".join(rows)}</div>'


def get_error_badge() -> str:
    """Return an HTML badge showing unread error count, or empty string."""
    count = error_store.get_unread_count()
    if count == 0:
        return ""
    return f'<span style="background:var(--danger);color:white;border-radius:50%;padding:2px 7px;font-size:11px;font-weight:700;margin-left:6px">{count}</span>'


def get_latest_error_toast(category: ErrorCategory | None = None, max_age_sec: float = 10.0) -> str:
    """Return the most recent user-facing error message if it's recent enough.

    Useful for showing inline status/toast messages in the UI without
    requiring the user to check the Errors tab.
    Returns empty string if no recent error matches.
    """
    errors = error_store.get_recent(5)
    if not errors:
        return ""
    from datetime import datetime as _dt
    now = _dt.now()
    for e in errors:
        if category and e["category"] != category.value:
            continue
        try:
            ts = _dt.fromisoformat(e["timestamp"])
            age = (now - ts).total_seconds()
            if age <= max_age_sec:
                sev = ErrorSeverity(e["severity"])
                icon = _SEVERITY_ICONS.get(sev, "")
                msg = e.get("user_message") or e["message"]
                return f"{icon} {msg}"
        except (ValueError, TypeError):
            continue
    return ""
