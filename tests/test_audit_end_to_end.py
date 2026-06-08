"""
tests/test_audit_end_to_end.py
End-to-end test verifying the complete audit logging flow.

This test verifies the entire audit workflow:
1. write_audit() appends entries to the database
2. list_audit() retrieves them in correct order
3. Audit entries have all required fields

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5
"""
import os
import tempfile

import pytest


@pytest.fixture
def clean_db(monkeypatch):
    """Provide a fresh test database."""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "test_audit_e2e.db")

    import db
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()

    yield db


def test_audit_end_to_end(clean_db):
    """Complete audit workflow: write entries, list them, verify ordering and fields."""
    from audit.service import write_audit, list_audit

    # Write several audit entries simulating real operations
    # Requirement 15.1: login/logout
    write_audit("admin", "login", None, "success")
    write_audit(None, "login", None, "failure")  # Failed login
    write_audit("admin", "logout", None, "success")

    # Requirement 15.2: CRUD operations
    write_audit("admin", "create_camera", "camera:1", "success")
    write_audit("operator", "update_camera", "camera:1", "success")
    write_audit("admin", "delete_camera", "camera:1", "success")

    write_audit("admin", "create_user", "user:bob", "success")
    write_audit("admin", "update_user", "user:bob", "success")
    write_audit("admin", "delete_user", "user:bob", "success")

    write_audit("operator", "create_watchlist", "watchlist:5", "success")
    write_audit("operator", "add_watchlist_entry", "watchlist:5", "success")
    write_audit("operator", "remove_watchlist_entry", "entry:10", "success")

    write_audit("admin", "activate_license", "license", "success")
    write_audit("admin", "activate_license", "license", "failure")

    # Retrieve all entries (Requirement 15.4: limit=0 returns all)
    all_entries = list_audit(0)
    assert len(all_entries) == 14

    # Verify most recent entry is first (Requirement 15.3, 15.4: most-recent-first)
    assert all_entries[0]["action"] == "activate_license"
    assert all_entries[0]["outcome"] == "failure"
    assert all_entries[0]["username"] == "admin"

    # Verify oldest entry is last
    assert all_entries[-1]["action"] == "login"
    assert all_entries[-1]["outcome"] == "success"
    assert all_entries[-1]["username"] == "admin"

    # Test limit functionality (Requirement 15.3: limit>0 returns that many)
    limited_entries = list_audit(5)
    assert len(limited_entries) == 5

    # Verify all entries have required fields
    for entry in all_entries:
        assert "id" in entry
        assert "username" in entry  # Can be None for failed logins
        assert "action" in entry
        assert "resource" in entry  # Can be None
        assert "outcome" in entry
        assert "timestamp" in entry
        assert entry["id"] > 0
        assert entry["action"] != ""
        assert entry["outcome"] in ["success", "failure"]

    # Verify the service exposes no update/delete (Requirement 15.5)
    import audit.service
    assert not hasattr(audit.service, "update_audit")
    assert not hasattr(audit.service, "delete_audit")

    print("✓ End-to-end audit test passed!")
    print(f"✓ Created {len(all_entries)} audit entries")
    print(f"✓ Verified ordering (most-recent-first)")
    print(f"✓ Verified limit functionality")
    print(f"✓ Verified all required fields present")
    print(f"✓ Verified append-only (no update/delete operations)")
