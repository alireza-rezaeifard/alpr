import sqlite3
import os
from datetime import datetime

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
        CREATE INDEX IF NOT EXISTS idx_detections_ts ON detections(timestamp);
        CREATE INDEX IF NOT EXISTS idx_detections_session ON detections(session_id);
    """)
    # Migrate existing detections table – safe to re-run on any database version
    _ensure_column(conn, "detections", "camera_id",   "camera_id INTEGER")
    _ensure_column(conn, "detections", "camera_name", "camera_name TEXT")
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
    conn = get_conn()
    conn.execute(
        "INSERT INTO detections (session_id, timestamp, source_type, source_file, plate_dtrb, "
        "plate_persian, confidence, frame_number, frame_time, camera_id, camera_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, datetime.now().isoformat(), source_type, source_file, plate_dtrb,
         plate_persian, confidence, frame_number, frame_time, camera_id, camera_name),
    )
    conn.commit()
    conn.close()


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
    conn = get_conn()
    rows = conn.execute(
        f"SELECT DATE(timestamp) as dt, COUNT(*) as cnt FROM detections WHERE datetime(timestamp) >= datetime('now', '-{days} days') GROUP BY DATE(timestamp) ORDER BY dt",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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
