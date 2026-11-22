import hashlib
import logging
import shutil
import sqlite3
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "database", "plpr.db")

# Fixed namespace for deterministic UUID5 backfill of legacy event rows.
EVENT_UID_NAMESPACE = uuid.UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")


def get_conn():
    # NOTE (R5 D-1): this connection sets the PERSISTENT journal mode (WAL is
    # recorded in the database header) and is therefore NOT read-only. It is
    # used by runtime writes, schema creation, and the authorized offline
    # migration — never by startup schema validation (see _validate_schema_at).
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_column(conn, table, column, ddl):
    """Add a column to *table* if it does not already exist (safe to re-run)."""
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _backfill_event_uids(conn) -> None:
    """Assign deterministic UUID5 values only to rows missing an event_uid.

    M0-A migration policy (audit F-7): this is a DATA backfill. It is gated
    behind ``init_db(run_migrations=True)`` and never runs from ordinary
    application startup. Authorized operator procedure (requires explicit
    owner approval before execution):

        1. Stop the backend (or ensure no writer holds the DB).
        2. Run a maintenance invocation that calls
           ``import db; db.init_db(run_migrations=True)`` with ``db.DB_PATH``
           pointing at the target database file.
        3. Verify ``SELECT COUNT(*) FROM vehicle_events WHERE event_uid IS NULL``
           returns 0.

    The backfill is idempotent and deterministic (fixed UUID5 namespace), so
    re-running it after authorization is safe. Ordinary startup still performs
    additive, idempotent schema-consistency steps (CREATE TABLE IF NOT EXISTS,
    ADD COLUMN, CREATE INDEX IF NOT EXISTS) because the persistence layer
    writes the event_uid column; those steps never rewrite existing rows.
    """
    rows = conn.execute(
        "SELECT id, event_key FROM vehicle_events WHERE event_uid IS NULL"
    ).fetchall()
    for row in rows:
        uid = str(uuid.uuid5(EVENT_UID_NAMESPACE, f"alpr:event:{row['event_key']}"))
        conn.execute(
            "UPDATE vehicle_events SET event_uid = ? WHERE id = ? AND event_uid IS NULL",
            (uid, row["id"]),
        )


# ---------------------------------------------------------------------------
# Schema definition + startup validation (audit F-7, Remediation 4).
#
# Normal production startup performs READ-ONLY schema validation and never
# mutates schema or data. Schema DDL and the event_uid backfill run only
# through explicit creation (``init_db(create=True)`` / ``migrate_database()``
# / ``python -m db migrate``), which must be aimed at a test or explicitly
# owner-authorized target database.
# ---------------------------------------------------------------------------
_SCHEMA_DDL = """
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_type TEXT NOT NULL,
        source_file TEXT,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        total_frames INTEGER DEFAULT 0,
        total_plates INTEGER DEFAULT 0,
        unique_plates INTEGER DEFAULT 0,
        status TEXT DEFAULT 'running'
    );
    CREATE TABLE IF NOT EXISTS detections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER REFERENCES sessions(id),
        timestamp TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_file TEXT,
        plate_dtrb TEXT,
        plate_persian TEXT,
        confidence REAL,
        frame_number INTEGER DEFAULT 0,
        frame_time TEXT
    );
    CREATE TABLE IF NOT EXISTS cameras (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL DEFAULT '',
        url         TEXT NOT NULL,
        skip_frames INTEGER NOT NULL DEFAULT 15,
        created_at  TEXT NOT NULL,
        updated_at  TEXT
    );
    CREATE TABLE IF NOT EXISTS app_config (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'Viewer',
        disabled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS revoked_tokens (
        jti TEXT PRIMARY KEY,
        exp INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS licenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 0,
        expiry TEXT NOT NULL,
        camera_limit INTEGER NOT NULL,
        activated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS watchlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        list_type TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS watchlist_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        watchlist_id INTEGER NOT NULL REFERENCES watchlists(id),
        plate_raw TEXT NOT NULL,
        plate_norm TEXT NOT NULL,
        label TEXT,
        reason TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        detection_id INTEGER NOT NULL REFERENCES detections(id),
        entry_id INTEGER NOT NULL REFERENCES watchlist_entries(id),
        plate_value TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        action TEXT NOT NULL,
        resource TEXT,
        outcome TEXT NOT NULL,
        timestamp TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_detections_ts ON detections(timestamp);
    CREATE INDEX IF NOT EXISTS idx_detections_session ON detections(session_id);
    CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);
    CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);
    CREATE INDEX IF NOT EXISTS idx_wl_entries_norm ON watchlist_entries(plate_norm);
    -- Phase 1 (M1, minimal): one durable row per finalized vehicle visit.
    -- UNIQUE(event_key) is the persistence-boundary idempotency guarantee:
    -- "INSERT ... ON CONFLICT(event_key) DO UPDATE" can never create a second
    -- row for the same track lifetime, even across process restarts.
    CREATE TABLE IF NOT EXISTS vehicle_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_key TEXT NOT NULL UNIQUE,
        event_uid TEXT,
        track_id TEXT NOT NULL,
        camera_id INTEGER,
        camera_name TEXT,
        session_id INTEGER,
        source_type TEXT NOT NULL DEFAULT 'rtsp',
        source_file TEXT,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        duration_ms INTEGER NOT NULL DEFAULT 0,
        frame_count INTEGER NOT NULL DEFAULT 0,
        observation_count INTEGER NOT NULL DEFAULT 0,
        plate_number TEXT NOT NULL,
        plate_norm TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0,
        agreement_ratio REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'confirmed',
        needs_review INTEGER NOT NULL DEFAULT 0,
        finalize_reason TEXT,
        plate_valid INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_events_camera_time ON vehicle_events(camera_id, last_seen DESC);
    CREATE INDEX IF NOT EXISTS idx_events_plate_norm ON vehicle_events(plate_norm, last_seen DESC);
"""

