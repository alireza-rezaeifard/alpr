"""
Property-based tests for plate_validator.validate_iranian_plate()
using the Hypothesis library.

Validates: Requirements 5.1, 5.2, 5.3, 5.5, 5.8, 5.9, 5.10, 5.11
"""
from __future__ import annotations

import sys
import os
import string

# Ensure root project directory is on sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from plate_validator import validate_iranian_plate, ValidationResult
from plate_reference import (
    LETTER_TO_CATEGORY,
    PERSIAN_LETTER_TO_CATEGORY,
    REGION_CODE_TO_PROVINCE,
)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# Valid latin series letters (from LETTER_TO_CATEGORY, excluding special keys like "diplomatic")
VALID_LATIN_LETTERS = [k for k in LETTER_TO_CATEGORY.keys() if len(k) == 1 and k.isalpha()]

# Valid Persian series letters (from PERSIAN_LETTER_TO_CATEGORY)
VALID_PERSIAN_LETTERS = list(PERSIAN_LETTER_TO_CATEGORY.keys())

# All valid letters (latin + Persian)
ALL_VALID_LETTERS = VALID_LATIN_LETTERS + VALID_PERSIAN_LETTERS

# Valid region codes
VALID_REGION_CODES = list(REGION_CODE_TO_PROVINCE.keys())

# Persian digit equivalents for 0-9
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"

# Separator characters that should be stripped
SEPARATORS = [" ", "-", "_"]


def digit_strategy():
    """Generate a single ASCII digit character."""
    return st.sampled_from(list("0123456789"))


def persian_digit_strategy():
    """Generate a single Persian digit character."""
    return st.sampled_from(list(PERSIAN_DIGITS))


def arabic_digit_strategy():
    """Generate a single Arabic-Indic digit character."""
    return st.sampled_from(list(ARABIC_DIGITS))


def any_digit_strategy():
    """Generate a digit in any encoding (ASCII, Persian, or Arabic)."""
    return st.one_of(digit_strategy(), persian_digit_strategy(), arabic_digit_strategy())


def valid_letter_strategy():
    """Generate a valid Iranian plate series letter."""
    return st.sampled_from(ALL_VALID_LETTERS)


def valid_region_code_strategy():
    """Generate a valid region code (2-digit string from REGION_CODE_TO_PROVINCE)."""
    return st.sampled_from(VALID_REGION_CODES)


def valid_confidence_strategy():
    """Generate a confidence value >= 0.4 (passes threshold)."""
    return st.floats(min_value=0.4, max_value=1.0, allow_nan=False, allow_infinity=False)


def valid_plate_strategy():
    """
    Generate a valid Iranian plate string: 2 digits + valid letter + 3 digits + valid region code.
    Uses ASCII digits by default.
    """
    return st.tuples(
        st.text(alphabet="0123456789", min_size=2, max_size=2),
        valid_letter_strategy(),
        st.text(alphabet="0123456789", min_size=3, max_size=3),
        valid_region_code_strategy(),
    ).map(lambda t: t[0] + t[1] + t[2] + t[3])


def valid_plate_any_encoding_strategy():
    """
    Generate a valid Iranian plate string with potentially Persian/Arabic digits
    and optional separators inserted.
    """
    return st.tuples(
        # Two digits (any encoding)
        any_digit_strategy(),
        any_digit_strategy(),
        # Valid series letter
        valid_letter_strategy(),
        # Three digits (any encoding)
        any_digit_strategy(),
        any_digit_strategy(),
        any_digit_strategy(),
        # Valid region code (always ASCII since it must match region table)
        valid_region_code_strategy(),
        # Optional separators to insert
        st.lists(st.sampled_from(SEPARATORS), min_size=0, max_size=3),
    ).map(_assemble_plate_with_separators)


