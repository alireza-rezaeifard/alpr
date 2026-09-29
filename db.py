import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "database", "plpr.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_column(conn, table, column, ddl):
    """Add a column to *table* if it does not already exist (safe to re-run)."""
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    conn.executescript("""
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
    """)
    # Migrate existing detections table – safe to re-run on any database version
    _ensure_column(conn, "detections", "camera_id",   "camera_id INTEGER")
    _ensure_column(conn, "detections", "camera_name", "camera_name TEXT")
    # Phase 1 (M2, minimal): link legacy rows to the event that emitted them
    # (NULL for all legacy rows — no backfill, nothing breaks).
    _ensure_column(conn, "detections", "event_key",   "event_key TEXT")
    conn.commit()
    conn.close()


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
# Phase 1: durable vehicle-event persistence (idempotent upsert boundary)
# ---------------------------------------------------------------------------
_UPSERT_EVENT_SQL = """
INSERT INTO vehicle_events (
    event_key, track_id, camera_id, camera_name, session_id, source_type,
    source_file, first_seen, last_seen, duration_ms, frame_count,
    observation_count, plate_number, plate_norm, confidence, agreement_ratio,
    status, needs_review, finalize_reason, plate_valid, created_at, updated_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(event_key) DO UPDATE SET
    last_seen = excluded.last_seen,
    duration_ms = excluded.duration_ms,
    frame_count = excluded.frame_count,
    observation_count = excluded.observation_count,
    plate_number = excluded.plate_number,
    plate_norm = excluded.plate_norm,
    confidence = excluded.confidence,
    agreement_ratio = excluded.agreement_ratio,
    status = excluded.status,
    needs_review = excluded.needs_review,
    finalize_reason = excluded.finalize_reason,
    updated_at = excluded.updated_at
"""


def upsert_vehicle_event(event) -> tuple[int, bool]:
    """Durably persist one finalized vehicle event, idempotently.

    ``event`` is a ``pipeline.types.VehicleEvent`` (duck-typed: only the
    attributes written to the table are read — keeps db.py decoupled from the
    pipeline package).

    The UNIQUE constraint on ``vehicle_events.event_key`` is the persistence
    boundary: repeated finalization of the same track — including after a
    process restart — updates the existing row instead of creating one.

    Returns ``(event_row_id, created)`` where ``created`` is True only when a
    new row was inserted (False when an existing event was updated/suppressed).
    """
    now = datetime.now().isoformat()
    conn = get_conn()
    try:
        # Existence check first (fast path); the UNIQUE constraint plus the
        # IntegrityError handler below still covers concurrent races.
        existing = conn.execute(
            "SELECT id FROM vehicle_events WHERE event_key = ?", (event.event_key,)
        ).fetchone()
        conn.execute(
            _UPSERT_EVENT_SQL,
            (
                event.event_key,
                event.track_id,
                event.camera_id,
                event.camera_name,
                event.session_id,
                event.source_type,
                event.source_file,
                event.first_seen,
                event.last_seen,
                event.duration_ms,
                event.frame_count,
                event.observation_count,
                event.plate_number,
                event.plate_norm,
                event.confidence,
                event.agreement_ratio,
                event.status,
                1 if event.needs_review else 0,
                getattr(event, "finalize_reason", None),
                1 if event.plate_valid else 0,
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM vehicle_events WHERE event_key = ?", (event.event_key,)
        ).fetchone()
        row_id = int(row["id"]) if row else 0
        return row_id, existing is None
    except sqlite3.IntegrityError:
        # Raced with another writer on the same event_key: the row exists, so
        # this call is a suppressed duplicate at the persistence boundary.
        conn.rollback()
        row = conn.execute(
            "SELECT id FROM vehicle_events WHERE event_key = ?", (event.event_key,)
        ).fetchone()
        return (int(row["id"]), False) if row else (0, False)
    finally:
        conn.close()


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