# Columns the runtime persistence/query paths depend on. Validation is strict:
# any missing column makes Event persistence or the detection/session flows
# silently degrade, so startup must reject the schema instead.
_REQUIRED_SCHEMA = {
    "sessions": (
        "id", "source_type", "source_file", "started_at", "ended_at",
        "total_frames", "total_plates", "unique_plates", "status",
    ),
    "detections": (
        "id", "session_id", "timestamp", "source_type", "source_file",
        "plate_dtrb", "plate_persian", "confidence", "frame_number",
        "frame_time", "camera_id", "camera_name", "event_key",
    ),
    "cameras": ("id", "name", "url", "skip_frames", "created_at", "updated_at"),
    "app_config": ("key", "value"),
    "users": ("id", "username", "password_hash", "role", "disabled", "created_at"),
    "revoked_tokens": ("jti", "exp"),
    "licenses": ("id", "key", "active", "expiry", "camera_limit", "activated_at"),
    "watchlists": ("id", "name", "list_type", "created_at"),
    "watchlist_entries": (
        "id", "watchlist_id", "plate_raw", "plate_norm", "label", "reason",
        "created_at",
    ),
    "alerts": ("id", "detection_id", "entry_id", "plate_value", "created_at"),
    "audit_log": ("id", "username", "action", "resource", "outcome", "timestamp"),
    "vehicle_events": (
        "id", "event_key", "event_uid", "track_id", "camera_id",
        "camera_name", "session_id", "source_type", "source_file",
        "first_seen", "last_seen", "duration_ms", "frame_count",
        "observation_count", "plate_number", "plate_norm", "confidence",
        "agreement_ratio", "status", "needs_review", "finalize_reason",
        "plate_valid", "created_at", "updated_at",
    ),
}

# The configured default production database. ``db.DB_PATH`` may be reassigned
# (tests redirect it); this constant anchors the production path so the
# validate-only startup default cannot be weakened by reassignment.
_PRODUCTION_DB_PATH = os.path.join(os.path.dirname(__file__), "database", "plpr.db")


class SchemaValidationError(RuntimeError):
    """Raised when normal startup validation finds the schema incompatible.

    The message lists every missing table/column/index and states that an
    explicit offline migration is required. Startup never attempts to repair
    the schema; Event persistence would silently fail (persist_failure →
    EXHAUSTED) on an incompatible schema, so the process must not serve
    requests in that state.
    """


class SchemaValidationUnavailable(RuntimeError):
    """Raised when the schema cannot be inspected reliably at all.

    Distinct from :class:`SchemaValidationError`: the database may be
    perfectly compatible, but no strictly read-only inspection (direct or
    through a disposable snapshot) could be performed — for example the file
    is locked, unreadable, or its WAL state cannot be captured. Startup must
    fail closed either way; the original SQLite/OS error is preserved as
    ``__cause__``.
    """


def _same_existing_file(path_a: str, path_b: str) -> bool | None:
    """File-identity comparison of two EXISTING paths (R5 D-2).

    Returns True when the two paths refer to the same file (verified via
    ``(st_dev, st_ino)``), False when both exist and provably differ, and
    ``None`` when the comparison is inconclusive (filesystem without inode
    identity, or stat failure). Windows: ``st_ino`` is the NTFS file index
    and is meaningful on NTFS; it may be 0 on FAT/exFAT, which yields
    ``None`` (fail closed upstream).
    """
    try:
        stat_a, stat_b = os.stat(path_a), os.stat(path_b)
    except OSError:
        return None
    if stat_a.st_ino == 0 or stat_b.st_ino == 0:
        return None  # filesystem without reliable inode identity
    return (stat_a.st_dev, stat_a.st_ino) == (stat_b.st_dev, stat_b.st_ino)


def _is_production_db_path() -> bool:
    """True when the configured ``DB_PATH`` refers to the production database.

    Identity is established in layers (R5 D-2):

    1. ``normcase(abspath(...))`` — fast path for identical spellings
       (handles Windows case and separator differences and CWD-relative
       forms, but NOT aliases).
    2. ``normcase(realpath(...))`` — resolves symlinks, NTFS junctions and
       substituted drives where the platform supports it. Hard-link aliases
       are NOT resolved here.
    3. ``(st_dev, st_ino)`` file identity via :func:`_same_existing_file` —
       catches hard-link aliases of two existing files.

    Fail-closed semantics: when the paths spell different canonical names,
    both files exist, and file identity CANNOT be established (stat failure
    or a filesystem without inode identity), the configured path is treated
    as PRODUCTION (validate-only). Identity checking must never downgrade to
    implicit schema creation. Reassigning ``db.DB_PATH`` to any alias of the
    production database must not bypass startup protection.
    """
    current = os.path.abspath(DB_PATH)
    production = os.path.abspath(_PRODUCTION_DB_PATH)
    if os.path.normcase(current) == os.path.normcase(production):
        return True
    try:
        current_real = os.path.normcase(os.path.realpath(current))
        production_real = os.path.normcase(os.path.realpath(production))
    except (OSError, ValueError):
        return True  # cannot canonicalize: fail closed
    if current_real == production_real:
        return True
    if os.path.exists(current) and os.path.exists(production):
        identity = _same_existing_file(current, production)
        if identity is None:
            return True  # inconclusive identity: fail closed
        return identity
    return False


def _connect_readonly(path: str):
    """Open *path* strictly read-only (no journal-mode or other PRAGMA writes)."""
    import urllib.parse
    abs_posix = os.path.abspath(path).replace("\\", "/")
    uri = "file:" + urllib.parse.quote(abs_posix, safe="/:") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _validate_vehicle_events_unique_indexes(conn) -> list[str]:
    """Check the UNIQUE index semantics the Event persistence path relies on.

    ``event_key`` must carry a UNIQUE index (``INSERT ... ON CONFLICT(event_key)``
    idempotency) and ``event_uid`` must carry a PARTIAL unique index
    (``WHERE event_uid IS NOT NULL``) so legacy NULL-uid rows remain allowed.
    Index identity is checked semantically (columns + uniqueness + partial
    WHERE clause), not by index name.
    """
    problems: list[str] = []
    indexes = conn.execute("PRAGMA index_list(vehicle_events)").fetchall()

    def _cols(name: str) -> list[str]:
        return [r["name"] for r in conn.execute(f"PRAGMA index_info({name})")]

    unique_column_sets = [_cols(idx["name"]) for idx in indexes if idx["unique"]]
    if ["event_key"] not in unique_column_sets:
        problems.append(
            "vehicle_events: missing UNIQUE index on event_key "
            "(persistence idempotency)")

    uid_partial_unique = False
    for idx in indexes:
        if not idx["unique"] or _cols(idx["name"]) != ["event_uid"]:
            continue
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
            (idx["name"],),
        ).fetchone()
        sql = (row["sql"] or "").upper() if row else ""
        if "IS NOT NULL" in sql:
            uid_partial_unique = True
    if not uid_partial_unique:
        problems.append(
            "vehicle_events: missing partial UNIQUE index on event_uid "
            "(WHERE event_uid IS NOT NULL)")
    return problems