def _assemble_plate_with_separators(t):
    """Assemble plate string, optionally inserting separators between segments."""
    d1, d2, letter, d3, d4, d5, region, seps = t
    # Build base plate
    base = d1 + d2 + letter + d3 + d4 + d5 + region
    if not seps:
        return base
    # Insert separators at random valid positions (between segments)
    # Positions: after prefix (2), after letter (3), after number (6)
    insert_points = [2, 3, 6]
    result = list(base)
    offset = 0
    for i, sep in enumerate(seps):
        if i < len(insert_points):
            pos = insert_points[i] + offset
            result.insert(pos, sep)
            offset += 1
    return "".join(result)


# ---------------------------------------------------------------------------
# Property 1: Valid Iranian plate acceptance with complete metadata
# ---------------------------------------------------------------------------

class TestProperty1ValidPlateAcceptance:
    """
    **Validates: Requirements 5.1, 5.2, 5.11**

    For any randomly generated valid Iranian plate string with confidence >= 0.4,
    validate_iranian_plate() SHALL return is_valid=True with non-null metadata where
    classified=True, category_display is non-empty, region_name is non-empty, and
    color_scheme is one of {white, yellow, green, red, blue, black}.
    """

    @given(plate=valid_plate_strategy(), confidence=valid_confidence_strategy())
    @settings(max_examples=100)
    def test_valid_plate_ascii_digits(self, plate: str, confidence: float):
        """Valid plate with ASCII digits should be accepted with full metadata."""
        result = validate_iranian_plate(plate, confidence)

        assert result.is_valid is True, f"Expected valid for plate={plate!r}, conf={confidence}"
        assert result.metadata is not None
        assert result.metadata.classified is True
        assert result.metadata.category_display is not None
        assert len(result.metadata.category_display) > 0
        assert result.metadata.region_name is not None
        assert len(result.metadata.region_name) > 0
        assert result.metadata.color_scheme in {"white", "yellow", "green", "red", "blue", "black"}

    @given(plate=valid_plate_any_encoding_strategy(), confidence=valid_confidence_strategy())
    @settings(max_examples=100)
    def test_valid_plate_mixed_encoding_and_separators(self, plate: str, confidence: float):
        """Valid plates with Persian/Arabic digits and separators should be accepted."""
        result = validate_iranian_plate(plate, confidence)

        assert result.is_valid is True, f"Expected valid for plate={plate!r}, conf={confidence}"
        assert result.metadata is not None
        assert result.metadata.classified is True
        assert result.metadata.category_display is not None
        assert len(result.metadata.category_display) > 0
        assert result.metadata.region_name is not None
        assert len(result.metadata.region_name) > 0
        assert result.metadata.color_scheme in {"white", "yellow", "green", "red", "blue", "black"}


# ---------------------------------------------------------------------------
# Property 2: Invalid length rejection
# ---------------------------------------------------------------------------

class TestProperty2InvalidLengthRejection:
    """
    **Validates: Requirements 5.3**

    For any string whose normalized length (after digit conversion and separator stripping)
    is NOT exactly 8 characters, validate_iranian_plate() SHALL return is_valid=False.
    """

    @given(
        text=st.text(
            alphabet=st.sampled_from(
                list(string.ascii_letters + string.digits + PERSIAN_DIGITS + ARABIC_DIGITS + " -_")
            ),
            min_size=0,
            max_size=30,
        ),
        confidence=valid_confidence_strategy(),
    )
    @settings(max_examples=100)
    def test_invalid_length_rejected(self, text: str, confidence: float):
        """Strings whose normalized length is not 8 should be rejected."""
        # Normalize the text the same way the validator does
        _PERSIAN_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
        _ARABIC_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        import re
        normalized = text.translate(_PERSIAN_MAP).translate(_ARABIC_MAP)
        normalized = re.sub(r"[\s\-_]", "", normalized)

        # Only test cases where the normalized length is NOT 8
        assume(len(normalized) != 8)

        result = validate_iranian_plate(text, confidence)
        assert result.is_valid is False, (
            f"Expected invalid for text={text!r} (normalized len={len(normalized)})"
        )


# ---------------------------------------------------------------------------
# Property 3: Invalid structure rejection
# ---------------------------------------------------------------------------

