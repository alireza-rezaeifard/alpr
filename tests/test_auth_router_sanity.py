"""Sanity tests for the auth router and default-admin bootstrap (task 6.2).

These exercise the core happy/edge paths against an isolated temp database.
Task 6.3 covers the fuller edge-case matrix separately.
"""
import importlib
import os

import pytest
from fastapi import HTTPException


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Point db at a fresh temp file and reset the cached server secret."""
    os.environ["ANPR_SECRET_KEY"] = "test-secret-for-sanity"
    import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    # Reload the router so module-level imports bind to the patched db module.
    import routers.auth as auth
    importlib.reload(auth)
    yield db, auth
    os.environ.pop("ANPR_SECRET_KEY", None)


def test_bootstrap_creates_single_default_admin(fresh_db):
    db, auth = fresh_db
    assert db.count_users() == 0

    created = auth.bootstrap_default_admin()
    assert created is True
    assert db.count_users() == 1

    admin = db.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
    assert admin is not None
    assert admin["role"] == "Admin"
    assert not bool(admin["disabled"])
    # Password is stored hashed, never in plaintext.
    assert admin["password_hash"] != auth.DEFAULT_ADMIN_PASSWORD

    # Idempotent: a second call must not create another account.
    assert auth.bootstrap_default_admin() is False
    assert db.count_users() == 1


def test_login_success_returns_token_role_expiry_permissions(fresh_db):
    db, auth = fresh_db
    auth.bootstrap_default_admin()

    resp = auth.login(auth.LoginRequest(username="admin", password="admin"))
    assert resp.token
    assert resp.role == "Admin"
    assert resp.expires_at  # ISO timestamp present
    assert "manage_users" in resp.permissions and "view" in resp.permissions


def test_login_rejects_wrong_password(fresh_db):
    db, auth = fresh_db
    auth.bootstrap_default_admin()
    with pytest.raises(HTTPException) as exc:
        auth.login(auth.LoginRequest(username="admin", password="wrong"))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "auth_failed"


def test_login_rejects_unknown_user(fresh_db):
    db, auth = fresh_db
    auth.bootstrap_default_admin()
    with pytest.raises(HTTPException) as exc:
        auth.login(auth.LoginRequest(username="nobody", password="x"))
    assert exc.value.detail["code"] == "auth_failed"


def test_login_rejects_disabled_account(fresh_db):
    db, auth = fresh_db
    from auth.security import hash_password
    created = db.create_user("dis", hash_password("pw"), "Operator")
    db.update_user(created["id"], disabled=True)
    with pytest.raises(HTTPException) as exc:
        auth.login(auth.LoginRequest(username="dis", password="pw"))
    assert exc.value.detail["code"] == "auth_failed"


def test_logout_revokes_token_jti(fresh_db):
    db, auth = fresh_db
    auth.bootstrap_default_admin()
    user = auth.AuthenticatedUser(
        id=1, username="admin", role="Admin", disabled=False,
        jti="jti-xyz", token_exp=9999999999,
    )
    result = auth.logout(user)
    assert result == {"status": "ok"}
    assert db.is_token_revoked("jti-xyz") is True
