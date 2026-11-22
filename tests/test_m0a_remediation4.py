"""Remediation 4 regression tests (audit F-7, F-14, F-15).

All persistence uses isolated temporary SQLite databases (autouse fixture in
``tests/conftest.py`` redirects ``db.DB_PATH``; the repository-wide guard
installed from the root ``conftest.py`` refuses the production database).
The production database is never opened, connected to, or validated here.
"""
from __future__ import annotations

import re
import sqlite3
import threading

import pytest

import db as db_module
import camera_manager as cm


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def event_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "r4.db"))
    db_module.init_db()
    return db_module


class _FakeProcessor:
    """Fake RTSPStreamProcessor with the shutdown-contract surface only."""

    def __init__(self, completed=False):
        self._completed = completed
        self.stop_calls = 0
        self.status = "streaming"
        self.lock = threading.Lock()
        self.plate_history = []

    def stop(self):
        self.stop_calls += 1
        if not self._completed:
            self.status = "error: shutdown timeout"

    def shutdown_completed(self):
        return self._completed

    def get_state(self):
        return {"status": self.status, "history": list(self.plate_history)}


class _FakeStartedProcessor:
    """Replacement processor constructed through _start_processor_locked."""

    instances: list = []

    def __init__(self, engine, source, **kwargs):
        self.engine = engine
        self.source = source
        self.kwargs = kwargs
        self.status = "initialized"
        self.lock = threading.Lock()
        self.plate_history = []
        _FakeStartedProcessor.instances.append(self)

    def start(self):
        self.status = "connecting"

    def shutdown_completed(self):
        return False

    def get_state(self):
        return {"status": self.status, "history": list(self.plate_history)}


@pytest.fixture()
def started_processor_cls(monkeypatch):
    _FakeStartedProcessor.instances = []
    monkeypatch.setattr("video_processor.RTSPStreamProcessor",
                        _FakeStartedProcessor)
    return _FakeStartedProcessor


def _manager(event_db):
    return cm.CameraManager(ensure_models_fn=lambda: (None, None, None),
                            tasks_registry={}, tasks_lock=threading.Lock())


def _incomplete_camera(event_db, manager, camera_id=1, budget_exhausted=False):
    """Register a camera whose retained processor has an incomplete shutdown."""
    sid = db_module.start_session("rtsp", "rtsp://cam")
    rt = cm.CameraRuntime(camera_id=camera_id, name="c", url="u",
                          skip_frames=15, status="error", task_id="t",
                          session_id=sid)
    if budget_exhausted:
        rt.shutdown_stop_attempts = manager._MAX_SHUTDOWN_STOP_RETRIES
    processor = _FakeProcessor(completed=False)
    rt.processor = processor
    manager._cameras[camera_id] = rt
    return rt, processor, sid


