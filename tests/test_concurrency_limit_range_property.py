"""
Property-based test for the concurrency-limit accepted range.

Feature: anpr-system-redesign, Property 13

Property 13: The concurrency limit is accepted exactly within 1..64.
    For any integer, setting the concurrency limit succeeds and persists if and
    only if the value lies in the inclusive range 1 to 64; out-of-range values
    are rejected with a validation error.

Validates: Requirements 5.6, 5.7

Two complementary layers are exercised:
  1. ``schemas.ConcurrencyConfig`` — a pydantic model whose ``value`` field is
     constrained with ``Field(ge=1, le=64)``. Construction must succeed iff
     ``1 <= value <= 64`` and otherwise raise ``pydantic.ValidationError``.
  2. ``camera_manager.CameraManager.set_concurrency_limit`` — must persist for
     values in 1..64 (reflected by ``get_limit()`` and by the database via
     ``db.get_concurrency_limit()``) and raise ``ValueError`` otherwise. A
     temporary SQLite database backs persistence; no processor is involved
     because only the limit is set/read.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

import db
from schemas import ConcurrencyConfig
from camera_manager import CameraManager


# Integers spanning well below and above the accepted 1..64 range.
limit_values = st.integers(min_value=-100, max_value=200)


@pytest.fixture()
def fresh_db(monkeypatch):
    """Point db at a fresh temp SQLite file initialized with the real schema."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "concurrency_limit_range_test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Layer 1: schema-level validation
# ---------------------------------------------------------------------------

@settings(max_examples=200)
@given(value=limit_values)
def test_concurrency_config_accepts_iff_in_range(value):
    """ConcurrencyConfig(value=n) succeeds iff 1 <= n <= 64."""
    if 1 <= value <= 64:
        cfg = ConcurrencyConfig(value=value)
        assert cfg.value == value
    else:
        with pytest.raises(ValidationError):
            ConcurrencyConfig(value=value)


# ---------------------------------------------------------------------------
# Layer 2: manager + persistence
# ---------------------------------------------------------------------------

@settings(max_examples=200, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(value=limit_values)
def test_set_concurrency_limit_persists_iff_in_range(value, fresh_db):
    """set_concurrency_limit persists for 1..64 and raises ValueError otherwise."""
    mgr = CameraManager(ensure_models_fn=lambda: (None, None, None))
    previous = mgr.get_limit()

    if 1 <= value <= 64:
        mgr.set_concurrency_limit(value)
        # In-memory state reflects the new limit.
        assert mgr.get_limit() == value
        # Persisted to the database.
        assert db.get_concurrency_limit() == value
    else:
        with pytest.raises(ValueError):
            mgr.set_concurrency_limit(value)
        # Rejected values leave both in-memory and persisted state unchanged.
        assert mgr.get_limit() == previous
        assert db.get_concurrency_limit() == previous
