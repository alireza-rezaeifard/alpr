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
    * ``db.save_detection`` persists detection rows (the reporting router's
      ``GET /api/reports/detections`` reads them back via ``get_all_detections``).
    * ``db.get_all_detections(limit, offset, source_type, search)`` returns the
      ``(rows, total)`` pair surfaced by ``routers/reports.list_detections``.

The query is exercised directly against a temporary SQLite database so the
correctness is tested against real persistence (no mocks). A pure-Python oracle
re-implements the filter/search/pagination semantics and is compared against the
database result.
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
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "reports_test.db"))
    db.init_db()
    yield db


def _reset_detections():
    """Clear detection-related tables so each generated example starts clean."""
    conn = db.get_conn()
    conn.execute("DELETE FROM detections")
    conn.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()


# --- Strategies -----------------------------------------------------------
#
# A small lowercase alphabet (no SQL LIKE wildcards '%'/'_', no uppercase) keeps
# the oracle a plain case-sensitive substring check that matches SQLite's LIKE
# semantics exactly: LIKE is case-insensitive only for ASCII letters, which we
# sidestep by using lowercase letters + digits only.
PLATE_ALPHABET = "abcdef0123456789"
SOURCE_TYPES = ["image", "video", "rtsp", "camera"]

plate_text = st.text(alphabet=PLATE_ALPHABET, min_size=0, max_size=6)
source_type_value = st.sampled_from(SOURCE_TYPES)

# One detection record: (source_type, plate_dtrb, plate_persian, confidence).
detection_record = st.tuples(
    source_type_value,
    plate_text,
    plate_text,
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)

# Filter parameters. ``None`` and 'all' both mean "no source filter"; the empty
# string also means "no filter" because the query guards with ``if source_type``.
source_filter = st.one_of(
    st.none(),
    st.just("all"),
    st.just(""),
    source_type_value,
)
# Search term. ``None`` / empty mean "no search". Short terms over the same
# alphabet produce a healthy mix of hits and misses.
search_term = st.one_of(
    st.none(),
    st.just(""),
    st.text(alphabet=PLATE_ALPHABET, min_size=1, max_size=2),
)


def _matches(record, source_type, search):
    """Pure oracle: does a stored record match the filter + search term?

    Mirrors ``db.get_all_detections``: a source filter is active only when it is
    truthy and not 'all'; a search is active only when it is truthy and matches
    a substring of either the DTRB text or the Persian string.
    """
    rec_source, rec_dtrb, rec_persian, _conf = record
    if source_type and source_type != "all":
        if rec_source != source_type:
            return False
    if search:
        if search not in rec_dtrb and search not in rec_persian:
            return False
    return True


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    records=st.lists(detection_record, min_size=0, max_size=25),
    limit=st.integers(min_value=1, max_value=1000),
    offset=st.integers(min_value=0, max_value=30),
    source_type=source_filter,
    search=search_term,
)
def test_detection_query_returns_exactly_matching_records_and_total(
    fresh_db, records, limit, offset, source_type, search
):
    """get_all_detections returns exactly the matching page and matching total."""
    _reset_detections()

    session_id = db.start_session("test")

    # Insert every generated record. Insertion order == ascending id, so the
    # query's ``ORDER BY id DESC`` is the reverse of insertion order.
    inserted = []  # list of (index, record) in insertion (id-ascending) order
    for idx, rec in enumerate(records):
        source, dtrb, persian, conf = rec
        db.save_detection(
            session_id=session_id,
            source_type=source,
            plate_dtrb=dtrb,
            plate_persian=persian,
            confidence=conf,
        )
        inserted.append((idx, rec))

    rows, total = db.get_all_detections(
        limit=limit, offset=offset, source_type=source_type, search=search
    )

    # --- Oracle: all matching records, ordered most-recent-first (id DESC) ---
    matching = [rec for (_i, rec) in inserted if _matches(rec, source_type, search)]
    expected_total = len(matching)
    # id DESC == reverse insertion order.
    matching_desc = list(reversed(matching))
    expected_page = matching_desc[offset : offset + limit]

    # 1. The reported total equals the count of ALL matching records (Req 13.1).
    assert total == expected_total

    # 2. No more than ``limit`` records are returned (Req 13.1 / 13.2).
    assert len(rows) <= limit

    # 3. Every returned record matches the filter and search term (Req 13.1).
    for row in rows:
        assert _matches(
            (row["source_type"], row["plate_dtrb"], row["plate_persian"], row["confidence"]),
            source_type,
            search,
        )

    # 4. The returned page is exactly the expected slice of matching records,
    #    in most-recent-first order (the "exactly the matching records" clause).
    assert len(rows) == len(expected_page)
    for row, exp in zip(rows, expected_page):
        exp_source, exp_dtrb, exp_persian, _exp_conf = exp
        assert row["source_type"] == exp_source
        assert row["plate_dtrb"] == exp_dtrb
        assert row["plate_persian"] == exp_persian
