"""
Property-based test for the role-change effect on authorization (task 7.2).

Feature: anpr-system-redesign, Property 6

Property 6: Role changes take effect on subsequent authorization checks.
    For any user and any new role, after the user's role is changed, the user's
    subsequent authorization checks are resolved against the new role's
    permission set.

Validates: Requirements 2.9

Mechanism under test:
    * ``auth.dependencies.current_user`` loads the user's role *fresh from the
      database* on every request (not the role embedded in the token).
    * ``auth.dependencies.require_permission`` resolves the permission against
      that freshly loaded role via ``auth.rbac.role_has_permission``.

So changing a user's role with ``db.update_user`` and then re-authenticating a
still-valid token must yield the *new* role and the *new* role's permissions.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Ensure the project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from auth.dependencies import AuthenticatedUser, current_user, require_permission
from auth.rbac import PERMISSIONS, ROLES, role_has_permission
from auth.security import create_session_token, get_secret, hash_password


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Point db at a fresh temp file and provide a stable signing secret."""
    os.environ["ANPR_SECRET_KEY"] = "test-secret-for-role-change"
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    yield db
    os.environ.pop("ANPR_SECRET_KEY", None)


def _authenticate(token: str) -> AuthenticatedUser:
    """Run the real ``current_user`` dependency with a Bearer token."""
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return current_user(credentials=credentials)


@settings(
    max_examples=100,
    deadline=None,  # bcrypt hashing + SQLite I/O per example can exceed the default deadline
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    initial_role=st.sampled_from(ROLES),
    new_role=st.sampled_from(ROLES),
    permission=st.sampled_from(PERMISSIONS),
)
def test_role_change_takes_effect_on_subsequent_auth(
    fresh_db, initial_role, new_role, permission
):
    """After a role change, a still-valid token authorizes against the new role."""
    # Unique username per example so repeated draws never collide in the DB.
    username = f"user_{uuid.uuid4().hex}"
    created = db.create_user(username, hash_password("pw"), initial_role)
    user_id = created["id"]

    # Issue a still-valid token. Its embedded role is the *initial* role; the
    # property is precisely that authorization ignores it in favor of the DB.
    token = create_session_token(
        user_id, initial_role, ttl=3600, now=int(time.time()), secret=get_secret()
    )

    # Sanity: before the change, authorization reflects the initial role.
    before = _authenticate(token)
    assert before.role == initial_role

    # Change the role.
    db.update_user(user_id, role=new_role)

    # The same, still-valid token must now resolve to the NEW role.
    after = _authenticate(token)
    assert after.role == new_role

    # And require_permission must permit/deny according to the NEW role.
    guard = require_permission(permission)
    expected = role_has_permission(new_role, permission)
    if expected:
        # Permitted: the dependency returns the authenticated user.
        result = guard(user=after)
        assert result.role == new_role
    else:
        # Denied: the dependency raises 403 forbidden.
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            guard(user=after)
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "forbidden"
