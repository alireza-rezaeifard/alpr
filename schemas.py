"""
schemas.py
Pydantic request/response models for new and validated API endpoints.
Requirements: 11.1, 12.2, 14.7
"""
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field


class CameraCreate(BaseModel):
    name: str = Field("", max_length=100)          # empty name allowed (Req 11.2)
    url: str
    skip_frames: int | None = Field(None, ge=1, le=1000)


class CameraUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    url: str | None = None
    skip_frames: int | None = Field(None, ge=1, le=1000)


class CameraView(BaseModel):
    id: int
    name: str
    url: str
    skip_frames: int
    status: str            # stopped|queued|connecting|connected|streaming|error
    task_id: str | None = None
    session_id: int | None = None


class StartResult(BaseModel):
    camera_id: int
    status: str            # running|queued|error
    task_id: str | None = None


class StopResult(BaseModel):
    status: str


class ConcurrencyConfig(BaseModel):
    value: int = Field(..., ge=1, le=64)           # Req 12.2/12.8


class ConcurrencyView(BaseModel):
    concurrency_limit: int


class PlateMetadataResponse(BaseModel):
    classified: bool
    category: str | None = None
    category_display: str | None = None
    color_scheme: str | None = None               # white|yellow|green|red|blue|black
    region_code: str | None = None
    region_name: str | None = None
    special_note: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Network camera scanner envelopes (Req 7.1-7.6)
# ---------------------------------------------------------------------------
class ScanStart(BaseModel):
    """Request to start a network scan over an inclusive IPv4 range (Req 7.1).

    ``start_ip``/``end_ip`` bound the range probed for RTSP-responsive hosts.
    ``timeout`` is the per-socket connect timeout in seconds.
    """
    start_ip: str = Field("192.168.1.1")
    end_ip: str = Field("192.168.1.254")
    timeout: float = Field(0.8, gt=0, le=30)


class ScanHost(BaseModel):
    """An RTSP-responsive host discovered during a scan (Req 7.2)."""
    ip: str
    port: int
    brand: str
    server: str | None = None


class ScanStartResult(BaseModel):
    """Acknowledgement that a scan has been started (Req 7.1)."""
    status: str                        # scanning
    start_ip: str
    end_ip: str


class ScanStatus(BaseModel):
    """Current scan running state, discovered hosts, and progress (Req 7.3)."""
    running: bool
    hosts: list[ScanHost] = Field(default_factory=list)
    completed: int                     # checks completed so far
    total: int                         # total checks planned


class ScanStopResult(BaseModel):
    """Acknowledgement that a scan has been stopped (Req 7.4)."""
    status: str                        # stopped


class TestUrlRequest(BaseModel):
    """Request to test whether a frame can be retrieved from an RTSP URL (Req 7.6)."""
    url: str


class TestUrlResult(BaseModel):
    """Result of an RTSP URL frame-retrieval test (Req 7.6)."""
    success: bool
    error: str | None = None


# ---------------------------------------------------------------------------
# Authentication & user management envelopes (Req 1.1, 2.x)
# ---------------------------------------------------------------------------
class LoginResponse(BaseModel):
    """Issued on successful login (Req 1.1)."""
    token: str
    role: str                          # Admin|Operator|Viewer
    expires_at: str                    # ISO-8601 expiry timestamp
    permissions: list[str] = Field(default_factory=list)


class UserView(BaseModel):
    """Public view of a user account (Req 2.x)."""
    id: int
    username: str
    role: str                          # Admin|Operator|Viewer
    disabled: bool
    created_at: str


# ---------------------------------------------------------------------------
# License management envelope (Req 3.1, 3.5)
# ---------------------------------------------------------------------------
class LicenseActivate(BaseModel):
    """License activation request carrying the encoded key (Req 3.1)."""
    key: str


class LicenseStatus(BaseModel):
    """License activation state and limits (Req 3.5)."""
    active: bool
    expiry: str | None = None          # ISO date; null when no license active
    camera_limit: int | None = None
    configured_cameras: int


# ---------------------------------------------------------------------------
# Watchlist & alert envelopes (Req 12.x)
# ---------------------------------------------------------------------------
class WatchlistEntryView(BaseModel):
    """A single plate entry within a watchlist (Req 12.2)."""
    id: int
    watchlist_id: int
    plate_value: str                   # raw plate value as supplied
    label: str | None = None
    reason: str | None = None
    created_at: str


class WatchlistView(BaseModel):
    """A watchlist with its entries (Req 12.1)."""
    id: int
    name: str
    list_type: str                     # e.g. blocklist|allowlist
    created_at: str
    entries: list[WatchlistEntryView] = Field(default_factory=list)


class AlertView(BaseModel):
    """An alert raised when a detection matches a watchlist entry (Req 12.4)."""
    id: int
    detection_id: int
    entry_id: int
    plate_value: str
    created_at: str


# ---------------------------------------------------------------------------
# Audit logging & retention envelopes (Req 15.x, 16.x)
# ---------------------------------------------------------------------------
class AuditEntryView(BaseModel):
    """An append-only audit log entry (Req 15.2)."""
    id: int
    username: str | None = None
    action: str
    resource: str | None = None
    outcome: str
    timestamp: str


class RetentionConfig(BaseModel):
    """Data retention policy: maximum age in days (Req 16.1)."""
    days: int


# ---------------------------------------------------------------------------
# Error envelope (Req 1.x, 2.x, 3.x, 13.x, etc.)
# ---------------------------------------------------------------------------
class ErrorCode(str, Enum):
    """Stable machine-readable error codes returned in error responses."""
    AUTH_REQUIRED = "auth_required"
    AUTH_FAILED = "auth_failed"
    FORBIDDEN = "forbidden"
    LICENSE_REQUIRED = "license_required"
    LICENSE_EXPIRED = "license_expired"
    LICENSE_LIMIT = "license_limit"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"


class ErrorResponse(BaseModel):
    """Standard error envelope `{ error, code }`."""
    error: str                         # human-readable message
    code: ErrorCode                    # machine-readable code
