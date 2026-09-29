"""Phase 1: feature-flag wiring compatibility tests (task §3, §11).

The legacy path must remain the default; the event pipeline must engage only
when explicitly opted in, and invalid configuration must fail safe to legacy.
"""
from __future__ import annotations

import importlib
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture()
def video_processor_mod(monkeypatch):
    """Import video_processor fresh for each test (flag read at construction)."""
    import video_processor
    importlib.reload(video_processor)
    yield video_processor


class _StubEngine:
    pass


# ---------------------------------------------------------------------------
# Legacy flag disabled (default)
# ---------------------------------------------------------------------------

def test_rtsp_processor_legacy_by_default(video_processor_mod):
    proc = video_processor_mod.RTSPStreamProcessor(_StubEngine(), "rtsp://x")
    assert proc.event_pipeline is None


def test_video_processor_legacy_by_default(video_processor_mod):
    proc = video_processor_mod.VideoProcessor(_StubEngine())
    assert proc.event_pipeline is None


# ---------------------------------------------------------------------------
# New flag enabled
# ---------------------------------------------------------------------------

def test_rtsp_processor_events_opt_in(video_processor_mod, monkeypatch):
    monkeypatch.setenv("ALPR_PIPELINE_RTSP", "events")
    proc = video_processor_mod.RTSPStreamProcessor(_StubEngine(), "rtsp://x",
                                                   camera_id=7)
    assert proc.event_pipeline is not None
    assert proc.event_pipeline.camera_id == 7
    assert proc.event_pipeline.source_type == "rtsp"


def test_video_processor_events_opt_in(video_processor_mod, monkeypatch):
    monkeypatch.setenv("ALPR_PIPELINE_MODE", "events")
    monkeypatch.setenv("ALPR_PIPELINE_VIDEO", "events")
    proc = video_processor_mod.VideoProcessor(_StubEngine())
    assert proc.event_pipeline is not None
    assert proc.event_pipeline.source_type == "video"


def test_global_mode_does_not_enable_rtsp_unless_sources_opt_in(
        video_processor_mod, monkeypatch):
    # Per-source default: only ALPR_PIPELINE_MODE=events opts RTSP in too.
    monkeypatch.setenv("ALPR_PIPELINE_MODE", "events")
    proc = video_processor_mod.RTSPStreamProcessor(_StubEngine(), "rtsp://x")
    assert proc.event_pipeline is not None
    monkeypatch.setenv("ALPR_PIPELINE_RTSP", "legacy")
    proc = video_processor_mod.RTSPStreamProcessor(_StubEngine(), "rtsp://x")
    assert proc.event_pipeline is None


# ---------------------------------------------------------------------------
# Invalid / missing configuration fails safe to legacy
# ---------------------------------------------------------------------------

def test_invalid_flag_value_fails_safe(video_processor_mod, monkeypatch):
    monkeypatch.setenv("ALPR_PIPELINE_RTSP", "banana")
    proc = video_processor_mod.RTSPStreamProcessor(_StubEngine(), "rtsp://x")
    assert proc.event_pipeline is None


def test_wiring_error_fails_safe(video_processor_mod, monkeypatch):
    monkeypatch.setenv("ALPR_PIPELINE_RTSP", "events")
    # Simulate a broken pipeline package: legacy must still be constructible.
    import builtins
    real_import = builtins.__import__

    def broken(name, *a, **k):
        if name.startswith("pipeline.integration"):
            raise RuntimeError("boom")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", broken)
    proc = video_processor_mod.RTSPStreamProcessor(_StubEngine(), "rtsp://x")
    assert proc.event_pipeline is None  # degraded to legacy, not crashed


# ---------------------------------------------------------------------------
# Disabling the flag restores previous processing behavior
# ---------------------------------------------------------------------------

def test_disable_restores_legacy_dedup_path(video_processor_mod, monkeypatch):
    monkeypatch.setenv("ALPR_PIPELINE_RTSP", "events")
    proc = video_processor_mod.RTSPStreamProcessor(_StubEngine(), "rtsp://x")
    assert proc.event_pipeline is not None
    monkeypatch.setenv("ALPR_PIPELINE_RTSP", "legacy")
    proc2 = video_processor_mod.RTSPStreamProcessor(_StubEngine(), "rtsp://x")
    assert proc2.event_pipeline is None
    # The legacy dedup state is still present and used.
    assert proc2._recent_emit_times == {}
    assert proc2._DEDUP_WINDOW_SECONDS == 60.0


# ---------------------------------------------------------------------------
# Existing API/history contract untouched (additive only)
# ---------------------------------------------------------------------------

def test_rtsp_status_shape_additive_only(video_processor_mod, monkeypatch):
    """With the flag OFF, the status endpoint payload keys are exactly the
    legacy set plus the additive (nullable) 'pipeline' key."""
    monkeypatch.delenv("ALPR_PIPELINE_RTSP", raising=False)
    monkeypatch.delenv("ALPR_PIPELINE_MODE", raising=False)
    proc = video_processor_mod.RTSPStreamProcessor(_StubEngine(), "rtsp://x")
    state = proc.get_state()
    assert set(state.keys()) == {"running", "status", "history",
                                 "live_detections", "error_message",
                                 "annotated", "jpeg_bytes"}
