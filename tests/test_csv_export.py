"""
tests/test_csv_export.py
Unit tests for the CSV export builder.

Tests the pure ``build_detection_csv`` function against Requirements 14.1-14.4.
"""
import pytest
from export.csv_export import build_detection_csv


def test_empty_result_yields_header_only():
    """Requirement 14.4: empty result sets produce header-only CSV."""
    result = build_detection_csv([])
    lines = [line.strip() for line in result.strip().splitlines()]
    assert len(lines) == 1
    assert lines[0] == "timestamp,source_type,plate_dtrb,plate_persian,confidence"


def test_fixed_header_columns():
    """Requirement 14.1: fixed header columns for timestamp, source_type, etc."""
    rows = [
        {
            "timestamp": "2024-01-01T12:00:00",
            "source_type": "image",
            "plate_dtrb": "12a34567",
            "plate_persian": "۱۲الف۳۴۵۶۷",
            "confidence": 0.95,
        }
    ]
    result = build_detection_csv(rows)
    lines = [line.strip() for line in result.strip().splitlines()]
    assert len(lines) == 2
    # Check header
    assert lines[0] == "timestamp,source_type,plate_dtrb,plate_persian,confidence"
    # Check data row
    assert "2024-01-01T12:00:00" in lines[1]
    assert "image" in lines[1]
    assert "12a34567" in lines[1]
    assert "۱۲الف۳۴۵۶۷" in lines[1]
    assert "0.95" in lines[1]


def test_camera_name_column_when_camera_sourced():
    """Requirement 14.3: camera_name column added when any row is camera-sourced."""
    rows = [
        {
            "timestamp": "2024-01-01T12:00:00",
            "source_type": "camera",
            "plate_dtrb": "12a34567",
            "plate_persian": "۱۲الف۳۴۵۶۷",
            "confidence": 0.95,
            "camera_name": "Front Gate",
        }
    ]
    result = build_detection_csv(rows)
    lines = [line.strip() for line in result.strip().splitlines()]
    # Check header includes camera_name
    assert lines[0] == "timestamp,source_type,plate_dtrb,plate_persian,confidence,camera_name"
    # Check data row includes camera name
    assert "Front Gate" in lines[1]


def test_no_camera_name_column_when_no_camera_source():
    """Requirement 14.3: camera_name column NOT added when no camera-sourced rows."""
    rows = [
        {
            "timestamp": "2024-01-01T12:00:00",
            "source_type": "image",
            "plate_dtrb": "12a34567",
            "plate_persian": "۱۲الف۳۴۵۶۷",
            "confidence": 0.95,
        }
    ]
    result = build_detection_csv(rows)
    lines = [line.strip() for line in result.strip().splitlines()]
    # Camera_name should NOT be in header
    assert lines[0] == "timestamp,source_type,plate_dtrb,plate_persian,confidence"
    assert "camera_name" not in lines[0]


def test_mixed_sources_with_camera():
    """Requirement 14.3: camera_name column added when ANY row has camera_name."""
    rows = [
        {
            "timestamp": "2024-01-01T12:00:00",
            "source_type": "image",
            "plate_dtrb": "12a34567",
            "plate_persian": "۱۲الف۳۴۵۶۷",
            "confidence": 0.95,
        },
        {
            "timestamp": "2024-01-01T12:01:00",
            "source_type": "camera",
            "plate_dtrb": "22b56789",
            "plate_persian": "۲۲ب۵۶۷۸۹",
            "confidence": 0.88,
            "camera_name": "Parking Lot",
        },
    ]
    result = build_detection_csv(rows)
    lines = [line.strip() for line in result.strip().splitlines()]
    # Header should include camera_name
    assert "camera_name" in lines[0]
    # First row (image) should have empty camera_name
    assert len(lines) == 3  # header + 2 data rows
    # Second row should have camera name
    assert "Parking Lot" in lines[2]


def test_all_matching_detections_included():
    """Requirement 14.2: all matching detection records are included."""
    rows = [
        {
            "timestamp": f"2024-01-01T12:0{i}:00",
            "source_type": "video",
            "plate_dtrb": f"1{i}a3456{i}",
            "plate_persian": f"۱{i}الف۳۴۵۶{i}",
            "confidence": 0.90 + i * 0.01,
        }
        for i in range(5)
    ]
    result = build_detection_csv(rows)
    lines = [line.strip() for line in result.strip().splitlines()]
    # Should have header + 5 data rows
    assert len(lines) == 6
    # Verify all plates are present
    csv_text = "\n".join(lines)
    for i in range(5):
        assert f"1{i}a3456{i}" in csv_text


def test_handles_missing_fields_gracefully():
    """CSV builder should handle rows with missing optional fields."""
    rows = [
        {
            "timestamp": "2024-01-01T12:00:00",
            "source_type": "image",
            # Missing plate_dtrb, plate_persian, confidence
        }
    ]
    result = build_detection_csv(rows)
    lines = [line.strip() for line in result.strip().splitlines()]
    assert len(lines) == 2  # header + 1 data row
    # Should not crash, fields should be empty


def test_rtsp_source_with_camera_name():
    """RTSP sources may also have camera_name populated."""
    rows = [
        {
            "timestamp": "2024-01-01T12:00:00",
            "source_type": "rtsp",
            "plate_dtrb": "12a34567",
            "plate_persian": "۱۲الف۳۴۵۶۷",
            "confidence": 0.95,
            "camera_name": "Live Stream 1",
        }
    ]
    result = build_detection_csv(rows)
    lines = [line.strip() for line in result.strip().splitlines()]
    assert "camera_name" in lines[0]
    assert "Live Stream 1" in lines[1]
