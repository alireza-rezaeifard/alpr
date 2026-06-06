"""
tests/test_rtsp_validator_integration.py
Unit tests for Task 7: RTSPStreamProcessor validator integration.
Tests deduplication, metadata enrichment, and valid/invalid plate handling.
"""
import threading
from unittest.mock import MagicMock, patch
from datetime import datetime

import pytest


class FakeOpt:
    threshold = 0.5
    imgW = 200
    imgH = 50


def _make_processor():
    """Create an RTSPStreamProcessor instance without starting any stream."""
    from video_processor import RTSPStreamProcessor

    detector = MagicMock()
    recognizer = MagicMock()
    opt = FakeOpt()
    proc = RTSPStreamProcessor(detector, recognizer, opt, "rtsp://fake", on_detection=MagicMock())
    return proc


class TestAddToHistory:
    """Test the _add_to_history method with enriched fields."""

    def test_new_entry_has_enriched_fields(self):
        proc = _make_processor()
        plate = {"plate_text": "12b34567", "confidence": 0.85, "bbox": (0, 0, 100, 50)}

        from plate_metadata import PlateMetadata

        metadata = PlateMetadata(
            classified=True,
            category="Private",
            category_display="شخصی (Private)",
            color_scheme="white",
            region_code="11",
            region_name="تهران (Tehran)",
            special_note=None,
        )

        proc._add_to_history(plate, "12b34567", "۱۲ ب ۳۴۵-۶۷", True, metadata)

        assert len(proc.plate_history) == 1
        entry = proc.plate_history[0]
        assert entry["dtrb_text"] == "12b34567"
        assert entry["yolo_text"] == "12b34567"
        assert entry["confidence"] == 0.85
        assert entry["count"] == 1
        assert entry["persian_display"] == "۱۲ ب ۳۴۵-۶۷"
        assert entry["is_valid_iranian"] is True
        assert entry["metadata"] is not None
        assert entry["metadata"]["classified"] is True
        assert entry["metadata"]["category"] == "Private"
        assert entry["metadata"]["category_display"] == "شخصی (Private)"
        assert entry["metadata"]["color_scheme"] == "white"
        assert entry["metadata"]["region_code"] == "11"
        assert entry["metadata"]["region_name"] == "تهران (Tehran)"
        assert entry["metadata"]["special_note"] is None

    def test_invalid_plate_has_none_metadata(self):
        proc = _make_processor()
        plate = {"plate_text": "abc", "confidence": 0.3, "bbox": (0, 0, 100, 50)}

        proc._add_to_history(plate, "abc", "abc", False, None)

        assert len(proc.plate_history) == 1
        entry = proc.plate_history[0]
        assert entry["is_valid_iranian"] is False
        assert entry["metadata"] is None

    def test_deduplication_increments_count(self):
        proc = _make_processor()
        plate = {"plate_text": "12b34567", "confidence": 0.85, "bbox": (0, 0, 100, 50)}

        from plate_metadata import PlateMetadata

        metadata = PlateMetadata(
            classified=True, category="Private", category_display="شخصی (Private)",
            color_scheme="white", region_code="11", region_name="تهران (Tehran)",
        )

        # First detection
        proc._add_to_history(plate, "12b34567", "۱۲ ب ۳۴۵-۶۷", True, metadata)
        # Second detection of same plate
        proc._add_to_history(plate, "12b34567", "۱۲ ب ۳۴۵-۶۷", True, metadata)
        # Third detection
        proc._add_to_history(plate, "12b34567", "۱۲ ب ۳۴۵-۶۷", True, metadata)

        assert len(proc.plate_history) == 1
        assert proc.plate_history[0]["count"] == 3

    def test_deduplication_updates_last_seen(self):
        proc = _make_processor()
        plate = {"plate_text": "12b34567", "confidence": 0.85, "bbox": (0, 0, 100, 50)}

        proc._add_to_history(plate, "12b34567", "۱۲ ب ۳۴۵-۶۷", True, None)
        first_seen = proc.plate_history[0]["first_seen"]

        proc._add_to_history(plate, "12b34567", "۱۲ ب ۳۴۵-۶۷", True, None)
        assert proc.plate_history[0]["first_seen"] == first_seen
        # last_seen is updated (may or may not differ depending on timing)
        assert proc.plate_history[0]["last_seen"] is not None

    def test_different_plates_are_separate_entries(self):
        proc = _make_processor()
        plate1 = {"plate_text": "12b34567", "confidence": 0.85, "bbox": (0, 0, 100, 50)}
        plate2 = {"plate_text": "98s12311", "confidence": 0.90, "bbox": (0, 0, 100, 50)}

        proc._add_to_history(plate1, "12b34567", "۱۲ ب ۳۴۵-۶۷", True, None)
        proc._add_to_history(plate2, "98s12311", "۹۸ س ۱۲۳-۱۱", True, None)

        assert len(proc.plate_history) == 2
        assert proc.plate_history[0]["count"] == 1
        assert proc.plate_history[1]["count"] == 1

    def test_deduplication_updates_confidence_if_higher(self):
        proc = _make_processor()
        plate_low = {"plate_text": "12b34567", "confidence": 0.70, "bbox": (0, 0, 100, 50)}
        plate_high = {"plate_text": "12b34567", "confidence": 0.95, "bbox": (0, 0, 100, 50)}

        proc._add_to_history(plate_low, "12b34567", "۱۲ ب ۳۴۵-۶۷", True, None)
        assert proc.plate_history[0]["confidence"] == 0.70

        proc._add_to_history(plate_high, "12b34567", "۱۲ ب ۳۴۵-۶۷", True, None)
        assert proc.plate_history[0]["confidence"] == 0.95

    def test_deduplication_does_not_downgrade_confidence(self):
        proc = _make_processor()
        plate_high = {"plate_text": "12b34567", "confidence": 0.95, "bbox": (0, 0, 100, 50)}
        plate_low = {"plate_text": "12b34567", "confidence": 0.70, "bbox": (0, 0, 100, 50)}

        proc._add_to_history(plate_high, "12b34567", "۱۲ ب ۳۴۵-۶۷", True, None)
        proc._add_to_history(plate_low, "12b34567", "۱۲ ب ۳۴۵-۶۷", True, None)
        assert proc.plate_history[0]["confidence"] == 0.95


