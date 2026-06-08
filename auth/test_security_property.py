"""
Property-based tests for auth/security.py password hashing.

Feature: anpr-system-redesign, Property 1

Property 1: Password hashing is a one-way, salted round-trip.
    For any password string:
      * verify_password(password, hash_password(password)) is True
      * the produced hash is never equal to the plaintext
      * two independent hashes of the same password differ (distinct salts)

Validates: Requirements 1.3
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from auth.security import hash_password, verify_password

# bcrypt only considers the first 72 bytes of input, so constrain generated
# passwords to stay within that limit (measured in UTF-8 bytes) to keep the
# round-trip meaningful and avoid silent truncation surprises. bcrypt also
# rejects NULL bytes by design, so they are excluded from the input space.
_passwords = st.text(
    # Exclude NULL bytes (bcrypt rejects them) and surrogate code points
    # (category "Cs"), which cannot be UTF-8 encoded by the byte-length filter.
    alphabet=st.characters(blacklist_characters="\x00", blacklist_categories=("Cs",)),
    min_size=0,
    max_size=72,
).filter(lambda s: len(s.encode("utf-8")) <= 72)


# Feature: anpr-system-redesign, Property 1
# Deadline disabled because bcrypt is intentionally slow (high work factor);
# per-example latency is expected and not a correctness signal.
@settings(max_examples=100, deadline=None)
@given(password=_passwords)
def test_password_hashing_is_one_way_salted_round_trip(password: str) -> None:
    hashed = hash_password(password)

    # One-way: the hash never equals the plaintext.
    assert hashed != password

    # Round-trip: the original password verifies against its hash.
    assert verify_password(password, hashed) is True

    # Salted: an independent hash of the same password differs.
    hashed_again = hash_password(password)
    assert hashed_again != hashed

    # Both salted hashes still verify against the same password.
    assert verify_password(password, hashed_again) is True
