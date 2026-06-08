"""
Property-based test for watchlist entry create/remove persistence (task 13.4).

Feature: anpr-system-redesign, Property 19

Property 19: Watchlist entry create/remove is a persistence round-trip.
    For any watchlist (name, list type) and any set of entries, creating the
    watchlist and adding entries makes them retrievable under that watchlist
    with the same field values plus an assigned integer identifier, and
    removing an entry makes it no longer retrievable.

Validates: Requirements 12.1, 12.2, 12.3

Mechanism under test:
    * ``db.create_watchlist`` / ``watchlist.service.create_watchlist`` insert a
      watchlist and return it with an assigned id.
    * ``watchlist.service.add_entry`` (delegating to ``db.add_watchlist_entry``)
      stores an entry's raw plate value plus optional label/reason; the raw
      value surfaces as ``plate_value`` in the public view.
    * ``db.get_watchlist_entry`` / ``db.list_watchlists`` read entries back.
    * ``watchlist.service.remove_entry`` (delegating to
      ``db.remove_watchlist_entry``) deletes an entry.

The helpers are exercised directly against a temporary SQLite database so the
round-trip is tested against real persistence (no mocks).
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
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "watchlist_test.db"))
    db.init_db()
    yield db


def _reset_watchlists():
    """Clear watchlist tables so each generated example starts clean."""
    conn = db.get_conn()
    conn.execute("DELETE FROM watchlist_entries")
    conn.execute("DELETE FROM watchlists")
    conn.commit()
    conn.close()


# Watchlist + entry field strategies.
names = st.text(max_size=120)
list_types = st.sampled_from(["blacklist", "whitelist", "vip", "custom"])
plate_values = st.text(max_size=40)
optional_text = st.one_of(st.none(), st.text(max_size=80))

# A set of entries: each is (plate_value, label, reason).
entries_strategy = st.lists(
    st.tuples(plate_values, optional_text, optional_text),
    min_size=1,
    max_size=8,
)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(name=names, list_type=list_types, entries=entries_strategy)
def test_watchlist_entry_create_remove_round_trip(fresh_db, name, list_type, entries):
    """Create + add entries round-trips; removing an entry deletes it."""
    _reset_watchlists()

    # --- Create watchlist (Req 12.1) ---
    watchlist = service.create_watchlist(name, list_type)
    assert isinstance(watchlist["id"], int)
    watchlist_id = watchlist["id"]
    assert watchlist["name"] == name
    assert watchlist["list_type"] == list_type

    # --- Add entries (Req 12.2) and verify each round-trips ---
    added_ids = []
    expected = {}  # entry_id -> (plate_value, label, reason)
    for plate_value, label, reason in entries:
        created = service.add_entry(watchlist_id, plate_value, label=label, reason=reason)

        # An integer identifier is assigned on create.
        assert isinstance(created["id"], int)
        entry_id = created["id"]
        assert created["watchlist_id"] == watchlist_id
        assert created["plate_value"] == plate_value
        assert created["label"] == label
        assert created["reason"] == reason

        # Reading the entry back returns the same fields + the id.
        read_back = db.get_watchlist_entry(entry_id)
        assert read_back is not None
        assert read_back["id"] == entry_id
        assert read_back["watchlist_id"] == watchlist_id
        assert read_back["plate_value"] == plate_value
        assert read_back["label"] == label
        assert read_back["reason"] == reason

        added_ids.append(entry_id)
        expected[entry_id] = (plate_value, label, reason)

    # All ids are unique (each entry persisted as a distinct row).
    assert len(set(added_ids)) == len(added_ids)

    # The entries are retrievable under their watchlist via list_watchlists.
    watchlists = db.list_watchlists()
    target = next((w for w in watchlists if w["id"] == watchlist_id), None)
    assert target is not None
    listed_ids = {e["id"] for e in target["entries"]}
    assert set(added_ids) == listed_ids
    for e in target["entries"]:
        plate_value, label, reason = expected[e["id"]]
        assert e["plate_value"] == plate_value
        assert e["label"] == label
        assert e["reason"] == reason

    # --- Remove each entry (Req 12.3) and verify it is no longer retrievable ---
    remaining = set(added_ids)
    for entry_id in added_ids:
        assert service.remove_entry(entry_id) is True
        remaining.discard(entry_id)

        # get_watchlist_entry returns None for the removed entry.
        assert db.get_watchlist_entry(entry_id) is None

        # The removed entry no longer appears under its watchlist; the
        # remaining entries are still present.
        watchlists_after = db.list_watchlists()
        target_after = next(
            (w for w in watchlists_after if w["id"] == watchlist_id), None
        )
        assert target_after is not None
        present_ids = {e["id"] for e in target_after["entries"]}
        assert entry_id not in present_ids
        assert present_ids == remaining
