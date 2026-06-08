"""
tests/test_scanner_integration.py
Integration tests for Task 10.2: network scanner probe/record/stop/test-url
flows and the scan-already-running conflict.

These tests call the router functions in ``routers.scanner`` directly, passing a
fake :class:`AuthenticatedUser` for the ``_user`` parameter so the
``require_permission`` / ``current_user`` ``Depends`` are bypassed (no real auth
wiring needed). Real network I/O is avoided by monkeypatching
``_scan_network_for_cameras`` (so starting a scan never probes), and OpenCV is
avoided by monkeypatching ``cv2.VideoCapture`` for the test-url flow.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
"""
from __future__ import annotations

import sys
import types

import pytest

import routers.scanner as scanner
from auth.dependencies import AuthenticatedUser
from fastapi import HTTPException

from schemas import ScanStart, TestUrlRequest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
def _fake_user() -> AuthenticatedUser:
    """A stand-in identity for the ``_user`` parameter of the endpoints."""
    return AuthenticatedUser(
        id=1,
        username="operator",
        role="Operator",
        disabled=False,
        jti="test-jti",
        token_exp=9999999999,
    )


@pytest.fixture(autouse=True)
def reset_scan_state():
    """Reset module-level scan state before and after each test to avoid leakage."""
    scanner._scan_state.update(
        {"running": False, "results": [], "progress": 0, "total": 0}
    )
    yield
    scanner._scan_state.update(
        {"running": False, "results": [], "progress": 0, "total": 0}
    )


# ---------------------------------------------------------------------------
# POST /api/scanner/scan — start (Req 7.1) and conflict (Req 7.5)
# ---------------------------------------------------------------------------
def test_start_scan_returns_scanning_ack(monkeypatch):
    """Starting a scan returns a scanning acknowledgement with the IP range (Req 7.1)."""
    called = {}

    def fake_scan(start_ip, end_ip, timeout):
        called["args"] = (start_ip, end_ip, timeout)

    monkeypatch.setattr(scanner, "_scan_network_for_cameras", fake_scan)

    result = scanner.start_scan(
        ScanStart(start_ip="192.168.1.10", end_ip="192.168.1.20", timeout=0.5),
        _user=_fake_user(),
    )

    assert result.status == "scanning"
    assert result.start_ip == "192.168.1.10"
    assert result.end_ip == "192.168.1.20"


def test_start_scan_uses_defaults_for_blank_ips(monkeypatch):
    """Blank IPs fall back to the default range (Req 7.1)."""
    monkeypatch.setattr(scanner, "_scan_network_for_cameras", lambda *a, **k: None)

    result = scanner.start_scan(
        ScanStart(start_ip="   ", end_ip="   ", timeout=0.8),
        _user=_fake_user(),
    )

    assert result.start_ip == "192.168.1.1"
    assert result.end_ip == "192.168.1.254"