def _snapshot_for_validation(path: str) -> str:
    """Capture a STABILITY-VERIFIED disposable snapshot of *path* (R6 D-1).

    Protocol (bounded retries):

    1. Fingerprint the source DB and, when present, its ``-wal`` sidecar:
       ``(st_dev, st_ino, size, sha256)`` — content, not size alone.
    2. Copy the DB and the WAL into a private temp directory.
    3. Re-fingerprint both source files and re-check WAL presence.
    4. Fingerprint the copied files and require them to equal the stable
       source fingerprints.

    Any mismatch between the pre-copy, post-copy, and copied fingerprints —
    including size-preserving content changes, WAL appends, checkpoints,
    WAL reset/replacement, or file replacement — means the source changed
    during the capture and the attempt is discarded and retried up to
    ``_SNAPSHOT_ATTEMPTS`` times. Retry exhaustion raises
    :class:`SchemaValidationUnavailable` (fail closed); a stale-but-valid
    snapshot is never accepted as the current schema.

    Coherence argument: any SQLite state transition between the two
    fingerprint checkpoints necessarily modifies the DB or WAL bytes (a
    checkpoint writes DB pages, a commit appends WAL frames, a WAL reset
    rewrites the WAL header), so verified byte-stability of both files
    across the window means the copied pair represents one coherent source
    state. The ``-shm`` is transient cache and deliberately not copied.

    Residual limitation: a change that completes and reverts to byte-identical
    content entirely inside the capture window is indistinguishable from no
    change — but then the observed state is byte-identical anyway, so the
    snapshot still faithfully represents that state.

    Raises ``SchemaValidationUnavailable`` (cause preserved) when the source
    cannot be read, a copy fails, or stability cannot be established.
    """
    wal = path + "-wal"
    last_instability = "source changed during capture"
    for attempt in range(1, _SNAPSHOT_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(_SNAPSHOT_RETRY_BACKOFF_S * (attempt - 1))
        # 1. Pre-copy fingerprints (read failures fail closed immediately:
        # an unreadable source cannot yield a trustworthy snapshot).
        try:
            db_pre = _file_fingerprint(path)
            wal_present = os.path.exists(wal)
            wal_pre = _file_fingerprint(wal) if wal_present else None
        except OSError as exc:
            raise _validation_unavailable(
                path, f"source database/WAL could not be read ({exc})", exc)
        # 2. Copy.
        tmp_dir = tempfile.mkdtemp(prefix="alpr_schema_validation_")
        snap = os.path.join(tmp_dir, "snapshot.db")
        try:
            shutil.copyfile(path, snap)
            if wal_present:
                shutil.copyfile(wal, snap + "-wal")
        except FileNotFoundError as exc:
            # WAL vanished between the existence check and its copy (or the
            # DB vanished): treat as source instability and retry.
            shutil.rmtree(tmp_dir, ignore_errors=True)
            last_instability = f"source file disappeared during copy ({exc})"
            continue
        except OSError as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise _validation_unavailable(
                path, f"snapshot copy failed ({exc})", exc)
        # 3./4. Post-copy verification of source stability and copy integrity.
        try:
            db_post = _file_fingerprint(path)
            wal_now_present = os.path.exists(wal)
            wal_post = (_file_fingerprint(wal)
                        if wal_now_present else None)
            copied_db = _file_fingerprint(snap)
            copied_wal = (_file_fingerprint(snap + "-wal")
                          if wal_present else None)
        except OSError as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            last_instability = f"verification read failed ({exc})"
            continue
        if wal_now_present != wal_present:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            last_instability = "WAL presence changed during capture"
            continue
        if db_post != db_pre or (wal_pre is not None and wal_post != wal_pre):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            last_instability = "source changed during capture"
            continue
        # Copied bytes must equal the stable source CONTENT (size + sha256);
        # st_dev/st_ino are identity of the source files and necessarily
        # differ for the copies.
        if copied_db[2:] != db_pre[2:] or (
                wal_pre is not None and copied_wal[2:] != wal_pre[2:]):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            last_instability = "copied bytes do not match the stable source"
            continue
        return snap
    raise _validation_unavailable(
        path,
        f"source stability could not be established across "
        f"{_SNAPSHOT_ATTEMPTS} attempts (last reason: {last_instability}); "
        "refusing to validate a possibly stale or mixed snapshot",
        None)


def _validation_unavailable(path: str, reason: str, cause
                            ) -> SchemaValidationUnavailable:
    """Build the typed fail-closed diagnostic, preserving *cause*."""
    error = SchemaValidationUnavailable(
        f"schema validation unavailable for {path}: {reason}; "
        "startup fails closed rather than validating an unverified "
        "snapshot or opening a write-capable connection to the target "
        "database")
    if cause is not None:
        error.__cause__ = cause
    return error


# Snapshot capture tuning (module-level so tests can adjust deterministically).
_SNAPSHOT_ATTEMPTS = 3
_SNAPSHOT_RETRY_BACKOFF_S = 0.05


def _file_fingerprint(path: str) -> tuple:
    """Content fingerprint ``(st_dev, st_ino, size, sha256)`` of *path*.

    Content-based (not size/mtime alone), so size-preserving writes are
    detected. Raises ``OSError`` when the file cannot be read or stated.
    """
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    st = os.stat(path)
    return (st.st_dev, st.st_ino, size, digest.hexdigest())


def _inspect_schema_problems(conn) -> list[str]:
    """Collect schema-compatibility problems from an open connection.

    Performs metadata inspection only (sqlite_master, PRAGMA table_info,
    index_list/index_info) — no DDL, no DML, no journal-mode changes.
    """
    problems: list[str] = []
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table, columns in _REQUIRED_SCHEMA.items():
        if table not in tables:
            problems.append(f"{table}: missing table")
            continue
        present = {
            r["name"] for r in conn.execute(f"PRAGMA table_info({table})")
        }
        missing = [c for c in columns if c not in present]
        if missing:
            problems.append(
                f"{table}: missing column(s) {', '.join(missing)}")
    if "vehicle_events" in tables:
        problems.extend(_validate_vehicle_events_unique_indexes(conn))
    return problems


def _validate_schema_at(path: str) -> None:
    """Strictly read-only schema validation of the database at *path* (R5 D-1).

    First attempts a direct read-only URI connection (no DDL, no DML, no
    journal-mode change, no file creation, no checkpoint). WAL states can
    make that attempt impossible (missing/stale ``-shm``, or committed
    content still in ``-wal`` that requires recovery): in that case the
    database and its ``-wal`` are copied to a disposable snapshot which is
    inspected instead, so committed WAL contents are observed correctly and
    the original is never opened for writing. This fallback is logged, never
    silent, and the fallback connection only ever touches the snapshot.

    Raises :class:`SchemaValidationError` listing every incompatible element
    when required tables, columns, or unique-index semantics are missing, or
    :class:`SchemaValidationUnavailable` (original error preserved as
    ``__cause__``) when no reliable inspection is possible. Startup fails
    closed in both cases.
    """
    if not os.path.exists(path):
        raise SchemaValidationError(
            f"offline migration required: database file does not exist: {path}; "
            "run the explicit offline migration (python -m db migrate) against "
            "an owner-authorized target")
    try:
        conn = _connect_readonly(path)
    except sqlite3.Error as exc:
        _validate_via_snapshot(path, exc)
        return
    try:
        problems = _inspect_schema_problems(conn)
    except sqlite3.Error as exc:
        # The open succeeded but inspection failed (typical WAL recovery
        # failure on a read-only connection). Retry on a snapshot.
        _validate_via_snapshot(path, exc)
        return
    finally:
        conn.close()
    if problems:
        raise SchemaValidationError(
            "offline migration required: incompatible schema ("
            + "; ".join(problems)
            + "); normal startup never repairs the schema")


def _validate_via_snapshot(path: str, original: Exception) -> None:
    """Validate through a disposable snapshot; fail closed if impossible.

    The fallback is logged (never silent); the failure chain preserves the
    first SQLite error as ``__cause__``.
    """
    logger.warning(
        "schema validation via read-only connection failed for %s (%s); "
        "retrying against a disposable snapshot copy (the original database "
        "is never opened for writing)", path, original)
    try:
        snap = _snapshot_for_validation(path)
    except SchemaValidationUnavailable:
        raise  # already typed by the capture protocol; cause preserved
    except OSError as snap_exc:
        # Compatibility: a capture helper that fails with a plain OSError
        # (e.g., monkeypatched in tests) is converted fail-closed as well.
        raise _validation_unavailable(
            path,
            f"read-only inspection failed ({original}) and a disposable "
            f"snapshot could not be taken ({snap_exc}); refusing to fall "
            "back to a write-capable connection on the target database",
            original)
    try:
        conn = sqlite3.connect(snap, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            problems = _inspect_schema_problems(conn)
        finally:
            # Close performs WAL recovery/checkpoint on the SNAPSHOT only.
            conn.close()
    except sqlite3.Error as exc:
        raise SchemaValidationUnavailable(
            f"schema validation unavailable for {path}: neither a read-only "
            f"connection ({original}) nor a snapshot copy ({exc}) could be "
            "inspected; startup fails closed rather than opening a "
            "write-capable connection to the target database"
        ) from original
    finally:
        shutil.rmtree(os.path.dirname(snap), ignore_errors=True)
    if problems:
        raise SchemaValidationError(
            "offline migration required: incompatible schema ("
            + "; ".join(problems)
            + "); normal startup never repairs the schema")


def init_db(run_migrations: bool = False, create: bool | None = None):
    """Create/verify the schema (audit F-7, Remediation 4).

    Mode resolution:

    * ``create=True`` — full schema creation (DDL) plus the additive column
      consistency steps and the partial unique index. Used by tests on
      isolated temporary databases and by :func:`migrate_database`.
    * ``create=False`` — read-only schema validation only, on any path.
    * default (``create=None``) — convenience creation ONLY when the
      configured ``DB_PATH`` is NOT the production database path (this keeps
      temporary test databases convenient). On the production path normal
      startup validates read-only and never mutates schema or data.

    ``run_migrations=True`` forces the creation mode everywhere and additionally
    runs the deterministic ``event_uid`` backfill; it is an explicitly
    authorized operator action and must never be invoked by api.py, ui.py,
    or any import-time path.
    """
    if create is None:
        create = bool(run_migrations) or not _is_production_db_path()
    if not create:
        _validate_schema_at(DB_PATH)
        return
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    try:
        conn.executescript(_SCHEMA_DDL)
        # Backward-compatible additive schema consistency for databases that
        # already have events. No data is rewritten here.
        _ensure_column(conn, "vehicle_events", "event_uid", "event_uid TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_uid "
            "ON vehicle_events(event_uid) WHERE event_uid IS NOT NULL"
        )
        if run_migrations:
            # Explicitly authorized data migration (default: OFF at startup).
            _backfill_event_uids(conn)
        # Migrate existing detections table – safe to re-run on any database version
        _ensure_column(conn, "detections", "camera_id",   "camera_id INTEGER")
        _ensure_column(conn, "detections", "camera_name", "camera_name TEXT")
        # Phase 1 (M2, minimal): link legacy rows to the event that emitted them
        # (NULL for all legacy rows — no backfill, nothing breaks).
        _ensure_column(conn, "detections", "event_key",   "event_key TEXT")
        conn.commit()
    finally:
        conn.close()
    # Confirm the created/updated schema satisfies the persistence path.
    _validate_schema_at(DB_PATH)


def migrate_database() -> dict:
    """Explicit offline schema migration + backfill (operator action only).

    Performs the complete schema preparation (DDL, additive columns, partial
    unique index) AND the deterministic ``event_uid`` backfill in one
    authorized step. This is the ONLY entry point that may migrate a
    production database, and only after explicit owner authorization:

        1. Stop the backend (or ensure no writer holds the DB).
        2. Point ``db.DB_PATH`` at the target database file.
        3. Run ``python -m db migrate`` (or ``import db; db.migrate_database()``).
        4. Verify the returned ``remaining_null_event_uid`` is 0.

    Normal startup (api.py / ui.py) never calls this function.
    """
    init_db(run_migrations=True, create=True)
    # Trailing verification goes through the SAME connection mechanism the
    # migration itself used (R5 D-1 §3.4): a second strictly read-only
    # connection could fail on WAL states even though the migration fully
    # succeeded, which must never turn a successful migration into a failure.
    conn = get_conn()
    try:
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM vehicle_events WHERE event_uid IS NULL"
        ).fetchone()["n"]
    finally:
        conn.close()
    return {"db_path": DB_PATH, "remaining_null_event_uid": int(pending)}


def start_session(source_type, source_file=None):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO sessions (source_type, source_file, started_at, status) VALUES (?, ?, ?, 'running')",
        (source_type, source_file, datetime.now().isoformat()),
    )
    session_id = cur.lastrowid
    conn.commit()
    conn.close()
    return session_id


