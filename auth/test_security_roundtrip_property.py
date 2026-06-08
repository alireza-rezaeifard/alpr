"""
Property-based tests for auth/security.py — valid session-token round-trip.

Run with Hypothesis (a minimum of 100 examples per property).

Feature: anpr-system-redesign, Property 2
Property 2: Valid session tokens round-trip to the issuing identity.

Validates: Requirements 1.1, 1.4
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from auth.security import (
    TokenClaims,
    create_session_token,
    verify_session_token,
)

ROLES = ("Admin", "Operator", "Viewer")

# A fixed secret keeps the round-trip pure and independent of the DB/env.
_SECRET = "test-secret-key-for-property-tests"

# Pure injected callbacks: nothing is revoked and every account is enabled,
# so verification depends only on the token's own signature/expiry/claims.
_NOT_REVOKED = lambda jti: False  # noqa: E731
_ENABLED = lambda sub: True  # noqa: E731


# Feature: anpr-system-redesign, Property 2
# For any user id, role, and positive time-to-live, verifying the token
# produced by create_session_token recovers the same user id and role and is
# accepted as authenticated.
# **Validates: Requirements 1.1, 1.4**
@settings(max_examples=100)
@given(
    user_id=st.integers(min_value=0, max_value=2**31 - 1),
    role=st.sampled_from(ROLES),
    ttl=st.integers(min_value=1, max_value=10 ** 9),
    now=st.integers(min_value=0, max_value=2**31 - 1),
)
def test_valid_token_round_trips_to_issuing_identity(user_id, role, ttl, now):
    token = create_session_token(
        user_id,
        role,
        ttl,
        now=now,
        secret=_SECRET,
    )

    result = verify_session_token(
        token,
        # Verify well within the token's validity window (token expires at
        # now + ttl); checking at issue time guarantees it is unexpired.
        now=now,
        secret=_SECRET,
        is_revoked=_NOT_REVOKED,
        is_account_enabled=_ENABLED,
    )

    # A valid token is accepted as authenticated (not an AuthError).
    assert isinstance(result, TokenClaims), (
        f"expected authenticated claims, got {result!r}"
    )
    # The recovered identity matches the issuing identity.
    assert result.sub == user_id
    assert result.role == role
    # Internal consistency: expiry is ttl seconds after issuance.
    assert result.iat == now
    assert result.exp == now + ttl