def test_start_scan_conflict_when_already_running(monkeypatch):
    """A second start while a scan is running is rejected with 409 conflict (Req 7.5)."""
    # Ensure no thread is actually spawned even if the guard were bypassed.
    monkeypatch.setattr(scanner, "_scan_network_for_cameras", lambda *a, **k: None)
    scanner._scan_state["running"] = True

    with pytest.raises(HTTPException) as exc_info:
        scanner.start_scan(
            ScanStart(start_ip="192.168.1.1", end_ip="192.168.1.254", timeout=0.8),
            _user=_fake_user(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "conflict"


# ---------------------------------------------------------------------------
# GET /api/scanner/status — probe/record + progress (Req 7.2, 7.3)
# ---------------------------------------------------------------------------
def test_status_reflects_discovered_hosts_and_progress(monkeypatch):
    """Status reports discovered hosts and progress recorded by the scan (Req 7.2, 7.3)."""

    def fake_scan(start_ip, end_ip, timeout):
        # Simulate the worker populating state synchronously.
        scanner._scan_state["running"] = True
        scanner._scan_state["total"] = 12
        scanner._scan_state["progress"] = 12
        scanner._scan_state["results"] = [
            {"ip": "192.168.1.10", "port": 554, "brand": "Hikvision", "server": "Hikvision"},
            {"ip": "192.168.1.11", "port": 8554, "brand": "Dahua", "server": ""},
        ]
        scanner._scan_state["running"] = False

    monkeypatch.setattr(scanner, "_scan_network_for_cameras", fake_scan)

    # Start the scan, then run the (synchronous) fake worker to record results.
    scanner.start_scan(
        ScanStart(start_ip="192.168.1.10", end_ip="192.168.1.11", timeout=0.5),
        _user=_fake_user(),
    )
    fake_scan("192.168.1.10", "192.168.1.11", 0.5)

    status = scanner.scan_status(_user=_fake_user())

    assert status.running is False
    assert status.completed == 12
    assert status.total == 12
    assert len(status.hosts) == 2
    assert status.hosts[0].ip == "192.168.1.10"
    assert status.hosts[0].port == 554
    assert status.hosts[0].brand == "Hikvision"
    assert status.hosts[1].ip == "192.168.1.11"
    assert status.hosts[1].brand == "Dahua"


def test_status_running_with_partial_progress():
    """Status reports an in-progress scan with partial progress (Req 7.3)."""
    scanner._scan_state.update(
        {"running": True, "results": [], "progress": 3, "total": 18}
    )

    status = scanner.scan_status(_user=_fake_user())

    assert status.running is True
    assert status.completed == 3
    assert status.total == 18
    assert status.hosts == []


# ---------------------------------------------------------------------------
# POST /api/scanner/stop — halt (Req 7.4)
# ---------------------------------------------------------------------------
def test_stop_scan_clears_running_flag():
    """Stopping a running scan clears the flag and reports stopped (Req 7.4)."""
    scanner._scan_state["running"] = True

    result = scanner.stop_scan(_user=_fake_user())

    assert result.status == "stopped"
    assert scanner._scan_state["running"] is False


def test_stop_scan_idempotent_when_not_running():
    """Stop is safe even when no scan is running (Req 7.4)."""
    scanner._scan_state["running"] = False

    result = scanner.stop_scan(_user=_fake_user())

    assert result.status == "stopped"
    assert scanner._scan_state["running"] is False


# ---------------------------------------------------------------------------
# POST /api/scanner/test — RTSP URL frame test (Req 7.6)
# ---------------------------------------------------------------------------
class _FakeCapture:
    """Minimal stand-in for cv2.VideoCapture used by the test-url endpoint."""

    def __init__(self, opened: bool, frame_ok: bool):
        self._opened = opened
        self._frame_ok = frame_ok
        self.released = False

    def set(self, prop, value):  # noqa: D401 - mirrors cv2 API
        return True

    def isOpened(self):
        return self._opened

    def read(self):
        if self._frame_ok:
            return True, object()  # ret=True, a frame object
        return False, None

    def release(self):
        self.released = True


def _install_fake_cv2(monkeypatch, opened: bool, frame_ok: bool):
    """Install a fake ``cv2`` module so the endpoint's ``import cv2`` resolves it."""
    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.CAP_PROP_BUFFERSIZE = 38  # arbitrary; matches cv2's constant slot
    captures = []

    def _factory(url):
        cap = _FakeCapture(opened, frame_ok)
        captures.append(cap)
        return cap

    fake_cv2.VideoCapture = _factory
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    return captures


def test_test_url_success_when_frame_retrieved(monkeypatch):
    """A retrievable frame yields success=True (Req 7.6)."""
    captures = _install_fake_cv2(monkeypatch, opened=True, frame_ok=True)

    result = scanner.test_rtsp_connection(
        TestUrlRequest(url="rtsp://example/stream"),
        _user=_fake_user(),
    )

    assert result.success is True
    assert result.error is None
    assert captures and captures[0].released is True  # capture released


def test_test_url_failure_when_cannot_connect(monkeypatch):
    """An unopenable capture yields success=False with a connect error (Req 7.6)."""
    captures = _install_fake_cv2(monkeypatch, opened=False, frame_ok=False)

    result = scanner.test_rtsp_connection(
        TestUrlRequest(url="rtsp://unreachable/stream"),
        _user=_fake_user(),
    )

    assert result.success is False
    assert result.error == "Cannot connect"
    assert captures and captures[0].released is True


def test_test_url_failure_when_no_frame(monkeypatch):
    """An opened capture that returns no frame yields success=False (Req 7.6)."""
    captures = _install_fake_cv2(monkeypatch, opened=True, frame_ok=False)

    result = scanner.test_rtsp_connection(
        TestUrlRequest(url="rtsp://example/noframe"),
        _user=_fake_user(),
    )

    assert result.success is False
    assert result.error == "Connected but no frames received"
    assert captures and captures[0].released is True