def end_session(session_id, total_frames, total_plates, unique_plates, status="done"):
    conn = get_conn()
    conn.execute(
        "UPDATE sessions SET ended_at=?, total_frames=?, total_plates=?, unique_plates=?, status=? WHERE id=?",
        (datetime.now().isoformat(), total_frames, total_plates, unique_plates, status, session_id),
    )
    conn.commit()
    conn.close()


def save_detection(session_id, source_type, plate_dtrb, plate_persian, confidence,
                   source_file=None, frame_number=0, frame_time=None,
                   camera_id=None, camera_name=None):
    """Persist a detection and run watchlist matching against it.

    The detection row is the primary committed action (Req 8.3, 8.4, 10.4): it
    is inserted and committed first, attributed to its originating
    ``session_id`` so it appears in live recent-history (Req 6.4). The
    ``plate_persian`` value supplied by callers is produced via
    ``format_plate_persian`` (Req 8.5).

    After the row is committed, the detection is matched against active
    watchlist entries and an alert is created per match (Req 12.4). Matching
    runs on the raw DTRB text (canonically normalized by the matcher), not the
    Persian display string. Alert creation is a separate concern isolated in a
    try/except so a matching failure can never corrupt the stored detection.

    Returns the new detection id.
    """
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO detections (session_id, timestamp, source_type, source_file, plate_dtrb, "
        "plate_persian, confidence, frame_number, frame_time, camera_id, camera_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, datetime.now().isoformat(), source_type, source_file, plate_dtrb,
         plate_persian, confidence, frame_number, frame_time, camera_id, camera_name),
    )
    detection_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Watchlist-matching hook (Req 12.4). Isolated so alert creation never
    # affects the already-committed detection record.
    try:
        _match_detection_against_watchlists(detection_id, plate_dtrb, plate_persian)
    except Exception:
        pass

    return detection_id


