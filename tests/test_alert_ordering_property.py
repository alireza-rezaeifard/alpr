"""
Property-based test for alert ordering (task 13.6).

Feature: anpr-system-redesign, Property 21

Property 21: Alerts are returned most-recent-first.
    For any number of alerts inserted, ``db.list_alerts()`` returns them ordered
    from most recent to least recent. The query orders by ``created_at DESC,
    id DESC``, so ``id`` is the tiebreaker when timestamps collide (the
    sub-second resolution of ``datetime.now().isoformat()`` can produce ties for
    rapid sequential inserts). Because alerts are inserted sequentially, both
    ``created_at`` and ``id`` are non-decreasing in insertion order, so the
    returned list must be non-increasing in ``(created_at, id)`` — equivalently
    strictly descending ``id`` order.

Validates: Requirements 12.6

Mechanism under test:
    * ``db.create_alert`` inserts an alert row (assigning ``created_at`` + id).
    * ``db.list_alerts`` returns alerts ordered ``created_at DESC, id DESC``.

The helper is exercised directly against a temporary SQLite database so the
ordering is tested against real persistence (no mocks). Foreign keys are not
enforced by ``db.get_conn`` (SQLite leaves ``PRAGMA foreign_keys`` OFF by
default), so arbitrary ``detection_id`` / ``entry_id`` integers are accepted.
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


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Point db at a fresh temp SQLite file initialized with the real schema."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "alerts_ordering_test.db"))
    db.init_db()
    yield db


def _reset_alerts():
    """Clear the alerts table so each generated example starts clean."""
    conn = db.get_conn()
    conn.execute("DELETE FROM alerts")
    conn.commit()
    conn.close()


# Strategy for a list of alerts to insert. Each alert carries arbitrary
# detection/entry ids (FKs are not enforced) and a plate value string.
alert_specs = st.lists(
    st.tuples(
        st.integers(min_value=1, max_value=10_000),  # detection_id
        st.integers(min_value=1, max_value=10_000),  # entry_id
        st.text(min_size=0, max_size=16),            # plate_value
    ),
    min_size=1,
    max_size=30,
)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(specs=alert_specs)
def test_list_alerts_most_recent_first(fresh_db, specs):
    """Inserted alerts are returned ordered most-recent-first (Req 12.6)."""
    _reset_alerts()

    inserted = []
    for detection_id, entry_id, plate_value in specs:
        alert = db.create_alert(detection_id, entry_id, plate_value)
        inserted.append(alert)

    listed = db.list_alerts()

    # Every inserted alert is returned exactly once.
    assert len(listed) == len(inserted)
    assert {a["id"] for a in listed} == {a["id"] for a in inserted}

    # The returned list is sorted non-increasing by (created_at, id): each
    # element is >= the next one in that ordering.
    keys = [(a["created_at"], a["id"]) for a in listed]
    assert keys == sorted(keys, reverse=True)

    # Since inserts are sequential (ids monotonically increasing), most-recent
    # first means ids appear in strictly descending order.
    ids = [a["id"] for a in listed]
    assert ids == sorted(ids, reverse=True)
    assert len(set(ids)) == len(ids)
