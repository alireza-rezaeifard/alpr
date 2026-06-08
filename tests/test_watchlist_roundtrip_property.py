"""
Property-based test for watchlist entry persistence round-trip (task 13.4).

Feature: anpr-system-redesign, Property 19

Property 19: Watchlist entry create/remove is a persistence round-trip.
    For any watchlist and any set of entries added to it, every added entry is
    retrievable afterwards with the exact values that were stored — the raw
    plate value (Req 12.2), the optional label, and the optional reason. After
    an entry is removed (Req 12.3), it no longer appears among the watchlist's
    active (non-deleted) entries, while every entry that was not removed is
    still present with its exact stored values.

Validates: Requirements 12.1, 12.2, 12.3

Mechanism under test (real persistence, no mocks):
    * ``watchlist.service.create_watchlist`` -> ``db.create_watchlist`` (Req 12.1)
    * ``watchlist.service.add_entry``        -> ``db.add_watchlist_entry`` (Req 12.2)
    * ``watchlist.service.remove_entry``     -> ``db.remove_watchlist_entry`` (Req 12.3)
    * ``watchlist.service.list_watchlists``  -> ``db.list_watchlists`` (retrieval)

The service layer preserves the supplied ``plate_value`` verbatim as the raw
value (a separate canonical ``plate_norm`` is stored only for matching), so the
round-trip must surface the original ``plate_value``, ``label`` and ``reason``
unchanged. Exercised against a temporary SQLite database initialized with the
real schema.
"""
from __future__ import annotations

import os
import sys

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Ensure the project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from watchlist import service


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Point db at a fresh temp SQLite file initialized with the real schema."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "watchlist_roundtrip_test.db"))
    db.init_db()
    yield db


# Text without NUL characters (SQLite truncates text at an embedded NUL byte,
# which is an unrelated storage quirk rather than a property of the round-trip).
_safe_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    min_size=0,
    max_size=20,
)

# An entry spec: a raw plate value plus an optional label and optional reason.
_entry_spec = st.tuples(
    _safe_text,                 # plate_value (raw, stored verbatim)
    st.one_of(st.none(), _safe_text),  # label
    st.one_of(st.none(), _safe_text),  # reason
)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    name=_safe_text,
    list_type=st.sampled_from(["blacklist", "whitelist", "vip", "watch"]),
    entry_specs=st.lists(_entry_spec, min_size=1, max_size=15),
    removal_seed=st.lists(st.booleans(), min_size=0, max_size=15),
)
def test_watchlist_entry_persistence_round_trip(
    fresh_db, name, list_type, entry_specs, removal_seed
):
    """Created/added entries round-trip; removed entries disappear (Req 12.1-12.3)."""
    # Req 12.1: create a watchlist.
    watchlist = service.create_watchlist(name, list_type)
    watchlist_id = watchlist["id"]

    # Req 12.2: add each entry, recording the entry id alongside its inputs so
    # we can assert exact value preservation on retrieval.
    expected = {}  # entry_id -> (plate_value, label, reason)
    for plate_value, label, reason in entry_specs:
        entry = service.add_entry(watchlist_id, plate_value, label=label, reason=reason)
        # The create call itself must echo back the exact stored values.
        assert entry["plate_value"] == plate_value
        assert entry["label"] == label
        assert entry["reason"] == reason
        expected[entry["id"]] = (plate_value, label, reason)

    def _entries_for_watchlist():
        for wl in service.list_watchlists():
            if wl["id"] == watchlist_id:
                return {e["id"]: e for e in wl["entries"]}
        return {}

    # Round-trip after adds: every added entry is retrievable with exact values.
    retrieved = _entries_for_watchlist()
    assert set(retrieved) == set(expected)
    for entry_id, (plate_value, label, reason) in expected.items():
        got = retrieved[entry_id]
        assert got["plate_value"] == plate_value
        assert got["label"] == label
        assert got["reason"] == reason
        assert got["watchlist_id"] == watchlist_id

    # Req 12.3: remove a subset of entries (pair each entry with a boolean flag).
    entry_ids = list(expected)
    removed_ids = set()
    for entry_id, remove in zip(entry_ids, removal_seed):
        if remove:
            assert service.remove_entry(entry_id) is True
            removed_ids.add(entry_id)

    remaining = {eid for eid in expected if eid not in removed_ids}

    # Round-trip after removals: removed entries are gone; the rest are intact.
    retrieved_after = _entries_for_watchlist()
    assert set(retrieved_after) == remaining
    for entry_id in removed_ids:
        assert entry_id not in retrieved_after
    for entry_id in remaining:
        plate_value, label, reason = expected[entry_id]
        got = retrieved_after[entry_id]
        assert got["plate_value"] == plate_value
        assert got["label"] == label
        assert got["reason"] == reason