def _session_row(sid):
    conn = db_module.get_conn()
    try:
        return conn.execute(
            "SELECT status, ended_at FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# F-14 — a retained incomplete processor is never replaced
# ---------------------------------------------------------------------------

def test_f14_start_camera_refuses_incomplete_shutdown(event_db):
    manager = _manager(event_db)
    rt, processor, sid = _incomplete_camera(
        event_db, manager, budget_exhausted=True)

    # ensure_models must never run: no replacement may even begin construction.
    manager._ensure_models = lambda: (_ for _ in ()).throw(
        AssertionError("replacement processor construction attempted"))

    result = manager.start_camera(1)

    assert result["status"] == "error"
    assert result["error"] == "shutdown_incomplete"
    # The original processor object, session and pending work are intact.
    assert rt.processor is processor
    assert rt.session_id == sid
    assert rt.shutdown_stop_attempts == manager._MAX_SHUTDOWN_STOP_RETRIES
    assert processor.stop_calls == 0  # start_camera must not stop it either
    row = _session_row(sid)
    assert row["status"] == "running" and row["ended_at"] is None


def test_f14_queue_promotion_preserves_queued_camera(event_db):
    manager = _manager(event_db)
    rt, processor, sid = _incomplete_camera(event_db, manager, camera_id=2)
    rt.status = "queued"
    manager._queue.append(2)

    with manager._lock:
        manager._promote_from_queue()

    # No replacement constructed; queue membership and ownership preserved.
    assert rt.processor is processor
    assert rt.session_id == sid
    assert 2 in manager._queue
    assert rt.status == "queued"
    assert processor.stop_calls == 0


def test_f14_queue_promotion_starts_after_shutdown_completed(
        event_db, started_processor_cls):
    manager = _manager(event_db)
    rt, processor, sid = _incomplete_camera(event_db, manager, camera_id=2)
    rt.status = "queued"
    manager._queue.append(2)

    with manager._lock:
        manager._promote_from_queue()
    assert 2 in manager._queue  # preserved while incomplete

    processor._completed = True  # later verified shutdown (watcher/API retry)
    with manager._lock:
        manager._promote_from_queue()

    assert not list(manager._queue)
    assert rt.processor is started_processor_cls.instances[0]
    assert rt.session_id != sid  # fresh session for the replacement
    assert rt.status in ("connecting", "connected", "streaming")


def test_f14_start_camera_succeeds_after_verified_shutdown(
        event_db, started_processor_cls):
    manager = _manager(event_db)
    rt, processor, sid = _incomplete_camera(event_db, manager)

    result = manager.start_camera(1)
    assert result["status"] == "error"

    processor._completed = True
    result = manager.start_camera(1)

    assert result["status"] == "running"
    assert rt.processor is started_processor_cls.instances[0]
    assert rt.processor is not processor
    # The old open session was safely finalized before the replacement.
    old = _session_row(sid)
    assert old["ended_at"] is not None
    assert rt.session_id != sid


# ---------------------------------------------------------------------------
# F-15 — removal is conditional on verified shutdown
# ---------------------------------------------------------------------------

def test_f15_remove_camera_deferred_on_incomplete_shutdown(
        event_db, monkeypatch):
    manager = _manager(event_db)
    rt, processor, sid = _incomplete_camera(event_db, manager)
    deleted: list[int] = []
    monkeypatch.setattr(cm, "delete_camera",
                        lambda cid: deleted.append(cid) or True)

    result = manager.remove_camera(1)

    assert result["removed"] is False
    assert result["reason"] == "shutdown_incomplete"
    # Runtime, exact processor object, session, and pending work all retained.
    assert manager._cameras.get(1) is rt
    assert rt.processor is processor
    assert rt.session_id == sid
    row = _session_row(sid)
    assert row["status"] == "running" and row["ended_at"] is None
    # The DB camera record was NOT deleted.
    assert deleted == []


def test_f15_remove_camera_succeeds_after_shutdown_completed(
        event_db, monkeypatch):
    manager = _manager(event_db)
    rt, processor, sid = _incomplete_camera(event_db, manager)
    deleted: list[int] = []
    monkeypatch.setattr(cm, "delete_camera",
                        lambda cid: deleted.append(cid) or True)

    result = manager.remove_camera(1)  # still incomplete
    assert result["removed"] is False

    processor._completed = True
    result = manager.remove_camera(1)

    assert result["removed"] is True
    assert deleted == [1]
    assert 1 not in manager._cameras
    row = _session_row(sid)
    assert row["ended_at"] is not None  # session finalized before removal


def test_f15_remove_camera_without_processor(event_db, monkeypatch):
    manager = _manager(event_db)
    rt = cm.CameraRuntime(camera_id=3, name="c", url="u", skip_frames=15,
                          status="stopped")
    manager._cameras[3] = rt
    deleted: list[int] = []
    monkeypatch.setattr(cm, "delete_camera",
                        lambda cid: deleted.append(cid) or True)

    result = manager.remove_camera(3)

    assert result["removed"] is True
    assert deleted == [3]
    assert 3 not in manager._cameras


def test_f15_remove_unknown_camera(event_db):
    manager = _manager(event_db)
    result = manager.remove_camera(999_999)
    assert result["removed"] is False
    assert result["reason"] == "not_found"


# ---------------------------------------------------------------------------
# F-7 — production startup is validation-only; migration is explicit
# ---------------------------------------------------------------------------

_DDL_OR_DML = re.compile(
    r"\b(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|REPLACE|VACUUM|ATTACH)\b",
    re.IGNORECASE)

_LEGACY_EVENT_DDL = """
    CREATE TABLE vehicle_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_key TEXT NOT NULL UNIQUE,
        track_id TEXT NOT NULL,
        camera_id INTEGER, camera_name TEXT, session_id INTEGER,
        source_type TEXT NOT NULL DEFAULT 'rtsp', source_file TEXT,
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
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
"""


@pytest.fixture()
def production_path_db(tmp_path, monkeypatch):
    """Point DB_PATH at a temp file AND simulate the production default path."""
    path = str(tmp_path / "prod_sim.db")

    def _use(path_value=path):
        monkeypatch.setattr(db_module, "DB_PATH", path_value)
        monkeypatch.setattr(db_module, "_PRODUCTION_DB_PATH", path_value)

    return path, _use


@pytest.fixture()
def traced_readonly(monkeypatch):
    """Record every SQL statement run through db._connect_readonly."""
    statements: list[str] = []
    original = db_module._connect_readonly

    def traced(path):
        conn = original(path)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(db_module, "_connect_readonly", traced)
    return statements


def _assert_no_ddl(statements):
    for stmt in statements:
        assert not _DDL_OR_DML.search(stmt), f"schema mutation attempted: {stmt}"


def test_f7_normal_init_compatible_db_emits_no_ddl(
        production_path_db, traced_readonly):
    path, use_production_path = production_path_db
    use_production_path()
    db_module.init_db(create=True)  # explicit creation on the isolated path
    count = len(traced_readonly)
    db_module.init_db()             # normal production startup

    _assert_no_ddl(traced_readonly[count:])
    assert traced_readonly[count:], "validation must actually inspect the schema"


def test_f7_normal_init_missing_db_file_raises_migration_required(
        production_path_db):
    path, use_production_path = production_path_db
    use_production_path()
    with pytest.raises(db_module.SchemaValidationError) as excinfo:
        db_module.init_db()  # file absent: refuse, never create
    assert "offline migration required" in str(excinfo.value)


def _legacy_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(_LEGACY_EVENT_DDL)
    conn.execute(
        "INSERT INTO vehicle_events (event_key, track_id, first_seen, "
        "last_seen, plate_number, plate_norm, created_at, updated_at) "
        "VALUES ('cam1:0:1', 'cam1:0:1', 'a', 'b', '12b34567', '12b34567', "
        "'a', 'b')")
    conn.commit()
    conn.close()
    return path


def test_f7_incompatible_schema_raises_migration_required(
        production_path_db):
    path, use_production_path = production_path_db
    _legacy_db(path)
    use_production_path()
    with pytest.raises(db_module.SchemaValidationError) as excinfo:
        db_module.init_db()
    message = str(excinfo.value)
    assert "offline migration required" in message
    assert "event_uid" in message  # the missing legacy column is named


def test_f7_missing_event_uid_and_partial_index_detected(production_path_db):
    path, use_production_path = production_path_db
    use_production_path()
    db_module.init_db(create=True)  # full schema
    conn = sqlite3.connect(path)
    conn.executescript(
        "DROP INDEX IF EXISTS idx_events_uid;"
        "ALTER TABLE vehicle_events DROP COLUMN event_uid;")
    conn.commit()
    conn.close()

    with pytest.raises(db_module.SchemaValidationError) as excinfo:
        db_module.init_db()
    message = str(excinfo.value)
    assert "event_uid" in message            # missing column
    assert "partial UNIQUE index" in message  # missing partial unique index


def test_f7_incorrect_unique_index_semantics_detected(production_path_db):
    path, use_production_path = production_path_db
    use_production_path()
    db_module.init_db(create=True)
    conn = sqlite3.connect(path)
    # A UNIQUE index WITHOUT the partial WHERE clause must be rejected:
    # legacy NULL-uid rows would violate it.
    conn.execute("DROP INDEX IF EXISTS idx_events_uid")
    conn.execute(
        "CREATE UNIQUE INDEX idx_events_uid_total ON vehicle_events(event_uid)")
    conn.commit()
    conn.close()

    with pytest.raises(db_module.SchemaValidationError) as excinfo:
        db_module.init_db()
    assert "partial UNIQUE index" in str(excinfo.value)


def test_f7_missing_table_and_column_detected(production_path_db):
    path, use_production_path = production_path_db
    use_production_path()
    db_module.init_db(create=True)
    conn = sqlite3.connect(path)
    conn.executescript(
        "DROP TABLE alerts;"
        "ALTER TABLE detections DROP COLUMN camera_name;")
    conn.commit()
    conn.close()

    with pytest.raises(db_module.SchemaValidationError) as excinfo:
        db_module.init_db()
    message = str(excinfo.value)
    assert "alerts: missing table" in message
    assert "detections: missing column(s) camera_name" in message


def test_f7_migrate_database_performs_schema_and_backfill(
        production_path_db):
    path, use_production_path = production_path_db
    _legacy_db(path)
    use_production_path()
    # Before migration the schema must be rejected...
    with pytest.raises(db_module.SchemaValidationError):
        db_module.init_db(create=False)

    summary = db_module.migrate_database()  # explicit operator action (temp DB)

    assert summary["db_path"] == path
    assert summary["remaining_null_event_uid"] == 0
    conn = sqlite3.connect(path)
    try:
        uid, key = conn.execute(
            "SELECT event_uid, event_key FROM vehicle_events").fetchone()
    finally:
        conn.close()
    import uuid as _uuid
    expected = str(_uuid.uuid5(
        db_module.EVENT_UID_NAMESPACE, "alpr:event:cam1:0:1"))
    assert uid == expected  # deterministic UUID5, historical key preserved


def test_f7_validation_passes_after_explicit_migration(production_path_db):
    path, use_production_path = production_path_db
    _legacy_db(path)
    use_production_path()
    db_module.migrate_database()
    db_module.init_db()  # normal startup now validates cleanly, no DDL
    db_module.init_db(create=False)


def test_f7_production_startup_never_reaches_migration(
        production_path_db, traced_readonly, monkeypatch):
    path, use_production_path = production_path_db
    use_production_path()
    db_module.init_db(create=True)
    # Any attempt to reach the backfill or the migration entry point from
    # normal startup is a hard failure.
    monkeypatch.setattr(
        db_module, "_backfill_event_uids",
        lambda conn: (_ for _ in ()).throw(
            AssertionError("backfill reached from normal startup")))
    monkeypatch.setattr(
        db_module, "migrate_database",
        lambda: (_ for _ in ()).throw(
            AssertionError("migrate_database reached from normal startup")))

    db_module.init_db()  # normal production startup
    _assert_no_ddl(traced_readonly)


def test_f7_api_ui_startup_never_enable_migration():
    """Source-level guard: no startup path passes migration flags."""
    for module_path in ("api.py", "ui.py"):
        with open(module_path, encoding="utf-8") as fh:
            source = fh.read()
        assert "run_migrations=True" not in source, module_path
        assert "create=True" not in source, module_path
        assert "migrate_database" not in source, module_path
        assert "init_db()" in source, module_path  # bare, validation-only call
