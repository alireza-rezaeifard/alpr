"""
Property-based test for session-history ordering (task 16.5).

Feature: anpr-system-redesign, Property 26

Property 26: Session history is returned most-recent-first.
    For any set of sessions opened over time, ``db.get_sessions_history()``
    returns them ordered from most recent to least recent. The query orders by
    ``id DESC LIMIT ?``; because sessions are inserted sequentially, both ``id``
    and ``started_at`` are non-decreasing in insertion order, so the returned
    list must be non-increasing in ``started_at`` and strictly descending in
    ``id`` (newest session first). When a ``limit`` is supplied, the most-recent
    ``limit`` sessions are the ones returned.

Validates: Requirements 13.7

Mechanism under test:
    * ``db.start_session`` opens a session (assigning ``id`` + ``started_at``).
    * ``db.get_sessions_history(limit=...)`` returns sessions ordered
      most-recent-first, capped at ``limit`` rows.

The helpers are exercised directly against a temporary SQLite database so the
ordering is tested against real persistence (no mocks).
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
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "session_history_ordering_test.db"))
    db.init_db()
    yield db


def _reset_sessions():
    """Clear the sessions table so each generated example starts clean."""
    conn = db.get_conn()
    conn.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()


# Strategy for a list of sessions to open. Each session carries a source type
# and an optional source file (the values do not affect ordering, only the
# insertion order / id / started_at do).
session_specs = st.lists(
    st.tuples(
        st.sampled_from(["image", "video", "rtsp", "camera"]),  # source_type
        st.text(min_size=0, max_size=16),                       # source_file
    ),
    min_size=1,
    max_size=30,
)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    specs=session_specs,
    limit=st.integers(min_value=1, max_value=50),
)
def test_session_history_most_recent_first(fresh_db, specs, limit):
    """Opened sessions are returned ordered most-recent-first (Req 13.7)."""
    _reset_sessions()

    # Open sessions sequentially; ids (and started_at) are monotonically
    # non-decreasing in insertion order.
    inserted_ids = [
        db.start_session(source_type, source_file)
        for source_type, source_file in specs
    ]

    listed = db.get_sessions_history(limit=limit)

    expected_count = min(limit, len(inserted_ids))
    assert len(listed) == expected_count

    # The returned list is strictly descending by id: newest session first.
    ids = [s["id"] for s in listed]
    assert ids == sorted(ids, reverse=True)
    assert len(set(ids)) == len(ids)

    # started_at is non-increasing across the returned list (most-recent-first
    # by start time); ties are possible at sub-second resolution.
    started = [s["started_at"] for s in listed]
    assert started == sorted(started, reverse=True)

    # The returned sessions are exactly the most-recent ``expected_count``
    # sessions (the highest ids), not an arbitrary subset.
    expected_ids = sorted(inserted_ids, reverse=True)[:expected_count]
    assert ids == expected_ids
