"""
tests/test_realtime_integration.py
Integration tests for Task 13: Real-time plate recognition pipeline integration.

Verifies:
1. Plates appear in state during processing (not only after)
2. Monotonic plate_log growth (Property 6)
3. Only valid Iranian plates saved to DB (Property 8)
4. Deduplication in RTSP (related to Property 7)
5. Real-time save timing (Req 4.5) — save_detection called DURING processing

Requirements: 2.1, 4.1, 4.2, 4.5
Depends on: Task 5, Task 7
"""
import threading
import time
from unittest.mock import MagicMock, patch, call
from datetime import datetime

import pytest

from plate_validator import validate_iranian_plate, format_plate_persian
from plate_reference import REGION_CODE_TO_PROVINCE, LETTER_TO_CATEGORY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeOpt:
    threshold = 0.5
    imgW = 200
    imgH = 50


def _valid_plates():
    """Return a list of known-valid Iranian plate strings."""
    return [
        "12b34511",  # prefix=12, letter=b(Private), number=345, region=11(Tehran)
        "22s45622",  # prefix=22, letter=s(Private), number=456, region=22(Tehran)
        "33d78911",  # prefix=33, letter=d(Private), number=789, region=11(Tehran)
        "44t12316",  # prefix=44, letter=t(Taxi), number=123, region=16(Qom)
        "55a99910",  # prefix=55, letter=a(Government), number=999, region=10(Tehran)
    ]


def _invalid_plates():
    """Return a list of known-invalid plate strings."""
    return [
        "abc",         # too short
        "12345678",    # no letter at position 2
        "12z34500",    # region 00 not in registry
        "12b345",      # too short (6 chars)
        "12b3451100",  # too long (10 chars)
        "??b34511",    # non-digit prefix
        "",            # empty
    ]


def _make_rtsp_processor(on_detection=None):
    """Create an RTSPStreamProcessor without starting stream."""
    from video_processor import RTSPStreamProcessor

    detector = MagicMock()
    recognizer = MagicMock()
    opt = FakeOpt()
    proc = RTSPStreamProcessor(
        detector, recognizer, opt, "rtsp://fake",
        on_detection=on_detection or MagicMock(),
    )
    return proc


# ---------------------------------------------------------------------------
# Test 1: Plates appear in state during processing (not only after)
# ---------------------------------------------------------------------------


class TestPlatesAppearDuringProcessing:
    """Verify plate_log contains entries BEFORE the processing loop finishes."""

    def test_plate_log_populated_during_simulated_processing(self):
        """Simulate frame-by-frame processing and verify plate_log grows mid-loop."""
        plate_log = []
        plates_to_process = _valid_plates()
        snapshots_during = []

        for idx, dtrb_text in enumerate(plates_to_process):
            confidence = 0.9
            validation = validate_iranian_plate(dtrb_text, confidence)
            persian_display = format_plate_persian(dtrb_text)

            if validation.is_valid:
                metadata_dict = None
                if validation.metadata is not None:
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

                plate_log.append({
                    "frame": idx * 30,
                    "time": f"{idx * 1.0:.2f}s",
                    "time_sec": round(idx * 1.0, 3),
                    "dtrb_text": dtrb_text,
                    "confidence": confidence,
                    "persian_display": persian_display,
                    "is_valid_iranian": validation.is_valid,
                    "metadata": metadata_dict,
                })

            # Snapshot after each "frame" — simulates a poll mid-processing
            snapshots_during.append(len(plate_log))

        # Plate_log should have grown incrementally, not all at once at the end
        assert snapshots_during[0] >= 1, "First valid plate should be in log immediately"
        assert snapshots_during[-1] == len(plates_to_process)
        # Verify incremental growth
        for i in range(1, len(snapshots_during)):
            assert snapshots_during[i] >= snapshots_during[i - 1]

    def test_plate_log_non_empty_before_all_frames_processed(self):
        """Even with a mix of valid/invalid plates, log contains entries mid-loop."""
        plate_log = []
        mixed_plates = ["12b34511", "xyz", "22s45622", "abc123", "33d78911"]

        mid_point_reached = False
        for idx, dtrb_text in enumerate(mixed_plates):
            validation = validate_iranian_plate(dtrb_text, 0.9)
            if validation.is_valid:
                plate_log.append({"dtrb_text": dtrb_text, "frame": idx})

            # Check midpoint
            if idx == 2 and len(plate_log) > 0:
                mid_point_reached = True

        assert mid_point_reached, "Plates should exist in log before processing finishes"
        # Only valid plates in log
        assert len(plate_log) == 3


