"""
Property-based test for retention pruning correctness (task 16.13).

Feature: anpr-system-redesign, Property 30

Property 30: Retention pruning removes exactly the records older than the cutoff.
    For any set of detection records and any retention policy of days greater
    than zero, ``prune_detections(now)`` removes exactly the detections whose
    timestamp is older than ``now - days`` and retains all others; when no
    policy is configured pruning removes nothing; and any attempt to set a
    policy of zero or fewer days is rejected with a validation error.

Validates: Requirements 16.1, 16.2, 16.3, 16.4

Mechanism under test:
    * ``retention.service.set_retention_policy(days)`` persists the policy when
      ``days > 0`` (Req 16.1) and raises ``RetentionPolicyError`` when
      ``days <= 0`` (Req 16.4).
    * ``retention.policy.retention_cutoff(now, days)`` computes ``now - days``
      (Req 16.3).
    * ``retention.service.prune_detections(now)`` deletes detections older than
      the cutoff while a policy is active (Req 16.2) and retains everything when
      no policy is configured (Req 16.4 / 16.3).

The pruning is exercised directly against a temporary SQLite database (no
mocks). A pure-Python reference model recomputes which detections should be
deleted/retained and the test asserts the database agrees exactly.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Ensure the project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from retention.policy import retention_cutoff
from retention.service import (
    RetentionPolicyError,
    prune_detections,
    set_retention_policy,
)

# A fixed reference "now" with no microseconds so every generated ISO timestamp
# shares the same textual format. SQLite compares the TEXT timestamp column
# lexicographically, which equals chronological ordering only when the format is
# uniform - which it is here.
NOW = datetime(2024, 6, 15, 12, 0, 0)

SECONDS_PER_DAY = 86_400


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Point db at a fresh temp SQLite file initialized with the real schema."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "retention_pruning_test.db"))
    db.init_db()
    yield db


def _reset():
    """Clear sessions/detections and reset the retention config between examples."""
    conn = db.get_conn()
    conn.execute("DELETE FROM detections")
    conn.execute("DELETE FROM sessions")
    conn.execute("DELETE FROM app_config WHERE key = 'retention_days'")
    conn.commit()
    conn.close()


def _insert_detection(session_id: int, tag: str, timestamp: datetime) -> None:
    """Insert one detection with an explicit timestamp and identifying tag."""
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO detections "
        "(session_id, source_type, plate_dtrb, plate_persian, confidence, timestamp) "
        "VALUES (?, 'test', ?, '-', 0.5, ?)",
        (session_id, tag, timestamp.isoformat()),
    )
    conn.commit()
    conn.close()


def _remaining_tags() -> set[str]:
    conn = db.get_conn()
    rows = conn.execute("SELECT plate_dtrb FROM detections").fetchall()
    conn.close()
    return {r["plate_dtrb"] for r in rows}


# --- Generators ---------------------------------------------------------------
# Each detection is identified by its index and given an "age" in seconds before
# NOW. The range spans ~0 to ~400 days so the cutoff (1..365 days) lands inside
# the population, exercising both deletion and retention plus the exact boundary.
age_seconds = st.integers(min_value=0, max_value=400 * SECONDS_PER_DAY)
policy_days = st.integers(min_value=1, max_value=365)


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(ages=st.lists(age_seconds, max_size=25), days=policy_days)
def test_prune_removes_exactly_records_older_than_cutoff(fresh_db, ages, days):
    """Req 16.2/16.3: with an active policy, prune deletes exactly the records
    whose timestamp is older than ``now - days`` and retains all others."""
    _reset()
    set_retention_policy(days)

    session_id = db.start_session("test", "retention-src")

    cutoff = retention_cutoff(NOW, days)
    expected_retained: set[str] = set()
    expected_deleted_count = 0
    for i, age in enumerate(ages):
        tag = f"d{i}"
        ts = NOW - timedelta(seconds=age)
        _insert_detection(session_id, tag, ts)
        # Deletion is strict (timestamp < cutoff); a timestamp equal to the
        # cutoff is retained.
        if ts < cutoff:
            expected_deleted_count += 1
        else:
            expected_retained.add(tag)

    deleted = prune_detections(NOW)

    assert deleted == expected_deleted_count
    assert _remaining_tags() == expected_retained


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(ages=st.lists(age_seconds, max_size=25))
def test_prune_retains_all_when_no_policy_configured(fresh_db, ages):
    """Req 16.4/16.3: when no retention policy is configured, prune removes
    nothing and every detection is retained."""
    _reset()
    # A stored value of 0 means "no policy configured" to the service layer
    # (get_retention_policy returns None for non-positive values).
    db.set_retention_days(0)

    session_id = db.start_session("test", "retention-src")

    expected_tags: set[str] = set()
    for i, age in enumerate(ages):
        tag = f"d{i}"
        _insert_detection(session_id, tag, NOW - timedelta(seconds=age))
        expected_tags.add(tag)

    deleted = prune_detections(NOW)

    assert deleted == 0
    assert _remaining_tags() == expected_tags


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(days=st.integers(min_value=1, max_value=10_000))
def test_set_retention_policy_persists_positive_days(fresh_db, days):
    """Req 16.1: setting a policy with days > 0 persists the value."""
    _reset()
    set_retention_policy(days)
    assert db.get_retention_days() == days


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(days=st.integers(min_value=-10_000, max_value=0))
def test_set_retention_policy_rejects_non_positive_days(fresh_db, days):
    """Req 16.4: setting a policy with days <= 0 is rejected and persists nothing."""
    _reset()
    with pytest.raises(RetentionPolicyError):
        set_retention_policy(days)
    # No retention_days row should have been written by the rejected call.
    conn = db.get_conn()
    row = conn.execute(
        "SELECT value FROM app_config WHERE key = 'retention_days'"
    ).fetchone()
    conn.close()
    assert row is None
