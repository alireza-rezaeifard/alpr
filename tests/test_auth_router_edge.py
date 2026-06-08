"""Edge-case tests for the auth router and authentication dependency (task 6.3).

Covers the matrix not exercised by ``test_auth_router_sanity.py``:

* missing-token rejection by ``auth.dependencies.current_user`` — a request
  with no Bearer credentials is rejected ``401 auth_required`` (Requirement 1.6);
* the default-admin bootstrap — exactly one Admin is created when the users
  table is empty and the operation is idempotent (Requirement 1.9);
* login failure outcomes — wrong password, unknown user, and disabled account
  all surface the same indistinguishable ``auth_failed`` (Requirements 1.2, 1.8).

These run against an isolated temp SQLite database so they never touch the real
application database.
"""
import importlib
import os

import pytest
from fastapi import HTTPException


@pytest.fixture()
def edge_db(tmp_path, monkeypatch):
    """Point db at a fresh temp file and bind a deterministic server secret.

    Yields ``(db, auth, dependencies)`` with the auth modules reloaded so their
    module-level imports resolve against the patched database path.
    """
    os.environ["ANPR_SECRET_KEY"] = "test-secret-for-edge"
    import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "edge.db"))
    db.init_db()

    import auth.dependencies as dependencies
    import routers.auth as auth
    importlib.reload(dependencies)
    importlib.reload(auth)
    yield db, auth, dependencies
    os.environ.pop("ANPR_SECRET_KEY", None)


# ---------------------------------------------------------------------------
# Missing-token rejection (Requirement 1.6)
# ---------------------------------------------------------------------------
def test_current_user_missing_credentials_rejected_auth_required(edge_db):
    _, _, dependencies = edge_db
    with pytest.raises(HTTPException) as exc:
        dependencies.current_user(credentials=None)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "auth_required"


def test_current_user_empty_token_rejected_auth_required(edge_db):
    """A Bearer header with an empty token string is treated as missing (Req 1.6)."""
    _, _, dependencies = edge_db
    from fastapi.security import HTTPAuthorizationCredentials

    empty = HTTPAuthorizationCredentials(scheme="Bearer", credentials="")
    with pytest.raises(HTTPException) as exc:
        dependencies.current_user(credentials=empty)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "auth_required"


# ---------------------------------------------------------------------------
# Default-admin bootstrap (Requirement 1.9)
# ---------------------------------------------------------------------------
def test_bootstrap_creates_exactly_one_admin_when_empty(edge_db):
    db, auth, _ = edge_db
    assert db.count_users() == 0

    assert auth.bootstrap_default_admin() is True
    assert db.count_users() == 1
    assert db.count_enabled_admins() == 1

    admin = db.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME)
    assert admin is not None
    assert admin["role"] == "Admin"
    assert not bool(admin["disabled"])


def test_bootstrap_is_idempotent_on_second_call(edge_db):
    db, auth, _ = edge_db
    assert auth.bootstrap_default_admin() is True

    # A second call must not create another account.
    assert auth.bootstrap_default_admin() is False
    assert db.count_users() == 1
    assert db.count_enabled_admins() == 1


def test_bootstrap_skips_when_any_user_exists(edge_db):
    """Bootstrap is a no-op when the table already holds an unrelated user (Req 1.9)."""
    db, auth, _ = edge_db
    from auth.security import hash_password

    db.create_user("someone", hash_password("pw"), "Operator")
    assert db.count_users() == 1

    assert auth.bootstrap_default_admin() is False
    assert db.count_users() == 1
    # No default admin was injected.
    assert db.get_user_by_username(auth.DEFAULT_ADMIN_USERNAME) is None


# ---------------------------------------------------------------------------
# Login failure outcomes — all indistinguishable auth_failed (Req 1.2, 1.8)
# ---------------------------------------------------------------------------
def test_login_wrong_password_returns_auth_failed(edge_db):
    db, auth, _ = edge_db
    auth.bootstrap_default_admin()

    with pytest.raises(HTTPException) as exc:
        auth.login(auth.LoginRequest(username="admin", password="not-the-password"))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "auth_failed"


def test_login_unknown_user_returns_auth_failed(edge_db):
    db, auth, _ = edge_db
    auth.bootstrap_default_admin()

    with pytest.raises(HTTPException) as exc:
        auth.login(auth.LoginRequest(username="ghost", password="whatever"))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "auth_failed"


def test_login_disabled_account_returns_auth_failed(edge_db):
    db, auth, _ = edge_db
    from auth.security import hash_password

    created = db.create_user("blocked", hash_password("correct-pw"), "Operator")
    db.update_user(created["id"], disabled=True)

    with pytest.raises(HTTPException) as exc:
        # Correct password, but the account is disabled.
        auth.login(auth.LoginRequest(username="blocked", password="correct-pw"))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "auth_failed"


def test_login_failures_are_indistinguishable(edge_db):
    """Unknown user, wrong password, and disabled account yield identical envelopes."""
    db, auth, _ = edge_db
    from auth.security import hash_password

    auth.bootstrap_default_admin()
    created = db.create_user("off", hash_password("pw"), "Viewer")
    db.update_user(created["id"], disabled=True)

    details = []
    for username, password in [
        ("admin", "wrong"),     # wrong password
        ("nobody", "wrong"),    # unknown user
        ("off", "pw"),          # disabled account
    ]:
        with pytest.raises(HTTPException) as exc:
            auth.login(auth.LoginRequest(username=username, password=password))
        details.append((exc.value.status_code, exc.value.detail))

    # Every failure path produces the exact same status and envelope.
    assert all(d == details[0] for d in details)
    assert details[0][0] == 401
    assert details[0][1]["code"] == "auth_failed"
