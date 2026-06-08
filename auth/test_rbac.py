"""
Unit tests for auth/rbac.py — role -> permission mapping and resolver.

Requirements: 2.1, 2.5, 2.6, 2.7
"""
from __future__ import annotations

from auth.rbac import (
    PERMISSIONS,
    ROLE_PERMISSIONS,
    ROLES,
    role_has_permission,
)


def test_three_roles_supported():
    # Requirement 2.1
    assert set(ROLES) == {"Admin", "Operator", "Viewer"}
    assert set(ROLE_PERMISSIONS) == {"Admin", "Operator", "Viewer"}


def test_viewer_permissions():
    # Requirement 2.7: Viewer may only view.
    assert ROLE_PERMISSIONS["Viewer"] == frozenset({"view"})


def test_operator_inherits_viewer_and_adds_management():
    # Requirement 2.6
    viewer = ROLE_PERMISSIONS["Viewer"]
    operator = ROLE_PERMISSIONS["Operator"]
    assert viewer <= operator
    assert operator == viewer | {
        "manage_cameras",
        "run_detection",
        "manage_watchlists",
    }


def test_admin_inherits_operator_and_holds_all_permissions():
    # Requirement 2.5: Admin holds every permission.
    operator = ROLE_PERMISSIONS["Operator"]
    admin = ROLE_PERMISSIONS["Admin"]
    assert operator <= admin
    assert admin == set(PERMISSIONS)


def test_hierarchy_is_strict_subset_chain():
    # Viewer subset of Operator subset of Admin (Requirements 2.5-2.7)
    viewer = ROLE_PERMISSIONS["Viewer"]
    operator = ROLE_PERMISSIONS["Operator"]
    admin = ROLE_PERMISSIONS["Admin"]
    assert viewer < operator < admin


def test_role_has_permission_matches_matrix():
    for role, perms in ROLE_PERMISSIONS.items():
        for permission in PERMISSIONS:
            assert role_has_permission(role, permission) == (permission in perms)


def test_role_has_permission_examples():
    assert role_has_permission("Viewer", "view") is True
    assert role_has_permission("Viewer", "manage_cameras") is False
    assert role_has_permission("Operator", "run_detection") is True
    assert role_has_permission("Operator", "manage_users") is False
    assert role_has_permission("Admin", "manage_users") is True
    assert role_has_permission("Admin", "view_audit") is True


def test_unknown_role_holds_no_permissions():
    assert role_has_permission("Ghost", "view") is False  # type: ignore[arg-type]
