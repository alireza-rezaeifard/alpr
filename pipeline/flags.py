"""Feature flags for the event-based pipeline (Phase 0).

Rule: the NEW pipeline is strictly opt-in. The legacy frame-based path in
``video_processor.py`` / ``api.py`` / ``alpr_engine.py`` stays the default
until Phase 1 proves the event pipeline on replay + live linger tests.

Environment overrides (all optional):
  ALPR_PIPELINE_MODE=legacy|events      global default (default: legacy)
  ALPR_PIPELINE_RTSP=legacy|events      per-source override (unset = global)
  ALPR_PIPELINE_VIDEO=legacy|events
  ALPR_PIPELINE_IMAGE=legacy|events
  ALPR_DUAL_WRITE_DETECTIONS=0|1        legacy-row dual write (default: 1)
"""
from __future__ import annotations

import os

LEGACY = "legacy"
EVENTS = "events"

_VALID_MODES = (LEGACY, EVENTS)


def _read_mode(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip().lower()
    return value if value in _VALID_MODES else default


def get_pipeline_mode(source: str | None = None) -> str:
    """Return the pipeline mode for *source* (rtsp|video|image|None).

    Resolution order: per-source env var, then global env var, then legacy.
    Unknown values fall back to legacy (fail safe: never enable new code by
    accident).
    """
    global_mode = _read_mode("ALPR_PIPELINE_MODE", LEGACY)
    if source is None:
        return global_mode
    key = f"ALPR_PIPELINE_{source.strip().upper()}"
    if key in os.environ:
        return _read_mode(key, global_mode)
    return global_mode


def use_event_pipeline(source: str | None = None) -> bool:
    """True only when the event-based pipeline is explicitly opted in."""
    return get_pipeline_mode(source) == EVENTS


def dual_write_detections() -> bool:
    """Legacy-row dual write stays on until migration step M5 proves otherwise."""
    return os.environ.get("ALPR_DUAL_WRITE_DETECTIONS", "1").strip() != "0"


# Convenience aliases matching the task wording.
OLD_PIPELINE = LEGACY
NEW_TRACKING_PIPELINE = EVENTS
