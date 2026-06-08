"""
auth/rbac.py
Role-Based Access Control (RBAC): role -> permission mapping and pure
permission resolution.

The permission matrix encodes the inheritance hierarchy Viewer subset of
Operator subset of Admin, with Admin holding every permission.

Requirements: 2.1, 2.5, 2.6, 2.7
"""
from __future__ import annotations

from typing import Literal, get_args

# The three supported roles (Requirement 2.1).
Role = Literal["Admin", "Operator", "Viewer"]

# The full set of permissions used to guard actions across the backend.
Permission = Literal[
    "view",
    "manage_cameras",
    "run_detection",
    "manage_watchlists",
    "manage_users",
    "manage_roles",
    "manage_licenses",
    "manage_config",
    "view_audit",
]

# Tuples of all valid role/permission literal values, derived from the types
# above so the two never drift apart.
ROLES: tuple[Role, ...] = get_args(Role)
PERMISSIONS: tuple[Permission, ...] = get_args(Permission)

# Permissions granted to the Viewer role: read-only access to detections,
# sessions, reports, and live camera streams (Requirement 2.7).
_VIEWER_PERMISSIONS: frozenset[Permission] = frozenset({"view"})

# Operator inherits all Viewer permissions plus camera, detection, and
# watchlist management (Requirement 2.6).
_OPERATOR_PERMISSIONS: frozenset[Permission] = _VIEWER_PERMISSIONS | frozenset(
    {"manage_cameras", "run_detection", "manage_watchlists"}
)

# Admin inherits all Operator (and therefore Viewer) permissions plus user,
# role, license, config, and audit management. Admin holds every permission
# (Requirement 2.5).
_ADMIN_PERMISSIONS: frozenset[Permission] = _OPERATOR_PERMISSIONS | frozenset(
    {"manage_users", "manage_roles", "manage_licenses", "manage_config", "view_audit"}
)

# The static role -> permission matrix consulted by the authorization guard.
# Viewer subset of Operator subset of Admin, and Admin == all permissions.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    "Viewer": _VIEWER_PERMISSIONS,
    "Operator": _OPERATOR_PERMISSIONS,
    "Admin": _ADMIN_PERMISSIONS,
}


def role_has_permission(role: Role, permission: Permission) -> bool:
    """Return True if and only if ``role`` holds ``permission``.

    Pure function: the result depends only on the static ``ROLE_PERMISSIONS``
    matrix. An unknown role holds no permissions.

    Requirements: 2.5, 2.6, 2.7
    """
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
