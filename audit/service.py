"""
audit/service.py
Append-only audit log writer and reader.

This module provides two functions that record and retrieve security-relevant
actions (Requirements 15.1–15.5):

* ``write_audit(user, action, resource, outcome)`` — append an audit entry with
  the username, action, resource, outcome, and timestamp. Called at login/logout
  (Req 15.1) and on create/update/delete of cameras, users, watchlists, and
  licenses (Req 15.2).

* ``list_audit(limit)`` — return audit entries ordered from most recent to least
  recent. When ``limit > 0``, return that many entries; when ``limit == 0``,
  return all entries (Requirements 15.3, 15.4).

The storage layer (``db.py``) exposes no update or delete operation for audit
rows, so entries are truly append-only (Requirement 15.5).

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import db


def write_audit(
    user: str | None,
    action: str,
    resource: str | None,
    outcome: str,
) -> dict:
    """Append an audit log entry and return the persisted row.

    Records the username (None for unauthenticated actions like failed login),
    the action (e.g., "login", "logout", "create_camera"), the affected resource
    (e.g., "camera:5", "user:admin"), the outcome ("success" or "failure"), and
    the current timestamp (Requirement 15.2).

    Called at:
        * Login/logout (Req 15.1)
        * Create/update/delete of cameras, users, watchlists, licenses (Req 15.2)

    Args:
        user: The username performing the action, or None for unauthenticated
            actions (e.g., failed login attempts).
        action: A short identifier for the action, e.g., "login", "logout",
            "create_camera", "update_user", "delete_watchlist".
        resource: An identifier for the affected resource, e.g., "camera:5",
            "user:admin", "watchlist:3", "license", or None when no specific
            resource is involved.
        outcome: "success" or "failure" indicating whether the action succeeded.

    Returns:
        The persisted audit entry as a dict with keys: id, username, action,
        resource, outcome, timestamp.

    Example:
        write_audit("admin", "create_camera", "camera:12", "success")
        write_audit(None, "login", None, "failure")
    """
    conn = db.get_conn()
    now = datetime.now().isoformat()
    try:
        cur = conn.execute(
            "INSERT INTO audit_log (username, action, resource, outcome, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (user, action, resource, outcome, now),
        )
        audit_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    return {
        "id": int(audit_id),
        "username": user,
        "action": action,
        "resource": resource,
        "outcome": outcome,
        "timestamp": now,
    }


def list_audit(limit: int) -> list[dict]:
    """Return audit log entries ordered from most recent to least recent.

    When ``limit > 0``, return at most that many entries (Requirement 15.3).
    When ``limit == 0``, return all entries (Requirement 15.4).

    Entries are ordered by timestamp descending, then by id descending so that
    ties (same timestamp) still resolve to insertion order, newest first.

    Args:
        limit: The maximum number of entries to return. When 0, return all
            entries. When positive, return at most that many.

    Returns:
        A list of audit entry dicts, each with keys: id, username, action,
        resource, outcome, timestamp.

    Example:
        list_audit(100)  # most recent 100 entries
        list_audit(0)    # all entries
    """
    conn = db.get_conn()
    try:
        sql = (
            "SELECT id, username, action, resource, outcome, timestamp "
            "FROM audit_log ORDER BY timestamp DESC, id DESC"
        )
        if limit > 0:
            rows = conn.execute(sql + " LIMIT ?", (int(limit),)).fetchall()
        else:
            rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    return [dict(r) for r in rows]
