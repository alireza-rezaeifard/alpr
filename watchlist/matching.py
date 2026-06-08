"""
watchlist/matching.py
Pure normalization + watchlist matching logic, plus alert persistence.

`normalize_for_match` and `find_matches` are PURE (no DB access) so the same
canonicalization is applied to detection plates and watchlist entry plates
(Requirement 12.7). `create_alert` performs the only database write
(Requirement 12.4).

Requirements: 12.4, 12.5, 12.7
"""
from __future__ import annotations

from typing import Any, Iterable

import db
# Reuse the existing digit-normalization / separator-stripping helpers so that
# detection plates and watchlist entries canonicalize identically to the rest
# of the plate pipeline (plate_validator / plate_metadata).
from plate_validator import _normalize_digits, _strip_separators


def normalize_for_match(value: Any) -> str:
    """Canonicalize a plate value for matching (Requirement 12.7).

    Converts Persian/Arabic digits to canonical ASCII digits and strips
    separators (spaces, dashes, underscores) so that values written in any
    digit script and any spacing format compare equal. Returns an empty string
    for null/blank input. Pure function — no side effects.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = _normalize_digits(text)
    text = _strip_separators(text)
    return text


def _entry_norm(entry: Any) -> str:
    """Return the canonical normalized plate form for a watchlist entry.

    Accepts a dict carrying ``plate_norm`` (already normalized), ``plate_raw``,
    or ``plate_value``. The value is re-normalized defensively so the match is
    correct even if a stored ``plate_norm`` was produced differently.
    """
    if isinstance(entry, dict):
        source = (
            entry.get("plate_norm")
            or entry.get("plate_raw")
            or entry.get("plate_value")
        )
    else:
        source = entry
    return normalize_for_match(source)


def find_matches(plate_value: Any, active_entries: Iterable[Any]) -> list:
    """Return the active entries whose normalized plate matches ``plate_value``.

    Pure matcher (Requirements 12.5, 12.7): both the detection plate value and
    each entry's plate are reduced to the canonical digit form before
    comparison. ``active_entries`` must already exclude deleted entries, since
    deleted entries are treated as inactive and never produce a match
    (Requirement 12.5). A blank/null ``plate_value`` matches nothing.
    """
    target = normalize_for_match(plate_value)
    if not target:
        return []
    return [entry for entry in active_entries if _entry_norm(entry) == target]


def _resolve_id(obj: Any) -> int:
    """Extract an integer id from an int or a dict carrying an ``id`` field."""
    if isinstance(obj, dict):
        return int(obj["id"])
    return int(obj)


def _resolve_plate_value(detection: Any) -> str:
    """Pick the plate value to record on the alert from a detection dict/value."""
    if isinstance(detection, dict):
        for key in ("plate_value", "plate_dtrb", "plate_persian"):
            val = detection.get(key)
            if val:
                return str(val)
        return ""
    return str(detection)


def create_alert(detection: Any, entry: Any) -> dict:
    """Persist an Alert referencing a detection and a matched entry (Req 12.4).

    ``detection`` and ``entry`` may be integer ids or dicts carrying an ``id``.
    The recorded ``plate_value`` is taken from the detection. This is the only
    function in this module that touches the database.
    """
    detection_id = _resolve_id(detection)
    entry_id = _resolve_id(entry)
    plate_value = _resolve_plate_value(detection)
    return db.create_alert(detection_id, entry_id, plate_value)
