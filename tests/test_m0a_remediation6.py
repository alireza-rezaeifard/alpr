"""Remediation 6 regression tests (D-1 snapshot consistency).

Deterministic concurrency tests: source mutations are injected through
monkeypatched ``shutil.copyfile`` / ``db._file_fingerprint`` hooks with
explicit attempt counters — no arbitrary sleeps, no real races. All database
work uses isolated temporary databases; the production database and its
sidecars are never opened, hashed, or aliased.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

import pytest

import db as db_module


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(db_module, "_SNAPSHOT_RETRY_BACKOFF_S", 0.0)


@pytest.fixture()
def production_path_db(tmp_path, monkeypatch):
    path = str(tmp_path / "prod_sim.db")

    def _use(path_value=path):
        monkeypatch.setattr(db_module, "DB_PATH", path_value)
        monkeypatch.setattr(db_module, "_PRODUCTION_DB_PATH", path_value)

    return path, _use


@pytest.fixture()
def connect_recorder(monkeypatch):
    """Record (target, [statements]) for every sqlite3.connect made through
    the db module's sqlite3 reference (the guarded connect)."""
    records: list[tuple[str, list[str]]] = []
    original = db_module.sqlite3.connect

    def traced(*args, **kwargs):
        target = args[0] if args else kwargs.get("database")
        stmts: list[str] = []
        conn = original(*args, **kwargs)
        conn.set_trace_callback(stmts.append)
        records.append((str(target), stmts))
        return conn

    monkeypatch.setattr(db_module.sqlite3, "connect", traced)
    return records


def _force_fallback(monkeypatch):
    """Make the direct read-only inspection path fail so the verified
    snapshot path is exercised."""
    def failing_readonly(target):
        raise sqlite3.OperationalError("readonly wal snapshot refused")

    monkeypatch.setattr(db_module, "_connect_readonly", failing_readonly)


