"""
test_backend.py
Integration tests for the Persian License Plate Recognition backend API.
Tests use FastAPI TestClient against in-memory test database.
Requirements: 16.1, 14.5, 14.7, 14.8
"""
import os
import sys
import tempfile
import pytest

# Use a temp DB so tests don't pollute the production DB
_TMP_DIR = tempfile.mkdtemp()
_TEST_DB = os.path.join(_TMP_DIR, "test.db")
os.environ.setdefault("PLPR_DB_PATH", _TEST_DB)

# Patch DB_PATH before importing anything that reads it
import db as _db
_db.DB_PATH = _TEST_DB

# Re-init the DB at the temp path so all helpers use it
from db import init_db
init_db()

# Patch _ensure_models on the api module so it doesn't try to load 2 GB models
import api as app_module

def _mock_ensure_models():
    return None, None, None

app_module._ensure_models = _mock_ensure_models

from fastapi.testclient import TestClient
from api import app

client = TestClient(app, raise_server_exceptions=True)


# ── Health ────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_ok(self):
        """Req 16.1 — /api/health returns {status: ok}."""
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok"


# ── Stats ─────────────────────────────────────────────────────────────────

class TestStats:
    def test_stats_fields(self):
        """Req 16.1 — /api/stats returns expected numeric fields."""
        r = client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        for field in ("total_detections", "unique_plates", "total_sessions"):
            assert field in data, f"Missing field: {field}"
        assert "avg_confidence" in data  # may be None


# ── Detections ────────────────────────────────────────────────────────────

class TestDetections:
    def test_detections_paginated(self):
        """Req 16.1 — /api/detections returns {data, total, limit, offset}."""
        r = client.get("/api/detections?limit=10&offset=0")
        assert r.status_code == 200
        data = r.json()
        assert "data" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert isinstance(data["data"], list)

    def test_detections_filter_image(self):
        r = client.get("/api/detections?source_type=image&limit=5")
        assert r.status_code == 200

    def test_detections_search(self):
        r = client.get("/api/detections?search=123")
        assert r.status_code == 200

    def test_detections_timeline(self):
        """Req 16.1 — /api/detections/timeline returns {data: list}."""
        r = client.get("/api/detections/timeline?days=7")
        assert r.status_code == 200
        data = r.json()
        assert "data" in data
        assert isinstance(data["data"], list)

    def test_detections_timeline_days_too_large(self):
        """Req 5.7 — days > 90 should be rejected."""
        r = client.get("/api/detections/timeline?days=91")
        assert r.status_code == 422

    def test_detections_timeline_days_zero(self):
        """Req 5.7 — days=0 should be rejected."""
        r = client.get("/api/detections/timeline?days=0")
        assert r.status_code == 422

    def test_detections_letters(self):
        """Req 16.1 — /api/detections/letters returns {data: list}."""
        r = client.get("/api/detections/letters")
        assert r.status_code == 200
        assert "data" in r.json()

    def test_detections_sources(self):
        """Req 16.1 — /api/detections/sources returns {data: list}."""
        r = client.get("/api/detections/sources")
        assert r.status_code == 200
        assert "data" in r.json()

    def test_detections_confidence(self):
        """Req 16.1 — /api/detections/confidence returns {data: list}."""
        r = client.get("/api/detections/confidence")
        assert r.status_code == 200
        assert "data" in r.json()


# ── Sessions ──────────────────────────────────────────────────────────────

class TestSessions:
    def test_sessions_fields(self):
        """Req 16.1 — /api/sessions returns {data: list}."""
        r = client.get("/api/sessions?limit=10")
        assert r.status_code == 200
        data = r.json()
        assert "data" in data
        assert isinstance(data["data"], list)


# ── Plate metadata ────────────────────────────────────────────────────────

