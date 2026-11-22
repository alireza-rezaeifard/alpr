"""Phase 1 guard-trip checks for the M0-A test isolation foundation.

These are safety self-checks, not feature tests. They prove that:
- the production-path detector works,
- the repository-wide connection guard refuses the
  production database before opening it,
- temporary databases still work normally.
"""
from __future__ import annotations

import os
import sqlite3

import pytest

import db
from tests.conftest import GUARD_FUNCTION_NAME, is_production_db_path


def _production_path() -> str:
    return os.path.join(os.path.dirname(db.__file__), "database", "plpr.db")


def test_guard_is_installed_before_collection():
    assert getattr(db.get_conn, "__name__", "") == GUARD_FUNCTION_NAME
    assert getattr(sqlite3.connect, "__name__", "") == "_m0a_guarded_connect"
    assert getattr(sqlite3.dbapi2.connect, "__name__", "") == "_m0a_guarded_connect"


def test_production_path_is_recognized(tmp_path):
    assert is_production_db_path(_production_path())
    assert is_production_db_path(os.path.join("database", "plpr.db"))
    assert is_production_db_path(str(tmp_path / "other.db")) is False
    assert is_production_db_path(None) is False


def test_production_connection_is_refused(monkeypatch):
    # Guard identity is asserted first so a broken guard cannot reach SQLite.
    assert getattr(db.get_conn, "__name__", "") == GUARD_FUNCTION_NAME
    monkeypatch.setattr(db, "DB_PATH", _production_path())
    with pytest.raises(RuntimeError, match="Refusing to open the production"):
        db.get_conn()


def test_temporary_database_remains_usable(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "guard_ok.db"))
    db.init_db()
    conn = db.get_conn()
    try:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        conn.close()


def test_direct_sqlite_production_connection_is_refused():
    with pytest.raises(RuntimeError, match="Refusing to open the production"):
        sqlite3.connect(_production_path())


def test_direct_sqlite_temporary_connection_works(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "direct.db"))
    try:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        conn.close()
