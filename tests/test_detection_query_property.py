"""
Property-based test for detection query correctness (task 16.2).

Feature: anpr-system-redesign, Property 23

Property 23: Detection queries return exactly the matching records and total.
    For any set of detection records and any combination of limit, offset,
    source-type filter, and search term, every returned record matches the
    filter and search term, no more than ``limit`` records are returned, and
    the reported total equals the count of all matching records.

Validates: Requirements 13.1

Mechanism under test:
    * ``db.save_detection`` persists detection rows (ids ascending with
      insertion order).
    * ``db.get_all_detections(limit, offset, source_type, search)`` returns
      ``(rows, total)`` where ``rows`` is the matching page ordered newest-first
      (id DESC) and ``total`` is the count of all matching rows before
      pagination.

The query is exercised directly against a temporary SQLite database so the
filtering/pagination is tested for real (no mocks). A pure-Python reference
model recomputes the expected matches and the test asserts the query agrees
with it exactly.
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
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "detection_query_test.db"))
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
# A single-case alphabet keeps the Python substring model exactly aligned with
# SQLite's LIKE semantics (LIKE is ASCII case-insensitive; using one case and
# no LIKE wildcard characters '%'/'_' avoids any ambiguity).
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

source_types = st.sampled_from(["image", "video", "rtsp", "camera"])
plate_text = st.text(alphabet=ALPHABET, max_size=6)
confidence = st.floats(min_value=0.0, max_value=1.0)

# One detection record is (source_type, plate_dtrb, plate_persian, confidence).
detection_spec = st.tuples(source_types, plate_text, plate_text, confidence)

# Query parameters.
source_filter = st.sampled_from(["image", "video", "rtsp", "camera", "all", None])
# Search term: None / empty (both mean "no search filter"), or a short token
# drawn from the same alphabet so substring matching is well-defined.
search_term = st.one_of(
    st.none(),
    st.just(""),
    st.text(alphabet=ALPHABET, min_size=1, max_size=3),
)
limit_param = st.integers(min_value=1, max_value=50)
offset_param = st.integers(min_value=0, max_value=20)


def _matches(record, source_type, search):
    """Pure-Python mirror of the get_all_detections WHERE clause."""
    _src, dtrb, persian, _conf = record
    if source_type and source_type != "all":
        if _src != source_type:
            return False
    if search:  # empty string / None => no search filter (matches db.py)
        if search not in dtrb and search not in persian:
            return False
    return True


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    records=st.lists(detection_spec, max_size=20),
    source_type=source_filter,
    search=search_term,
    limit=limit_param,
    offset=offset_param,
)
def test_detection_query_returns_exact_matches_and_total(
    fresh_db, records, source_type, search, limit, offset
):
    """The query page and total agree exactly with the reference model."""
    _reset()

    session_id = db.start_session("image", "query-src")

    # Persist the generated records, remembering the id assigned to each so the
    # reference model can reproduce the newest-first (id DESC) ordering.
    saved = []  # list of (id, record)
    for record in records:
        src, dtrb, persian, conf = record
        det_id = db.save_detection(session_id, src, dtrb, persian, conf)
        saved.append((det_id, record))

    rows, total = db.get_all_detections(
        limit=limit, offset=offset, source_type=source_type, search=search
    )

    # Reference: matching records, newest-first (id DESC), then paginate.
    matching = [(rid, rec) for (rid, rec) in saved if _matches(rec, source_type, search)]
    matching_desc = sorted(matching, key=lambda t: t[0], reverse=True)
    expected_page_ids = [rid for (rid, _rec) in matching_desc[offset : offset + limit]]

    returned_ids = [r["id"] for r in rows]

    # 1) The reported total equals the count of all matching records.
    assert total == len(matching)

    # 2) No more than `limit` records are returned.
    assert len(rows) <= limit

    # 3) The returned page is exactly the matching records for this page,
    #    in newest-first order.
    assert returned_ids == expected_page_ids

    # 4) Every returned record actually matches the filter and search term.
    for r in rows:
        if source_type and source_type != "all":
            assert r["source_type"] == source_type
        if search:
            assert search in (r["plate_dtrb"] or "") or search in (r["plate_persian"] or "")
