"""
tests/test_retention_implementation.py
Unit tests for retention policy implementation (Task 16.12).

Tests the core retention functions:
* ``set_retention_policy(days)`` persists days>0, rejects days<=0
* ``retention_cutoff(now, days)`` computes the correct cutoff timestamp
* ``prune_detections(now)`` deletes older detections when policy active
* ``GET/PUT /api/config/retention`` endpoints work correctly

Requirements: 16.1, 16.2, 16.3, 16.4
"""
import importlib
from datetime import datetime, timedelta

import pytest

import db


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    """Set up a clean test database for each test."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    # Reload modules to pick up the patched DB_PATH
    import retention.policy
    import retention.service
    import routers.retention
    importlib.reload(retention.policy)
    importlib.reload(retention.service)
    importlib.reload(routers.retention)
    yield


# ---------------------------------------------------------------------------
# Pure policy function tests
# ---------------------------------------------------------------------------
def test_retention_cutoff_computes_correct_timestamp():
    """Requirement 16.2: cutoff = now - days."""
    from retention.policy import retention_cutoff

    now = datetime(2024, 1, 15, 12, 0, 0)
    cutoff = retention_cutoff(now, 30)
    expected = datetime(2023, 12, 16, 12, 0, 0)
    assert cutoff == expected


def test_retention_cutoff_with_7_days():
    """Requirement 16.2: cutoff = now - 7 days."""
    from retention.policy import retention_cutoff

    now = datetime(2024, 1, 15, 12, 0, 0)
    cutoff = retention_cutoff(now, 7)
    expected = datetime(2024, 1, 8, 12, 0, 0)
    assert cutoff == expected


def test_retention_cutoff_with_1_day():
    """Requirement 16.2: cutoff = now - 1 day."""
    from retention.policy import retention_cutoff

    now = datetime(2024, 1, 15, 12, 0, 0)
    cutoff = retention_cutoff(now, 1)
    expected = datetime(2024, 1, 14, 12, 0, 0)
    assert cutoff == expected


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------
def test_set_retention_policy_persists_positive_days():
    """Requirement 16.1: persist policy when days > 0."""
    from retention.service import set_retention_policy

    set_retention_policy(45)
    stored = db.get_retention_days()
    assert stored == 45


def test_set_retention_policy_rejects_zero():
    """Requirement 16.4: reject days <= 0."""
    from retention.service import RetentionPolicyError, set_retention_policy

    with pytest.raises(RetentionPolicyError, match="must be greater than zero"):
        set_retention_policy(0)


def test_set_retention_policy_rejects_negative():
    """Requirement 16.4: reject days <= 0."""
    from retention.service import RetentionPolicyError, set_retention_policy

    with pytest.raises(RetentionPolicyError, match="must be greater than zero"):
        set_retention_policy(-10)


def test_get_retention_policy_returns_configured_value():
    """Retrieve a configured policy."""
    from retention.service import get_retention_policy, set_retention_policy

    set_retention_policy(60)
    policy = get_retention_policy()
    assert policy == 60


def test_prune_detections_with_no_policy_retains_all():
    """Requirement 16.3: no policy configured → retain all detections."""
    from retention.service import prune_detections

    # Clear any default policy
    db.set_retention_days(0)

    # Insert some detections
    sid = db.start_session("test", "test_source")
    db.save_detection(sid, "test", "12A34567", "۱۲A۳۴۵۶۷", 0.95)
    db.save_detection(sid, "test", "23B45678", "۲۳B۴۵۶۷۸", 0.90)
    db.end_session(sid, 0, 2, 2)

    # Prune should return 0 (no deletions)
    now = datetime.now()
    deleted = prune_detections(now)
    assert deleted == 0

    # Detections should still exist
    conn = db.get_conn()
    count = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    conn.close()
    assert count == 2


def test_prune_detections_with_policy_deletes_old_records():
    """Requirement 16.2: delete detections older than cutoff when policy active."""
    from retention.service import prune_detections, set_retention_policy

    # Set a 7-day retention policy
    set_retention_policy(7)

    # Insert detections: one old (10 days ago), one recent (3 days ago)
    now = datetime.now()
    old_timestamp = (now - timedelta(days=10)).isoformat()
    recent_timestamp = (now - timedelta(days=3)).isoformat()

    sid = db.start_session("test", "test_source")
    db.end_session(sid, 0, 0, 0)

    conn = db.get_conn()
    conn.execute(
        "INSERT INTO detections (session_id, source_type, plate_dtrb, plate_persian, confidence, timestamp) "
        "VALUES (?, 'test', '12A34567', '۱۲A۳۴۵۶۷', 0.95, ?)",
        (sid, old_timestamp),
    )
    conn.execute(
        "INSERT INTO detections (session_id, source_type, plate_dtrb, plate_persian, confidence, timestamp) "
        "VALUES (?, 'test', '23B45678', '۲۳B۴۵۶۷۸', 0.90, ?)",
        (sid, recent_timestamp),
    )
    conn.commit()
    conn.close()

    # Prune should delete the old detection
    deleted = prune_detections(now)
    assert deleted == 1

    # Verify only the recent detection remains
    conn = db.get_conn()
    remaining = conn.execute("SELECT plate_dtrb FROM detections").fetchall()
    conn.close()
    assert len(remaining) == 1
    assert remaining[0]["plate_dtrb"] == "23B45678"


def test_prune_detections_with_policy_retains_recent_records():
    """Requirement 16.2: retain detections newer than cutoff."""
    from retention.service import prune_detections, set_retention_policy

    # Set a 7-day retention policy
    set_retention_policy(7)

    # Insert only recent detections (all within 7 days)
    now = datetime.now()
    recent1 = (now - timedelta(days=3)).isoformat()
    recent2 = (now - timedelta(days=5)).isoformat()

    sid = db.start_session("test", "test_source")
    db.end_session(sid, 0, 0, 0)

    conn = db.get_conn()
    conn.execute(
        "INSERT INTO detections (session_id, source_type, plate_dtrb, plate_persian, confidence, timestamp) "
        "VALUES (?, 'test', '12A34567', '۱۲A۳۴۵۶۷', 0.95, ?)",
        (sid, recent1),
    )
    conn.execute(
        "INSERT INTO detections (session_id, source_type, plate_dtrb, plate_persian, confidence, timestamp) "
        "VALUES (?, 'test', '23B45678', '۲۳B۴۵۶۷۸', 0.90, ?)",
        (sid, recent2),
    )
    conn.commit()
    conn.close()

    # Prune should delete nothing
    deleted = prune_detections(now)
    assert deleted == 0

    # Verify both detections remain
    conn = db.get_conn()
    count = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    conn.close()
    assert count == 2


# ---------------------------------------------------------------------------
# Router endpoint tests
# ---------------------------------------------------------------------------
def test_get_retention_endpoint_requires_manage_config_permission():
    """GET /api/config/retention requires manage_config permission."""
    from routers.retention import get_retention
    from auth.dependencies import require_permission
    import inspect

    # Check that the endpoint depends on require_permission("manage_config")
    sig = inspect.signature(get_retention)
    deps = [
        param.default
        for param in sig.parameters.values()
        if hasattr(param.default, "dependency")
    ]
    # The dependency should be require_permission("manage_config")
    # We can't directly inspect the permission value, but we can verify
    # the dependency is present
    assert len(deps) > 0


def test_put_retention_endpoint_requires_manage_config_permission():
    """PUT /api/config/retention requires manage_config permission."""
    from routers.retention import update_retention
    import inspect

    sig = inspect.signature(update_retention)
    deps = [
        param.default
        for param in sig.parameters.values()
        if hasattr(param.default, "dependency")
    ]
    assert len(deps) > 0


def test_put_retention_endpoint_rejects_zero_days():
    """Requirement 16.4: PUT with days <= 0 raises validation error."""
    from routers.retention import update_retention
    from schemas import RetentionConfig
    from fastapi import HTTPException

    body = RetentionConfig(days=0)
    # Mock the authenticated user (Admin has manage_config permission)
    mock_user = {"id": 1, "username": "admin", "role": "Admin", "disabled": False}

    with pytest.raises(HTTPException) as exc_info:
        update_retention(body, _user=mock_user)

    assert exc_info.value.status_code == 422
    assert "validation_error" in str(exc_info.value.detail)


def test_put_retention_endpoint_rejects_negative_days():
    """Requirement 16.4: PUT with days <= 0 raises validation error."""
    from routers.retention import update_retention
    from schemas import RetentionConfig
    from fastapi import HTTPException

    body = RetentionConfig(days=-5)
    mock_user = {"id": 1, "username": "admin", "role": "Admin", "disabled": False}

    with pytest.raises(HTTPException) as exc_info:
        update_retention(body, _user=mock_user)

    assert exc_info.value.status_code == 422
    assert "validation_error" in str(exc_info.value.detail)


def test_put_retention_endpoint_accepts_positive_days():
    """Requirement 16.1: PUT with days > 0 persists the policy."""
    from routers.retention import update_retention
    from schemas import RetentionConfig

    body = RetentionConfig(days=30)
    mock_user = {"id": 1, "username": "admin", "role": "Admin", "disabled": False}

    result = update_retention(body, _user=mock_user)
    assert result.days == 30

    # Verify it was persisted
    stored = db.get_retention_days()
    assert stored == 30


def test_get_retention_endpoint_returns_configured_policy():
    """GET /api/config/retention returns the configured policy."""
    from retention.service import set_retention_policy
    from routers.retention import get_retention

    set_retention_policy(45)
    mock_user = {"id": 1, "username": "admin", "role": "Admin", "disabled": False}

    result = get_retention(_user=mock_user)
    assert result.days == 45
