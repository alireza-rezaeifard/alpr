"""
Property-based tests for auth/rbac.py — role -> permission resolution.

Feature: anpr-system-redesign, Property 5

Property 5: Authorization permits an action exactly when the role holds the
permission.
    For any role drawn from {Admin, Operator, Viewer} and any permission:
      * role_has_permission(role, permission) is True iff the permission is in
        that role's permission set
      * Admin holds every permission
      * Viewer subset of Operator subset of Admin

Validates: Requirements 2.2, 2.3, 2.5, 2.6, 2.7
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from auth.rbac import (
    PERMISSIONS,
    ROLE_PERMISSIONS,
    ROLES,
    role_has_permission,
)

# Sample roles and permissions from the canonical literal tuples so the
# generators stay in lock-step with the type definitions.
_roles = st.sampled_from(ROLES)
_permissions = st.sampled_from(PERMISSIONS)


# Feature: anpr-system-redesign, Property 5
@settings(max_examples=100)
@given(role=_roles, permission=_permissions)
def test_authorization_permits_iff_role_holds_permission(
    role: str, permission: str
) -> None:
    # The guard permits the action if and only if the role holds the
    # permission per the static matrix (Requirements 2.2, 2.3).
    assert role_has_permission(role, permission) == (
        permission in ROLE_PERMISSIONS[role]
    )


# Feature: anpr-system-redesign, Property 5
@settings(max_examples=100)
@given(permission=_permissions)
def test_admin_holds_every_permission(permission: str) -> None:
    # Admin holds every permission (Requirement 2.5).
    assert role_has_permission("Admin", permission) is True


# Feature: anpr-system-redesign, Property 5
@settings(max_examples=100)
@given(permission=_permissions)
def test_viewer_subset_operator_subset_admin(permission: str) -> None:
    # Viewer subset of Operator subset of Admin (Requirements 2.6, 2.7):
    # any permission held by a lower role is also held by the higher roles.
    if role_has_permission("Viewer", permission):
        assert role_has_permission("Operator", permission) is True
    if role_has_permission("Operator", permission):
        assert role_has_permission("Admin", permission) is True