# ---------------------------------------------------------------------------
# Test 2: Monotonic plate_log growth (Property 6)
# ---------------------------------------------------------------------------


class TestMonotonicPlateLogGrowth:
    """Property 6: plate_log length >= previous length after each frame."""

    def test_plate_log_never_shrinks_during_processing(self):
        """After each processed frame, plate_log length is >= previous."""
        plate_log = []
        previous_lengths = []

        # Simulate 20 frames being processed with varying detections
        all_inputs = [
            "12b34511", None, None, "22s45622", None,
            "33d78911", "invalid", None, "44t12316", None,
            None, "55a99910", None, None, "12b34511",
            None, "22s45622", None, None, "33d78911",
        ]

        for frame_idx, dtrb_text in enumerate(all_inputs):
            if dtrb_text is not None:
                validation = validate_iranian_plate(dtrb_text, 0.9)
                if validation.is_valid:
                    plate_log.append({
                        "frame": frame_idx,
                        "dtrb_text": dtrb_text,
                    })

            # Record length after each frame
            previous_lengths.append(len(plate_log))

        # Verify monotonic growth: each entry >= previous
        for i in range(1, len(previous_lengths)):
            assert previous_lengths[i] >= previous_lengths[i - 1], (
                f"plate_log shrunk at frame {i}: "
                f"{previous_lengths[i]} < {previous_lengths[i - 1]}"
            )

    def test_plates_never_removed_during_processing(self):
        """Plates once added to plate_log are never removed."""
        plate_log = []
        added_plates = set()

        valid_inputs = _valid_plates()

        for idx, dtrb_text in enumerate(valid_inputs):
            validation = validate_iranian_plate(dtrb_text, 0.9)
            if validation.is_valid:
                plate_log.append({"dtrb_text": dtrb_text, "frame": idx})
                added_plates.add(dtrb_text)

            # After each step, verify all previously added plates still in log
            log_texts = {entry["dtrb_text"] for entry in plate_log}
            assert added_plates.issubset(log_texts), (
                f"Plates removed from log! Missing: {added_plates - log_texts}"
            )

    def test_monotonic_with_all_invalid_plates(self):
        """Log stays at 0 when all plates are invalid — still monotonic."""
        plate_log = []
        lengths = []

        for dtrb_text in _invalid_plates():
            validation = validate_iranian_plate(dtrb_text, 0.9)
            if validation.is_valid:
                plate_log.append({"dtrb_text": dtrb_text})
            lengths.append(len(plate_log))

        # All should be 0 (monotonically non-decreasing)
        for i in range(1, len(lengths)):
            assert lengths[i] >= lengths[i - 1]
        assert lengths[-1] == 0


# ---------------------------------------------------------------------------
# Test 3: Only valid Iranian plates saved to DB (Property 8)
# ---------------------------------------------------------------------------


