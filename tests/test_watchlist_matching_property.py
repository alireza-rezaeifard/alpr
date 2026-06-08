"""
Property-based test for match-on-detection alert creation (task 13.5).

Feature: anpr-system-redesign, Property 20

Property 20: Detections matching an active watchlist entry raise exactly one
    referencing alert.
    For any detection plate value and watchlist entry that are equal after
    canonical normalization (in any digit script and with any separator
    spacing), saving the detection creates EXACTLY ONE alert that references
    both the detection and the matched entry. A detection whose plate matches
    no active entry raises no alert. An entry that has been deleted is inactive
    and never produces an alert, even for a plate that would otherwise match.

Validates: Requirements 12.4, 12.5, 12.7

Mechanism under test:
    * ``watchlist.matching.normalize_for_match`` canonicalizes a plate value
      (Persian/Arabic -> ASCII digits, separator stripping) (Req 12.7).
    * ``watchlist.matching.find_matches`` returns the active entries whose
      normalized plate equals the detection's normalized plate (Req 12.5, 12.7).
    * ``watchlist.matching.create_alert`` persists an alert referencing the
      detection and the entry (Req 12.4).
    * ``db.save_detection`` runs the matching hook after committing a detection
      and creates one alert per matching active entry (Req 12.4).

The hook + helpers are exercised end-to-end against a temporary SQLite database
so the behaviour is tested against real persistence (no mocks). Watchlist
entries are removed by deletion, so a "deleted" entry simply no longer exists
in ``list_active_entries`` and therefore can never match.
"""
from __future__ import annotations

import os
import sys

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Ensure the project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from watchlist import matching, service


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Point db at a fresh temp SQLite file initialized with the real schema."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "watchlist_matching_test.db"))
    db.init_db()
    yield db


def _reset_tables():
    """Clear watchlist/detection/alert tables so each example starts clean."""
    conn = db.get_conn()
    conn.execute("DELETE FROM alerts")
    conn.execute("DELETE FROM watchlist_entries")
    conn.execute("DELETE FROM watchlists")
    conn.execute("DELETE FROM detections")
    conn.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------
# A canonical "core" plate uses only ASCII digits and a few letters. Letters are
# never altered by normalization and separators are never present in the core,
# so ``normalize_for_match(core) == core`` by construction.
CORE_ALPHABET = "0123456789abjdwsAB"

# Each ASCII digit can be rendered in ASCII, Persian, or Arabic-Indic script;
# all three forms normalize back to the same ASCII digit (Req 12.7).
_DIGIT_VARIANTS = {
    "0": ["0", "\u06f0", "\u0660"],
    "1": ["1", "\u06f1", "\u0661"],
    "2": ["2", "\u06f2", "\u0662"],
    "3": ["3", "\u06f3", "\u0663"],
    "4": ["4", "\u06f4", "\u0664"],
    "5": ["5", "\u06f5", "\u0665"],
    "6": ["6", "\u06f6", "\u0666"],
    "7": ["7", "\u06f7", "\u0667"],
    "8": ["8", "\u06f8", "\u0668"],
    "9": ["9", "\u06f9", "\u0669"],
}

# Separators are stripped by normalization (spaces, dashes, underscores), so
# inserting any of them between characters does not change the canonical form.
_SEPARATORS = ["", " ", "-", "_", "  "]

core_plates = st.text(alphabet=CORE_ALPHABET, min_size=1, max_size=8)


@st.composite
def _variant_of(draw, core: str) -> str:
    """Render a script/separator variant of ``core`` that normalizes back to it.

    Digits are randomly rendered in ASCII/Persian/Arabic script and arbitrary
    separators are interleaved between (and around) the characters. The result
    satisfies ``normalize_for_match(result) == core``.
    """
    chars = []
    for ch in core:
        if ch in _DIGIT_VARIANTS:
            chars.append(draw(st.sampled_from(_DIGIT_VARIANTS[ch])))
        else:
            chars.append(ch)
    seps = [draw(st.sampled_from(_SEPARATORS)) for _ in range(len(chars) + 1)]
    result = seps[0]
    for ch, sep in zip(chars, seps[1:]):
        result += ch + sep
    return result


