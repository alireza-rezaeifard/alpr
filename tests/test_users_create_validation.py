"""Unit tests for create-user validation (task 7.4).

Covers the POST /api/users create path in ``routers/users.py``:
    * required username/password/role fields on the ``UserCreate`` body, and
    * role enumeration against ``auth.rbac.ROLES``.

The ``create_user`` endpoint is called directly with an explicit
``_user`` admin identity so the ``Depends(require_permission(...))`` guard is
bypassed — these tests focus on validation, not authorization.

Requirements: 2.1, 2.8
"""
import importlib
import os

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Point db at a fresh temp file and reload the users router against it."""
    os.environ["ANPR_SECRET_KEY"] = "test-secret-for-users-create"
    import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    import routers.users as users
    importlib.reload(users)
    yield db, users
    os.environ.pop("ANPR_SECRET_KEY", None)


def _admin(users):
    """Build an admin AuthenticatedUser to pass as the injected ``_user``."""
    return users.AuthenticatedUser(
        id=1,
        username="admin",
        role="Admin",
        disabled=False,
        jti="jti-admin",
        token_exp=9999999999,
    )


# ---------------------------------------------------------------------------
# Valid creation (Req 2.8)
# ---------------------------------------------------------------------------
def test_create_user_valid_returns_userview_with_role(fresh_db):
    db, users = fresh_db
    body = users.UserCreate(username="alice", password="s3cret", role="Operator")

    result = users.create_user(body=body, user=_admin(users))

    assert isinstance(result, users.UserView)
    assert result.username == "alice"
    assert result.role == "Operator"
    assert result.disabled is False
    assert result.id > 0
    assert result.created_at  # populated timestamp

    # Persisted and never stores the plaintext password.
    stored = db.get_user_by_username("alice")
    assert stored is not None
    assert stored["role"] == "Operator"
    assert stored["password_hash"] != "s3cret"


@pytest.mark.parametrize("role", ["Admin", "Operator", "Viewer"])
def test_create_user_accepts_each_supported_role(fresh_db, role):
    db, users = fresh_db
    body = users.UserCreate(username=f"user_{role}", password="pw", role=role)

    result = users.create_user(body=body, user=_admin(users))

    assert result.role == role


# ---------------------------------------------------------------------------
# Role enumeration (Req 2.1)
# ---------------------------------------------------------------------------
def test_create_user_rejects_unknown_role(fresh_db):
    db, users = fresh_db
    body = users.UserCreate(username="bob", password="pw", role="Superuser")

    with pytest.raises(HTTPException) as exc:
        users.create_user(body=body, user=_admin(users))

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "validation_error"
    # No user is created when the role is invalid.
    assert db.get_user_by_username("bob") is None


def test_create_user_rejects_empty_string_role(fresh_db):
    db, users = fresh_db
    body = users.UserCreate(username="carol", password="pw", role="")

    with pytest.raises(HTTPException) as exc:
        users.create_user(body=body, user=_admin(users))

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "validation_error"


# ---------------------------------------------------------------------------
# Required fields on the request body (Req 2.8)
# ---------------------------------------------------------------------------
def test_usercreate_requires_username():
    import routers.users as users
    with pytest.raises(ValidationError):
        users.UserCreate(password="pw", role="Viewer")


def test_usercreate_requires_password():
    import routers.users as users
    with pytest.raises(ValidationError):
        users.UserCreate(username="dave", role="Viewer")


def test_usercreate_requires_role():
    import routers.users as users
    with pytest.raises(ValidationError):
        users.UserCreate(username="erin", password="pw")


def test_usercreate_rejects_empty_username():
    import routers.users as users
    with pytest.raises(ValidationError):
        users.UserCreate(username="", password="pw", role="Viewer")


def test_usercreate_rejects_empty_password():
    import routers.users as users
    with pytest.raises(ValidationError):
        users.UserCreate(username="frank", password="", role="Viewer")
