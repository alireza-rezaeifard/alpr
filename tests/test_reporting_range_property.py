"""
Property-based test for reporting range parameters (task 16.3).

Feature: anpr-system-redesign, Property 24

Property 24: Reporting range parameters are bounded and complete.
    *For any* requested detection-list limit, the value is accepted if and only
    if it lies in 1..1000; *for any* requested timeline day count in 1..90, the
    result contains a per-day count bucket for each day in the requested range.

Validates: Requirements 13.2, 13.3

Mechanism under test:
    * ``GET /api/reports/detections`` bounds the ``limit`` query parameter to the
      inclusive range 1..1000 (Req 13.2).
    * ``GET /api/reports/timeline`` bounds the ``days`` query parameter to the
      inclusive range 1..90 and returns per-day detection counts that must be
      complete across the requested range (Req 13.3).

Both endpoints are exercised through a real FastAPI app wired to a temporary
SQLite database (no mocks). Authentication/authorization is satisfied by
overriding ``current_user`` with an Admin identity (the ``view`` permission
guard then resolves against the real RBAC matrix).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Ensure the project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from auth.dependencies import AuthenticatedUser, current_user
from routers import reports


# Inclusive bounds defined by Requirements 13.2 and 13.3.
LIMIT_MIN, LIMIT_MAX = 1, 1000
DAYS_MIN, DAYS_MAX = 1, 90


def _admin_user() -> AuthenticatedUser:
    """An authenticated Admin identity (holds the ``view`` permission)."""
    return AuthenticatedUser(
        id=1,
        username="admin",
        role="Admin",
        disabled=False,
        jti="test-jti",
        token_exp=4_000_000_000,
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient over a fresh temp SQLite db with auth overridden."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "reports_test.db"))
    db.init_db()

    app = FastAPI()
    app.include_router(reports.router)
    app.dependency_overrides[current_user] = _admin_user

    with TestClient(app) as test_client:
        yield test_client


def _reset_detections():
    """Clear the detections table so each generated example starts clean."""
    conn = db.get_conn()
    conn.execute("DELETE FROM detections")
    conn.commit()
    conn.close()


def _insert_detection_on(day_offset: int) -> None:
    """Insert one detection at noon, ``day_offset`` days before today."""
    ts = (datetime.now() - timedelta(days=day_offset)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO detections (session_id, timestamp, source_type, plate_dtrb, "
        "plate_persian, confidence) VALUES (?, ?, ?, ?, ?, ?)",
        (None, ts.isoformat(), "image", "12a34567", "test", 0.9),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Clause 1 — detection-list limit is bounded (accepted iff in 1..1000).
# Feature: anpr-system-redesign, Property 24 — Validates: Requirements 13.2
# ---------------------------------------------------------------------------
@settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(limit=st.integers(min_value=-50, max_value=1100))
def test_detection_limit_is_bounded(client, limit):
    """A detection-list limit is accepted iff it lies in the inclusive 1..1000."""
    resp = client.get("/api/reports/detections", params={"limit": limit})
    in_range = LIMIT_MIN <= limit <= LIMIT_MAX
    if in_range:
        assert resp.status_code == 200, (
            f"limit={limit} is in range and should be accepted, "
            f"got {resp.status_code}"
        )
    else:
        assert resp.status_code == 422, (
            f"limit={limit} is out of range and should be rejected, "
            f"got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Clause 2a — timeline day count is bounded (accepted iff in 1..90).
# Feature: anpr-system-redesign, Property 24 — Validates: Requirements 13.3
# ---------------------------------------------------------------------------
@settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(days=st.integers(min_value=-50, max_value=200))
def test_timeline_days_is_bounded(client, days):
    """A timeline day count is accepted iff it lies in the inclusive 1..90."""
    resp = client.get("/api/reports/timeline", params={"days": days})
    in_range = DAYS_MIN <= days <= DAYS_MAX
    if in_range:
        assert resp.status_code == 200, (
            f"days={days} is in range and should be accepted, "
            f"got {resp.status_code}"
        )
    else:
        assert resp.status_code == 422, (
            f"days={days} is out of range and should be rejected, "
            f"got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Clause 2b — timeline is complete across the requested range: for a day count
# in 1..90 the result has a per-day bucket for every day in the range.
# Feature: anpr-system-redesign, Property 24 — Validates: Requirements 13.3
# ---------------------------------------------------------------------------
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(data=st.data())
def test_timeline_is_complete_over_requested_range(client, data):
    """Every day in the requested range appears as a bucket in the timeline."""
    _reset_detections()

    days = data.draw(st.integers(min_value=DAYS_MIN, max_value=DAYS_MAX))
    # Populate detections on an arbitrary subset of the in-range days. Days with
    # no detection must still appear in the series (with a zero count) for the
    # series to be complete across the requested range.
    max_offset = days - 1
    populated = data.draw(
        st.sets(st.integers(min_value=0, max_value=max_offset), max_size=min(days, 10))
    )
    for offset in populated:
        _insert_detection_on(offset)

    resp = client.get("/api/reports/timeline", params={"days": days})
    assert resp.status_code == 200
    timeline = resp.json()["timeline"]
    returned_dates = {entry["dt"] for entry in timeline}

    today = datetime.now().date()
    expected_dates = {
        (today - timedelta(days=offset)).isoformat() for offset in range(days)
    }

    missing = expected_dates - returned_dates
    assert not missing, (
        f"timeline for days={days} is missing per-day buckets for "
        f"{sorted(missing)}; populated offsets={sorted(populated)}"
    )
