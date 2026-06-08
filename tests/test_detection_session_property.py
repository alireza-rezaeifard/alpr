"""
Property-based test for detection-session persistence (task 13.7).

Feature: anpr-system-redesign, Property 22

Property 22: Detections are persisted under their originating session.
    Every saved detection is stored under the session id it was created in and
    is retrievable as part of that session's detections. Detections saved under
    one session are never attributed to another (cross-session isolation), and
    every saved detection appears in live recent-history.

Validates: Requirements 8.3, 10.4, 6.4

Mechanism under test:
    * ``db.start_session`` opens a session and returns its integer id.
    * ``db.save_detection`` persists a detection attributed to a session id.
    * The detections table is queried directly (WHERE session_id = ?) to read
      a session's detections back.
    * ``db.get_recent_detections`` exposes detections in live recent-history.

The helpers are exercised directly against a temporary SQLite database so the
persistence is tested for real (no mocks).
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
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "detection_session_test.db"))
    db.init_db()
    yield db


def _reset():
    """Clear sessions and detections so each generated example starts clean."""
    conn = db.get_conn()
    conn.execute("DELETE FROM detections")
    conn.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()


def _detections_for_session(session_id):
    """Read a session's detections directly from the detections table."""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT id, session_id, plate_dtrb, plate_persian, confidence "
        "FROM detections WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Generators ---------------------------------------------------------------
source_types = st.sampled_from(["image", "video", "rtsp"])
plate_dtrb = st.text(max_size=12)
plate_persian = st.text(max_size=20)
confidence = st.floats(min_value=0.0, max_value=1.0)

# A detection is (source_type, dtrb, persian, confidence). Each detection is
# assigned to one of the created sessions by index.
detection_spec = st.tuples(source_types, plate_dtrb, plate_persian, confidence)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    num_sessions=st.integers(min_value=1, max_value=4),
    detections=st.lists(
        st.tuples(st.integers(min_value=0), detection_spec),
        max_size=15,
    ),
)
def test_detections_persisted_under_originating_session(
    fresh_db, num_sessions, detections
):
    """Each detection lands under the session it was created in, exclusively."""
    _reset()

    # Create the requested sessions; remember the originating session per id.
    session_ids = [db.start_session("image", f"src-{i}") for i in range(num_sessions)]

    # Track which detection ids we expect under each session.
    expected_by_session = {sid: set() for sid in session_ids}
    all_saved_ids = []

    for raw_idx, (source_type, dtrb, persian, conf) in detections:
        session_id = session_ids[raw_idx % num_sessions]
        det_id = db.save_detection(
            session_id, source_type, dtrb, persian, conf, source_file=f"src-{raw_idx}"
        )
        expected_by_session[session_id].add(det_id)
        all_saved_ids.append(det_id)

    # 1) Every saved detection row carries its originating session id, and is
    #    retrievable as part of that session's detections (Req 8.3, 10.4).
    for session_id in session_ids:
        rows = _detections_for_session(session_id)
        retrieved_ids = {r["id"] for r in rows}
        assert retrieved_ids == expected_by_session[session_id]
        for r in rows:
            assert r["session_id"] == session_id

    # 2) Cross-session isolation: a detection saved under one session never
    #    appears under any other session.
    for session_id in session_ids:
        others = set().union(
            *(expected_by_session[o] for o in session_ids if o != session_id)
        ) if num_sessions > 1 else set()
        retrieved_ids = {r["id"] for r in _detections_for_session(session_id)}
        assert retrieved_ids.isdisjoint(others)

    # 3) Every saved detection appears in live recent-history (Req 6.4).
    recent = db.get_recent_detections(limit=len(all_saved_ids) + 10)
    recent_ids = {d["id"] for d in recent}
    for det_id in all_saved_ids:
        assert det_id in recent_ids
