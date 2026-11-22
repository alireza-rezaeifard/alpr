"""Repository-wide production-database guard for pytest collection.

This module is test infrastructure, not production code. It is installed from
the root ``conftest.py`` before test modules are collected, so it covers
``tests/``, root-level tests, ``auth/``, and ``licensing/`` when those paths are
explicitly collected.

The guard wraps ``db.get_conn``, ``sqlite3.connect``, and
``sqlite3.dbapi2.connect``. It normalizes SQLite ``file:`` URIs, URL-encoded
paths, Windows drive paths, relative paths, ``..`` segments, and case variants
without opening the database.

Known boundary limit: a function captured with ``from sqlite3 import connect``
before guard installation cannot be retroactively replaced. No repository test
currently uses that pattern; a static test checks for it.
"""
from __future__ import annotations

import os
import re
import sqlite3
from urllib.parse import unquote, urlparse

# Importing db must fail loudly here: silently disabling the guard would make
# the safety boundary unverifiable.
import db as _db


def _normalize_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


_PRODUCTION_DB = _normalize_path(_db.DB_PATH)
_ORIGINAL_GET_CONN = _db.get_conn
_ORIGINAL_SQLITE_CONNECT = sqlite3.connect
_ORIGINAL_DBAPI_CONNECT = sqlite3.dbapi2.connect

GUARD_FUNCTION_NAME = "_m0a_guarded_get_conn"


def _path_text(database) -> str | None:
    if database is None:
        return None
    if isinstance(database, bytes):
        database = database.decode("utf-8", "surrogateescape")
    if isinstance(database, os.PathLike):
        database = os.fspath(database)
    if not isinstance(database, str):
        return None
    if database == ":memory:" or database.startswith("file::memory:"):
        return None
    if database.startswith("file:"):
        parsed = urlparse(database)
        path = unquote(parsed.path)
        netloc = unquote(parsed.netloc)
        if netloc and netloc.lower() != "localhost":
            if re.fullmatch(r"[A-Za-z]:", netloc):
                path = netloc + path
            else:
                path = f"//{netloc}{path}"
        # file:///D:/... parses as /D:/...
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        database = path
    return database


def is_production_db_path(database) -> bool:
    """True when *database* resolves to the repository's production DB."""
    path = _path_text(database)
    if not path:
        return False
    try:
        return _normalize_path(path) == _PRODUCTION_DB
    except (OSError, ValueError):
        return False


def _refuse(database) -> None:
    raise RuntimeError(
        "Refusing to open the production database in tests: "
        f"{database!r}. Patch db.DB_PATH or pass a temporary path first."
    )


def _m0a_guarded_get_conn(*args, **kwargs):
    if is_production_db_path(_db.DB_PATH):
        _refuse(_db.DB_PATH)
    if _ORIGINAL_GET_CONN is None:  # pragma: no cover - defensive
        raise RuntimeError("db.get_conn is unavailable")
    return _ORIGINAL_GET_CONN(*args, **kwargs)


def _m0a_guarded_connect(database, *args, **kwargs):
    if is_production_db_path(database):
        _refuse(database)
    return _ORIGINAL_SQLITE_CONNECT(database, *args, **kwargs)


def install_guard(config) -> None:
    """Install all SQLite connection guards once, before test collection."""
    if getattr(config, "_m0a_guard_installed", False):
        return
    _db.get_conn = _m0a_guarded_get_conn
    sqlite3.connect = _m0a_guarded_connect
    sqlite3.dbapi2.connect = _m0a_guarded_connect
    config._m0a_original_get_conn = _ORIGINAL_GET_CONN
    config._m0a_original_sqlite_connect = _ORIGINAL_SQLITE_CONNECT
    config._m0a_original_dbapi_connect = _ORIGINAL_DBAPI_CONNECT
    config._m0a_guard_installed = True


def restore_guard(config) -> None:
    if not getattr(config, "_m0a_guard_installed", False):
        return
    _db.get_conn = config._m0a_original_get_conn
    sqlite3.connect = config._m0a_original_sqlite_connect
    sqlite3.dbapi2.connect = config._m0a_original_dbapi_connect
    config._m0a_guard_installed = False
