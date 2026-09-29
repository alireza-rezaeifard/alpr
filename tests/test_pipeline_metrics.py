"""Phase 0: structured metrics (design Appendix E.1, D.1 row 2)."""
from __future__ import annotations

from pipeline.metrics import EMA_ALPHA, PipelineMetrics


def test_counters_increment_per_scope():
    m = PipelineMetrics()
    m.inc("cam1", "frames_captured")
    m.inc("cam1", "frames_captured")
    m.inc("cam1", "frames_skipped_schedule")
    m.inc("cam2", "frames_captured")
    snap = m.snapshot()
    assert snap["counters"]["cam1"]["frames_captured"] == 2
    assert snap["counters"]["cam1"]["frames_skipped_schedule"] == 1
    assert snap["counters"]["cam2"]["frames_captured"] == 1
    assert "captured_at" in snap


def test_gauges_last_value_wins():
    m = PipelineMetrics()
    m.set_gauge("cam1", "live_tracks", 3)
    m.set_gauge("cam1", "live_tracks", 5)
    assert m.snapshot()["gauges"]["cam1"]["live_tracks"] == 5.0


def test_latency_ema_math():
    m = PipelineMetrics()
    m.observe_latency("cam1", "last_inference_ms_ema", 100.0)
    first = m.snapshot()["ema_ms"]["cam1"]["last_inference_ms_ema"]
    assert first == 100.0                      # first sample seeds the EMA
    m.observe_latency("cam1", "last_inference_ms_ema", 200.0)
    second = m.snapshot()["ema_ms"]["cam1"]["last_inference_ms_ema"]
    expected = EMA_ALPHA * 200.0 + (1.0 - EMA_ALPHA) * 100.0
    assert abs(second - expected) < 1e-9


def test_snapshot_is_json_serialisable():
    import json
    m = PipelineMetrics()
    m.inc("p", "events_emitted")
    m.set_gauge("p", "db_queue_depth", 1.0)
    m.observe_latency("p", "e2e_ms", 12.5)
    json.dumps(m.snapshot())  # must not raise


def test_reset_scope_clears_only_that_scope():
    m = PipelineMetrics()
    m.inc("a", "x")
    m.inc("b", "x")
    m.reset_scope("a")
    snap = m.snapshot()
    assert "a" not in snap["counters"]
    assert snap["counters"]["b"]["x"] == 1
