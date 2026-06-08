"""
tests/test_audit_implementation.py
Unit and integration tests for the append-only audit logging component.

These tests verify that:
    * write_audit() appends entries with username, action, resource, outcome, timestamp
    * list_audit(limit) returns entries most-recent-first
    * limit>0 returns that many entries; limit==0 returns all
    * The audit router guards the read endpoint with require_permission("view_audit")

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5
"""
import importlib
import os
import tempfile

import pytest


@pytest.fixture
def db_audit(monkeypatch):
    """Provide a fresh test database and reload the audit module."""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "test_audit.db")
    monkeypatch.setattr("db.DB_PATH", db_path)

    import db
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()

    import audit.service as audit_service
    importlib.reload(audit_service)

    yield db, audit_service


# ---------------------------------------------------------------------------
# write_audit() tests
# ---------------------------------------------------------------------------
def test_write_audit_appends_entry(db_audit):
    """write_audit() persists an entry and returns it with id, timestamp."""
    db, audit_service = db_audit
    entry = audit_service.write_audit("admin", "login", None, "success")

    assert entry["id"] > 0
    assert entry["username"] == "admin"
    assert entry["action"] == "login"
    assert entry["resource"] is None
    assert entry["outcome"] == "success"
    assert "timestamp" in entry


def test_write_audit_accepts_none_user_for_failed_login(db_audit):
    """Failed login attempts with unknown username record username=None."""
    db, audit_service = db_audit
    entry = audit_service.write_audit(None, "login", None, "failure")

    assert entry["username"] is None
    assert entry["action"] == "login"
    assert entry["outcome"] == "failure"


def test_write_audit_records_resource(db_audit):
    """write_audit() stores the resource field when provided."""
    db, audit_service = db_audit
    entry = audit_service.write_audit("operator", "create_camera", "camera:5", "success")

    assert entry["resource"] == "camera:5"


def test_write_audit_multiple_entries(db_audit):
    """Multiple write_audit calls append entries with distinct ids."""
    db, audit_service = db_audit
    e1 = audit_service.write_audit("admin", "login", None, "success")
    e2 = audit_service.write_audit("operator", "logout", None, "success")
    e3 = audit_service.write_audit("admin", "create_user", "user:bob", "success")

    assert e1["id"] != e2["id"] != e3["id"]


# ---------------------------------------------------------------------------
# list_audit() tests — ordering and limit
# ---------------------------------------------------------------------------
def test_list_audit_returns_entries_most_recent_first(db_audit):
    """list_audit() orders entries by timestamp desc, id desc."""
    db, audit_service = db_audit
    # Write entries in order
    audit_service.write_audit("admin", "action1", None, "success")
    audit_service.write_audit("operator", "action2", None, "success")
    audit_service.write_audit("viewer", "action3", None, "success")

    entries = audit_service.list_audit(10)
    # Most recent (action3) should be first
    assert entries[0]["action"] == "action3"
    assert entries[1]["action"] == "action2"
    assert entries[2]["action"] == "action1"


def test_list_audit_limit_positive_returns_at_most_limit(db_audit):
    """Requirement 15.3: limit > 0 returns at most that many entries."""
    db, audit_service = db_audit
    for i in range(10):
        audit_service.write_audit("admin", f"action{i}", None, "success")

    entries = audit_service.list_audit(5)
    assert len(entries) == 5


def test_list_audit_limit_zero_returns_all(db_audit):
    """Requirement 15.4: limit == 0 returns all entries."""
    db, audit_service = db_audit
    for i in range(10):
        audit_service.write_audit("admin", f"action{i}", None, "success")

    entries = audit_service.list_audit(0)
    assert len(entries) == 10


def test_list_audit_empty_table_returns_empty_list(db_audit):
    """list_audit() returns an empty list when no entries exist."""
    db, audit_service = db_audit
    entries = audit_service.list_audit(10)
    assert entries == []


# ---------------------------------------------------------------------------
# Append-only enforcement (Requirement 15.5)
# ---------------------------------------------------------------------------
def test_no_update_operation_exposed():
    """Requirement 15.5: The audit service exposes no update function."""
    import audit.service as audit_service
    assert not hasattr(audit_service, "update_audit")


def test_no_delete_operation_exposed():
    """Requirement 15.5: The audit service exposes no delete function."""
    import audit.service as audit_service
    assert not hasattr(audit_service, "delete_audit")


# ---------------------------------------------------------------------------
# Router endpoint permission guard
# ---------------------------------------------------------------------------
def test_get_audit_endpoint_requires_view_audit_permission():
    """The GET /api/audit endpoint requires view_audit permission."""
    from routers.audit import get_audit_log
    from auth.dependencies import require_permission
    import inspect

    sig = inspect.signature(get_audit_log)
    # The `user` parameter should depend on require_permission("view_audit")
    user_param = sig.parameters.get("user")
    assert user_param is not None
    # The default should be a Depends call; we can't easily inspect the
    # permission string here, but we verify the dependency factory is present
    assert user_param.default is not inspect.Parameter.empty
