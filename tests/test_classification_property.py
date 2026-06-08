"""
Property-based tests for plate_metadata.derive_metadata()
using the Hypothesis library.

Property 16: Plate classification is total and structure-driven.
derive_metadata never raises (total function) and:
  - returns classified=True with category/color/region populated for structurally
    valid plates (2 digits + 1 letter + 3 digits + 2-digit region code), and
  - returns classified=False with a non-empty reason for empty/whitespace/None
    and malformed/non-conforming input.

Feature: anpr-system-redesign, Property 16
Validates: Requirements 11.3, 11.4, 11.5
"""
from __future__ import annotations

import sys
import os
import string

# Ensure root project directory is on sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from plate_metadata import derive_metadata, normalize_plate, PlateMetadata
from plate_reference import (
    LETTER_TO_CATEGORY,
    PERSIAN_LETTER_TO_CATEGORY,
    REGION_CODE_TO_PROVINCE,
)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

VALID_COLOR_SCHEMES = {"white", "yellow", "green", "red", "blue", "black"}

# Valid single-character latin series letters (exclude special keys like "diplomatic")
VALID_LATIN_LETTERS = [k for k in LETTER_TO_CATEGORY.keys() if len(k) == 1 and k.isalpha()]
# Valid Persian series letters
VALID_PERSIAN_LETTERS = list(PERSIAN_LETTER_TO_CATEGORY.keys())
# All valid letters
ALL_VALID_LETTERS = VALID_LATIN_LETTERS + VALID_PERSIAN_LETTERS
# Valid region codes
VALID_REGION_CODES = list(REGION_CODE_TO_PROVINCE.keys())

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
SEPARATORS = [" ", "-", "_"]


def any_digit_strategy():
    """Generate a single digit in any encoding (ASCII, Persian, or Arabic)."""
    return st.sampled_from(list("0123456789") + list(PERSIAN_DIGITS) + list(ARABIC_DIGITS))


def valid_plate_strategy():
    """
    Generate a structurally valid Iranian plate string:
    2 digits + valid letter + 3 digits + valid (known) region code.
    Digits may be ASCII/Persian/Arabic; separators may be inserted between segments.
    """
    return st.tuples(
        any_digit_strategy(),
        any_digit_strategy(),
        st.sampled_from(ALL_VALID_LETTERS),
        any_digit_strategy(),
        any_digit_strategy(),
        any_digit_strategy(),
        st.sampled_from(VALID_REGION_CODES),
        st.lists(st.sampled_from(SEPARATORS), min_size=0, max_size=3),
    ).map(_assemble_plate_with_separators)


def _assemble_plate_with_separators(t):
    """Assemble plate string, optionally inserting separators between segments."""
    d1, d2, letter, d3, d4, d5, region, seps = t
    base = d1 + d2 + letter + d3 + d4 + d5 + region
    if not seps:
        return base
    insert_points = [2, 3, 6]  # after prefix, after letter, after number
    result = list(base)
    offset = 0
    for i, sep in enumerate(seps):
        if i < len(insert_points):
            pos = insert_points[i] + offset
            result.insert(pos, sep)
            offset += 1
    return "".join(result)


# Arbitrary strings: random text, plate-like fragments, symbols, mixed scripts
ARBITRARY_TEXT_ALPHABET = list(
    string.ascii_letters + string.digits + PERSIAN_DIGITS + ARABIC_DIGITS + " -_!@#$%^&*()"
) + VALID_PERSIAN_LETTERS


def arbitrary_text_strategy():
    """Generate arbitrary strings, including empty and whitespace-only."""
    return st.one_of(
        st.text(min_size=0, max_size=30),
        st.text(alphabet=st.sampled_from(ARBITRARY_TEXT_ALPHABET), min_size=0, max_size=30),
        st.sampled_from(["", " ", "   ", "\t", "\n", "  \t \n "]),
    )


# ---------------------------------------------------------------------------
# Property 16: Plate classification is total and structure-driven
# Feature: anpr-system-redesign, Property 16
# ---------------------------------------------------------------------------

class TestProperty16TotalStructureDrivenClassification:
    """
    **Validates: Requirements 11.3, 11.4, 11.5**

    derive_metadata is a total function (never raises) whose result is driven by the
    structural shape of the input string.
    """

    @given(raw=st.one_of(arbitrary_text_strategy(), valid_plate_strategy(), st.none()))
    @settings(max_examples=200)
    def test_derive_metadata_never_raises(self, raw):
        """
        For ANY input (including None, empty, whitespace, random text, valid plates),
        derive_metadata returns a PlateMetadata and never raises (total function).
        """
        result = derive_metadata(raw)
        assert isinstance(result, PlateMetadata)
        assert isinstance(result.classified, bool)

    @given(raw=st.none() | st.sampled_from(["", " ", "   ", "\t", "\n", "  \t\n  "]))
    @settings(max_examples=100)
    def test_empty_whitespace_none_unclassified_with_reason(self, raw):
        """
        Req 11.5: empty / whitespace-only / null input is unclassified with a reason.
        """
        result = derive_metadata(raw)
        assert result.classified is False, f"Expected unclassified for raw={raw!r}"
        assert result.reason is not None and len(result.reason) > 0, (
            f"Expected a non-empty reason for raw={raw!r}"
        )

    @given(raw=arbitrary_text_strategy())
    @settings(max_examples=200)
    def test_nonconforming_input_unclassified_with_reason(self, raw):
        """
        Req 11.4/11.5: any input that does not conform to the standard plate structure
        is unclassified with a non-empty reason.
        """
        # Restrict to inputs the parser rejects (i.e. genuinely non-conforming).
        assume(normalize_plate(raw) is None)
        result = derive_metadata(raw)
        assert result.classified is False, f"Expected unclassified for raw={raw!r}"
        assert result.reason is not None and len(result.reason) > 0, (
            f"Expected a non-empty reason for raw={raw!r}"
        )

    @given(raw=valid_plate_strategy())
    @settings(max_examples=200)
    def test_structurally_valid_plate_classified_with_metadata(self, raw):
        """
        Req 11.3: a structurally valid plate is classified with category, color scheme,
        region code, and region name all populated.
        """
        result = derive_metadata(raw)
        assert result.classified is True, f"Expected classified for raw={raw!r}"
        assert result.category is not None and len(result.category) > 0, (
            f"category not populated for raw={raw!r}"
        )
        assert result.category_display is not None and len(result.category_display) > 0, (
            f"category_display not populated for raw={raw!r}"
        )
        assert result.color_scheme in VALID_COLOR_SCHEMES, (
            f"color_scheme={result.color_scheme!r} not a known scheme for raw={raw!r}"
        )
        assert result.region_code is not None and len(result.region_code) == 2, (
            f"region_code not populated for raw={raw!r}"
        )
        assert result.region_name is not None and len(result.region_name) > 0, (
            f"region_name not populated for raw={raw!r}"
        )
        # No reason should be set on a classified result.
        assert result.reason is None, f"reason unexpectedly set for classified raw={raw!r}"
