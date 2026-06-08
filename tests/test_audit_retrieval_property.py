"""
Property-based test for audit retrieval limit/ordering (task 16.10).

Feature: anpr-system-redesign, Property 29

Property 29: Audit retrieval honors limit and most-recent-first ordering.
    For any set of audit entries appended over time and any limit value,
    ``audit.service.list_audit(limit)`` satisfies:
        * limit > 0  -> exactly min(limit, total) entries are returned
                        (Requirement 15.3).
        * limit == 0 -> all entries are returned (Requirement 15.4).
        * In every case the result is ordered most-recent-first, i.e.
          descending by (timestamp, id). Because entries are appended
          sequentially their ids are monotonically increasing and their
          timestamps are non-decreasing, so the returned rows must be the
          most-recent ``min(limit, total)`` entries (the highest ids),
          strictly descending by id (Requirement 15.4).

Validates: Requirements 15.3, 15.4

Mechanism under test:
    * ``audit.service.write_audit`` appends an entry (assigning id + timestamp).
    * ``audit.service.list_audit(limit)`` returns entries most-recent-first,
      capped at ``limit`` rows (or all rows when limit == 0).

The audit service is exercised directly against a temporary SQLite database so
ordering and the limit semantics are tested against real persistence (no mocks).
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
import audit.service as audit_service


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Point db at a fresh temp SQLite file initialized with the real schema."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "audit_retrieval_test.db"))
    db.init_db()
    yield db


def _reset_audit():
    """Clear the audit_log table so each generated example starts clean."""
    conn = db.get_conn()
    conn.execute("DELETE FROM audit_log")
    conn.commit()
    conn.close()


# Strategy for a list of audit entries to append. The username/action/resource/
# outcome values do not affect ordering or the limit semantics; only the number
# of entries and their insertion order (id + timestamp) matter.
audit_specs = st.lists(
    st.tuples(
        st.one_of(st.none(), st.text(min_size=0, max_size=16)),  # username
        st.text(min_size=1, max_size=16),                        # action
        st.one_of(st.none(), st.text(min_size=0, max_size=16)),  # resource
        st.sampled_from(["success", "failure"]),                 # outcome
    ),
    min_size=0,
    max_size=30,
)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    specs=audit_specs,
    # limit == 0 means "return all"; positive limits cap the result. We also
    # cover limits larger than the number of entries written.
    limit=st.integers(min_value=0, max_value=50),
)
def test_audit_retrieval_limit_and_ordering(fresh_db, specs, limit):
    """list_audit honors limit and most-recent-first ordering (Req 15.3, 15.4)."""
    _reset_audit()

    # Append entries sequentially; ids (and timestamps) are monotonically
    # non-decreasing in insertion order.
    inserted_ids = [
        audit_service.write_audit(user, action, resource, outcome)["id"]
        for user, action, resource, outcome in specs
    ]
    total = len(inserted_ids)

    listed = audit_service.list_audit(limit)

    # --- Limit semantics (Req 15.3 / 15.4) ---
    if limit == 0:
        expected_count = total
    else:
        expected_count = min(limit, total)
    assert len(listed) == expected_count

    ids = [e["id"] for e in listed]

    # No duplicates returned.
    assert len(set(ids)) == len(ids)

    # --- Most-recent-first ordering (Req 15.4) ---
    # Strictly descending by id: newest entry first.
    assert ids == sorted(ids, reverse=True)

    # timestamp is non-increasing across the result (most-recent-first by time;
    # ties on sub-second-resolution timestamps resolve by id desc).
    timestamps = [e["timestamp"] for e in listed]
    assert timestamps == sorted(timestamps, reverse=True)

    # The returned entries are exactly the most-recent ``expected_count``
    # entries (the highest ids), not an arbitrary subset.
    expected_ids = sorted(inserted_ids, reverse=True)[:expected_count]
    assert ids == expected_ids