# ---------------------------------------------------------------------------
# Phase 1: durable vehicle-event persistence (identity-safe transaction)
# ---------------------------------------------------------------------------
_INSERT_EVENT_SQL = """
INSERT INTO vehicle_events (
    event_key, event_uid, track_id, camera_id, camera_name, session_id,
    source_type, source_file, first_seen, last_seen, duration_ms, frame_count,
    observation_count, plate_number, plate_norm, confidence, agreement_ratio,
    status, needs_review, finalize_reason, plate_valid, created_at, updated_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""

_UPDATE_EVENT_SQL = """
UPDATE vehicle_events SET
    last_seen = ?, duration_ms = ?, frame_count = ?, observation_count = ?,
    plate_number = ?, plate_norm = ?, confidence = ?, agreement_ratio = ?,
    status = ?, needs_review = ?, finalize_reason = ?, plate_valid = ?,
    updated_at = ?
WHERE id = ?
"""


class EventPersistenceError(RuntimeError):
    """Raised by :func:`upsert_vehicle_event` when persistence failed and the
    row is NOT durable (persist_failure). ``result`` carries the structured
    :class:`EventPersistResult`.
    """

    def __init__(self, message: str, result: "EventPersistResult") -> None:
        super().__init__(message)
        self.result = result


class EventIdentityConflict(EventPersistenceError):
    """Raised by :func:`upsert_vehicle_event` when an existing Event identity
    contradicts the incoming one (identity_conflict). The existing row is
    never overwritten; ``result`` carries the structured outcome.
    """


@dataclass(frozen=True)
class EventPersistResult:
    """Structured persistence outcome (approved M0-A contract)."""

    outcome: str                 # created | updated | identity_conflict | persist_failure
    event_row_id: int | None = None
    event_uid: str | None = None
    detail: str | None = None


def _metadata_conflict(row, event) -> str | None:
    """Return the first incompatible immutable identity field, if any."""
    for field in ("session_id", "camera_id", "source_type", "source_file"):
        if row[field] != getattr(event, field, None):
            return field
    return None


def _is_identity_integrity_error(exc: sqlite3.IntegrityError) -> bool:
    """True only for uniqueness failures on the two Event identity columns.

    Other integrity errors (NOT NULL, foreign keys, unrelated constraints)
    are persistence failures, not evidence that an Event identity conflicts.
    """
    message = str(exc).lower()
    return ("unique constraint failed" in message
            and ("event_key" in message or "event_uid" in message))


def persist_event(event) -> EventPersistResult:
    """Persist one event atomically with identity-conflict rejection.

    ``BEGIN IMMEDIATE`` serializes writers before the identity read, so the
    created/updated/conflict decision cannot race. Same key + same uid updates;
    same key or uid with a different identity returns ``identity_conflict`` and
    never mutates the existing row.
    """
    event_uid = getattr(event, "event_uid", None)
    if not event_uid:
        event_uid = str(uuid.uuid4())
        event.event_uid = event_uid

    now = datetime.now().isoformat()
    conn = None
    try:
        conn = get_conn()
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        by_key = conn.execute(
            "SELECT * FROM vehicle_events WHERE event_key = ?", (event.event_key,)
        ).fetchone()
        by_uid = conn.execute(
            "SELECT * FROM vehicle_events WHERE event_uid = ?", (event_uid,)
        ).fetchone()

        if by_key is not None and by_key["event_uid"] != event_uid:
            conn.rollback()
            return EventPersistResult("identity_conflict", by_key["id"], event_uid,
                                      "event_key belongs to a different event_uid")
        if by_uid is not None and by_uid["event_key"] != event.event_key:
            conn.rollback()
            return EventPersistResult("identity_conflict", by_uid["id"], event_uid,
                                      "event_uid belongs to a different event_key")

        if by_key is None and by_uid is None:
            cur = conn.execute(_INSERT_EVENT_SQL, (
                event.event_key, event_uid, event.track_id, event.camera_id,
                event.camera_name, event.session_id, event.source_type,
                event.source_file, event.first_seen, event.last_seen,
                event.duration_ms, event.frame_count, event.observation_count,
                event.plate_number, event.plate_norm, event.confidence,
                event.agreement_ratio, event.status,
                1 if event.needs_review else 0,
                getattr(event, "finalize_reason", None),
                1 if event.plate_valid else 0, now, now,
            ))
            row_id = int(cur.lastrowid)
            conn.commit()
            return EventPersistResult("created", row_id, event_uid)

        row = by_key if by_key is not None else by_uid
        conflict = _metadata_conflict(row, event)
        if conflict is not None:
            conn.rollback()
            return EventPersistResult("identity_conflict", row["id"], event_uid,
                                      f"immutable metadata mismatch: {conflict}")

        conn.execute(_UPDATE_EVENT_SQL, (
            event.last_seen, event.duration_ms, event.frame_count,
            event.observation_count, event.plate_number, event.plate_norm,
            event.confidence, event.agreement_ratio, event.status,
            1 if event.needs_review else 0,
            getattr(event, "finalize_reason", None),
            1 if event.plate_valid else 0, now, row["id"],
        ))
        conn.commit()
        return EventPersistResult("updated", int(row["id"]), event_uid)
    except sqlite3.IntegrityError as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        if _is_identity_integrity_error(exc):
            return EventPersistResult("identity_conflict", None, event_uid, str(exc))
        return EventPersistResult("persist_failure", None, event_uid, str(exc))
    except Exception as exc:  # surfaced as a result, never reported as success
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return EventPersistResult("persist_failure", None, event_uid, str(exc))
    finally:
        if conn is not None:
            conn.close()


def upsert_vehicle_event(event) -> tuple[int, bool]:
    """Backward-compatible wrapper around :func:`persist_event`.

    Compatibility contract (audit F-10): ``(row_id, created)`` is returned
    ONLY for the ordinary outcomes ``created``/``updated``. Exceptional
    outcomes are raised explicitly instead of being silently collapsed into
    ``(0, False)``:

    * ``identity_conflict`` → :class:`EventIdentityConflict`
    * ``persist_failure``   → :class:`EventPersistenceError`

    No caller inside this repository relies on the old silent collapse (the
    production pipeline uses :func:`persist_event` directly); external
    callers that prefer the structured result should call
    :func:`persist_event` instead.
    """
    result = persist_event(event)
    if result.outcome == "identity_conflict":
        raise EventIdentityConflict(result.detail or "identity conflict", result)
    if result.outcome == "persist_failure":
        raise EventPersistenceError(result.detail or "persist failure", result)
    return (result.event_row_id or 0, result.outcome == "created")


def get_vehicle_event_stats() -> dict:
    """Bounded observability totals over the vehicle_events table."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status = 'confirmed' THEN 1 ELSE 0 END) AS confirmed, "
            "SUM(CASE WHEN needs_review = 1 THEN 1 ELSE 0 END) AS needs_review "
            "FROM vehicle_events"
        ).fetchone()
        return {
            "total_events": int(row["total"] or 0),
            "confirmed_events": int(row["confirmed"] or 0),
            "needs_review_events": int(row["needs_review"] or 0),
        }
    finally:
        conn.close()