class TestPlateMetadata:
    def test_valid_latin_plate(self):
        """Req 14.7, 16.1 — latin plate returns classified=True with full fields."""
        r = client.get("/api/plate/metadata?plate=12b34511")
        assert r.status_code == 200
        data = r.json()
        assert data.get("classified") is True
        assert data.get("category") == "Private"
        assert data.get("color_scheme") == "white"
        assert data.get("region_code") == "11"
        assert data.get("region_name") is not None

    def test_valid_taxi_plate(self):
        """Req 14.4 — taxi letter returns Taxi category, yellow color."""
        r = client.get("/api/plate/metadata?plate=12t34511")
        assert r.status_code == 200
        data = r.json()
        assert data.get("classified") is True
        assert data.get("category") == "Taxi"
        assert data.get("color_scheme") == "yellow"

    def test_valid_government_plate(self):
        """Req 14.4 — government letter returns Government category, red color."""
        r = client.get("/api/plate/metadata?plate=12a34511")
        assert r.status_code == 200
        data = r.json()
        assert data.get("classified") is True
        assert data.get("category") == "Government"
        assert data.get("color_scheme") == "red"

    def test_valid_persian_plate(self):
        """Req 14.8 — Persian digits normalize to same result as latin."""
        r_latin = client.get("/api/plate/metadata?plate=12b34511")
        r_persian = client.get("/api/plate/metadata?plate=\u06f1\u06f2b\u06f3\u06f4\u06f5\u06f1\u06f1")
        assert r_latin.status_code == 200
        assert r_persian.status_code == 200
        latin_data = r_latin.json()
        persian_data = r_persian.json()
        assert latin_data.get("category") == persian_data.get("category")
        assert latin_data.get("color_scheme") == persian_data.get("color_scheme")
        assert latin_data.get("region_code") == persian_data.get("region_code")

    def test_formatted_plate(self):
        """Req 14.8 — formatted plate (spaces/dashes) parses to same result."""
        r_raw = client.get("/api/plate/metadata?plate=12b34511")
        r_fmt = client.get("/api/plate/metadata?plate=12 b 345-11")
        assert r_raw.status_code == 200
        assert r_fmt.status_code == 200
        raw_data = r_raw.json()
        fmt_data = r_fmt.json()
        assert raw_data.get("category") == fmt_data.get("category")

    def test_unknown_region(self):
        """Req 14.3 — region code not in reference data returns unknown-region."""
        r = client.get("/api/plate/metadata?plate=12b34500")
        assert r.status_code == 200
        data = r.json()
        assert data.get("classified") is True
        region_name = data.get("region_name", "")
        assert region_name is not None
        assert "00" in region_name or "Unknown" in region_name

    def test_empty_plate(self):
        """Req 14.6 — empty plate returns not-classified."""
        r = client.get("/api/plate/metadata?plate=")
        assert r.status_code == 200
        data = r.json()
        assert data.get("classified") is False
        assert data.get("reason") is not None

    def test_malformed_plate(self):
        """Req 14.6, 16.6 — malformed plate returns not-classified, no error raised."""
        for bad in ["abc", "12345678", "tooshort", "!@#$%^&*", "", "    "]:
            r = client.get(f"/api/plate/metadata?plate={bad}")
            assert r.status_code == 200, f"Unexpected status for plate={bad!r}"
            data = r.json()
            assert data.get("classified") is False, f"Should not be classified for plate={bad!r}"
            assert data.get("reason") is not None, f"Reason missing for plate={bad!r}"


# ── Camera CRUD ───────────────────────────────────────────────────────────

