"""
Property-based tests for auth/security.py disabled-account rejection.

Feature: anpr-system-redesign, Property 4

Property 4: Disabled accounts cannot authenticate.
    For any account marked disabled, a login attempt with otherwise-correct
    credentials (a structurally valid, correctly signed, unexpired, non-revoked
    session token) is rejected with an authentication-failure and yields no
    session token / TokenClaims. Specifically, verify_session_token returns an
    AuthError whose reason is 'disabled'.

Validates: Requirements 1.8
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from auth.security import (
    AuthError,
    TokenClaims,
    create_session_token,
    verify_session_token,
)

# Roles embedded in tokens (design.md: Admin|Operator|Viewer). The disabled
# check is role-independent, so any role string is a valid generator input.
_roles = st.sampled_from(["Admin", "Operator", "Viewer"])

# Non-empty secrets so signing/verification share a real key.
_secrets = st.text(min_size=1, max_size=64)

# Positive user ids.
_user_ids = st.integers(min_value=1, max_value=2_000_000)

# Issue time (unix seconds) within a sane range.
_now = st.integers(min_value=0, max_value=4_000_000_000)

# Time-to-live strictly positive; bounded so iat + ttl stays representable.
_ttls = st.integers(min_value=1, max_value=10_000_000)


# Feature: anpr-system-redesign, Property 4
@settings(max_examples=100)
@given(
    user_id=_user_ids,
    role=_roles,
    secret=_secrets,
    issued=_now,
    ttl=_ttls,
)
def test_disabled_account_token_is_rejected(
    user_id: int,
    role: str,
    secret: str,
    issued: int,
    ttl: int,
) -> None:
    # Build an OTHERWISE-VALID token: correct signature, not yet expired.
    token = create_session_token(
        user_id,
        role,
        ttl,
        now=issued,
        secret=secret,
    )

    # Verify at a moment strictly before expiry so only the disabled-account
    # check can cause rejection. is_revoked says "never revoked" so the only
    # failing gate is the account-enabled callback.
    verify_at = issued  # iat < exp, so the token is live at issue time

    result = verify_session_token(
        token,
        now=verify_at,
        secret=secret,
        is_revoked=lambda _jti: False,
        is_account_enabled=lambda _sub: False,
    )

    # No valid claims may be returned for a disabled account.
    assert not isinstance(result, TokenClaims)
    # The rejection must be an authentication failure tagged 'disabled'.
    assert isinstance(result, AuthError)
    assert result.reason == "disabled"