def _file_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _wal_db(path, committed_wal_ddl=False, drop_event_key=False, wal_dml=False):
    """Create a WAL temp database (via the app's own creation path)."""
    db_module.init_db(create=True)
    conn = sqlite3.connect(path)
    if drop_event_key:
        conn.execute("ALTER TABLE detections DROP COLUMN event_key")
    conn.commit()
    conn.close()
    if committed_wal_ddl or wal_dml:
        body = ("ALTER TABLE detections ADD COLUMN event_key TEXT"
                if committed_wal_ddl else
                "INSERT INTO sessions(source_type, started_at) "
                "VALUES ('probe', 't')")
        code = ("import sqlite3, sys, os\n"
                "c = sqlite3.connect(sys.argv[1])\n"
                f"c.execute({body!r})\n"
                "c.commit()\n"
                "os._exit(0)\n")
        result = subprocess.run([sys.executable, "-c", code, path],
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        assert os.path.exists(path + "-wal")


class _CopyHook:
    """Scripted shutil.copyfile wrapper with a DB-copy attempt counter.

    ``on_db(src, dst, attempt)`` / ``on_wal(src, dst, attempt)`` run BEFORE
    the real copy; they may mutate sources or raise to simulate concurrent
    writers deterministically.
    """

    def __init__(self, source_path, on_db=None, on_wal=None):
        self.source_path = source_path
        self.on_db = on_db
        self.on_wal = on_wal
        self.db_attempts = 0
        self.dirs: list[str] = []
        self.real_copyfile = shutil.copyfile

    def __call__(self, src, dst, **kwargs):
        is_wal = src.endswith("-wal")
        if not is_wal:
            self.db_attempts += 1
            if os.path.dirname(dst) not in self.dirs:
                self.dirs.append(os.path.dirname(dst))
            if self.on_db:
                self.on_db(src, dst, self.db_attempts)
        else:
            if self.on_wal:
                self.on_wal(src, dst, self.db_attempts)
        return self.real_copyfile(src, dst, **kwargs)


# ---------------------------------------------------------------------------
# A. Stable snapshot tests (fallback forced)
# ---------------------------------------------------------------------------

def test_r6_stable_rollback_journal_db(tmp_path, monkeypatch,
                                      production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    db_module.init_db(create=True)  # full schema
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")  # rollback-journal mode
    finally:
        conn.close()
    assert not os.path.exists(path + "-wal")
    use_production_path()
    _force_fallback(monkeypatch)

    db_module.init_db()  # verified snapshot path, stable source

    assert os.path.exists(path)  # still there, untouched


def test_r6_stable_wal_db_after_writer_close(tmp_path, monkeypatch,
                                             production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path)
    use_production_path()
    _force_fallback(monkeypatch)

    db_module.init_db()  # verified snapshot observes the stable WAL pair

    # Reaching here means validation succeeded through the snapshot path.


def test_r6_committed_wal_schema_observed_from_verified_snapshot(
        tmp_path, monkeypatch, production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path, committed_wal_ddl=True, drop_event_key=True)
    use_production_path()
    _force_fallback(monkeypatch)
    before = (_file_bytes(path), _file_bytes(path + "-wal"))

    db_module.init_db()  # verified snapshot observes the committed ALTER

    assert (_file_bytes(path), _file_bytes(path + "-wal")) == before


def test_r6_missing_shm_with_committed_wal(tmp_path, monkeypatch,
                                           production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path, committed_wal_ddl=True, drop_event_key=True)
    shm = path + "-shm"
    if os.path.exists(shm):
        os.remove(shm)
    use_production_path()
    _force_fallback(monkeypatch)

    db_module.init_db()


# ---------------------------------------------------------------------------
# B. Controlled concurrent-writer tests (deterministic hooks)
# ---------------------------------------------------------------------------

def _append_byte(path):
    with open(path, "ab") as fh:
        fh.write(b"\x00")


def test_r6_wal_commit_between_db_and_wal_copy_detected_then_retried(
        tmp_path, monkeypatch, production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path)
    use_production_path()
    _force_fallback(monkeypatch)
    hook = _CopyHook(path, on_wal=lambda s, d, a: _append_byte(path) if a == 1 else None)
    monkeypatch.setattr(shutil, "copyfile", hook)

    db_module.init_db()  # attempt 1 unstable → retry → attempt 2 stable

    assert hook.db_attempts >= 2


def test_r6_wal_append_during_db_copy_detected(tmp_path, monkeypatch,
                                               production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path)
    use_production_path()
    _force_fallback(monkeypatch)
    hook = _CopyHook(path, on_db=lambda s, d, a: _append_byte(path + "-wal") if a == 1 else None)
    monkeypatch.setattr(shutil, "copyfile", hook)

    db_module.init_db()

    assert hook.db_attempts >= 2


def test_r6_checkpoint_during_snapshot_detected(tmp_path, monkeypatch,
                                                production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path, committed_wal_ddl=True, drop_event_key=True)
    use_production_path()
    _force_fallback(monkeypatch)

    def checkpoint_during_copy(src, dst, attempt):
        if attempt == 1:  # real SQLite checkpoint against the temp source
            conn = sqlite3.connect(path)
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                conn.close()

    hook = _CopyHook(path, on_wal=checkpoint_during_copy)
    monkeypatch.setattr(shutil, "copyfile", hook)

    db_module.init_db()

    assert hook.db_attempts >= 2


def test_r6_wal_disappears_during_copy_retries(tmp_path, monkeypatch,
                                               production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path)
    use_production_path()
    _force_fallback(monkeypatch)

    def wal_vanishes(src, dst, attempt):
        if attempt == 1:
            os.remove(path + "-wal")

    hook = _CopyHook(path, on_wal=wal_vanishes)
    monkeypatch.setattr(shutil, "copyfile", hook)

    db_module.init_db()  # attempt 1 fails to copy WAL → retry without WAL

    assert hook.db_attempts >= 2


def test_r6_wal_replaced_during_copy_detected(tmp_path, monkeypatch,
                                              production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path, wal_dml=True)  # real WAL content; main DB schema complete
    use_production_path()
    _force_fallback(monkeypatch)

    def replace_wal(src, dst, attempt):
        if attempt == 1:  # reset-style replacement: empty WAL
            with open(path + "-wal", "wb") as fh:
                fh.write(b"")

    hook = _CopyHook(path, on_wal=replace_wal)
    monkeypatch.setattr(shutil, "copyfile", hook)

    db_module.init_db()

    assert hook.db_attempts >= 2


def test_r6_main_db_change_during_copy_detected(tmp_path, monkeypatch,
                                                production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path)
    use_production_path()
    _force_fallback(monkeypatch)

    def write_during_copy(src, dst, attempt):
        if attempt == 1:  # a real, valid write against the temp source
            conn = sqlite3.connect(path)
            try:
                conn.execute(
                    "INSERT INTO app_config(key, value) VALUES ('probe', '1')")
                conn.commit()
            finally:
                conn.close()

    hook = _CopyHook(path, on_wal=write_during_copy)
    monkeypatch.setattr(shutil, "copyfile", hook)

    db_module.init_db()

    assert hook.db_attempts >= 2


def test_r6_persistent_instability_exhausts_retry_budget(
        tmp_path, monkeypatch, production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path)
    use_production_path()
    _force_fallback(monkeypatch)
    hook = _CopyHook(path, on_wal=lambda s, d, a: _append_byte(path + "-wal"))
    monkeypatch.setattr(shutil, "copyfile", hook)

    with pytest.raises(db_module.SchemaValidationUnavailable) as excinfo:
        db_module.init_db()

    assert hook.db_attempts == db_module._SNAPSHOT_ATTEMPTS
    assert "source stability could not be established" in str(excinfo.value)
    # All attempted snapshot directories were cleaned up.
    for d in hook.dirs:
        assert not os.path.exists(d)


# ---------------------------------------------------------------------------
# C. No-mutation tests
# ---------------------------------------------------------------------------

def test_r6_fallback_never_opens_write_connection_to_original(
        tmp_path, monkeypatch, production_path_db, connect_recorder):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path, committed_wal_ddl=True, drop_event_key=True)
    use_production_path()
    _force_fallback(monkeypatch)
    # get_conn is write-capable: it must be unreachable from validation.
    monkeypatch.setattr(
        db_module, "get_conn",
        lambda: (_ for _ in ()).throw(
            AssertionError("get_conn reached from validation")))
    baseline = len(connect_recorder)  # exclude this test's own setup connects

    db_module.init_db()

    for target, stmts in connect_recorder[baseline:]:
        assert "alpr_schema_validation_" in target or "mode=ro" in target, \
            f"unexpected connection target: {target}"
        for stmt in stmts:
            assert not any(
                kw in stmt.upper() for kw in
                ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ",
                 "REPLACE ", "VACUUM ")), stmt


