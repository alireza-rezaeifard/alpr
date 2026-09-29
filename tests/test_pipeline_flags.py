"""Phase 0: feature flags — new pipeline disabled by default (§3.5 M3).

The legacy path in video_processor/api/alpr_engine remains the default; the
event pipeline is strictly opt-in via environment flags.
"""
from __future__ import annotations

import pytest

from pipeline import flags


def test_default_is_legacy_everywhere():
    assert flags.get_pipeline_mode() == flags.LEGACY
    assert flags.get_pipeline_mode("rtsp") == flags.LEGACY
    assert flags.get_pipeline_mode("video") == flags.LEGACY
    assert flags.get_pipeline_mode("image") == flags.LEGACY
    assert flags.use_event_pipeline() is False
    assert flags.use_event_pipeline("rtsp") is False
    assert flags.dual_write_detections() is True     # M5 keeps dual write on


def test_global_events_opt_in(monkeypatch):
    monkeypatch.setenv("ALPR_PIPELINE_MODE", "events")
    assert flags.use_event_pipeline() is True
    assert flags.use_event_pipeline("rtsp") is True  # inherits global


def test_per_source_override_wins(monkeypatch):
    monkeypatch.setenv("ALPR_PIPELINE_MODE", "events")
    monkeypatch.setenv("ALPR_PIPELINE_VIDEO", "legacy")
    assert flags.get_pipeline_mode("video") == flags.LEGACY    # stay safe
    assert flags.get_pipeline_mode("rtsp") == flags.EVENTS
    monkeypatch.delenv("ALPR_PIPELINE_VIDEO")
    assert flags.get_pipeline_mode("video") == flags.EVENTS


def test_invalid_values_fail_safe_to_legacy(monkeypatch):
    monkeypatch.setenv("ALPR_PIPELINE_MODE", "banana")
    assert flags.get_pipeline_mode() == flags.LEGACY
    monkeypatch.setenv("ALPR_PIPELINE_MODE", "EVENTS")  # case-insensitive
    assert flags.get_pipeline_mode() == flags.EVENTS


def test_dual_write_can_be_turned_off_only_explicitly(monkeypatch):
    monkeypatch.setenv("ALPR_DUAL_WRITE_DETECTIONS", "0")
    assert flags.dual_write_detections() is False
    monkeypatch.setenv("ALPR_DUAL_WRITE_DETECTIONS", "1")
    assert flags.dual_write_detections() is True


def test_aliases_document_the_contract():
    assert flags.NEW_TRACKING_PIPELINE == "events"
    assert flags.LEGACY != flags.EVENTS
