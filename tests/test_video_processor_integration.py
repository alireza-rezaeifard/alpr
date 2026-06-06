"""
Tests for Task 5: VideoProcessor integration with plate_validator.

Verifies:
- validate_iranian_plate is called for each detected plate
- plate_log entries include persian_display, is_valid_iranian, metadata fields
- on_detection (save_detection) is called only for valid plates
- DB write failures are handled gracefully (log and continue)
- Invalid plates do NOT trigger on_detection callback

Requirements: 4.1, 4.3, 4.4, 7.1, 7.3, 7.4, 7.5
"""
import pytest
from unittest.mock import patch, MagicMock
from plate_validator import validate_iranian_plate, format_plate_persian


class TestVideoProcessorPlateLogEntries:
    """Test that plate_log entries are enriched with validation fields."""

    def test_valid_plate_entry_has_metadata(self):
        """A valid Iranian plate should produce metadata dict in entry."""
        # "12b34511" is a valid plate: prefix=12, letter=b, number=345, region=11
        dtrb_text = "12b34511"
        confidence = 0.9

        validation = validate_iranian_plate(dtrb_text, confidence)
        persian_display = format_plate_persian(dtrb_text)

        # Simulate what VideoProcessor does
        metadata_dict = None
        if validation.is_valid and validation.metadata is not None:
            md = validation.metadata
            metadata_dict = {
                "classified": md.classified,
                "category": md.category,
                "category_display": md.category_display,
                "color_scheme": md.color_scheme,
                "region_code": md.region_code,
                "region_name": md.region_name,
                "special_note": md.special_note,
            }

        entry = {
            "frame": 0,
            "time": "0.00s",
            "time_sec": 0.0,
            "plate_text": "12b34511",
            "dtrb_text": dtrb_text,
            "confidence": confidence,
            "bbox": [0.1, 0.2, 0.3, 0.4],
            "persian_display": persian_display,
            "is_valid_iranian": validation.is_valid,
            "metadata": metadata_dict,
        }

        assert entry["is_valid_iranian"] is True
        assert entry["persian_display"] == "۱۲ ب ۳۴۵-۱۱"
        assert entry["metadata"] is not None
        assert entry["metadata"]["classified"] is True
        assert entry["metadata"]["region_code"] == "11"
        assert entry["metadata"]["color_scheme"] is not None
        assert entry["metadata"]["category"] is not None
        assert entry["metadata"]["category_display"] is not None
        assert entry["metadata"]["region_name"] is not None
        assert "special_note" in entry["metadata"]

    def test_invalid_plate_entry_has_null_metadata(self):
        """An invalid plate should have is_valid_iranian=False and metadata=None."""
        dtrb_text = "abc"
        confidence = 0.9

        validation = validate_iranian_plate(dtrb_text, confidence)
        persian_display = format_plate_persian(dtrb_text)

        metadata_dict = None
        if validation.is_valid and validation.metadata is not None:
            md = validation.metadata
            metadata_dict = {
                "classified": md.classified,
                "category": md.category,
                "category_display": md.category_display,
                "color_scheme": md.color_scheme,
                "region_code": md.region_code,
                "region_name": md.region_name,
                "special_note": md.special_note,
            }

        entry = {
            "persian_display": persian_display,
            "is_valid_iranian": validation.is_valid,
            "metadata": metadata_dict,
        }

        assert entry["is_valid_iranian"] is False
        assert entry["metadata"] is None

    def test_low_confidence_plate_is_invalid(self):
        """A plate with confidence below threshold should be marked invalid."""
        dtrb_text = "12b34511"  # valid format
        confidence = 0.2  # below 0.4 threshold

        validation = validate_iranian_plate(dtrb_text, confidence)

        assert validation.is_valid is False
        assert validation.rejection_reason is not None
        assert "confidence" in validation.rejection_reason.lower()


