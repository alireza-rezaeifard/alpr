"""
Property-based test for camera create/update persistence (task 9.2).

Feature: anpr-system-redesign, Property 10

Property 10: Camera create/update is a persistence round-trip.
    For any valid camera fields (name, URL, skip-frame), creating a camera then
    reading it back returns the same field values together with an assigned
    integer identifier, and updating a camera then reading it back returns the
    updated values.

Validates: Requirements 4.1, 4.3

Mechanism under test:
    * ``db.create_camera`` inserts a row and returns the camera (with id).
    * ``db.get_camera`` reads a camera back by id.
    * ``db.update_camera`` applies partial field changes and returns the result.
    * ``db.list_cameras`` enumerates persisted cameras.

The helpers are exercised directly against a temporary SQLite database so the
round-trip is tested against real persistence (no mocks).
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
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "cameras_test.db"))
    db.init_db()
    yield db


def _reset_cameras():
    """Clear the cameras table so each generated example starts clean."""
    conn = db.get_conn()
    conn.execute("DELETE FROM cameras")
    conn.commit()
    conn.close()


# Valid camera-field strategies.
names = st.text(max_size=120)
urls = st.text(max_size=200)
skip_frames = st.integers(min_value=1, max_value=1000)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    name=names,
    url=urls,
    skip=skip_frames,
    new_name=names,
    new_url=urls,
    new_skip=skip_frames,
)
def test_camera_create_update_round_trip(
    fresh_db, name, url, skip, new_name, new_url, new_skip
):
    """Create-then-read and update-then-read both round-trip the field values."""
    _reset_cameras()

    # --- Create round-trip (Req 4.1) ---
    created = db.create_camera(name, url, skip)

    # An integer identifier is assigned on create.
    assert isinstance(created["id"], int)
    camera_id = created["id"]
    assert created["name"] == name
    assert created["url"] == url
    assert created["skip_frames"] == skip

    # Reading the camera back returns the same field values + the id.
    read_back = db.get_camera(camera_id)
    assert read_back is not None
    assert read_back["id"] == camera_id
    assert read_back["name"] == name
    assert read_back["url"] == url
    assert read_back["skip_frames"] == skip

    # The persisted camera is enumerated by list_cameras.
    listed = db.list_cameras()
    assert any(c["id"] == camera_id for c in listed)

    # --- Update round-trip (Req 4.3) ---
    updated = db.update_camera(
        camera_id, name=new_name, url=new_url, skip_frames=new_skip
    )
    assert updated is not None
    assert updated["id"] == camera_id
    assert updated["name"] == new_name
    assert updated["url"] == new_url
    assert updated["skip_frames"] == new_skip

    # Reading back after update returns the updated values, same identifier.
    read_after_update = db.get_camera(camera_id)
    assert read_after_update is not None
    assert read_after_update["id"] == camera_id
    assert read_after_update["name"] == new_name
    assert read_after_update["url"] == new_url
    assert read_after_update["skip_frames"] == new_skip
