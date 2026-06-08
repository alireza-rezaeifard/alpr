"""
watchlist/service.py
Watchlist CRUD and alert retrieval, backed by the database helpers in ``db.py``.

This service is the thin domain layer between the watchlist routers and the
persistence helpers. It is responsible for:

* creating a watchlist (name, list type) — Requirement 12.1;
* adding an entry (raw plate value plus optional label/reason), storing both the
  raw value and a canonical normalized form for matching — Requirements 12.2,
  12.7;
* removing an entry by deletion — Requirement 12.3;
* listing watchlists together with their entries — Requirements 12.1, 12.2;
* listing alerts most-recent-first — Requirement 12.6.

Normalization note: the canonical ``plate_norm`` stored alongside each entry is
produced by :func:`watchlist.matching.normalize_for_match` when that module is
available. To avoid a hard import-ordering dependency on the parallel matching
work, a small local normalizer (reusing the repository's Persian/Arabic
digit-normalization convention) is used as a fallback. Both implementations
perform the same canonicalization — digit normalization plus separator
stripping — so entries remain matchable regardless of which path is taken.

Requirements: 12.1, 12.2, 12.3, 12.6, 12.7
"""
from __future__ import annotations

import re

import db

# Persian/Arabic → ASCII digit maps mirror plate_validator/plate_metadata so the
# fallback normalization is identical to the rest of the codebase.
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_STRIP_RE = re.compile(r"[\s\-_]")


def _fallback_normalize(value: str) -> str:
    """Canonicalize a plate value: ASCII digits + separators stripped.

    Mirrors the digit-normalization + separator-stripping convention used by
    ``plate_validator`` and ``watchlist.matching`` so that an entry stored via
    this fallback still matches detections normalized by the matcher.
    """
    text = (value or "").translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)
    return _STRIP_RE.sub("", text)


def _normalize(value: str) -> str:
    """Return the canonical match form, preferring ``watchlist.matching``.

    Importing lazily and defensively avoids a hard ordering dependency on the
    matching module (built in a parallel task); the local fallback guarantees
    this service works standalone.
    """
    try:
        from watchlist.matching import normalize_for_match

        return normalize_for_match(value)
    except Exception:
        return _fallback_normalize(value)


# ---------------------------------------------------------------------------
# Watchlist CRUD (Requirements 12.1, 12.2, 12.3)
# ---------------------------------------------------------------------------
def create_watchlist(name: str, list_type: str) -> dict:
    """Create a watchlist with the given name and list type (Req 12.1)."""
    return db.create_watchlist(name, list_type)


def list_watchlists() -> list[dict]:
    """Return all watchlists, each with their entries (Req 12.1, 12.2)."""
    return db.list_watchlists()


def get_watchlist(watchlist_id: int) -> dict | None:
    """Return a single watchlist header (no entries), or None when absent."""
    return db.get_watchlist(watchlist_id)


def add_entry(
    watchlist_id: int,
    plate_value: str,
    label: str | None = None,
    reason: str | None = None,
) -> dict:
    """Add an entry to a watchlist, storing raw + normalized plate (Req 12.2, 12.7).

    The supplied ``plate_value`` is preserved verbatim as the raw value while a
    canonical normalized form is stored for matching.
    """
    plate_norm = _normalize(plate_value)
    return db.add_watchlist_entry(
        watchlist_id,
        plate_raw=plate_value,
        plate_norm=plate_norm,
        label=label,
        reason=reason,
    )


def remove_entry(entry_id: int) -> bool:
    """Remove (delete) a watchlist entry. Returns True when removed (Req 12.3)."""
    return db.remove_watchlist_entry(entry_id)


# ---------------------------------------------------------------------------
# Alerts (Requirement 12.6)
# ---------------------------------------------------------------------------
def list_alerts(limit: int | None = None) -> list[dict]:
    """Return alerts ordered most-recent-first (Req 12.6)."""
    return db.list_alerts(limit=limit)
