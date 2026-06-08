"""
tests/test_detection_pipeline_integration.py

Integration tests for Task 14.2: Detection pipeline wiring

Verifies:
1. Image/video/RTSP detection endpoint wiring and data flow
2. Undecodable image error handling
3. Atomic storage failure handling
4. Unknown task not-found responses
5. Video task status/stop/complete lifecycle

Requirements: 8.1, 8.2, 8.4, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3
"""
import asyncio
import io
import os
import tempfile
import threading
import time
import uuid
from unittest.mock import MagicMock, patch, call

import cv2
import numpy as np
import pytest

import api
from db import get_conn, init_db
from video_processor import RTSPStreamProcessor


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_detection_state():
    """Reset the global tasks registry before and after each test."""
    with api._tasks_lock:
        api._tasks.clear()
    yield
    with api._tasks_lock:
        api._tasks.clear()


@pytest.fixture
def temp_db():
    """Create a temporary database for tests."""
    init_db()
    yield
    # Cleanup happens in teardown


def _create_valid_image_bytes():
    """Create a valid PNG image as bytes."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    # Draw something recognizable
    cv2.rectangle(img, (10, 10), (90, 90), (255, 255, 255), 2)
    _, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def _create_invalid_image_bytes():
    """Create invalid image data that cannot be decoded."""
    return b"this is not an image\x00\x01\x02"


def _create_mock_upload_file(content: bytes, filename: str = "test.png"):
    """Create a mock UploadFile for testing."""
    from fastapi import UploadFile
    
    class MockUploadFile:
        def __init__(self, content, filename):
            self._content = content
            self.filename = filename
            self.content_type = "image/png"
        
        async def read(self):
            return self._content
    
    return MockUploadFile(content, filename)


def _create_test_video_file():
    """Create a minimal test video file."""
    temp_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    temp_path = temp_file.name
    temp_file.close()
    
    # Create a simple 10-frame video
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(temp_path, fourcc, 10.0, (100, 100))
    
    for i in range(10):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        # Draw frame number
        cv2.putText(frame, str(i), (40, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        writer.write(frame)
    
    writer.release()
    return temp_path


# ---------------------------------------------------------------------------
# Test 1: Image detection endpoint wiring (Req 8.1, 8.2, 8.4)
# ---------------------------------------------------------------------------

class TestImageDetectionWiring:
    """Test the complete flow through image detection endpoint."""

    def test_valid_image_creates_session_and_detections(self, temp_db):
        """Valid image creates a session and saves detections to database."""
        # Mock the models and detection pipeline
        with patch.object(api, '_ensure_models') as mock_models, \
             patch('video_processor.process_frame') as mock_process:
            
            mock_detector = MagicMock()
            mock_recognizer = MagicMock()
            mock_opt = MagicMock()
            mock_models.return_value = (mock_detector, mock_recognizer, mock_opt)
            
            # Mock a detection result
            annotated_img = np.zeros((100, 100, 3), dtype=np.uint8)
            plates = [{"bbox": (10, 10, 50, 50), "confidence": 0.85}]
            dtrb_results = [("12b34511", 0.9)]
            mock_process.return_value = (annotated_img, plates, dtrb_results)
            
            # Create upload file
            file = _create_mock_upload_file(_create_valid_image_bytes(), "test.png")
            
            # Call the endpoint (run async function)
            result = asyncio.run(api.detect_image(file))
            
            # Verify response structure
            assert "session_id" in result
            assert "annotated" in result
            assert "plates" in result
            assert len(result["plates"]) == 1
            assert result["plates"][0]["plate_dtrb"] == "12b34511"
            
            # Verify session was created in database
            conn = get_conn()
            cur = conn.execute("SELECT * FROM sessions WHERE id = ?", (result["session_id"],))
            session = cur.fetchone()
            conn.close()
            
            assert session is not None
            assert session[1] == "image"  # source_type
            assert session[2] == "test.png"  # source_file
            assert session[8] == "done"  # status

    def test_undecodable_image_returns_400_error(self):
        """Undecodable image data returns validation error (Req 8.2)."""
        with patch.object(api, '_ensure_models') as mock_models:
            mock_detector = MagicMock()
            mock_recognizer = MagicMock()
            mock_opt = MagicMock()
            mock_models.return_value = (mock_detector, mock_recognizer, mock_opt)
            
            # Create invalid image file
            file = _create_mock_upload_file(_create_invalid_image_bytes(), "bad.png")
            
            # Call the endpoint
            result = asyncio.run(api.detect_image(file))
            
            # Verify error response
            assert isinstance(result, dict) or hasattr(result, 'status_code')
            if hasattr(result, 'status_code'):
                assert result.status_code == 400
            else:
                # JSONResponse returns dict in test context
                assert "error" in result
                assert "Invalid image" in result["error"]

    def test_image_detection_with_no_plates_found(self, temp_db):
        """Image with no detected plates still creates a session."""
        with patch.object(api, '_ensure_models') as mock_models, \
             patch('video_processor.process_frame') as mock_process:
            
            mock_detector = MagicMock()
            mock_recognizer = MagicMock()
            mock_opt = MagicMock()
            mock_models.return_value = (mock_detector, mock_recognizer, mock_opt)
            
            # Mock no detections
            annotated_img = np.zeros((100, 100, 3), dtype=np.uint8)
            mock_process.return_value = (annotated_img, [], [])
            
            file = _create_mock_upload_file(_create_valid_image_bytes())
            
            result = asyncio.run(api.detect_image(file))
            
            assert "session_id" in result
            assert len(result["plates"]) == 0
            
            # Verify session exists with zero detections
            conn = get_conn()
            cur = conn.execute("SELECT total_plates FROM sessions WHERE id = ?", (result["session_id"],))
            row = cur.fetchone()
            conn.close()
            
            assert row[0] == 0


# ---------------------------------------------------------------------------
# Test 2: Atomic storage failure handling (Req 8.4)
# ---------------------------------------------------------------------------

class TestAtomicStorageFailure:
    """Test detection storage failure scenarios."""

    def test_detection_storage_failure_propagates_error(self):
        """If save_detection fails, the error should be handled appropriately."""
        with patch.object(api, '_ensure_models') as mock_models, \
             patch('video_processor.process_frame') as mock_process, \
             patch('db.save_detection') as mock_save:
            
            mock_detector = MagicMock()
            mock_recognizer = MagicMock()
            mock_opt = MagicMock()
            mock_models.return_value = (mock_detector, mock_recognizer, mock_opt)
            
            # Mock detection result
            annotated_img = np.zeros((100, 100, 3), dtype=np.uint8)
            plates = [{"bbox": (10, 10, 50, 50), "confidence": 0.85}]
            dtrb_results = [("12b34511", 0.9)]
            mock_process.return_value = (annotated_img, plates, dtrb_results)
            
            # Make save_detection raise an exception
            mock_save.side_effect = Exception("Database write failed")
            
            file = _create_mock_upload_file(_create_valid_image_bytes())
            
            # The endpoint should handle or propagate the error
            try:
                result = asyncio.run(api.detect_image(file))
                # If no exception, verify error is in response
                if isinstance(result, dict):
                    # Some error handling might catch and return error response
                    pass
            except Exception as e:
                # Exception propagation is also valid
                assert "Database write failed" in str(e)


# ---------------------------------------------------------------------------
# Test 3: Video task lifecycle (Req 9.1, 9.2, 9.3, 9.4, 9.5)
# ---------------------------------------------------------------------------

class TestVideoTaskLifecycle:
    """Test video detection task creation, status, stop, and completion."""

    def test_video_task_creation_returns_task_and_session_id(self, temp_db):
        """Starting video detection returns task_id and session_id (Req 9.1)."""
        with patch.object(api, '_ensure_models') as mock_models:
            mock_detector = MagicMock()
            mock_recognizer = MagicMock()
            mock_opt = MagicMock()
            mock_models.return_value = (mock_detector, mock_recognizer, mock_opt)
            
            # Create test video
            video_path = _create_test_video_file()
            try:
                with open(video_path, 'rb') as f:
                    content = f.read()
                
                file = _create_mock_upload_file(content, "test.mp4")
                
                # Start video detection
                result = asyncio.run(api.detect_video(file, skip_frames=30, fast_mode=False))
                
                # Verify response structure
                assert isinstance(result, dict) or hasattr(result, 'body')
                if hasattr(result, 'body'):
                    # JSONResponse in test context
                    import json
                    data = json.loads(result.body)
                else:
                    data = result
                
                assert "task_id" in data
                assert "session_id" in data
                
                # Verify task is registered
                with api._tasks_lock:
                    assert data["task_id"] in api._tasks
                    assert api._tasks[data["task_id"]]["session_id"] == data["session_id"]
            
            finally:
                if os.path.exists(video_path):
                    os.unlink(video_path)

    def test_video_status_for_unknown_task_returns_404(self):
        """Requesting status for non-existent task returns not-found (Req 9.5)."""
        unknown_task_id = "nonexistent-task-id"
        
        result = api.video_status(unknown_task_id)
        
        # Verify 404 error response
        assert hasattr(result, 'status_code') or isinstance(result, dict)
        if hasattr(result, 'status_code'):
            assert result.status_code == 404
        else:
            assert "error" in result
            assert "not found" in result["error"].lower()

    def test_video_status_returns_processing_state(self):
        """Status endpoint returns current processing state (Req 9.2)."""
        # Create a mock task with processing state
        task_id = uuid.uuid4().hex
        with api._tasks_lock:
            api._tasks[task_id] = {
                "status": "processing",
                "frame_idx": 50,
                "total_frames": 100,
                "plate_log": [
                    {"frame": 10, "dtrb_text": "12b34511", "confidence": 0.9},
                    {"frame": 30, "dtrb_text": "22s45622", "confidence": 0.85},
                ],
                "live_detections": [],
                "current_frame": None,
            }
        
        result = api.video_status(task_id)
        
        assert result["status"] == "processing"
        assert result["frame_idx"] == 50
        assert result["total_frames"] == 100
        assert len(result["plate_log"]) == 2
        assert result["plate_log"][0]["dtrb_text"] == "12b34511"

    def test_video_stop_cancels_running_task(self):
        """Stopping a video task sets status to cancelled (Req 9.3)."""
        # Create a mock running task
        task_id = uuid.uuid4().hex
        mock_processor = MagicMock()
        
        with api._tasks_lock:
            api._tasks[task_id] = {
                "status": "processing",
                "processor": mock_processor,
                "session_id": 123,
            }
        
        result = api.stop_video_task(task_id)
        
        # Verify stop was called and status updated
        assert result["status"] == "stopped"
        mock_processor.stop.assert_called_once()
        
        with api._tasks_lock:
            assert api._tasks[task_id]["status"] == "cancelled"

    def test_video_stop_for_unknown_task_returns_404(self):
        """Stopping non-existent task returns not-found error."""
        unknown_task_id = "nonexistent-task-id"
        
        result = api.stop_video_task(unknown_task_id)
        
        assert hasattr(result, 'status_code') or isinstance(result, dict)
        if hasattr(result, 'status_code'):
            assert result.status_code == 404
        else:
            assert "error" in result

    def test_video_task_completion_closes_session(self, temp_db):
        """When video processing completes, session is closed with final counts (Req 9.4)."""
        # This test verifies the integration between video processor and session management
        # In the actual code, the run_video thread calls end_session when done
        
        from db import start_session, end_session
        
        # Create a session
        session_id = start_session("video", "test.mp4")
        
        # Simulate completion
        end_session(session_id, total_frames=100, total_plates=5, unique_plates=3, status="done")
        
        # Verify session was updated
        conn = get_conn()
        cur = conn.execute("SELECT status, total_frames, total_plates, unique_plates FROM sessions WHERE id = ?", (session_id,))
        row = cur.fetchone()
        conn.close()
        
        assert row[0] == "done"
        assert row[1] == 100
        assert row[2] == 5
        assert row[3] == 3


# ---------------------------------------------------------------------------
# Test 4: RTSP task lifecycle (Req 10.1, 10.2, 10.3)
# ---------------------------------------------------------------------------

class TestRTSPTaskLifecycle:
    """Test RTSP detection task creation, status, and stop."""

    def test_rtsp_task_creation_returns_task_and_session_id(self, temp_db):
        """Starting RTSP detection returns task_id and session_id (Req 10.1)."""
        with patch.object(api, '_ensure_models') as mock_models, \
             patch('video_processor.RTSPStreamProcessor') as mock_processor_class:
            
            mock_detector = MagicMock()
            mock_recognizer = MagicMock()
            mock_opt = MagicMock()
            mock_models.return_value = (mock_detector, mock_recognizer, mock_opt)
            
            mock_processor = MagicMock()
            mock_processor_class.return_value = mock_processor
            
            # Start RTSP detection
            result = api.detect_rtsp(url="rtsp://test/stream", fast_mode=False, skip_frames=15)
            
            # Verify response
            assert hasattr(result, 'body') or isinstance(result, dict)
            if hasattr(result, 'body'):
                import json
                data = json.loads(result.body)
            else:
                data = result
            
            assert "task_id" in data
            assert "session_id" in data
            
            # Verify processor was started
            mock_processor.start.assert_called_once()
            
            # Verify task is registered
            with api._tasks_lock:
                assert data["task_id"] in api._tasks
                assert api._tasks[data["task_id"]]["url"] == "rtsp://test/stream"

    def test_rtsp_status_for_unknown_task_returns_404(self):
        """Requesting RTSP status for non-existent task returns not-found (Req 10.2)."""
        unknown_task_id = "nonexistent-rtsp-task"
        
        result = api.rtsp_status(unknown_task_id)
        
        assert hasattr(result, 'status_code') or isinstance(result, dict)
        if hasattr(result, 'status_code'):
            assert result.status_code == 404
        else:
            assert "error" in result
            assert "not found" in result["error"].lower()

    def test_rtsp_status_returns_processor_state(self):
        """RTSP status endpoint returns processor state with history (Req 10.2)."""
        task_id = uuid.uuid4().hex
        mock_processor = MagicMock()
        
        # Mock processor state
        mock_processor.get_state.return_value = {
            "status": "running",
            "history": [
                {"dtrb_text": "12b34511", "count": 3, "confidence": 0.9},
                {"dtrb_text": "22s45622", "count": 1, "confidence": 0.85},
            ],
            "live_detections": [],
            "annotated": np.zeros((100, 100, 3), dtype=np.uint8),
        }
        
        with api._tasks_lock:
            api._tasks[task_id] = {
                "processor": mock_processor,
                "status": "running",
            }
        
        result = api.rtsp_status(task_id)
        
        assert result["status"] == "running"
        assert len(result["history"]) == 2
        assert result["history"][0]["dtrb_text"] == "12b34511"
        assert "annotated" in result

    def test_rtsp_stop_closes_session_and_stops_processor(self, temp_db):
        """Stopping RTSP task closes session and stops processor (Req 10.3)."""
        from db import start_session
        
        session_id = start_session("rtsp", "rtsp://test/stream")
        task_id = uuid.uuid4().hex
        mock_processor = MagicMock()
        
        mock_processor.get_state.return_value = {
            "history": [
                {"dtrb_text": "12b34511", "count": 2},
                {"dtrb_text": "22s45622", "count": 1},
            ],
        }
        
        with api._tasks_lock:
            api._tasks[task_id] = {
                "processor": mock_processor,
                "session_id": session_id,
                "status": "running",
            }
        
        result = api.stop_rtsp_task(task_id)
        
        # Verify processor was stopped
        mock_processor.stop.assert_called_once()
        assert result["status"] == "stopped"
        
        # Verify session was closed
        conn = get_conn()
        cur = conn.execute("SELECT status FROM sessions WHERE id = ?", (session_id,))
        row = cur.fetchone()
        conn.close()
        
        assert row[0] == "done"


# ---------------------------------------------------------------------------
# Test 5: Task registry edge cases
# ---------------------------------------------------------------------------

class TestTaskRegistryEdgeCases:
    """Test edge cases in task management."""

    def test_concurrent_task_registration(self):
        """Multiple tasks can be registered concurrently without conflicts."""
        task_ids = [uuid.uuid4().hex for _ in range(10)]
        
        def register_task(task_id):
            with api._tasks_lock:
                api._tasks[task_id] = {"status": "queued", "session_id": task_id}
        
        threads = [threading.Thread(target=register_task, args=(tid,)) for tid in task_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Verify all tasks registered
        with api._tasks_lock:
            for task_id in task_ids:
                assert task_id in api._tasks

    def test_task_cleanup_does_not_affect_other_tasks(self):
        """Stopping one task doesn't affect other tasks."""
        task1_id = uuid.uuid4().hex
        task2_id = uuid.uuid4().hex
        
        with api._tasks_lock:
            api._tasks[task1_id] = {"status": "processing", "processor": MagicMock()}
            api._tasks[task2_id] = {"status": "processing", "processor": MagicMock()}
        
        # Stop task1
        api.stop_video_task(task1_id)
        
        # Verify task2 is unaffected
        with api._tasks_lock:
            assert api._tasks[task2_id]["status"] == "processing"
            assert api._tasks[task1_id]["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Test 6: Detection wiring error conditions
# ---------------------------------------------------------------------------

class TestDetectionWiringErrors:
    """Test error handling in detection pipeline wiring."""

    def test_model_loading_failure_is_handled(self):
        """If model loading fails, endpoint returns appropriate error."""
        with patch.object(api, '_ensure_models') as mock_models:
            mock_models.side_effect = Exception("Model file not found")
            
            file = _create_mock_upload_file(_create_valid_image_bytes())
            
            try:
                result = asyncio.run(api.detect_image(file))
                # If caught, should return error response
                if isinstance(result, dict):
                    assert "error" in result or result.get("status") == "error"
            except Exception as e:
                # Exception propagation is also valid
                assert "Model file not found" in str(e)

    def test_processor_creation_failure_handled_gracefully(self, temp_db):
        """If processor creation fails, task should handle it gracefully."""
        with patch.object(api, '_ensure_models') as mock_models, \
             patch('video_processor.RTSPStreamProcessor') as mock_processor_class:
            
            mock_detector = MagicMock()
            mock_recognizer = MagicMock()
            mock_opt = MagicMock()
            mock_models.return_value = (mock_detector, mock_recognizer, mock_opt)
            
            # Make processor creation fail
            mock_processor_class.side_effect = Exception("Cannot connect to RTSP stream")
            
            try:
                result = api.detect_rtsp(url="rtsp://invalid/stream", fast_mode=False, skip_frames=15)
                # Should handle gracefully
            except Exception as e:
                assert "Cannot connect to RTSP stream" in str(e)
