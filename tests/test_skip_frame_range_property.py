"""
Property-based test for skip-frame range validation on the camera schemas.

Feature: anpr-system-redesign, Property 11

Property 11: Skip-frame values are accepted exactly within 1..1000.
    For any integer, a camera or video skip-frame value is accepted if and only
    if it lies in the inclusive range 1 to 1000; out-of-range values are
    rejected with a validation-error.

The skip-frame constraint lives in schemas.py as ``Field(ge=1, le=1000)`` on
both ``CameraCreate`` and ``CameraUpdate`` (Req 4.7). The same Field pattern
governs the video-detection skip-frame value (Req 9.6); no separate video
request model with ``skip_frames`` exists yet, so the camera models exercise
the identical validation rule.

Validates: Requirements 4.7, 9.6
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from schemas import CameraCreate, CameraUpdate


# Bounds of the inclusive accepted range.
_LOW = 1
_HIGH = 1000

# Wide integer range spanning well below and well above the accepted window so
# both in-range and out-of-range values are generated densely.
_skip_values = st.integers(min_value=-2000, max_value=3000)


def _build(model, n: int):
    """Construct the given camera model with skip_frames=n.

    A valid ``url`` is supplied so that only skip_frames governs acceptance for
    CameraCreate (url is required there); CameraUpdate tolerates a missing url.
    """
    if model is CameraCreate:
        return model(url="rtsp://example/stream", skip_frames=n)
    return model(skip_frames=n)


# Feature: anpr-system-redesign, Property 11
@pytest.mark.parametrize("model", [CameraCreate, CameraUpdate])
@settings(max_examples=200)
@given(n=_skip_values)
def test_skip_frames_accepted_iff_in_range(model, n: int) -> None:
    in_range = _LOW <= n <= _HIGH
    if in_range:
        # Accepted: construction succeeds and the value round-trips unchanged.
        instance = _build(model, n)
        assert instance.skip_frames == n
    else:
        # Rejected: out-of-range values raise a pydantic ValidationError.
        with pytest.raises(ValidationError):
            _build(model, n)
