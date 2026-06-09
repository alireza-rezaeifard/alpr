"""
tests/test_audit_integration.py
Integration tests verifying that audit logging is called at the correct points.

These tests verify that write_audit() is called:
    * On login (success and failure) — Requirement 15.1
    * On logout — Requirement 15.1
    * On camera create/update/delete — Requirement 15.2
    * On user create/update/delete — Requirement 15.2
    * On watchlist create and entry add/remove — Requirement 15.2
    * On license activation — Requirement 15.2

Requirements: 15.1, 15.2
"""
import importlib
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_audit(monkeypatch):
    """Mock write_audit to verify it's called with correct arguments.

    Each router binds ``from audit.service import write_audit`` at import time,
    so the name lives in the *router* module's namespace. Patching
    ``audit.service.write_audit`` would not affect those already-bound names, so
    we patch the name where it is actually looked up — in every router module
    that records audit entries. They all share the same MagicMock so a test can
    assert on the single call regardless of which router it exercised.
    """
    import audit.service
    import routers.auth
    import routers.cameras
    import routers.users
    import routers.watchlists
    import routers.licenses

    mock = MagicMock()
    monkeypatch.setattr(audit.service, "write_audit", mock)
    for module in (
        routers.auth,
        routers.cameras,
        routers.users,
        routers.watchlists,
        routers.licenses,
    ):
        monkeypatch.setattr(module, "write_audit", mock)
    return mock


@pytest.fixture
def db_test(monkeypatch):
    """Provide a fresh test database."""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "test_audit_integration.db")
    monkeypatch.setattr("db.DB_PATH", db_path)

    import db
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()

    # Create a test user for authentication
    from auth.security import hash_password
    db.create_user("testadmin", hash_password("password"), "Admin")

    yield db


@pytest.fixture
def admin_user():
    """A mock authenticated admin user."""
    from auth.dependencies import AuthenticatedUser
    return AuthenticatedUser(
        id=1,
        username="testadmin",
        role="Admin",
        disabled=False,
        jti="test-jti",
        token_exp=9999999999,
    )


# ---------------------------------------------------------------------------
# Auth router audit logging (Requirement 15.1)
# ---------------------------------------------------------------------------
def test_login_success_logs_audit(db_test, mock_audit):
    """Successful login calls write_audit with username, login, success."""
    import routers.auth as auth

    body = auth.LoginRequest(username="testadmin", password="password")
    auth.login(body)

    # Verify write_audit was called with correct parameters
    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"  # username
    assert args[1] == "login"       # action
    assert args[2] is None          # resource
    assert args[3] == "success"     # outcome


def test_login_failure_logs_audit(db_test, mock_audit):
    """Failed login calls write_audit with username, login, failure."""
    import routers.auth as auth

    body = auth.LoginRequest(username="testadmin", password="wrongpassword")
    try:
        auth.login(body)
    except:
        pass  # Expected to fail

    # Verify write_audit was called with failure outcome
    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "login"
    assert args[3] == "failure"


def test_logout_logs_audit(admin_user, mock_audit):
    """Logout calls write_audit with username, logout, success."""
    import routers.auth as auth

    auth.logout(admin_user)

    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "logout"
    assert args[3] == "success"


# ---------------------------------------------------------------------------
# Camera router audit logging (Requirement 15.2)
# ---------------------------------------------------------------------------
def test_create_camera_logs_audit(admin_user, mock_audit, monkeypatch):
    """Creating a camera logs audit entry."""
    import routers.cameras as cameras

    # Mock camera manager
    mock_manager = MagicMock()
    mock_manager.add_camera.return_value = {
        "id": 42, "name": "Test Cam", "url": "rtsp://test", "skip_frames": 15,
        "status": "stopped", "task_id": None, "session_id": None
    }
    monkeypatch.setattr(cameras, "get_camera_manager", lambda: mock_manager)

    body = cameras.CameraCreate(name="Test Cam", url="rtsp://test", skip_frames=15)
    cameras.create_camera(body, admin_user)

    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "create_camera"
    assert args[2] == "camera:42"
    assert args[3] == "success"


def test_update_camera_logs_audit(admin_user, mock_audit, monkeypatch):
    """Updating a camera logs audit entry."""
    import routers.cameras as cameras

    mock_manager = MagicMock()
    mock_manager.update_camera_info.return_value = {
        "id": 5, "name": "Updated", "url": "rtsp://new", "skip_frames": 20,
        "status": "stopped", "task_id": None, "session_id": None
    }
    monkeypatch.setattr(cameras, "get_camera_manager", lambda: mock_manager)

    body = cameras.CameraUpdate(name="Updated")
    cameras.update_camera(5, body, admin_user)

    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "update_camera"
    assert args[2] == "camera:5"
    assert args[3] == "success"


def test_delete_camera_logs_audit(admin_user, mock_audit, monkeypatch):
    """Deleting a camera logs audit entry."""
    import routers.cameras as cameras

    mock_manager = MagicMock()
    mock_manager.remove_camera.return_value = True
    monkeypatch.setattr(cameras, "get_camera_manager", lambda: mock_manager)

    cameras.delete_camera(7, admin_user)

    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "delete_camera"
    assert args[2] == "camera:7"
    assert args[3] == "success"


