"""M0-A test fixtures and legacy guard exports.

The production-database guard itself is installed repository-wide from the
root ``conftest.py`` via ``tests.isolation``. This module keeps the autouse
temporary-path fixture and re-exports the guard helpers used by the focused
isolation tests.
"""
from __future__ import annotations

import pytest

from tests.isolation import (  # re-exported for focused guard tests
    GUARD_FUNCTION_NAME,
    is_production_db_path,
    _db,
)


@pytest.fixture(autouse=True)
def _m0a_isolate_db_path(tmp_path, monkeypatch):
    """Every test starts with an isolated temporary DB path."""
    monkeypatch.setattr(_db, "DB_PATH", str(tmp_path / "default_test.db"))
    yield
