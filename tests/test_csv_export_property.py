"""
Property-based test for the detection CSV export builder (task 16.7).

Feature: anpr-system-redesign, Property 27

Property 27: Export reflects matches, required fields, and the camera-name rule.
    For any set of detection rows, ``build_detection_csv`` produces a CSV whose
    data rows correspond exactly (one-to-one, in order) to the input rows, whose
    header always carries the required fields (timestamp, source type, DTRB text,
    Persian plate, confidence), whose ``camera_name`` column is present if and
    only if at least one row is camera-sourced, and whose output is header-only
    when the input is empty.

Validates: Requirements 14.1, 14.2, 14.3, 14.4

No mocks are used: the real pure builder is exercised directly and its output
is parsed back with the standard ``csv`` reader for verification.
"""
from __future__ import annotations

import csv
import io
import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

# Ensure the project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from export.csv_export import build_detection_csv

# Required header columns, in the fixed order the builder emits (Requirement 14.1).
REQUIRED_FIELDS = ["timestamp", "source_type", "plate_dtrb", "plate_persian", "confidence"]

# Free text that round-trips through CSV quoting; exclude CR/NL only to keep the
# field/value comparison unambiguous (the csv module would quote them, but they
# add no value to the property under test).
_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc"), blacklist_characters="\r\n"),
    max_size=20,
)
_source_type = st.sampled_from(["image", "video", "camera", "rtsp"])
# Non-empty camera name (the builder treats None/"" as "no camera name").
_camera_name = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc"), blacklist_characters="\r\n"),
    min_size=1,
    max_size=20,
)
_confidence = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


@st.composite
def _detection_row(draw):
    """Generate a single detection row, occasionally carrying a camera name."""
    row = {
        "timestamp": draw(_text),
        "source_type": draw(_source_type),
        "plate_dtrb": draw(_text),
        "plate_persian": draw(_text),
        "confidence": draw(_confidence),
    }
    # Attach a camera name on some rows so the camera-name rule is exercised
    # across the input space (both branches reachable).
    if draw(st.booleans()):
        row["camera_name"] = draw(_camera_name)
    return row


def _parse_csv(text: str) -> list[list[str]]:
    """Parse the produced CSV back into a list of records (header + data)."""
    return list(csv.reader(io.StringIO(text)))


# ---------------------------------------------------------------------------
# Property 27: Export reflects matches, required fields, and the camera-name rule
# Feature: anpr-system-redesign, Property 27
# ---------------------------------------------------------------------------
@settings(max_examples=200, deadline=None)
@given(rows=st.lists(_detection_row(), max_size=12))
def test_export_reflects_matches_fields_and_camera_rule(rows):
    """**Validates: Requirements 14.1, 14.2, 14.3, 14.4**

    Feature: anpr-system-redesign, Property 27
    """
    csv_text = build_detection_csv(rows)
    records = _parse_csv(csv_text)

    # There is always at least a header record (Requirements 14.1, 14.4).
    assert len(records) >= 1
    header = records[0]
    data = records[1:]

    # (1) Required fields always present, in the fixed leading order (Req 14.1).
    assert header[: len(REQUIRED_FIELDS)] == REQUIRED_FIELDS

    # (2) Camera-name rule: the column is present iff some row is camera-sourced
    #     (i.e. has a non-empty camera_name) (Req 14.3).
    expected_camera_column = any(row.get("camera_name") for row in rows)
    assert ("camera_name" in header) == expected_camera_column
    if expected_camera_column:
        assert header == REQUIRED_FIELDS + ["camera_name"]

    # (3) Export reflects exactly the matching rows: one data row per input row,
    #     in order (Req 14.2); empty input yields header-only output (Req 14.4).
    assert len(data) == len(rows)

    # (4) Each data row carries the required field values of its source row, and
    #     a camera-sourced row's camera name is populated in the camera column.
    for source_row, record in zip(rows, data):
        cells = dict(zip(header, record))
        assert cells["timestamp"] == str(source_row.get("timestamp", ""))
        assert cells["source_type"] == str(source_row.get("source_type", ""))
        assert cells["plate_dtrb"] == str(source_row.get("plate_dtrb", ""))
        assert cells["plate_persian"] == str(source_row.get("plate_persian", ""))
        assert cells["confidence"] == str(source_row.get("confidence", ""))
        if expected_camera_column:
            assert cells["camera_name"] == str(source_row.get("camera_name", ""))


@settings(max_examples=100, deadline=None)
@given(st.just([]))
def test_empty_result_is_header_only(rows):
    """**Validates: Requirements 14.4**

    Feature: anpr-system-redesign, Property 27

    An empty result set yields a file containing only the header row, with no
    camera-name column.
    """
    records = _parse_csv(build_detection_csv(rows))
    assert records == [REQUIRED_FIELDS]