def _match_detection_against_watchlists(detection_id, plate_dtrb, plate_persian):
    """Match a freshly stored detection against active watchlist entries.

    Uses a lazy import of ``watchlist.matching`` to avoid the circular import
    that would result from importing it at module load (matching imports db).
    The detection's raw DTRB text is matched (the matcher canonicalizes it);
    one alert is created per matching active entry (Req 12.4, 12.5, 12.7).
    """
    from watchlist import matching

    active_entries = list_active_entries()
    matches = matching.find_matches(plate_dtrb, active_entries)
    if not matches:
        return
    detection = {
        "id": detection_id,
        "plate_dtrb": plate_dtrb,
        "plate_persian": plate_persian,
    }
    for entry in matches:
        matching.create_alert(detection, entry)


def get_stats():
    conn = get_conn()
    stats = {}
    row = conn.execute("SELECT COUNT(*) as total, COUNT(DISTINCT plate_dtrb) as unique_p, ROUND(AVG(confidence), 4) as avg_conf FROM detections").fetchone()
    stats["total_detections"] = row["total"]
    stats["unique_plates"] = row["unique_p"]
    stats["avg_confidence"] = row["avg_conf"]

    row = conn.execute("SELECT COUNT(*) as total FROM sessions").fetchone()
    stats["total_sessions"] = row["total"]

    row = conn.execute("SELECT COUNT(*) FROM sessions WHERE datetime(started_at) >= datetime('now', '-7 days')").fetchone()
    stats["sessions_7d"] = row[0]

    row = conn.execute("SELECT COUNT(*) FROM detections WHERE datetime(timestamp) >= datetime('now', '-7 days')").fetchone()
    stats["detections_7d"] = row[0]

    conn.close()
    return stats


