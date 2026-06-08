"""
Unit tests for auth/dependencies.py — the FastAPI security dependency chain.

These exercise the dependency *functions* directly (without spinning up an HTTP
server) against a temporary SQLite database, covering:

* authentication: missing token -> 401 auth_required (Req 1.6); expired /
  invalid / revoked token and disabled account -> 401 auth_failed (Req 1.5);
  valid token -> authenticated identity carrying the current DB role (Req 1.4).
* authorization: require_permission permits/denies by the user's current role,
  raising 403 forbidden when lacking the permission (Req 2.2, 2.3, 2.4).
* licensing: require_license raises license_required / license_expired /
  license_limit with the right codes/status (Req 3.3, 3.4, 3.6) and is omitted
  for the always-reachable endpoints (Req 3.7).

Feature: anpr-system-redesign
"""
from __future__ import annotations

import os
import tempfile
import time
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import db
from schemas import ErrorCode

from auth import dependencies as deps
from auth.security import create_session_token, hash_password


@pytest.fixture()
def temp_db(monkeypatch):
    """Point db at a fresh temporary SQLite file and force a fixed secret."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "deps_test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setenv("ANPR_SECRET_KEY", "unit-test-secret")
    db.init_db()
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


def _make_user(role: str = "Admin", disabled: bool = False) -> int:
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, role, disabled, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (f"user_{role}_{int(time.time()*1000)}", hash_password("pw"),
         role, 1 if disabled else 0, "2024-01-01T00:00:00"),
    )
    uid = cur.lastrowid
    conn.commit()
    conn.close()
    return uid


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _activate_license(expiry: str, camera_limit: int) -> None:
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO licenses (key, active, expiry, camera_limit, activated_at) "
        "VALUES (?, 1, ?, ?, ?)",
        ("k", expiry, camera_limit, "2024-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# current_user (Requirements 1.4, 1.5, 1.6)
# ---------------------------------------------------------------------------
def test_missing_token_is_auth_required(temp_db):
    with pytest.raises(HTTPException) as exc:
        deps.current_user(credentials=None)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == ErrorCode.AUTH_REQUIRED.value


def test_valid_token_yields_authenticated_user_with_db_role(temp_db):
    uid = _make_user(role="Operator")
    token = create_session_token(uid, "Operator", ttl=3600, secret="unit-test-secret")
    user = deps.current_user(credentials=_creds(token))
    assert user.id == uid
    assert user.role == "Operator"
    assert not user.disabled


def test_role_change_takes_effect_on_next_request(temp_db):
    """Token issued as Viewer; DB role bumped to Admin -> current_user reports Admin."""
    uid = _make_user(role="Viewer")
    token = create_session_token(uid, "Viewer", ttl=3600, secret="unit-test-secret")
    conn = db.get_conn()
    conn.execute("UPDATE users SET role = 'Admin' WHERE id = ?", (uid,))
    conn.commit()
    conn.close()
    user = deps.current_user(credentials=_creds(token))
    assert user.role == "Admin"


def test_expired_token_is_auth_failed(temp_db):
    uid = _make_user()
    token = create_session_token(
        uid, "Admin", ttl=10, now=int(time.time()) - 1000, secret="unit-test-secret"
    )
    with pytest.raises(HTTPException) as exc:
        deps.current_user(credentials=_creds(token))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == ErrorCode.AUTH_FAILED.value


def test_invalid_signature_is_auth_failed(temp_db):
    uid = _make_user()
    token = create_session_token(uid, "Admin", ttl=3600, secret="a-different-secret")
    with pytest.raises(HTTPException) as exc:
        deps.current_user(credentials=_creds(token))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == ErrorCode.AUTH_FAILED.value


def test_revoked_token_is_auth_failed(temp_db):
    uid = _make_user()
    token = create_session_token(uid, "Admin", ttl=3600, secret="unit-test-secret")
    user = deps.current_user(credentials=_creds(token))
    db.add_revoked_token(user.jti, user.token_exp)
    with pytest.raises(HTTPException) as exc:
        deps.current_user(credentials=_creds(token))
    assert exc.value.detail["code"] == ErrorCode.AUTH_FAILED.value


def test_disabled_account_is_auth_failed(temp_db):
    uid = _make_user(disabled=True)
    token = create_session_token(uid, "Admin", ttl=3600, secret="unit-test-secret")
    with pytest.raises(HTTPException) as exc:
        deps.current_user(credentials=_creds(token))
    assert exc.value.detail["code"] == ErrorCode.AUTH_FAILED.value


# ---------------------------------------------------------------------------
# require_permission (Requirements 2.2, 2.3, 2.4)
# ---------------------------------------------------------------------------
def test_require_permission_permits_when_role_holds_it(temp_db):
    uid = _make_user(role="Operator")
    token = create_session_token(uid, "Operator", ttl=3600, secret="unit-test-secret")
    user = deps.current_user(credentials=_creds(token))
    dep = deps.require_permission("manage_cameras")
    assert dep(user=user) is user


def test_require_permission_denies_when_role_lacks_it(temp_db):
    uid = _make_user(role="Viewer")
    token = create_session_token(uid, "Viewer", ttl=3600, secret="unit-test-secret")
    user = deps.current_user(credentials=_creds(token))
    dep = deps.require_permission("manage_users")
    with pytest.raises(HTTPException) as exc:
        dep(user=user)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == ErrorCode.FORBIDDEN.value


# ---------------------------------------------------------------------------
# require_license (Requirements 3.3, 3.4, 3.6)
# ---------------------------------------------------------------------------
def _admin_user(temp_db) -> deps.AuthenticatedUser:
    uid = _make_user(role="Admin")
    token = create_session_token(uid, "Admin", ttl=3600, secret="unit-test-secret")
    return deps.current_user(credentials=_creds(token))


def test_require_license_required_when_none_active(temp_db):
    user = _admin_user(temp_db)
    dep = deps.require_license()
    with pytest.raises(HTTPException) as exc:
        dep(user=user)
    assert exc.value.status_code == 402
    assert exc.value.detail["code"] == ErrorCode.LICENSE_REQUIRED.value


def test_require_license_expired(temp_db):
    user = _admin_user(temp_db)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _activate_license(expiry=yesterday, camera_limit=4)
    dep = deps.require_license()
    with pytest.raises(HTTPException) as exc:
        dep(user=user)
    assert exc.value.status_code == 402
    assert exc.value.detail["code"] == ErrorCode.LICENSE_EXPIRED.value


def test_require_license_valid_passes(temp_db):
    user = _admin_user(temp_db)
    future = (date.today() + timedelta(days=30)).isoformat()
    _activate_license(expiry=future, camera_limit=4)
    dep = deps.require_license()
    assert dep(user=user) is user


def test_require_license_limit_on_camera_start(temp_db):
    user = _admin_user(temp_db)
    future = (date.today() + timedelta(days=30)).isoformat()
    _activate_license(expiry=future, camera_limit=2)
    dep = deps.require_license(
        check_camera_limit=True, running_count_provider=lambda: 2
    )
    with pytest.raises(HTTPException) as exc:
        dep(user=user)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == ErrorCode.LICENSE_LIMIT.value


def test_require_license_under_limit_passes(temp_db):
    user = _admin_user(temp_db)
    future = (date.today() + timedelta(days=30)).isoformat()
    _activate_license(expiry=future, camera_limit=4)
    dep = deps.require_license(
        check_camera_limit=True, running_count_provider=lambda: 1
    )
    assert dep(user=user) is user
