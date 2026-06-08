"""
Property-based tests for auth/security.py — session-token rejection.

Feature: anpr-system-redesign, Property 3
Property 3: Invalid session tokens are always rejected.

For any token that is expired, has a tampered signature/payload, or has been
revoked via logout, ``verify_session_token`` rejects the request by returning
an :class:`AuthError` (never valid :class:`TokenClaims`) and therefore issues
no usable session identity.

The expiry / revocation / account-enabled lookups are injected so the logic is
exercised without a database.

Validates: Requirements 1.2, 1.5, 1.7
"""
from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from auth.security import (
    AuthError,
    TokenClaims,
    create_session_token,
    verify_session_token,
)

# Keep every check DB-free and deterministic.
_NEVER_REVOKED = lambda jti: False          # noqa: E731
_ALWAYS_REVOKED = lambda jti: True          # noqa: E731
_ALWAYS_ENABLED = lambda sub: True          # noqa: E731

_roles = st.sampled_from(["Admin", "Operator", "Viewer"])
_user_ids = st.integers(min_value=1, max_value=10_000_000)
_secrets = st.text(min_size=1, max_size=64)
_ttls = st.integers(min_value=1, max_value=1_000_000)
_issued = st.integers(min_value=0, max_value=2_000_000_000)


# ---------------------------------------------------------------------------
# Feature: anpr-system-redesign, Property 3 — expired tokens (Requirement 1.5)
# ---------------------------------------------------------------------------
@settings(max_examples=200)
@given(
    user_id=_user_ids,
    role=_roles,
    ttl=_ttls,
    secret=_secrets,
    issued=_issued,
    extra=st.integers(min_value=0, max_value=10_000_000),
)
def test_expired_token_is_rejected(user_id, role, ttl, secret, issued, extra):
    """A token verified at or after its expiry is rejected as ``expired``."""
    token = create_session_token(
        user_id, role, ttl, now=issued, secret=secret
    )
    # Verify at a moment at or after expiry (exp == issued + ttl).
    verify_at = issued + ttl + extra
    result = verify_session_token(
        token,
        now=verify_at,
        secret=secret,
        is_revoked=_NEVER_REVOKED,
        is_account_enabled=_ALWAYS_ENABLED,
    )
    assert isinstance(result, AuthError)
    assert not isinstance(result, TokenClaims)
    assert result.reason == "expired"


# ---------------------------------------------------------------------------
# Feature: anpr-system-redesign, Property 3 — tampered tokens (Requirement 1.2)
# ---------------------------------------------------------------------------
@settings(max_examples=200)
@given(
    user_id=_user_ids,
    role=_roles,
    ttl=_ttls,
    secret=_secrets,
    issued=_issued,
    index=st.integers(min_value=0),
    replacement=st.characters(
        min_codepoint=33, max_codepoint=126  # printable, no whitespace
    ),
)
def test_tampered_token_is_rejected(
    user_id, role, ttl, secret, issued, index, replacement
):
    """Any single-character mutation of a valid token is rejected.

    A forged/tampered token represents credentials that do not correspond to a
    legitimately issued session, so verification must never return claims.
    """
    token = create_session_token(
        user_id, role, ttl, now=issued, secret=secret
    )
    pos = index % len(token)
    original_char = token[pos]
    assume(replacement != original_char)
    tampered = token[:pos] + replacement + token[pos + 1:]
    assume(tampered != token)

    # Verify well before expiry so expiry can never be the rejection reason.
    result = verify_session_token(
        tampered,
        now=issued,
        secret=secret,
        is_revoked=_NEVER_REVOKED,
        is_account_enabled=_ALWAYS_ENABLED,
    )
    assert isinstance(result, AuthError)
    assert not isinstance(result, TokenClaims)
    # A mutation either breaks structure or invalidates the HMAC signature.
    assert result.reason in {"malformed", "invalid_signature", "expired"}


# ---------------------------------------------------------------------------
# Feature: anpr-system-redesign, Property 3 — revoked tokens (Requirement 1.7)
# ---------------------------------------------------------------------------
@settings(max_examples=200)
@given(
    user_id=_user_ids,
    role=_roles,
    ttl=_ttls,
    secret=_secrets,
    issued=_issued,
    elapsed=st.integers(min_value=0),
)
def test_revoked_token_is_rejected(
    user_id, role, ttl, secret, issued, elapsed
):
    """A structurally valid, unexpired token whose ``jti`` has been revoked
    (as on logout) is rejected as ``revoked``."""
    token = create_session_token(
        user_id, role, ttl, now=issued, secret=secret
    )
    # Stay strictly before expiry so revocation is the operative reason.
    verify_at = issued + (elapsed % ttl)
    result = verify_session_token(
        token,
        now=verify_at,
        secret=secret,
        is_revoked=_ALWAYS_REVOKED,
        is_account_enabled=_ALWAYS_ENABLED,
    )
    assert isinstance(result, AuthError)
    assert not isinstance(result, TokenClaims)
    assert result.reason == "revoked"