def get_recent_detections(limit=20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, timestamp, source_type, plate_dtrb, plate_persian, confidence, source_file FROM detections ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_detections(limit=500, offset=0, source_type=None, search=None):
    conn = get_conn()
    params = []
    where = []
    if source_type and source_type != "all":
        where.append("source_type = ?")
        params.append(source_type)
    if search:
        where.append("(plate_dtrb LIKE ? OR plate_persian LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where_clause = " AND ".join(where) if where else "1"
    rows = conn.execute(
        f"SELECT id, timestamp, source_type, plate_dtrb, plate_persian, confidence, source_file FROM detections WHERE {where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    total = conn.execute(
        f"SELECT COUNT(*) FROM detections WHERE {where_clause}", params,
    ).fetchone()[0]
    conn.close()
    return [dict(r) for r in rows], total


def get_detections_timeline(days=7):
    """Per-day detection counts over the last *days* days.

    Returns a list of ``{"dt": "YYYY-MM-DD", "cnt": int}`` entries ordered
    oldest-to-newest. The series is COMPLETE across the requested range: every
    day in the requested window (today and the preceding ``days - 1`` days)
    appears as a bucket, with a count of 0 for days that have no detections.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT DATE(timestamp) as dt, COUNT(*) as cnt FROM detections "
        "WHERE datetime(timestamp) >= datetime('now', ? ) "
        "GROUP BY DATE(timestamp)",
        (f"-{int(days)} days",),
    ).fetchall()
    conn.close()

    # Grouped counts keyed by ISO date for days that actually have detections.
    counts = {r["dt"]: r["cnt"] for r in rows}

    # Build the full date series so days with zero detections still appear.
    today = datetime.now().date()
    series = []
    for offset in range(int(days) - 1, -1, -1):  # oldest-to-newest
        day = (today - timedelta(days=offset)).isoformat()
        series.append({"dt": day, "cnt": counts.get(day, 0)})
    return series


def get_letter_frequency():
    conn = get_conn()
    rows = conn.execute(
        "SELECT plate_persian, COUNT(*) as cnt FROM detections WHERE plate_persian NOT NULL GROUP BY plate_persian ORDER BY cnt DESC LIMIT 20",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_source_distribution():
    conn = get_conn()
    rows = conn.execute(
        "SELECT source_type, COUNT(*) as cnt FROM detections GROUP BY source_type",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_confidence_distribution():
    conn = get_conn()
    rows = conn.execute(
        "SELECT CAST(ROUND(confidence, 1) AS REAL) as bin, COUNT(*) as cnt FROM detections GROUP BY bin ORDER BY bin",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sessions_history(limit=20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, source_type, source_file, started_at, ended_at, total_frames, total_plates, unique_plates, status FROM sessions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Camera CRUD helpers
# ---------------------------------------------------------------------------

def create_camera(name: str, url: str, skip_frames: int = 15) -> dict:
    conn = get_conn()
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO cameras (name, url, skip_frames, created_at) VALUES (?, ?, ?, ?)",
        (name, url, skip_frames, now),
    )
    camera_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"id": camera_id, "name": name, "url": url, "skip_frames": skip_frames, "created_at": now}


def list_cameras() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, url, skip_frames, created_at, updated_at FROM cameras ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_camera(camera_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT id, name, url, skip_frames, created_at, updated_at FROM cameras WHERE id = ?",
        (camera_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_camera(camera_id: int, name: str | None = None, url: str | None = None, skip_frames: int | None = None) -> dict | None:
    conn = get_conn()
    fields = []
    params = []
    if name is not None:
        fields.append("name = ?")
        params.append(name)
    if url is not None:
        fields.append("url = ?")
        params.append(url)
    if skip_frames is not None:
        fields.append("skip_frames = ?")
        params.append(skip_frames)
    if not fields:
        conn.close()
        return get_camera(camera_id)
    fields.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    params.append(camera_id)
    conn.execute(f"UPDATE cameras SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return get_camera(camera_id)


def delete_camera(camera_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ---------------------------------------------------------------------------
# App config helpers
# ---------------------------------------------------------------------------

def get_concurrency_limit() -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT value FROM app_config WHERE key = 'concurrency_limit'"
    ).fetchone()
    conn.close()
    return int(row["value"]) if row else 4


def set_concurrency_limit(value: int) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO app_config (key, value) VALUES ('concurrency_limit', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(value),),
    )
    conn.commit()
    conn.close()


def get_retention_days() -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT value FROM app_config WHERE key = 'retention_days'"
    ).fetchone()
    conn.close()
    return int(row["value"]) if row else 90


def set_retention_days(value: int) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO app_config (key, value) VALUES ('retention_days', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(value),),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Authentication helpers (revocation set, user lookup, server secret)
# ---------------------------------------------------------------------------

def add_revoked_token(jti: str, exp: int) -> None:
    """Add a token id to the revocation set (Req 1.7). Idempotent on jti."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO revoked_tokens (jti, exp) VALUES (?, ?) "
        "ON CONFLICT(jti) DO UPDATE SET exp = excluded.exp",
        (jti, int(exp)),
    )
    conn.commit()
    conn.close()


def is_token_revoked(jti: str) -> bool:
    """Return True if the token id is present in the revocation set (Req 1.7)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,)
    ).fetchone()
    conn.close()
    return row is not None


def purge_expired_revoked_tokens(now: int) -> int:
    """Remove revocation entries whose tokens have already expired.

    Keeps the revocation set bounded; safe to call periodically. Returns the
    number of rows removed.
    """
    conn = get_conn()
    cur = conn.execute("DELETE FROM revoked_tokens WHERE exp <= ?", (int(now),))
    removed = cur.rowcount
    conn.commit()
    conn.close()
    return removed


def get_user_by_id(user_id: int) -> dict | None:
    """Load a user account by id (used for the account-enabled check, Req 1.8)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, username, password_hash, role, disabled, created_at "
        "FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def count_users() -> int:
    """Return the number of user accounts (used to detect first-run, Req 1.9)."""
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    conn.close()
    return int(row[0])


def is_user_enabled(user_id: int) -> bool:
    """Return True only if the user exists and is not disabled (Req 1.8)."""
    user = get_user_by_id(user_id)
    return bool(user) and not bool(user["disabled"])


def get_or_create_session_secret() -> str:
    """Return the persisted HMAC server secret, generating one on first use.

    The secret is stored under ``app_config`` so issued session tokens remain
    valid across restarts. An explicit ``ANPR_SECRET_KEY`` environment variable
    always takes precedence and is resolved by ``auth.security``.
    """
    import secrets as _secrets

    conn = get_conn()
    row = conn.execute(
        "SELECT value FROM app_config WHERE key = 'session_secret'"
    ).fetchone()
    if row:
        conn.close()
        return row["value"]
    secret = _secrets.token_urlsafe(48)
    conn.execute(
        "INSERT INTO app_config (key, value) VALUES ('session_secret', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (secret,),
    )
    conn.commit()
    conn.close()
    return secret


# ---------------------------------------------------------------------------
# User management CRUD helpers (Req 2.8, 2.9, 2.10)
# ---------------------------------------------------------------------------

def _user_public(row) -> dict:
    """Map a users row to the public view shape (excludes password_hash)."""
    return {
        "id": int(row["id"]),
        "username": str(row["username"]),
        "role": str(row["role"]),
        "disabled": bool(row["disabled"]),
        "created_at": str(row["created_at"]),
    }


def get_user_by_username(username: str) -> dict | None:
    """Load a user account by username, or None when absent."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, username, password_hash, role, disabled, created_at "
        "FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(username: str, password_hash: str, role: str) -> dict:
    """Insert a new user account and return its public view (Req 2.8).

    Raises ``sqlite3.IntegrityError`` if the username already exists (the
    ``username`` column is UNIQUE), so callers can map that to a conflict.
    """
    conn = get_conn()
    now = datetime.now().isoformat()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, disabled, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (username, password_hash, role, now),
        )
        user_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return {
        "id": int(user_id),
        "username": username,
        "role": role,
        "disabled": False,
        "created_at": now,
    }


def list_users() -> list:
    """Return all user accounts (public view), ordered by id."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, username, password_hash, role, disabled, created_at "
        "FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return [_user_public(r) for r in rows]


def update_user(
    user_id: int,
    *,
    role: str | None = None,
    disabled: bool | None = None,
    password_hash: str | None = None,
) -> dict | None:
    """Update mutable fields of a user account and return its public view.

    Only the provided fields are changed. Returns ``None`` if no user with
    ``user_id`` exists.
    """
    if get_user_by_id(user_id) is None:
        return None
    fields = []
    params = []
    if role is not None:
        fields.append("role = ?")
        params.append(role)
    if disabled is not None:
        fields.append("disabled = ?")
        params.append(1 if disabled else 0)
    if password_hash is not None:
        fields.append("password_hash = ?")
        params.append(password_hash)
    if fields:
        params.append(user_id)
        conn = get_conn()
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
        conn.close()
    updated = get_user_by_id(user_id)
    return _user_public(updated) if updated else None


def delete_user(user_id: int) -> bool:
    """Delete a user account. Returns True when a row was removed."""
    conn = get_conn()
    cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def count_enabled_admins() -> int:
    """Return the number of enabled (not disabled) Admin accounts (Req 2.10)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'Admin' AND disabled = 0"
    ).fetchone()
    conn.close()
    return int(row[0])


# ---------------------------------------------------------------------------
# License helpers (Req 3.1, 3.2, 3.5)
# ---------------------------------------------------------------------------

def get_active_license() -> dict | None:
    """Return the most recent active license record, or ``None`` if none exists."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, key, active, expiry, camera_limit, activated_at "
        "FROM licenses WHERE active = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def deactivate_licenses() -> int:
    """Mark every license record inactive. Returns the number of rows changed.

    Called before storing a newly activated license so at most one license is
    ever active (Req 3.1).
    """
    conn = get_conn()
    cur = conn.execute("UPDATE licenses SET active = 0 WHERE active = 1")
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed


def insert_active_license(key: str, expiry: str, camera_limit: int) -> dict:
    """Insert a new active license row and return it (Req 3.1)."""
    conn = get_conn()
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO licenses (key, active, expiry, camera_limit, activated_at) "
        "VALUES (?, 1, ?, ?, ?)",
        (key, expiry, camera_limit, now),
    )
    license_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": license_id,
        "key": key,
        "active": 1,
        "expiry": expiry,
        "camera_limit": camera_limit,
        "activated_at": now,
    }


