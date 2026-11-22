"""Remediation 5 regression tests (audit D-1, D-2).

All database work uses isolated temporary databases (autouse fixture in
``tests/conftest.py`` redirects ``db.DB_PATH``; the repository-wide guard
installed from the root ``conftest.py`` refuses the production database).
Production-path identity tests monkeypatch ``db._PRODUCTION_DB_PATH`` to a
temporary file — the real production database and its sidecars are never
opened, hashed, or aliased here.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

import db as db_module


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def production_path_db(tmp_path, monkeypatch):
    """Point DB_PATH at a temp file AND simulate the production default path."""
    path = str(tmp_path / "prod_sim.db")

    def _use(path_value=path):
        monkeypatch.setattr(db_module, "DB_PATH", path_value)
        monkeypatch.setattr(db_module, "_PRODUCTION_DB_PATH", path_value)

    return path, _use


@pytest.fixture()
def trace_all_connects(monkeypatch):
    """Record every SQL statement executed on ANY connection created through
    ``db.sqlite3.connect`` (covers the read-only and snapshot paths)."""
    statements: list[str] = []
    original = db_module.sqlite3.connect

    def traced(*args, **kwargs):
        conn = original(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(db_module.sqlite3, "connect", traced)
    return statements


_DDL_OR_DML = re.compile(
    r"\b(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|REPLACE|VACUUM|ATTACH)\b",
    re.IGNORECASE)


def _assert_no_ddl_or_dml(statements):
    for stmt in statements:
        assert not _DDL_OR_DML.search(stmt), f"schema mutation attempted: {stmt}"


def _file_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _raw_journal_mode(path):
    """Read the persisted journal mode through a plain writable connection
    (the test's own connection — not via db.get_conn)."""
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# D-1 — WAL-compatible, strictly read-only schema validation
# ---------------------------------------------------------------------------

def test_d1_validation_reads_clean_wal_db_readonly(
        production_path_db, trace_all_connects):
    path, use_production_path = production_path_db
    use_production_path()
    db_module.init_db(create=True)  # get_conn persists WAL mode; clean close
    assert _raw_journal_mode(path) == "wal"
    wal_path = path + "-wal"
    assert not os.path.exists(wal_path)  # clean close: no committed WAL left

    count = len(trace_all_connects)
    db_module.init_db()  # normal production startup (validate-only)

    _assert_no_ddl_or_dml(trace_all_connects[count:])
    assert trace_all_connects[count:], "validation must inspect the schema"


def test_d1_validation_does_not_mutate_db_wal_or_journal(
        production_path_db, trace_all_connects):
    path, use_production_path = production_path_db
    use_production_path()
    db_module.init_db(create=True)  # get_conn persists WAL; clean close
    before_db = _file_bytes(path)
    wal = path + "-wal"
    wal_before = _file_bytes(wal) if os.path.exists(wal) else None
    shm = path + "-shm"
    shm_before = _file_bytes(shm) if os.path.exists(shm) else None

    count = len(trace_all_connects)
    db_module.init_db()

    # Original database byte-identical; no committed WAL content introduced.
    assert _file_bytes(path) == before_db, "validation modified the database file"
    assert (_file_bytes(wal) if os.path.exists(wal) else None) == wal_before, \
        "validation modified the WAL"
    assert (_file_bytes(shm) if os.path.exists(shm) else None) == shm_before, \
        "validation modified the SHM"
    _assert_no_ddl_or_dml(trace_all_connects[count:])
    # Journal mode still WAL (read by this test's own connection).
    assert _raw_journal_mode(path) == "wal"


_UNCLEAN_WRITER = (
    "import sqlite3, sys, os\n"
    "conn = sqlite3.connect(sys.argv[1])\n"
    "conn.execute('PRAGMA journal_mode=WAL')\n"
    "conn.execute('ALTER TABLE detections ADD COLUMN event_key TEXT')\n"
    "conn.commit()\n"
    "os._exit(0)\n"  # die WITHOUT close: committed DDL stays in -wal
)


def _leave_committed_ddl_in_wal(path, monkeypatch):
    """Build a db whose required ``event_key`` column exists ONLY in an
    uncheckpointed WAL left behind by a writer that died without closing."""
    monkeypatch.setattr(db_module, "DB_PATH", path)
    db_module.init_db(create=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("ALTER TABLE detections DROP COLUMN event_key")
        conn.commit()
    finally:
        conn.close()  # clean close: -wal checkpointed and deleted
    assert not os.path.exists(path + "-wal")
    result = subprocess.run(
        [sys.executable, "-c", _UNCLEAN_WRITER, path],
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert os.path.exists(path + "-wal"), "expected committed WAL content"


def test_d1_validation_observes_committed_wal_schema(
        production_path_db, monkeypatch):
    path, use_production_path = production_path_db
    _leave_committed_ddl_in_wal(path, monkeypatch)
    use_production_path()
    db_before, wal_before = _file_bytes(path), _file_bytes(path + "-wal")

    db_module.init_db()  # must observe the committed WAL ALTER, not fail

    # The original database, WAL and SHM are untouched by validation.
    assert _file_bytes(path) == db_before
    assert _file_bytes(path + "-wal") == wal_before


def test_d1_validation_observes_wal_schema_with_shm_absent(
        production_path_db, monkeypatch):
    path, use_production_path = production_path_db
    _leave_committed_ddl_in_wal(path, monkeypatch)
    shm = path + "-shm"
    if os.path.exists(shm):
        os.remove(shm)  # stale/absent SHM: the hardest read-only WAL state
    use_production_path()

    # The snapshot fallback must recover the committed WAL content.
    db_module.init_db()


def test_d1_snapshot_fallback_observes_committed_wal_schema(
        production_path_db, monkeypatch):
    """When the direct read-only connection cannot inspect the database, the
    disposable-snapshot fallback must still observe committed WAL content."""
    path, use_production_path = production_path_db
    _leave_committed_ddl_in_wal(path, monkeypatch)
    use_production_path()
    db_before, wal_before = _file_bytes(path), _file_bytes(path + "-wal")

    def failing_readonly(target):
        raise sqlite3.OperationalError("readonly wal snapshot refused")

    monkeypatch.setattr(db_module, "_connect_readonly", failing_readonly)
    db_module.init_db()  # snapshot fallback path end-to-end

    assert _file_bytes(path) == db_before
    assert _file_bytes(path + "-wal") == wal_before


def test_d1_readonly_failure_yields_typed_unavailable_diagnostic(
        production_path_db, monkeypatch):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    db_module.init_db(create=True)
    use_production_path()
    original_error = sqlite3.OperationalError("unable to open database file")

    def failing_readonly(target):
        raise original_error

    def failing_snapshot(target):
        raise OSError("snapshot refused")

    monkeypatch.setattr(db_module, "_connect_readonly", failing_readonly)
    monkeypatch.setattr(db_module, "_snapshot_for_validation", failing_snapshot)

    with pytest.raises(db_module.SchemaValidationUnavailable) as excinfo:
        db_module.init_db()
    message = str(excinfo.value)
    assert "schema validation unavailable" in message
    assert "refusing to fall back to a write-capable connection" in message
    assert excinfo.value.__cause__ is original_error  # cause preserved
    # Distinct from the incompatible-schema diagnostic:
    assert not isinstance(excinfo.value, db_module.SchemaValidationError)


def test_d1_migration_trailing_verification_survives_readonly_failure(
        production_path_db, monkeypatch):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    # Minimal legacy schema (no event_uid) + one legacy row.
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE vehicle_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL UNIQUE,
            track_id TEXT NOT NULL, camera_id INTEGER, camera_name TEXT,
            session_id INTEGER, source_type TEXT NOT NULL DEFAULT 'rtsp',
            source_file TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            frame_count INTEGER NOT NULL DEFAULT 0,
            observation_count INTEGER NOT NULL DEFAULT 0,
            plate_number TEXT NOT NULL, plate_norm TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            agreement_ratio REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'confirmed',
            needs_review INTEGER NOT NULL DEFAULT 0,
            finalize_reason TEXT, plate_valid INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        INSERT INTO vehicle_events (event_key, track_id, first_seen, last_seen,
            plate_number, plate_norm, created_at, updated_at)
            VALUES ('cam1:0:1', 'cam1:0:1', 'a', 'b', '12b34567',
                    '12b34567', 'a', 'b');
    """)
    conn.commit()
    conn.close()
    use_production_path()

    def failing_readonly(target):
        raise sqlite3.OperationalError("readonly wal snapshot refused")

    monkeypatch.setattr(db_module, "_connect_readonly", failing_readonly)

    summary = db_module.migrate_database()  # must NOT fail post-migration

    assert summary["db_path"] == path
    assert summary["remaining_null_event_uid"] == 0


# ---------------------------------------------------------------------------
# D-2 — robust production database path identity
# ---------------------------------------------------------------------------

def _setup_production_anchor(tmp_path, monkeypatch, filename="anchor.db"):
    """Create an existing 'production' file and anchor identity to it."""
    anchor = tmp_path / filename
    anchor.write_bytes(b"production anchor")
    monkeypatch.setattr(db_module, "_PRODUCTION_DB_PATH", str(anchor))
    return anchor


def test_d2_identical_spelling_is_production(tmp_path, monkeypatch):
    anchor = _setup_production_anchor(tmp_path, monkeypatch)
    monkeypatch.setattr(db_module, "DB_PATH", str(anchor))
    assert db_module._is_production_db_path() is True


def test_d2_case_separator_and_dotpath_normalization(tmp_path, monkeypatch):
    anchor = _setup_production_anchor(tmp_path, monkeypatch)
    weird = str(tmp_path / "Sub" / ".." / str(anchor.name).upper())
    if os.path.normcase(str(anchor)) == os.path.normcase(weird):
        pytest.skip("filesystem is case-insensitive: spelling already equal")
    monkeypatch.setattr(db_module, "DB_PATH", weird)
    assert db_module._is_production_db_path() is True


def test_d2_relative_path_from_different_cwd(tmp_path, monkeypatch):
    anchor = _setup_production_anchor(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)  # different CWD: relative spelling resolves
    monkeypatch.setattr(db_module, "DB_PATH", anchor.name)
    assert db_module._is_production_db_path() is True


def test_d2_symlink_alias_is_production(tmp_path, monkeypatch):
    anchor = _setup_production_anchor(tmp_path, monkeypatch)
    alias = tmp_path / "alias.db"
    try:
        os.symlink(str(anchor), str(alias))
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unsupported/privileged on this platform")
    monkeypatch.setattr(db_module, "DB_PATH", str(alias))
    assert db_module._is_production_db_path() is True


def test_d2_hardlink_alias_is_production(tmp_path, monkeypatch):
    anchor = _setup_production_anchor(tmp_path, monkeypatch)
    alias = tmp_path / "hardlink.db"
    try:
        os.link(str(anchor), str(alias))
    except (OSError, NotImplementedError):
        pytest.skip("hard links unsupported on this platform/filesystem")
    monkeypatch.setattr(db_module, "DB_PATH", str(alias))
    assert db_module._is_production_db_path() is True


def test_d2_distinct_files_are_non_production(tmp_path, monkeypatch):
    anchor = _setup_production_anchor(tmp_path, monkeypatch)
    other = tmp_path / "other.db"
    other.write_bytes(b"other database")
    monkeypatch.setattr(db_module, "DB_PATH", str(other))
    assert db_module._is_production_db_path() is False


def test_d2_missing_file_with_alias_spelling(tmp_path, monkeypatch):
    anchor = _setup_production_anchor(tmp_path, monkeypatch)
    # A symlinked name whose target does not exist: realpath resolves the
    # link, so identity still matches the (missing) production path.
    dangling = tmp_path / "dangling.db"
    try:
        os.symlink(str(anchor) + ".missing", str(dangling))
        # anchor+".missing" does not exist either: dangling alias of a
        # missing production path is compared canonically.
        missing_anchor = str(anchor) + ".missing"
        monkeypatch.setattr(db_module, "_PRODUCTION_DB_PATH", missing_anchor)
        monkeypatch.setattr(db_module, "DB_PATH", str(dangling))
        assert db_module._is_production_db_path() is True
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unsupported/privileged on this platform")


def test_d2_missing_non_alias_file_is_non_production(tmp_path, monkeypatch):
    anchor = _setup_production_anchor(tmp_path, monkeypatch)
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "absent.db"))
    assert db_module._is_production_db_path() is False


def test_d2_fail_closed_when_identity_cannot_be_established(
        tmp_path, monkeypatch):
    anchor = _setup_production_anchor(tmp_path, monkeypatch)
    other = tmp_path / "other.db"
    other.write_bytes(b"other database")
    monkeypatch.setattr(db_module, "DB_PATH", str(other))
    # Realpath raises (canonicalization impossible): fail closed.
    def failing_realpath(path):
        raise OSError("realpath unavailable")
    monkeypatch.setattr(os.path, "realpath", failing_realpath)
    assert db_module._is_production_db_path() is True


def test_d2_fail_closed_when_stat_identity_inconclusive(
        tmp_path, monkeypatch):
    anchor = _setup_production_anchor(tmp_path, monkeypatch)
    other = tmp_path / "other.db"
    other.write_bytes(b"other database")
    monkeypatch.setattr(db_module, "DB_PATH", str(other))
    # Two existing files whose inode identity cannot be determined: fail
    # closed (treated as production), never downgrade to create=True.
    monkeypatch.setattr(db_module, "_same_existing_file", lambda a, b: None)
    assert db_module._is_production_db_path() is True


def test_d2_fail_closed_when_stat_identity_differs(
        tmp_path, monkeypatch):
    anchor = _setup_production_anchor(tmp_path, monkeypatch)
    other = tmp_path / "other.db"
    other.write_bytes(b"other database")
    monkeypatch.setattr(db_module, "DB_PATH", str(other))
    monkeypatch.setattr(db_module, "_same_existing_file", lambda a, b: False)
    assert db_module._is_production_db_path() is False


def test_d2_alias_does_not_bypass_validate_only_startup(
        production_path_db, trace_all_connects, tmp_path, monkeypatch):
    """End-to-end: an existing-file alias of the production anchor still gets
    validate-only startup (no implicit creation)."""
    path, use_production_path = production_path_db
    use_production_path()
    db_module.init_db(create=True)  # compatible schema at the anchor
    # Alias via hard link where supported, else a second spelling is
    # impossible (same string) — so skip rather than weaken the test.
    alias = tmp_path / "prod_alias.db"
    try:
        os.link(path, str(alias))
    except (OSError, NotImplementedError):
        pytest.skip("hard links unsupported on this platform/filesystem")
    monkeypatch.setattr(db_module, "DB_PATH", str(alias))
    assert db_module._is_production_db_path() is True

    count = len(trace_all_connects)
    db_module.init_db()  # validate-only through the alias
    _assert_no_ddl_or_dml(trace_all_connects[count:])
    assert trace_all_connects[count:]