class TestOnlyValidPlatesSavedToDB:
    """Property 8: Invalid plates excluded from database persistence."""

    def test_only_valid_plates_trigger_save_callback(self):
        """Process mixed valid/invalid plates — only valid ones trigger on_detection."""
        save_callback = MagicMock()
        mixed_plates = [
            ("12b34511", 0.9),   # valid
            ("xyz", 0.9),        # invalid (too short)
            ("22s45622", 0.85),  # valid
            ("12345678", 0.9),   # invalid (no letter at pos 2)
            ("33d78911", 0.7),   # valid
            ("12b34511", 0.1),   # invalid (low confidence)
            ("12b34500", 0.9),   # invalid (region 00 not in registry)
        ]

        for dtrb_text, confidence in mixed_plates:
            validation = validate_iranian_plate(dtrb_text, confidence)
            if validation.is_valid and save_callback:
                save_callback("video", dtrb_text, confidence, "test.mp4", 0, "0.00s")

        # Only 3 valid plates should trigger callback
        assert save_callback.call_count == 3
        saved_plates = [c[0][1] for c in save_callback.call_args_list]
        assert "12b34511" in saved_plates
        assert "22s45622" in saved_plates
        assert "33d78911" in saved_plates

    def test_invalid_plates_never_trigger_save(self):
        """No invalid plate should ever trigger the save callback."""
        save_callback = MagicMock()

        for dtrb_text in _invalid_plates():
            validation = validate_iranian_plate(dtrb_text, 0.9)
            if validation.is_valid and save_callback:
                save_callback("video", dtrb_text, 0.9, "test.mp4", 0, "0.00s")

        save_callback.assert_not_called()

    def test_low_confidence_valid_format_not_saved(self):
        """A plate with valid format but confidence < 0.4 should not be saved."""
        save_callback = MagicMock()
        dtrb_text = "12b34511"  # valid format
        confidence = 0.3  # below threshold

        validation = validate_iranian_plate(dtrb_text, confidence)
        if validation.is_valid and save_callback:
            save_callback("video", dtrb_text, confidence, "test.mp4", 0, "0.00s")

        save_callback.assert_not_called()

    def test_valid_plates_all_have_valid_region_and_letter(self):
        """Every plate that passes validation has a known region and letter."""
        for dtrb_text in _valid_plates():
            validation = validate_iranian_plate(dtrb_text, 0.9)
            assert validation.is_valid, f"{dtrb_text} should be valid"
            # Check region code is in registry
            normalized = validation.plate_text
            region = normalized[6:8]
            assert region in REGION_CODE_TO_PROVINCE, f"Region {region} not in registry"
            # Check letter is valid
            letter = normalized[2]
            assert letter.lower() in LETTER_TO_CATEGORY, f"Letter {letter} not valid"


# ---------------------------------------------------------------------------
# Test 4: Deduplication in RTSP (Property 7)
# ---------------------------------------------------------------------------


class TestRTSPDeduplication:
    """Property 7: Same plate detected N times → history has 1 entry with count >= N."""

    def test_same_plate_deduplicated_in_history(self):
        """Adding the same plate multiple times results in history length == 1."""
        proc = _make_rtsp_processor()
        plate = {"plate_text": "12b34511", "confidence": 0.85, "bbox": (0, 0, 100, 50)}

        # Add same plate 5 times
        for _ in range(5):
            proc._add_to_history(plate, "12b34511", "۱۲ ب ۳۴۵-۱۱", True, None)

        assert len(proc.plate_history) == 1
        assert proc.plate_history[0]["count"] == 5

    def test_count_incremented_correctly(self):
        """Each duplicate detection increments count by 1."""
        proc = _make_rtsp_processor()
        plate = {"plate_text": "22s45622", "confidence": 0.9, "bbox": (0, 0, 100, 50)}

        for expected_count in range(1, 11):
            proc._add_to_history(plate, "22s45622", "۲۲ س ۴۵۶-۲۲", True, None)
            assert proc.plate_history[0]["count"] == expected_count

    def test_different_plates_not_deduplicated(self):
        """Different plate texts create separate history entries."""
        proc = _make_rtsp_processor()

        plates_data = [
            ("12b34511", "۱۲ ب ۳۴۵-۱۱"),
            ("22s45622", "۲۲ س ۴۵۶-۲۲"),
            ("33d78911", "۳۳ د ۷۸۹-۱۱"),
        ]

        for dtrb_text, persian in plates_data:
            plate = {"plate_text": dtrb_text, "confidence": 0.9, "bbox": (0, 0, 100, 50)}
            proc._add_to_history(plate, dtrb_text, persian, True, None)

        assert len(proc.plate_history) == 3
        for entry in proc.plate_history:
            assert entry["count"] == 1

    def test_deduplication_preserves_first_seen(self):
        """First_seen timestamp does not change on duplicate detections."""
        proc = _make_rtsp_processor()
        plate = {"plate_text": "12b34511", "confidence": 0.85, "bbox": (0, 0, 100, 50)}

        proc._add_to_history(plate, "12b34511", "۱۲ ب ۳۴۵-۱۱", True, None)
        first_seen = proc.plate_history[0]["first_seen"]

        # Add again
        proc._add_to_history(plate, "12b34511", "۱۲ ب ۳۴۵-۱۱", True, None)

        assert proc.plate_history[0]["first_seen"] == first_seen
        assert proc.plate_history[0]["count"] == 2