def test_r6_original_files_untouched_by_fallback(tmp_path, monkeypatch,
                                                 production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path, committed_wal_ddl=True, drop_event_key=True)
    use_production_path()
    _force_fallback(monkeypatch)
    probe = sqlite3.connect(path)
    try:
        mode_before = probe.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        probe.close()
    before = tuple(  # captured AFTER the probe's checkpoint-on-close settles
        _file_bytes(p) if os.path.exists(p) else None
        for p in (path, path + "-wal", path + "-shm"))

    db_module.init_db()

    after = tuple(
        _file_bytes(p) if os.path.exists(p) else None
        for p in (path, path + "-wal", path + "-shm"))
    assert after == before
    probe = sqlite3.connect(path)
    try:
        mode_after = probe.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        probe.close()
    assert mode_after == mode_before == "wal"


# ---------------------------------------------------------------------------
# D. Exception and cleanup tests
# ---------------------------------------------------------------------------

def test_r6_db_copy_failure_fails_closed(tmp_path, monkeypatch,
                                         production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    db_module.init_db(create=True)
    use_production_path()
    _force_fallback(monkeypatch)
    boom = PermissionError("db copy refused")

    def fail_db(src, dst, **kw):
        raise boom

    monkeypatch.setattr(shutil, "copyfile", fail_db)

    with pytest.raises(db_module.SchemaValidationUnavailable) as excinfo:
        db_module.init_db()
    assert "snapshot copy failed" in str(excinfo.value)
    assert excinfo.value.__cause__ is boom


def test_r6_wal_copy_failure_fails_closed(tmp_path, monkeypatch,
                                          production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path, committed_wal_ddl=True, drop_event_key=True)
    use_production_path()
    _force_fallback(monkeypatch)
    boom = PermissionError("wal copy refused")
    real_copyfile = shutil.copyfile

    def fail_wal(src, dst, **kw):
        if src.endswith("-wal"):
            raise boom
        return real_copyfile(src, dst, **kw)

    monkeypatch.setattr(shutil, "copyfile", fail_wal)

    with pytest.raises(db_module.SchemaValidationUnavailable) as excinfo:
        db_module.init_db()
    assert "snapshot copy failed" in str(excinfo.value)
    assert excinfo.value.__cause__ is boom


def test_r6_fingerprint_failure_fails_closed(tmp_path, monkeypatch,
                                             production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    db_module.init_db(create=True)
    use_production_path()
    _force_fallback(monkeypatch)
    boom = OSError("fingerprint refused")

    def failing_fingerprint(target):
        raise boom

    monkeypatch.setattr(db_module, "_file_fingerprint", failing_fingerprint)

    with pytest.raises(db_module.SchemaValidationUnavailable) as excinfo:
        db_module.init_db()
    assert "could not be read" in str(excinfo.value)
    assert excinfo.value.__cause__ is boom


def test_r6_temp_dirs_cleaned_after_partial_copy(
        tmp_path, monkeypatch, production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path, committed_wal_ddl=True, drop_event_key=True)
    use_production_path()
    _force_fallback(monkeypatch)
    dirs: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(*a, **kw):
        d = real_mkdtemp(*a, **kw)
        dirs.append(d)
        return d

    monkeypatch.setattr(db_module.tempfile, "mkdtemp", recording_mkdtemp)
    real_copyfile = shutil.copyfile

    def fail_wal(src, dst, **kw):
        if src.endswith("-wal"):
            raise PermissionError("wal copy refused")
        return real_copyfile(src, dst, **kw)

    monkeypatch.setattr(shutil, "copyfile", fail_wal)

    with pytest.raises(db_module.SchemaValidationUnavailable):
        db_module.init_db()

    assert dirs, "expected a snapshot attempt"
    for d in dirs:
        assert not os.path.exists(d), f"leftover snapshot dir: {d}"


def test_r6_retry_uses_fresh_directories(tmp_path, monkeypatch,
                                         production_path_db):
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    _wal_db(path)
    use_production_path()
    _force_fallback(monkeypatch)
    dirs: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(*a, **kw):
        d = real_mkdtemp(*a, **kw)
        dirs.append(d)
        return d

    monkeypatch.setattr(db_module.tempfile, "mkdtemp", recording_mkdtemp)
    hook = _CopyHook(
        path,
        on_wal=lambda s, d, a: _append_byte(path + "-wal") if a == 1 else None)
    monkeypatch.setattr(shutil, "copyfile", hook)

    db_module.init_db()  # one unstable attempt, then success

    assert len(dirs) == hook.db_attempts  # one fresh dir per attempt
    assert len(set(dirs)) == len(dirs)    # never reused
    for d in dirs[:-1]:
        assert not os.path.exists(d)      # discarded attempts cleaned


def test_r6_corrupted_copy_never_validated(tmp_path, monkeypatch,
                                           production_path_db,
                                           connect_recorder):
    """Copy-integrity failure on every attempt must end in fail-closed
    exhaustion, and no snapshot may ever be opened for inspection."""
    path, use_production_path = production_path_db
    monkeypatch.setattr(db_module, "DB_PATH", path)
    db_module.init_db(create=True)
    use_production_path()
    _force_fallback(monkeypatch)
    real_copyfile = shutil.copyfile

    def corrupt_copy(src, dst, **kw):
        result = real_copyfile(src, dst, **kw)
        with open(dst, "ab") as fh:  # tamper with the copy itself
            fh.write(b"tampered")
        return result

    monkeypatch.setattr(shutil, "copyfile", corrupt_copy)

    with pytest.raises(db_module.SchemaValidationUnavailable) as excinfo:
        db_module.init_db()
    assert "copied bytes do not match" in str(excinfo.value)
    snapshot_opens = [t for t, _ in connect_recorder
                      if "alpr_schema_validation_" in t]
    assert snapshot_opens == [], "a tampered snapshot was inspected"