# ---------------------------------------------------------------------------
# User router audit logging (Requirement 15.2)
# ---------------------------------------------------------------------------
def test_create_user_logs_audit(db_test, admin_user, mock_audit):
    """Creating a user logs audit entry."""
    import routers.users as users

    body = users.UserCreate(username="newuser", password="pass", role="Viewer")
    users.create_user(body, admin_user)

    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "create_user"
    assert args[2] == "user:newuser"
    assert args[3] == "success"


def test_update_user_logs_audit(db_test, admin_user, mock_audit):
    """Updating a user logs audit entry."""
    import routers.users as users

    # Create another user to update
    from auth.security import hash_password
    db_test.create_user("targetuser", hash_password("pass"), "Viewer")

    body = users.UserUpdate(role="Operator")
    user_id = db_test.get_user_by_username("targetuser")["id"]
    users.update_user(user_id, body, admin_user)

    # Called twice: once for update, potentially for bootstrap
    # Just check the most recent call
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "update_user"
    assert f"user:{user_id}" in args[2]
    assert args[3] == "success"


def test_delete_user_logs_audit(db_test, admin_user, mock_audit):
    """Deleting a user logs audit entry."""
    import routers.users as users

    # Create another user to delete
    from auth.security import hash_password
    db_test.create_user("deleteuser", hash_password("pass"), "Viewer")

    user_id = db_test.get_user_by_username("deleteuser")["id"]
    users.delete_user(user_id, admin_user)

    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "delete_user"
    assert f"user:{user_id}" in args[2]
    assert args[3] == "success"


# ---------------------------------------------------------------------------
# Watchlist router audit logging (Requirement 15.2)
# ---------------------------------------------------------------------------
def test_create_watchlist_logs_audit(db_test, admin_user, mock_audit, monkeypatch):
    """Creating a watchlist logs audit entry."""
    import routers.watchlists as watchlists
    import watchlist.service
    
    # Mock the service
    mock_service = MagicMock()
    mock_service.create_watchlist.return_value = {
        "id": 10, "name": "Blocklist", "list_type": "block", 
        "created_at": "2024-01-01", "entries": []
    }
    monkeypatch.setattr(watchlists, "service", mock_service)

    body = watchlists.WatchlistCreate(name="Blocklist", list_type="block")
    watchlists.create_watchlist(body, admin_user)

    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "create_watchlist"
    assert args[2] == "watchlist:10"
    assert args[3] == "success"


def test_add_watchlist_entry_logs_audit(db_test, admin_user, mock_audit, monkeypatch):
    """Adding a watchlist entry logs audit entry."""
    import routers.watchlists as watchlists
    
    mock_service = MagicMock()
    mock_service.get_watchlist.return_value = {"id": 1}
    mock_service.add_entry.return_value = {
        "id": 99, "watchlist_id": 1, "plate_value": "ABC123",
        "label": None, "reason": None, "created_at": "2024-01-01"
    }
    monkeypatch.setattr(watchlists, "service", mock_service)

    body = watchlists.WatchlistEntryCreate(plate_value="ABC123")
    watchlists.add_entry(1, body, admin_user)

    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "add_watchlist_entry"
    assert args[2] == "watchlist:1"
    assert args[3] == "success"


def test_remove_watchlist_entry_logs_audit(admin_user, mock_audit, monkeypatch):
    """Removing a watchlist entry logs audit entry."""
    import routers.watchlists as watchlists
    
    mock_service = MagicMock()
    mock_service.remove_entry.return_value = True
    monkeypatch.setattr(watchlists, "service", mock_service)

    watchlists.remove_entry(5, admin_user)

    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "remove_watchlist_entry"
    assert args[2] == "entry:5"
    assert args[3] == "success"


# ---------------------------------------------------------------------------
# License router audit logging (Requirement 15.2)
# ---------------------------------------------------------------------------
def test_activate_license_success_logs_audit(admin_user, mock_audit, monkeypatch):
    """Successful license activation logs audit entry."""
    import routers.licenses as licenses
    import licensing.service
    
    mock_service = MagicMock()
    mock_service.activate_license.return_value = None
    mock_service.get_license_status.return_value = licenses.LicenseStatus(
        active=True, expiry="2025-12-31", camera_limit=10, configured_cameras=0
    )
    monkeypatch.setattr(licenses, "service", mock_service)

    payload = licenses.LicenseActivate(key="test-key")
    licenses.activate(payload, admin_user)

    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "activate_license"
    assert args[2] == "license"
    assert args[3] == "success"


def test_activate_license_failure_logs_audit(admin_user, mock_audit, monkeypatch):
    """Failed license activation logs audit entry with failure outcome."""
    import routers.licenses as licenses
    import licensing.service
    from licensing.service import LicenseValidationError
    
    mock_service = MagicMock()
    mock_service.activate_license.side_effect = LicenseValidationError("Invalid key")
    monkeypatch.setattr(licenses, "service", mock_service)

    payload = licenses.LicenseActivate(key="bad-key")
    try:
        licenses.activate(payload, admin_user)
    except:
        pass  # Expected to fail

    mock_audit.assert_called_once()
    args = mock_audit.call_args[0]
    assert args[0] == "testadmin"
    assert args[1] == "activate_license"
    assert args[2] == "license"
    assert args[3] == "failure"
