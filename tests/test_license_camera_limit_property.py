"""
Property-based test for the camera-start license-limit guard in
auth/dependencies.require_license(check_camera_limit=True).

Feature: anpr-system-redesign, Property 9

Property 9: Camera starts never exceed the license camera limit.
    For any license camera limit L and any running-camera count >= L, a
    camera-start request is rejected with a license-limit response (HTTP 403,
    code 'license_limit'). Conversely, when the running count is < L the
    camera-start is permitted and the authenticated user is returned.

Validates: Requirements 3.6
"""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import db
from schemas import ErrorCode

from auth import dependencies as deps


# ---------------------------------------------------------------------------
# Temp SQLite fixture: point db at a fresh file with one active license row.
# ---------------------------------------------------------------------------
@pytest.fixture()
def temp_db(monkeypatch):
    """Point db at a fresh temporary SQLite file and initialise the schema."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "license_limit_test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


def _activate_license(camera_limit: int) -> None:
    """Insert a single active, unexpired license with the given camera limit."""
    future = (date.today() + timedelta(days=365)).isoformat()
    conn = db.get_conn()
    conn.execute("UPDATE licenses SET active = 0 WHERE active = 1")
    conn.execute(
        "INSERT INTO licenses (key, active, expiry, camera_limit, activated_at) "
        "VALUES (?, 1, ?, ?, ?)",
        ("test-key", future, camera_limit, "2024-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()


def _admin_user() -> deps.AuthenticatedUser:
    """Build an authenticated Admin identity directly (no token round-trip)."""
    return deps.AuthenticatedUser(
        id=1,
        username="admin",
        role="Admin",
        disabled=False,
        jti="test-jti",
        token_exp=4_000_000_000,
    )


# Small positive camera limits, per task guidance (1..32).
_limits = st.integers(min_value=1, max_value=32)


# Feature: anpr-system-redesign, Property 9
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_camera_start_never_exceeds_license_limit(temp_db, data) -> None:
    limit = data.draw(_limits)
    _activate_license(camera_limit=limit)
    user = _admin_user()

    # --- At or above the limit: must be rejected with license_limit (403) ---
    running_at_or_above = data.draw(st.integers(min_value=limit, max_value=limit + 32))
    dep_reject = deps.require_license(
        check_camera_limit=True,
        running_count_provider=lambda: running_at_or_above,
    )
    with pytest.raises(HTTPException) as exc:
        dep_reject(user=user)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == ErrorCode.LICENSE_LIMIT.value

    # --- Strictly below the limit: must be permitted (returns the user) ---
    running_below = data.draw(st.integers(min_value=0, max_value=limit - 1))
    dep_permit = deps.require_license(
        check_camera_limit=True,
        running_count_provider=lambda: running_below,
    )
    assert dep_permit(user=user) is user
