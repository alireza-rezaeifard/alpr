"""
Property-based test for audit append completeness (task 16.9).

Feature: anpr-system-redesign, Property 28

Property 28: Auditable actions always append a complete audit entry.
    For any sequence of auditable actions, every ``audit.service.write_audit``
    call appends exactly one new entry to the append-only audit log, and each
    stored entry is *complete* — it records the user, action, resource, outcome,
    and a (non-empty, auto-populated) timestamp, with every field matching what
    was supplied. After N write_audit calls the store therefore holds exactly N
    entries.

Validates: Requirements 15.1, 15.2

Mechanism under test:
    * ``audit.service.write_audit(user, action, resource, outcome)`` inserts one
      append-only row, stamping the current timestamp (Req 15.1, 15.2).
    * ``audit.service.list_audit(limit)`` returns the stored entries.

The functions are exercised directly against a temporary SQLite database
initialized with the real schema (no mocks), so completeness is verified against
real persistence.
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
from audit import service as audit_service


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Point db at a fresh temp SQLite file initialized with the real schema."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "audit_completeness_test.db"))
    db.init_db()
    yield db


def _reset_audit():
    """Clear the audit_log table so each generated example starts clean."""
    conn = db.get_conn()
    conn.execute("DELETE FROM audit_log")
    conn.commit()
    conn.close()


# Strategy for a sequence of auditable actions. Each field is populated
# (non-empty) so completeness of every recorded field can be asserted.
#   user     -> the acting username (e.g. "admin")
#   action   -> the action identifier (e.g. "create_camera", "login")
#   resource -> the affected resource (e.g. "camera:5")
#   outcome  -> "success" or "failure"
action_specs = st.lists(
    st.tuples(
        st.text(min_size=1, max_size=24),                  # user
        st.text(min_size=1, max_size=24),                  # action
        st.text(min_size=1, max_size=24),                  # resource
        st.sampled_from(["success", "failure"]),           # outcome
    ),
    min_size=1,
    max_size=30,
)

REQUIRED_FIELDS = ("username", "action", "resource", "outcome", "timestamp")


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(specs=action_specs)
def test_write_audit_appends_complete_entry(fresh_db, specs):
    """Each write_audit appends exactly one complete entry (Req 15.1, 15.2)."""
    _reset_audit()

    written = []
    for i, (user, action, resource, outcome) in enumerate(specs, start=1):
        entry = audit_service.write_audit(user, action, resource, outcome)
        written.append((user, action, resource, outcome))

        # Each call appends exactly one entry: count grows by one.
        assert len(audit_service.list_audit(0)) == i

        # The returned entry is itself complete and matches the inputs.
        for field in REQUIRED_FIELDS:
            assert field in entry
            assert entry[field] is not None
        assert entry["timestamp"] != ""
        assert entry["username"] == user
        assert entry["action"] == action
        assert entry["resource"] == resource
        assert entry["outcome"] == outcome

    # After N calls the append-only store holds exactly N entries.
    stored = audit_service.list_audit(0)
    assert len(stored) == len(written)

    # Every stored entry is complete: all required fields present, populated,
    # and the timestamp is a non-empty string.
    for row in stored:
        for field in REQUIRED_FIELDS:
            assert field in row
            assert row[field] is not None
        assert isinstance(row["timestamp"], str)
        assert row["timestamp"] != ""
        assert row["outcome"] in ("success", "failure")

    # The multiset of (user, action, resource, outcome) recorded equals what was
    # written — nothing dropped, duplicated, or altered.
    recorded = sorted(
        (r["username"], r["action"], r["resource"], r["outcome"]) for r in stored
    )
    assert recorded == sorted(written)
