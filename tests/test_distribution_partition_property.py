"""
Property-based test for distribution partitioning (task 16.4).

Feature: anpr-system-redesign, Property 25

Property 25: Distribution groupings partition the detection set.
    A distribution grouping (source distribution, Req 13.5; confidence
    distribution, Req 13.6) must *partition* the set of stored detections:
        * the sum of all group counts equals the total number of detections
          (collectively exhaustive — nothing is omitted),
        * group keys are unique so no detection is counted twice (mutually
          exclusive — no double-counting),
        * for source distribution the set of group keys equals the set of
          distinct source types present in the data, and for confidence
          distribution every group count is positive and accounted for.

Validates: Requirements 13.5, 13.6

Mechanism under test:
    * ``db.save_detection`` persists a detection attributed to a session.
    * ``db.get_source_distribution`` groups detections by ``source_type``.
    * ``db.get_confidence_distribution`` groups detections by a rounded
      confidence bin.

Both grouping helpers are exercised directly against a temporary SQLite
database so the partitioning is tested for real (no mocks).
"""
from __future__ import annotations

import os
import sys

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Ensure the project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Point db at a fresh temp SQLite file initialized with the real schema."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "distribution_partition_test.db"))
    db.init_db()
    yield db


def _reset():
    """Clear sessions and detections so each generated example starts clean."""
    conn = db.get_conn()
    conn.execute("DELETE FROM detections")
    conn.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()


# --- Generators ---------------------------------------------------------------
# A small fixed source-type domain so groups aggregate across many detections.
source_types = st.sampled_from(["image", "video", "rtsp", "camera"])
confidence = st.floats(min_value=0.0, max_value=1.0)

# A detection is (source_type, confidence).
detection_spec = st.tuples(source_types, confidence)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(detections=st.lists(detection_spec, max_size=25))
def test_distributions_partition_detection_set(fresh_db, detections):
    """Source and confidence distributions partition the stored detections."""
    _reset()

    session_id = db.start_session("image", "partition-src")

    expected_source_types = set()
    for source_type, conf in detections:
        db.save_detection(
            session_id,
            source_type,
            plate_dtrb="",
            plate_persian="",
            confidence=conf,
            source_file="partition",
        )
        expected_source_types.add(source_type)

    total = len(detections)

    # --- Source distribution (Req 13.5) --------------------------------------
    source_dist = db.get_source_distribution()
    source_keys = [g["source_type"] for g in source_dist]

    # No double-counting: each group key appears exactly once.
    assert len(source_keys) == len(set(source_keys))
    # Mutually exclusive + collectively exhaustive: group keys are exactly the
    # distinct source types present in the data.
    assert set(source_keys) == expected_source_types
    # Counts are positive and sum to the total detection count (no omissions).
    assert all(g["cnt"] > 0 for g in source_dist)
    assert sum(g["cnt"] for g in source_dist) == total

    # --- Confidence distribution (Req 13.6) ----------------------------------
    confidence_dist = db.get_confidence_distribution()
    confidence_bins = [g["bin"] for g in confidence_dist]

    # No double-counting: each bin appears exactly once.
    assert len(confidence_bins) == len(set(confidence_bins))
    # Counts are positive and sum to the total detection count (no omissions).
    assert all(g["cnt"] > 0 for g in confidence_dist)
    assert sum(g["cnt"] for g in confidence_dist) == total
