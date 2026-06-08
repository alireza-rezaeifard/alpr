"""
retention/policy.py
Pure retention policy functions: cutoff computation.

This module contains the pure logic for data retention policy enforcement. All
functions are deterministic (no database access, no side effects) so they can be
tested independently and composed safely.

``retention_cutoff(now, days)`` is the core pure function that computes the
timestamp before which detections should be pruned (Requirements 16.2, 16.3).

Requirements: 16.2, 16.3
"""
from __future__ import annotations

from datetime import datetime, timedelta


def retention_cutoff(now: datetime, days: int) -> datetime:
    """Compute the timestamp before which detections should be pruned.

    Pure function. Returns ``now - days`` (Requirement 16.2). When ``days`` is
    zero or negative, this function still produces a cutoff (in the future or at
    ``now``), but the service layer rejects such policies before this function
    is called (Requirement 16.4).

    Args:
        now: The current timestamp.
        days: The retention period in days.

    Returns:
        The cutoff timestamp: detections older than this are eligible for
        deletion when a retention policy is active.

    Examples:
        >>> from datetime import datetime
        >>> now = datetime(2024, 1, 15, 12, 0, 0)
        >>> retention_cutoff(now, 30)
        datetime.datetime(2023, 12, 16, 12, 0, 0)
        >>> retention_cutoff(now, 7)
        datetime.datetime(2024, 1, 8, 12, 0, 0)
    """
    return now - timedelta(days=days)
