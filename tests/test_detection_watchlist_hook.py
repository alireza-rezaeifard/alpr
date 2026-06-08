"""
test_detection_watchlist_hook.py
Unit tests for the watchlist + Persian-format hook wired into the detection
save point (`db.save_detection`).

Verifies:
- A stored detection matching an active watchlist entry creates exactly one
  referencing alert (Req 12.4).
- Matching is performed on the raw DTRB text canonically (Persian-digit /
  separator variants in the entry still match) (Req 12.5, 12.7).
- A detection with no matching entry creates no alerts.
- Detections are stored under their originating session and appear in live
  recent-history (Req 8.3, 10.4, 6.4).
- The returned detection id references the inserted row.

Feature: anpr-system-redesign
Requirements: 8.3, 8.5, 10.4, 6.4, 12.4
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Point db at a fresh temp SQLite file initialized with the real schema."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "detection_hook_test.db"))
    db.init_db()
    yield db


def test_match_creates_exactly_one_referencing_alert(fresh_db):
    wl = db.create_watchlist("blacklist", "block")
    entry = db.add_watchlist_entry(wl["id"], "12b34511", "12b34511", label="wanted")

    sid = db.start_session("image", "upload.jpg")
    det_id = db.save_detection(sid, "image", "12b34511", "۱۲ ب ۳۴۵-۱۱", 0.95, "upload.jpg")

    alerts = db.list_alerts()
    assert len(alerts) == 1
    assert alerts[0]["detection_id"] == det_id
    assert alerts[0]["entry_id"] == entry["id"]


def test_match_is_canonical_across_digit_scripts_and_separators(fresh_db):
    wl = db.create_watchlist("blacklist", "block")
    # Entry stored with separators and Persian digits in the raw value; the
    # matcher must canonicalize both sides before comparing.
    db.add_watchlist_entry(wl["id"], "۱۲-ب-۳۴۵-۱۱", "12b34511")

    sid = db.start_session("rtsp", "rtsp://cam")
    db.save_detection(sid, "rtsp", "12b34511", "۱۲ ب ۳۴۵-۱۱", 0.9, "rtsp://cam")

    assert len(db.list_alerts()) == 1


def test_no_match_creates_no_alert(fresh_db):
    wl = db.create_watchlist("blacklist", "block")
    db.add_watchlist_entry(wl["id"], "99z99999", "99z99999")

    sid = db.start_session("video", "clip.mp4")
    db.save_detection(sid, "video", "12b34511", "۱۲ ب ۳۴۵-۱۱", 0.8, "clip.mp4")

    assert db.list_alerts() == []


def test_detection_persisted_under_session_and_in_recent_history(fresh_db):
    sid = db.start_session("image", "upload.jpg")
    det_id = db.save_detection(sid, "image", "12b34511", "۱۲ ب ۳۴۵-۱۱", 0.95, "upload.jpg")

    conn = db.get_conn()
    row = conn.execute(
        "SELECT session_id, plate_persian FROM detections WHERE id = ?", (det_id,)
    ).fetchone()
    conn.close()
    assert row["session_id"] == sid
    assert row["plate_persian"] == "۱۲ ب ۳۴۵-۱۱"

    recent = db.get_recent_detections(limit=10)
    assert any(d["id"] == det_id for d in recent)


def test_alert_creation_failure_does_not_break_persistence(fresh_db, monkeypatch):
    wl = db.create_watchlist("blacklist", "block")
    db.add_watchlist_entry(wl["id"], "12b34511", "12b34511")

    # Force the matching hook to raise; the detection must still persist.
    import watchlist.matching as matching

    def boom(*a, **k):
        raise RuntimeError("matching exploded")

    monkeypatch.setattr(matching, "find_matches", boom)

    sid = db.start_session("image", "upload.jpg")
    det_id = db.save_detection(sid, "image", "12b34511", "۱۲ ب ۳۴۵-۱۱", 0.95, "upload.jpg")

    conn = db.get_conn()
    cnt = conn.execute("SELECT COUNT(*) FROM detections WHERE id = ?", (det_id,)).fetchone()[0]
    conn.close()
    assert cnt == 1
    assert db.list_alerts() == []
