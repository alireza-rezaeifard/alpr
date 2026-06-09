"""
tests/test_users_last_admin_property.py

Property 7: The last enabled Admin cannot be removed.

For any set of user accounts, a delete, a disable, or a role change away from
Admin that would reduce the number of *enabled* Admin accounts to zero is
rejected with a ``validation_error`` (HTTP 422), and the count of enabled
Admins never reaches zero through such operations.

The router functions in ``routers/users.py`` (``update_user`` / ``delete_user``)
are invoked directly. The ``require_permission("manage_users")`` dependency is
bypassed by passing an Admin ``AuthenticatedUser`` as the ``_user`` argument.

Feature: anpr-system-redesign, Property 7
Validates: Requirements 2.10
"""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import db
from auth.dependencies import AuthenticatedUser
from routers.users import UserUpdate, delete_user, update_user

# An Admin identity used to satisfy the require_permission(_user) parameter.
ADMIN = AuthenticatedUser(
    id=0, username="root", role="Admin", disabled=False, jti="j", token_exp=9_999_999_999
)

# A user spec is (role, disabled).
_user_spec = st.tuples(
    st.sampled_from(["Admin", "Operator", "Viewer"]), st.booleans()
)

# A spec that is guaranteed NOT to be an enabled Admin: either a non-Admin role
# (with any disabled flag) or a disabled Admin.
_non_enabled_admin = st.one_of(
    st.tuples(st.sampled_from(["Operator", "Viewer"]), st.booleans()),
    st.tuples(st.just("Admin"), st.just(True)),
)


@pytest.fixture()
def temp_db(monkeypatch):
    """Point db.* helpers at a throwaway SQLite database for the test."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "users_test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    try:
        yield
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _reset_users() -> None:
    """Empty the users table so each Hypothesis example starts clean.

    The function-scoped temp_db fixture is created once and shared across all
    generated examples, so state must be reset per example.
    """
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM users")
        conn.commit()
    finally:
        conn.close()


def _insert_users(specs) -> list[int]:
    """Insert users with the given (role, disabled) specs; return their ids."""
    ids = []
    for i, (role, disabled) in enumerate(specs):
        created = db.create_user(f"user{i}", "hash", role)
        if disabled:
            db.update_user(created["id"], disabled=True)
        ids.append(created["id"])
    return ids


def _apply(op: str, user_id: int) -> None:
    """Apply the named operation to the user via the router functions."""
    if op == "delete":
        delete_user(user_id, user=ADMIN)
    elif op == "disable":
        update_user(user_id, UserUpdate(disabled=True), user=ADMIN)
    elif op == "enable":
        update_user(user_id, UserUpdate(disabled=False), user=ADMIN)
    elif op == "to_operator":
        update_user(user_id, UserUpdate(role="Operator"), user=ADMIN)
    elif op == "to_viewer":
        update_user(user_id, UserUpdate(role="Viewer"), user=ADMIN)
    elif op == "to_admin":
        update_user(user_id, UserUpdate(role="Admin"), user=ADMIN)
    else:  # pragma: no cover - guard against typos
        raise AssertionError(f"unknown op {op}")


# ---------------------------------------------------------------------------
# Invariant: any single operation preserves "at least one enabled Admin" when
# the system started with at least one, and any rejection is a validation error.
# ---------------------------------------------------------------------------
# Feature: anpr-system-redesign, Property 7
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    specs=st.lists(_user_spec, min_size=1, max_size=8),
    op=st.sampled_from(
        ["delete", "disable", "enable", "to_operator", "to_viewer", "to_admin"]
    ),
    target=st.integers(min_value=0, max_value=7),
)
def test_operation_never_drops_enabled_admins_to_zero(temp_db, specs, op, target):
    _reset_users()
    ids = _insert_users(specs)
    target_id = ids[target % len(ids)]

    before = db.count_enabled_admins()

    raised: HTTPException | None = None
    try:
        _apply(op, target_id)
    except HTTPException as exc:
        raised = exc

    after = db.count_enabled_admins()

    # The enabled-Admin count never reaches zero when it started >= 1.
    if before >= 1:
        assert after >= 1

    # Any rejection is a validation error and leaves the count unchanged.
    if raised is not None:
        assert raised.status_code == 422
        assert raised.detail["code"] == "validation_error"
        assert after == before


# ---------------------------------------------------------------------------
# Focused property: when exactly one enabled Admin exists, every removing
# operation targeting it is rejected as a validation error.
# ---------------------------------------------------------------------------
# Feature: anpr-system-redesign, Property 7
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    others=st.lists(_non_enabled_admin, max_size=7),
    op=st.sampled_from(["delete", "disable", "to_operator", "to_viewer"]),
)
def test_last_enabled_admin_cannot_be_removed(temp_db, others, op):
    _reset_users()
    _insert_users(others)
    admin = db.create_user("the_admin", "hash", "Admin")  # enabled by default

    # Precondition: exactly one enabled Admin in the system.
    assert db.count_enabled_admins() == 1

    with pytest.raises(HTTPException) as exc_info:
        _apply(op, admin["id"])

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "validation_error"
    # The operation was rejected, so the enabled Admin still stands.
    assert db.count_enabled_admins() == 1
