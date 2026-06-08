"""
audit
Append-only audit logging support.

This package provides the audit writer and reader that record security-relevant
actions performed by authenticated users (Requirement 15). Audit entries are
written at the point where the action occurs — at login/logout (Req 15.1) and on
create/update/delete of cameras, users, watchlists, and licenses (Req 15.2).

The storage layer exposes no update or delete operation for audit rows, so they
are truly append-only (Requirement 15.5). Reads are ordered from most recent to
least recent (Requirement 15.3, 15.4).

Key functions:
    * ``write_audit(user, action, resource, outcome)`` — append an audit entry
    * ``list_audit(limit)`` — return entries, most-recent-first

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5
"""