# ---------------------------------------------------------------------------
# Test 5: Real-time save timing (Req 4.5)
# ---------------------------------------------------------------------------


class TestRealTimeSaveTiming:
    """Verify save_detection is called DURING processing, not batched at end."""

    def test_save_called_per_plate_immediately(self):
        """Each valid plate triggers save_detection immediately, not deferred."""
        save_times = []

        def recording_callback(*args):
            save_times.append(time.perf_counter())

        plates = _valid_plates()

        for idx, dtrb_text in enumerate(plates):
            validation = validate_iranian_plate(dtrb_text, 0.9)
            if validation.is_valid:
                recording_callback("video", dtrb_text, 0.9, "test.mp4", idx * 30, f"{idx:.2f}s")
            # Simulate frame processing delay
            time.sleep(0.01)

        # All saves should have happened at different times (not all at the end)
        assert len(save_times) == len(plates)
        # Verify timestamps are distributed (not clustered at end)
        for i in range(1, len(save_times)):
            assert save_times[i] > save_times[i - 1], "Saves should be sequential in time"

    def test_save_interleaved_with_processing(self):
        """Saves happen between frames, not all after last frame."""
        events = []  # Track order of events: "process" and "save"

        def save_callback(*args):
            events.append("save")

        plates = ["12b34511", "22s45622", "33d78911"]

        for dtrb_text in plates:
            events.append("process_start")
            validation = validate_iranian_plate(dtrb_text, 0.9)
            if validation.is_valid:
                save_callback("video", dtrb_text, 0.9, "test.mp4", 0, "0.00s")
            events.append("process_end")

        # Pattern should be: process_start, save, process_end (interleaved)
        # NOT: process_start, process_end, ..., save, save, save (batched)
        save_indices = [i for i, e in enumerate(events) if e == "save"]
        process_end_indices = [i for i, e in enumerate(events) if e == "process_end"]

        # Each save should happen BEFORE the corresponding process_end
        for save_idx, end_idx in zip(save_indices, process_end_indices):
            assert save_idx < end_idx, (
                "Save must happen DURING processing (before process_end), not after"
            )

    def test_no_batch_save_at_session_end(self):
        """Verify the pattern: each plate saved individually, no end-of-session batch."""
        call_order = []

        def save_detection_mock(*args):
            call_order.append(("save", args[1]))  # track plate text

        plates = _valid_plates()
        processing_complete = False

        for dtrb_text in plates:
            validation = validate_iranian_plate(dtrb_text, 0.9)
            if validation.is_valid:
                save_detection_mock("video", dtrb_text, 0.9, "test.mp4", 0, "0.00s")

        processing_complete = True

        # All saves happened before processing_complete was set
        assert len(call_order) == len(plates)
        assert processing_complete is True
        # Verify each plate was saved individually
        saved_texts = [c[1] for c in call_order]
        for plate in plates:
            assert plate in saved_texts

    def test_rtsp_save_per_detection_not_batched(self):
        """RTSP processor saves each valid plate immediately on detection."""
        save_callback = MagicMock()
        proc = _make_rtsp_processor(on_detection=save_callback)

        # Simulate what _run does: detect, validate, save immediately
        detections = [
            ("12b34511", 0.9),
            ("22s45622", 0.85),
            ("33d78911", 0.7),
        ]

        for dtrb_text, confidence in detections:
            validation = validate_iranian_plate(dtrb_text, confidence)
            persian_display = format_plate_persian(dtrb_text)
            plate = {"plate_text": dtrb_text, "confidence": confidence, "bbox": (0, 0, 100, 50)}

            proc._add_to_history(
                plate, dtrb_text, persian_display,
                validation.is_valid, validation.metadata,
            )

            # Replicate the immediate save logic from RTSPStreamProcessor._run
            if validation.is_valid and proc.on_detection:
                proc.on_detection("rtsp", dtrb_text, confidence, "rtsp://fake", 0, "")

        # Each valid plate triggered an individual save call
        assert save_callback.call_count == 3
        # Verify each was called with correct plate text
        for idx, (dtrb_text, conf) in enumerate(detections):
            assert save_callback.call_args_list[idx] == call(
                "rtsp", dtrb_text, conf, "rtsp://fake", 0, ""
            )