def count_cameras() -> int:
    """Return the number of configured cameras (Req 3.5)."""
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) FROM cameras").fetchone()
    conn.close()
    return int(row[0])


# ---------------------------------------------------------------------------
# Watchlist alert helpers (Req 12.4, 12.6)
# ---------------------------------------------------------------------------

def create_alert(detection_id: int, entry_id: int, plate_value: str) -> dict:
    """Insert an alert referencing a detection and a matched watchlist entry (Req 12.4).

    Returns the persisted alert row as a dict.
    """
    conn = get_conn()
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO alerts (detection_id, entry_id, plate_value, created_at) "
        "VALUES (?, ?, ?, ?)",
        (detection_id, entry_id, plate_value, now),
    )
    alert_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": int(alert_id),
        "detection_id": int(detection_id),
        "entry_id": int(entry_id),
        "plate_value": plate_value,
        "created_at": now,
    }


# ---------------------------------------------------------------------------
# Watchlist & alert helpers (Req 12.1, 12.2, 12.3, 12.6)
# ---------------------------------------------------------------------------

def _watchlist_entry_public(row) -> dict:
    """Map a watchlist_entries row to the WatchlistEntryView shape.

    The raw plate value supplied at creation (``plate_raw``) is exposed as
    ``plate_value``; the canonical ``plate_norm`` is kept internal for matching.
    """
    return {
        "id": int(row["id"]),
        "watchlist_id": int(row["watchlist_id"]),
        "plate_value": str(row["plate_raw"]),
        "label": row["label"],
        "reason": row["reason"],
        "created_at": str(row["created_at"]),
    }


def create_watchlist(name: str, list_type: str) -> dict:
    """Insert a new watchlist and return it with an empty entry list (Req 12.1)."""
    conn = get_conn()
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO watchlists (name, list_type, created_at) VALUES (?, ?, ?)",
        (name, list_type, now),
    )
    watchlist_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": int(watchlist_id),
        "name": name,
        "list_type": list_type,
        "created_at": now,
        "entries": [],
    }


def get_watchlist(watchlist_id: int) -> dict | None:
    """Return a single watchlist (without entries), or None when absent."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, name, list_type, created_at FROM watchlists WHERE id = ?",
        (watchlist_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_watchlists() -> list:
    """Return all watchlists, each with their entries (Req 12.1, 12.2)."""
    conn = get_conn()
    wl_rows = conn.execute(
        "SELECT id, name, list_type, created_at FROM watchlists ORDER BY id"
    ).fetchall()
    entry_rows = conn.execute(
        "SELECT id, watchlist_id, plate_raw, plate_norm, label, reason, created_at "
        "FROM watchlist_entries ORDER BY id"
    ).fetchall()
    conn.close()

    entries_by_wl: dict[int, list] = {}
    for r in entry_rows:
        entries_by_wl.setdefault(int(r["watchlist_id"]), []).append(
            _watchlist_entry_public(r)
        )

    watchlists = []
    for wl in wl_rows:
        watchlists.append(
            {
                "id": int(wl["id"]),
                "name": str(wl["name"]),
                "list_type": str(wl["list_type"]),
                "created_at": str(wl["created_at"]),
                "entries": entries_by_wl.get(int(wl["id"]), []),
            }
        )
    return watchlists


def add_watchlist_entry(
    watchlist_id: int,
    plate_raw: str,
    plate_norm: str,
    label: str | None = None,
    reason: str | None = None,
) -> dict:
    """Insert an entry into a watchlist and return its public view (Req 12.2).

    Stores both the raw plate value as supplied and the canonical ``plate_norm``
    used for matching (Req 12.7).
    """
    conn = get_conn()
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO watchlist_entries "
        "(watchlist_id, plate_raw, plate_norm, label, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (watchlist_id, plate_raw, plate_norm, label, reason, now),
    )
    entry_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": int(entry_id),
        "watchlist_id": int(watchlist_id),
        "plate_value": plate_raw,
        "label": label,
        "reason": reason,
        "created_at": now,
    }


def remove_watchlist_entry(entry_id: int) -> bool:
    """Delete a watchlist entry. Returns True when a row was removed (Req 12.3)."""
    conn = get_conn()
    cur = conn.execute("DELETE FROM watchlist_entries WHERE id = ?", (entry_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_watchlist_entry(entry_id: int) -> dict | None:
    """Return a single watchlist entry (public view), or None when absent."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, watchlist_id, plate_raw, plate_norm, label, reason, created_at "
        "FROM watchlist_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    conn.close()
    return _watchlist_entry_public(row) if row else None


def list_active_entries() -> list:
    """Return all watchlist entries available for matching (Req 12.5).

    Entries are removed by deletion, so every persisted entry is active. Each
    row includes ``plate_norm`` so the matcher can compare canonical forms.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, watchlist_id, plate_raw, plate_norm, label, reason, created_at "
        "FROM watchlist_entries ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_alerts(limit: int | None = None) -> list:
    """Return alerts ordered most-recent-first (Req 12.6).

    Ordered by ``created_at`` then ``id`` descending so ties (same timestamp)
    still resolve to insertion order, newest first. When ``limit`` is provided
    and positive, at most that many alerts are returned.
    """
    conn = get_conn()
    sql = (
        "SELECT id, detection_id, entry_id, plate_value, created_at "
        "FROM alerts ORDER BY created_at DESC, id DESC"
    )
    if limit is not None and limit > 0:
        rows = conn.execute(sql + " LIMIT ?", (int(limit),)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_alert(detection_id: int, entry_id: int, plate_value: str) -> dict:
    """Insert an alert referencing a detection and watchlist entry (Req 12.4)."""
    conn = get_conn()
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO alerts (detection_id, entry_id, plate_value, created_at) "
        "VALUES (?, ?, ?, ?)",
        (detection_id, entry_id, plate_value, now),
    )
    alert_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": int(alert_id),
        "detection_id": int(detection_id),
        "entry_id": int(entry_id),
        "plate_value": plate_value,
        "created_at": now,
    }


if __name__ == "__main__":  # operator entry point; never invoked by app startup
    import argparse

    parser = argparse.ArgumentParser(
        description="ALPR database maintenance (audit F-7)")
    parser.add_argument(
        "command", choices=("migrate", "validate"),
        help="migrate: explicit offline schema migration + backfill (requires "
             "owner authorization; point db.DB_PATH at the target first). "
             "validate: read-only schema validation, no mutation.")
    args = parser.parse_args()
    if args.command == "migrate":
        print(migrate_database())
    else:
        init_db(create=False)
        print(f"schema OK: {DB_PATH}")
