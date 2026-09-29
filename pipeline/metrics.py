"""Structured pipeline metrics (design Appendix E.1).

Simple counters, last-value gauges, and α=0.2 exponential moving averages.
``snapshot()`` returns plain JSON-serialisable dicts — exactly what
``GET /api/events/health`` will serve in Phase 3. threading.Lock guards
mutations; readers never block writers for long.
"""
from __future__ import annotations

import threading
import time

EMA_ALPHA = 0.2


class PipelineMetrics:
    """Thread-safe metric registry with per-camera and process scopes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[str, int]] = {}
        self._gauges: dict[str, dict[str, float]] = {}
        self._ema: dict[str, dict[str, float]] = {}

    # -- mutation ------------------------------------------------------
    def inc(self, scope: str, name: str, amount: int = 1) -> None:
        """Increment a counter (families: frames, inference, tracker,
        consensus, sinks, alerts — Appendix E.1)."""
        with self._lock:
            self._counters.setdefault(scope, {}).setdefault(name, 0)
            self._counters[scope][name] += amount

    def set_gauge(self, scope: str, name: str, value: float) -> None:
        """Set a last-value gauge (e.g. live_tracks, queue depths)."""
        with self._lock:
            self._gauges.setdefault(scope, {})[name] = float(value)

    def observe_latency(self, scope: str, name: str, ms: float) -> None:
        """Record a latency sample as an EMA (e.g. *_ms_ema)."""
        with self._lock:
            bucket = self._ema.setdefault(scope, {})
            previous = bucket.get(name)
            bucket[name] = ms if previous is None else (
                EMA_ALPHA * ms + (1.0 - EMA_ALPHA) * previous
            )

    # -- reading -------------------------------------------------------
    def snapshot(self) -> dict:
        """Return a JSON-serialisable snapshot of all scopes."""
        with self._lock:
            return {
                "captured_at": time.time(),
                "counters": {s: dict(c) for s, c in self._counters.items()},
                "gauges": {s: dict(g) for s, g in self._gauges.items()},
                "ema_ms": {s: dict(e) for s, e in self._ema.items()},
            }

    def reset_scope(self, scope: str) -> None:
        """Clear one scope (tests and camera teardown)."""
        with self._lock:
            self._counters.pop(scope, None)
            self._gauges.pop(scope, None)
            self._ema.pop(scope, None)


# Process-global registry; Phase 0 tests use fresh instances instead.
GLOBAL_METRICS = PipelineMetrics()
