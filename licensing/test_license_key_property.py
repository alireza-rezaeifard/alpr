"""
Property-based tests for licensing/license_key.py.

Feature: anpr-system-redesign, Property 8

Property 8: License keys round-trip and validity respects expiry.
    For any license claims (expiry date and camera limit), decoding a correctly
    signed key recovers the same expiry and limit; for any tampered or forged key
    decoding fails (returns None); and for any expiry earlier than the current date
    the active license is treated as invalid (valid iff expiry >= now).

Validates: Requirements 3.1, 3.2, 3.4
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import date, datetime

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

# Ensure the project root is importable when pytest is invoked from elsewhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from licensing.license_key import (
    LicenseClaims,
    decode_license_key,
    encode_license_key,
    is_license_valid,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Expiry claims are ISO date strings; generating from real dates keeps them
# well-formed and realistic.
_expiry_dates = st.dates()
_expiry_strings = _expiry_dates.map(lambda d: d.isoformat())

# Camera limits are non-negative ints (st.integers never yields bool).
_camera_limits = st.integers(min_value=0, max_value=10_000)

# Non-empty signing secrets.
_secrets = st.text(min_size=1, max_size=64)

# base64url alphabet used in keys (no padding, no '.').
_B64URL_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


# ---------------------------------------------------------------------------
# Round-trip: encode then decode recovers the same claims (Req 3.1)
# ---------------------------------------------------------------------------

# Feature: anpr-system-redesign, Property 8
@settings(max_examples=200)
@given(expiry=_expiry_strings, camera_limit=_camera_limits, secret=_secrets)
def test_roundtrip_recovers_claims(expiry: str, camera_limit: int, secret: str) -> None:
    claims = LicenseClaims(expiry=expiry, camera_limit=camera_limit)
    key = encode_license_key(claims, secret=secret)

    decoded = decode_license_key(key, secret=secret)

    assert decoded is not None
    assert decoded.expiry == expiry
    assert decoded.camera_limit == camera_limit


# ---------------------------------------------------------------------------
# Forged: decoding with the wrong secret fails (Req 3.2)
# ---------------------------------------------------------------------------

# Feature: anpr-system-redesign, Property 8
@settings(max_examples=150)
@given(
    expiry=_expiry_strings,
    camera_limit=_camera_limits,
    secret=_secrets,
    wrong_secret=_secrets,
)
def test_wrong_secret_decode_fails(
    expiry: str, camera_limit: int, secret: str, wrong_secret: str
) -> None:
    # A key signed under one secret must not verify under a different secret.
    assume(secret != wrong_secret)
    key = encode_license_key(LicenseClaims(expiry=expiry, camera_limit=camera_limit), secret=secret)

    assert decode_license_key(key, secret=wrong_secret) is None


# ---------------------------------------------------------------------------
# Tampered: mutating any character of a valid key fails to decode (Req 3.2)
# ---------------------------------------------------------------------------

# Feature: anpr-system-redesign, Property 8
@settings(max_examples=200)
@given(
    expiry=_expiry_strings,
    camera_limit=_camera_limits,
    secret=_secrets,
    data=st.data(),
)
def test_tampered_key_decode_fails(
    expiry: str, camera_limit: int, secret: str, data: st.DataObject
) -> None:
    key = encode_license_key(LicenseClaims(expiry=expiry, camera_limit=camera_limit), secret=secret)

    # Pick a non-separator character position and flip it to a different
    # base64url character, preserving the single-'.' two-part structure.
    index = data.draw(st.integers(min_value=0, max_value=len(key) - 1))
    assume(key[index] != ".")
    replacement = data.draw(st.sampled_from(_B64URL_ALPHABET))
    assume(replacement != key[index])

    tampered = key[:index] + replacement + key[index + 1 :]

    assert decode_license_key(tampered, secret=secret) is None


# ---------------------------------------------------------------------------
# Validity vs expiry, against a temporary SQLite licenses table (Req 3.4)
# ---------------------------------------------------------------------------

@pytest.fixture()
def temp_db(monkeypatch):
    """Point db.* helpers at a throwaway SQLite database for the test."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "license_test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    try:
        yield
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _set_single_license(expiry: date, *, active: bool) -> None:
    """Replace the licenses table contents with one row at the given expiry."""
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM licenses")
        conn.execute(
            "INSERT INTO licenses (key, active, expiry, camera_limit, activated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("k", 1 if active else 0, expiry.isoformat(), 1, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


# Feature: anpr-system-redesign, Property 8
@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(expiry=_expiry_dates, now=_expiry_dates)
def test_active_license_valid_iff_not_expired(temp_db, expiry: date, now: date) -> None:
    _set_single_license(expiry, active=True)

    # An active license is valid exactly when its expiry is not before `now`.
    assert is_license_valid(now) is (expiry >= now)


# Feature: anpr-system-redesign, Property 8
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(expiry=_expiry_dates, now=_expiry_dates)
def test_inactive_license_never_valid(temp_db, expiry: date, now: date) -> None:
    # When no active license row exists, validity is always False regardless of
    # expiry (Req 3.4 — only an active, unexpired license is valid).
    _set_single_license(expiry, active=False)

    assert is_license_valid(now) is False