class TestProperty3InvalidStructureRejection:
    """
    **Validates: Requirements 5.5, 5.8**

    For any 8-character string where position 2 is NOT a valid series letter,
    OR where positions 6-7 are NOT a known region code,
    validate_iranian_plate() SHALL return is_valid=False.
    """

    @given(
        prefix=st.text(alphabet="0123456789", min_size=2, max_size=2),
        bad_letter=st.text(
            alphabet=st.sampled_from(list(string.digits + "!@#$%^&*()")),
            min_size=1,
            max_size=1,
        ),
        number=st.text(alphabet="0123456789", min_size=3, max_size=3),
        region=valid_region_code_strategy(),
        confidence=valid_confidence_strategy(),
    )
    @settings(max_examples=100)
    def test_invalid_series_letter_rejected(
        self, prefix: str, bad_letter: str, number: str, region: str, confidence: float
    ):
        """8-char strings with invalid series letter at position 2 should be rejected."""
        # Ensure the bad_letter is truly not a valid plate letter
        assume(bad_letter.lower() not in LETTER_TO_CATEGORY)
        assume(bad_letter not in PERSIAN_LETTER_TO_CATEGORY)

        plate = prefix + bad_letter + number + region
        result = validate_iranian_plate(plate, confidence)
        assert result.is_valid is False, (
            f"Expected invalid for plate={plate!r} (bad letter={bad_letter!r})"
        )

    @given(
        prefix=st.text(alphabet="0123456789", min_size=2, max_size=2),
        letter=valid_letter_strategy(),
        number=st.text(alphabet="0123456789", min_size=3, max_size=3),
        bad_region=st.text(alphabet="0123456789", min_size=2, max_size=2),
        confidence=valid_confidence_strategy(),
    )
    @settings(max_examples=100)
    def test_invalid_region_code_rejected(
        self, prefix: str, letter: str, number: str, bad_region: str, confidence: float
    ):
        """8-char strings with unknown region code should be rejected."""
        # Ensure the region code is NOT in the known registry
        assume(bad_region not in REGION_CODE_TO_PROVINCE)

        plate = prefix + letter + number + bad_region
        result = validate_iranian_plate(plate, confidence)
        assert result.is_valid is False, (
            f"Expected invalid for plate={plate!r} (bad region={bad_region!r})"
        )


# ---------------------------------------------------------------------------
# Property 4: Low confidence rejection
# ---------------------------------------------------------------------------

class TestProperty4LowConfidenceRejection:
    """
    **Validates: Requirements 5.9**

    For any string input with confidence < 0.4,
    validate_iranian_plate() SHALL return is_valid=False regardless of text.
    """

    @given(
        text=st.text(min_size=0, max_size=20),
        confidence=st.floats(
            min_value=0.0,
            max_value=0.3999999,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100)
    def test_low_confidence_always_rejected(self, text: str, confidence: float):
        """Any input with confidence below 0.4 should be rejected."""
        result = validate_iranian_plate(text, confidence)
        assert result.is_valid is False, (
            f"Expected invalid for conf={confidence} (below threshold 0.4)"
        )


# ---------------------------------------------------------------------------
# Property 5: Rejection reason completeness
# ---------------------------------------------------------------------------

class TestProperty5RejectionReasonCompleteness:
    """
    **Validates: Requirements 5.10, 5.11**

    For any input that results in is_valid=False, the rejection_reason field SHALL be
    a non-empty string and metadata SHALL be None.
    """

    @given(
        text=st.text(min_size=0, max_size=20),
        confidence=st.floats(
            min_value=0.0,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100)
    def test_rejected_plates_have_reason_and_no_metadata(self, text: str, confidence: float):
        """When is_valid=False, rejection_reason must be non-empty and metadata must be None."""
        result = validate_iranian_plate(text, confidence)

        if not result.is_valid:
            assert result.rejection_reason is not None, (
                f"rejection_reason is None for invalid plate text={text!r}, conf={confidence}"
            )
            assert len(result.rejection_reason) > 0, (
                f"rejection_reason is empty for invalid plate text={text!r}, conf={confidence}"
            )
            assert result.metadata is None, (
                f"metadata should be None for invalid plate text={text!r}, conf={confidence}"
            )