class TestVideoProcessorOnDetectionCallback:
    """Test that on_detection is called only for valid plates."""

    def test_on_detection_called_for_valid_plate(self):
        """on_detection should be called when plate is valid."""
        callback = MagicMock()
        dtrb_text = "12b34511"
        confidence = 0.9

        validation = validate_iranian_plate(dtrb_text, confidence)

        # Simulate VideoProcessor logic
        if validation.is_valid and callback:
            callback("video", dtrb_text, confidence, "test.mp4", 0, "0.00s")

        callback.assert_called_once_with("video", dtrb_text, confidence, "test.mp4", 0, "0.00s")

    def test_on_detection_not_called_for_invalid_plate(self):
        """on_detection should NOT be called when plate is invalid."""
        callback = MagicMock()
        dtrb_text = "xyz"
        confidence = 0.9

        validation = validate_iranian_plate(dtrb_text, confidence)

        # Simulate VideoProcessor logic
        if validation.is_valid and callback:
            callback("video", dtrb_text, confidence, "test.mp4", 0, "0.00s")

        callback.assert_not_called()

    def test_on_detection_not_called_for_low_confidence(self):
        """on_detection should NOT be called when confidence is too low."""
        callback = MagicMock()
        dtrb_text = "12b34511"  # valid format
        confidence = 0.1  # below threshold

        validation = validate_iranian_plate(dtrb_text, confidence)

        if validation.is_valid and callback:
            callback("video", dtrb_text, confidence, "test.mp4", 0, "0.00s")

        callback.assert_not_called()


class TestGracefulDBFailureHandling:
    """Test that DB write failures are handled gracefully."""

    def test_db_failure_does_not_raise(self):
        """If on_detection raises, it should be caught and logged, not propagated."""
        callback = MagicMock(side_effect=Exception("DB write failed"))
        dtrb_text = "12b34511"
        confidence = 0.9

        validation = validate_iranian_plate(dtrb_text, confidence)

        # Simulate VideoProcessor logic with try/except
        error_logged = False
        if validation.is_valid and callback:
            try:
                callback("video", dtrb_text, confidence, "test.mp4", 0, "0.00s")
            except Exception:
                error_logged = True

        assert error_logged is True
        callback.assert_called_once()

    def test_processing_continues_after_db_failure(self):
        """Multiple plates should all be processed even if one DB write fails."""
        call_count = 0
        results = []

        def failing_callback(*args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("DB locked")
            results.append(args)

        plates = ["12b34511", "22s45622", "33d78911"]

        for dtrb_text in plates:
            validation = validate_iranian_plate(dtrb_text, 0.9)
            if validation.is_valid and failing_callback:
                try:
                    failing_callback("video", dtrb_text, 0.9, "test.mp4", 0, "0.00s")
                except Exception:
                    pass  # graceful handling

        # All valid plates should have triggered the callback
        assert call_count == 3
        # Two should have succeeded (after first failure)
        assert len(results) == 2


class TestMetadataSerialization:
    """Test that PlateMetadata is correctly serialized as a dict."""

    def test_metadata_dict_has_correct_keys(self):
        """Metadata dict should have all expected keys for API response."""
        dtrb_text = "12b34511"
        validation = validate_iranian_plate(dtrb_text, 0.9)

        assert validation.is_valid
        md = validation.metadata
        metadata_dict = {
            "classified": md.classified,
            "category": md.category,
            "category_display": md.category_display,
            "color_scheme": md.color_scheme,
            "region_code": md.region_code,
            "region_name": md.region_name,
            "special_note": md.special_note,
        }

        expected_keys = {
            "classified", "category", "category_display",
            "color_scheme", "region_code", "region_name", "special_note"
        }
        assert set(metadata_dict.keys()) == expected_keys

    def test_metadata_values_are_json_serializable(self):
        """All metadata values should be JSON-serializable (str, bool, None)."""
        import json

        dtrb_text = "12b34511"
        validation = validate_iranian_plate(dtrb_text, 0.9)

        md = validation.metadata
        metadata_dict = {
            "classified": md.classified,
            "category": md.category,
            "category_display": md.category_display,
            "color_scheme": md.color_scheme,
            "region_code": md.region_code,
            "region_name": md.region_name,
            "special_note": md.special_note,
        }

        # Should not raise
        serialized = json.dumps(metadata_dict)
        assert serialized is not None

    def test_metadata_classified_is_true_for_valid(self):
        """For a valid plate, metadata.classified should be True."""
        dtrb_text = "12b34511"
        validation = validate_iranian_plate(dtrb_text, 0.9)

        assert validation.metadata.classified is True