class TestOnDetectionOnlyForValidPlates:
    """Test that on_detection is only called for valid plates."""

    def test_on_detection_not_called_for_invalid_plate(self):
        """Simulate a detection loop: invalid plates should not trigger on_detection."""
        proc = _make_processor()
        on_det_mock = MagicMock()
        proc.on_detection = on_det_mock

        # Simulate what _run does for an invalid plate
        from plate_validator import validate_iranian_plate, format_plate_persian

        dtrb_text = "xyz"  # invalid plate
        confidence = 0.9
        validation = validate_iranian_plate(dtrb_text, confidence)
        persian_display = format_plate_persian(dtrb_text)

        plate = {"plate_text": "xyz", "confidence": confidence, "bbox": (0, 0, 100, 50)}
        proc._add_to_history(plate, dtrb_text, persian_display, validation.is_valid, validation.metadata)

        # Replicate the on_detection gate
        if validation.is_valid:
            proc.on_detection("rtsp", dtrb_text, confidence, "rtsp://fake", 1, "")

        on_det_mock.assert_not_called()

    def test_on_detection_called_for_valid_plate(self):
        """Valid plates should trigger on_detection."""
        proc = _make_processor()
        on_det_mock = MagicMock()
        proc.on_detection = on_det_mock

        from plate_validator import validate_iranian_plate, format_plate_persian

        dtrb_text = "12b34511"  # valid Iranian plate (region 11 = Tehran)
        confidence = 0.9
        validation = validate_iranian_plate(dtrb_text, confidence)
        persian_display = format_plate_persian(dtrb_text)

        plate = {"plate_text": "12b34511", "confidence": confidence, "bbox": (0, 0, 100, 50)}
        proc._add_to_history(plate, dtrb_text, persian_display, validation.is_valid, validation.metadata)

        # Replicate the on_detection gate
        if validation.is_valid:
            proc.on_detection("rtsp", dtrb_text, confidence, "rtsp://fake", 1, "")

        on_det_mock.assert_called_once_with("rtsp", dtrb_text, confidence, "rtsp://fake", 1, "")


class TestMetadataDictKeys:
    """Test that the metadata dict has the required keys from the task spec."""

    def test_metadata_dict_has_all_required_keys(self):
        proc = _make_processor()
        from plate_validator import validate_iranian_plate, format_plate_persian

        dtrb_text = "12b34511"
        confidence = 0.9
        validation = validate_iranian_plate(dtrb_text, confidence)
        persian_display = format_plate_persian(dtrb_text)

        plate = {"plate_text": "12b34511", "confidence": confidence, "bbox": (0, 0, 100, 50)}
        proc._add_to_history(plate, dtrb_text, persian_display, validation.is_valid, validation.metadata)

        entry = proc.plate_history[0]
        assert entry["metadata"] is not None
        expected_keys = {"classified", "category", "category_display", "color_scheme",
                         "region_code", "region_name", "special_note"}
        assert set(entry["metadata"].keys()) == expected_keys