@st.composite
def matching_scenario(draw):
    """Generate a matching core plus equivalent detection/entry variants and noise.

    Returns ``(core, det_variant, entry_variant, other_cores)`` where
    ``det_variant`` and ``entry_variant`` both normalize to ``core`` and every
    value in ``other_cores`` normalizes to something different from ``core``.
    """
    core = draw(core_plates)
    det_variant = draw(_variant_of(core))
    entry_variant = draw(_variant_of(core))
    raw_others = draw(st.lists(core_plates, min_size=0, max_size=5))
    # Non-matching cores must normalize to a value distinct from the match core.
    others = [
        c for c in raw_others if matching.normalize_for_match(c) != core
    ]
    return core, det_variant, entry_variant, others


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------
@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(scenario=matching_scenario())
def test_matching_detection_raises_exactly_one_referencing_alert(fresh_db, scenario):
    """A matching detection creates exactly one alert referencing both (Req 12.4, 12.7)."""
    core, det_variant, entry_variant, others = scenario
    _reset_tables()

    wl = service.create_watchlist("list", "blacklist")

    # The single matching entry (digit-script / separator variant of the core).
    matching_entry = service.add_entry(wl["id"], entry_variant, label="wanted")

    # Noise entries that must NOT match (distinct normalized forms).
    for other in others:
        service.add_entry(wl["id"], other)

    sid = db.start_session("image", "upload.jpg")
    det_id = db.save_detection(
        sid, "image", det_variant, "persian-display", 0.95, "upload.jpg"
    )

    alerts = db.list_alerts()
    # EXACTLY ONE alert, referencing both the detection and the matched entry.
    assert len(alerts) == 1
    assert alerts[0]["detection_id"] == det_id
    assert alerts[0]["entry_id"] == matching_entry["id"]

    # The detection plate and the entry plate are indeed canonically equal.
    assert matching.normalize_for_match(det_variant) == matching.normalize_for_match(
        entry_variant
    )


@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    core=core_plates,
    others=st.lists(core_plates, min_size=0, max_size=6),
    det_seed=st.data(),
)
def test_non_matching_detection_raises_no_alert(fresh_db, core, others, det_seed):
    """A detection matching no active entry raises no alert (Req 12.4, 12.5)."""
    _reset_tables()

    target_norm = matching.normalize_for_match(core)
    # Keep only entries whose normalized form differs from the detection's.
    non_matching = [c for c in others if matching.normalize_for_match(c) != target_norm]

    wl = service.create_watchlist("list", "blacklist")
    for other in non_matching:
        service.add_entry(wl["id"], other)

    det_variant = det_seed.draw(_variant_of(core))
    sid = db.start_session("video", "clip.mp4")
    db.save_detection(sid, "video", det_variant, "persian-display", 0.8, "clip.mp4")

    assert db.list_alerts() == []


@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(scenario=matching_scenario())
def test_deleted_entry_never_matches(fresh_db, scenario):
    """A deleted entry is inactive and raises no alert for a matching detection (Req 12.5)."""
    core, det_variant, entry_variant, others = scenario
    _reset_tables()

    wl = service.create_watchlist("list", "blacklist")
    matching_entry = service.add_entry(wl["id"], entry_variant, label="wanted")
    for other in others:
        service.add_entry(wl["id"], other)

    # Delete the only entry that would match (Req 12.3 -> inactive, Req 12.5).
    assert service.remove_entry(matching_entry["id"]) is True

    sid = db.start_session("rtsp", "rtsp://cam")
    db.save_detection(sid, "rtsp", det_variant, "persian-display", 0.9, "rtsp://cam")

    # No alert is created for the deleted (inactive) entry.
    assert db.list_alerts() == []