class TestCameraEndpoints:
    def test_list_cameras_empty(self):
        """Req 16.1 — /api/cameras returns {data: list}."""
        r = client.get("/api/cameras")
        assert r.status_code == 200
        data = r.json()
        assert "data" in data
        assert isinstance(data["data"], list)

    def test_create_camera(self):
        """Req 11.1 — POST /api/cameras creates a camera."""
        r = client.post("/api/cameras", json={
            "name": "Test Camera",
            "url": "rtsp://192.168.1.1/test",
            "skip_frames": 15,
        })
        assert r.status_code == 200
        data = r.json()
        assert data.get("name") == "Test Camera"
        assert data.get("url") == "rtsp://192.168.1.1/test"
        assert data.get("skip_frames") == 15
        assert "id" in data

    def test_create_camera_empty_name(self):
        """Req 11.2 — empty name is allowed."""
        r = client.post("/api/cameras", json={
            "name": "",
            "url": "rtsp://192.168.1.2/test",
        })
        assert r.status_code == 200
        data = r.json()
        assert data.get("name") == ""

    def test_update_camera(self):
        """Req 11.5 — PATCH /api/cameras/{id} updates the name."""
        create_r = client.post("/api/cameras", json={
            "name": "Old Name",
            "url": "rtsp://192.168.1.3/test",
        })
        assert create_r.status_code == 200
        camera_id = create_r.json()["id"]

        update_r = client.patch(f"/api/cameras/{camera_id}", json={"name": "New Name"})
        assert update_r.status_code == 200
        assert update_r.json().get("name") == "New Name"

    def test_delete_camera(self):
        """Req 11.4 — DELETE /api/cameras/{id} removes the camera."""
        create_r = client.post("/api/cameras", json={
            "name": "ToDelete",
            "url": "rtsp://192.168.1.4/test",
        })
        assert create_r.status_code == 200
        camera_id = create_r.json()["id"]

        del_r = client.delete(f"/api/cameras/{camera_id}")
        assert del_r.status_code == 200

        # Verify it's gone
        list_r = client.get("/api/cameras")
        ids = [c["id"] for c in list_r.json()["data"]]
        assert camera_id not in ids

    def test_delete_nonexistent_camera(self):
        """404 when deleting a camera that doesn't exist."""
        r = client.delete("/api/cameras/99999")
        assert r.status_code == 404


# ── Concurrency config ────────────────────────────────────────────────────

class TestConcurrencyConfig:
    def test_get_concurrency_limit(self):
        """Req 12.7 — GET /api/config/concurrency returns {concurrency_limit}."""
        r = client.get("/api/config/concurrency")
        assert r.status_code == 200
        data = r.json()
        assert "concurrency_limit" in data
        assert isinstance(data["concurrency_limit"], int)

    def test_set_concurrency_limit_valid(self):
        """Req 12.2 — PUT /api/config/concurrency with valid value."""
        r = client.put("/api/config/concurrency", json={"value": 3})
        assert r.status_code == 200
        assert r.json().get("concurrency_limit") == 3

    def test_set_concurrency_limit_invalid_low(self):
        """Req 12.8 — value=0 is rejected (Pydantic ge=1 constraint)."""
        r = client.put("/api/config/concurrency", json={"value": 0})
        assert r.status_code == 422

    def test_set_concurrency_limit_invalid_high(self):
        """Req 12.8 — value=65 is rejected (Pydantic le=64 constraint)."""
        r = client.put("/api/config/concurrency", json={"value": 65})
        assert r.status_code == 422


# ── Sampling interval validation ──────────────────────────────────────────

class TestSamplingIntervalValidation:
    def test_video_skip_frames_too_low(self):
        """Req 9.1 — skip_frames=0 rejected before session is created."""
        import io as _io
        dummy_video = _io.BytesIO(b"fake video data")
        r = client.post(
            "/api/detect/video",
            files={"file": ("test.mp4", dummy_video, "video/mp4")},
            data={"skip_frames": "0"},
        )
        assert r.status_code == 422

    def test_video_skip_frames_too_high(self):
        """Req 9.1 — skip_frames=1001 rejected."""
        import io as _io
        dummy_video = _io.BytesIO(b"fake video data")
        r = client.post(
            "/api/detect/video",
            files={"file": ("test.mp4", dummy_video, "video/mp4")},
            data={"skip_frames": "1001"},
        )
        assert r.status_code == 422
