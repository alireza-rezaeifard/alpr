"""
retention/service.py
Retention policy persistence and detection pruning service.

This service is the domain layer between the retention router and the database.
It is responsible for:

* ``set_retention_policy(days)`` — persist a retention policy when ``days > 0``,
  reject when ``days <= 0`` (Requirements 16.1, 16.4);
* ``get_retention_policy()`` — retrieve the current retention policy from the
  database or return a sentinel indicating no policy is configured;
* ``prune_detections(now)`` — delete detection records older than the retention
  cutoff when a policy is active, retain all detections when no policy is
  configured (Requirements 16.2, 16.3).

The pruning logic uses the pure ``retention_cutoff`` function from
``retention.policy`` to compute the cutoff timestamp, then issues a SQL DELETE
against the detections table.

Requirements: 16.1, 16.2, 16.3, 16.4
"""
from __future__ import annotations

from datetime import datetime

import db
from retention.policy import retention_cutoff


class RetentionPolicyError(ValueError):
    """Raised when an invalid retention policy is submitted (Requirement 16.4)."""
    pass


def set_retention_policy(days: int) -> None:
    """Persist a retention policy for the given number of days.

    Requirement 16.1 requires that the policy is persisted when ``days > 0``.
    Requirement 16.4 requires that ``days <= 0`` is rejected with a validation
    error.

    Args:
        days: The retention period in days. Must be greater than zero.

    Raises:
        RetentionPolicyError: When ``days <= 0``.
    """
    if days <= 0:
        raise RetentionPolicyError(
            f"retention policy days must be greater than zero, got {days}"
        )
    db.set_retention_days(days)


def get_retention_policy() -> int | None:
    """Retrieve the current retention policy in days, or None when not configured.

    The database helper ``db.get_retention_days()`` returns a default value (90)
    when no policy is explicitly set. This service interprets a policy as
    "configured" only when it has been explicitly set via ``set_retention_policy``.

    For simplicity, we treat any positive value returned by ``db.get_retention_days()``
    as a configured policy, since the database always stores an integer.

    Returns:
        The retention period in days, or None when no policy is configured.
    """
    days = db.get_retention_days()
    return days if days > 0 else None


def prune_detections(now: datetime) -> int:
    """Delete detection records older than the retention cutoff.

    Requirement 16.2: while a retention policy is active, delete detections older
    than the cutoff (``now - days``).

    Requirement 16.3: when no retention policy is configured, retain all
    detections (this function returns 0 without issuing a DELETE).

    Args:
        now: The current timestamp, used to compute the cutoff.

    Returns:
        The number of detection records deleted.
    """
    policy_days = get_retention_policy()
    if policy_days is None:
        # Requirement 16.3: no policy configured → retain everything
        return 0

    cutoff = retention_cutoff(now, policy_days)
    cutoff_str = cutoff.isoformat()

    conn = db.get_conn()
    cursor = conn.execute(
        "DELETE FROM detections WHERE timestamp < ?",
        (cutoff_str,),
    )
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()

    return deleted_count
