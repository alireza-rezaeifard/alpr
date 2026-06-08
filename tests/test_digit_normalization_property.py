"""
Property-based test for canonical digit normalization across scripts
using the Hypothesis library.

Feature: anpr-system-redesign, Property 14

Validates: Requirements 11.2, 12.7
"""
from __future__ import annotations

import os
import sys

# Ensure root project directory is on sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import given, settings
from hypothesis import strategies as st

from plate_metadata import _normalise_digits
from watchlist.matching import normalize_for_match

# ---------------------------------------------------------------------------
# Script-specific digit mapping tables (index == underlying digit value)
# ---------------------------------------------------------------------------
LATIN_DIGITS = "0123456789"
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"

# ASCII digit -> script digit maps
_TO_PERSIAN = str.maketrans(LATIN_DIGITS, PERSIAN_DIGITS)
_TO_ARABIC = str.maketrans(LATIN_DIGITS, ARABIC_INDIC_DIGITS)


def _render(canonical: str, table) -> str:
    """Render a canonical ASCII digit string into the given script."""
    return canonical.translate(table)


# ---------------------------------------------------------------------------
# Property 14: Digit normalization is canonical across scripts
# ---------------------------------------------------------------------------
class TestProperty14CanonicalDigitNormalization:
    """
    **Validates: Requirements 11.2, 12.7**

    For any sequence of digits expressed in Persian, Arabic-Indic, or Latin
    form, normalizing each representation of the same underlying digits yields
    one identical canonical ASCII string.
    """

    @given(canonical=st.text(alphabet=LATIN_DIGITS, min_size=0, max_size=20))
    @settings(max_examples=200)
    def test_normalise_digits_canonical_across_scripts(self, canonical: str):
        """plate_metadata._normalise_digits maps all three scripts to the same ASCII string."""
        persian = _render(canonical, _TO_PERSIAN)
        arabic = _render(canonical, _TO_ARABIC)
        latin = canonical

        norm_persian = _normalise_digits(persian)
        norm_arabic = _normalise_digits(arabic)
        norm_latin = _normalise_digits(latin)

        # All representations canonicalize to the identical Latin/ASCII string
        assert norm_persian == canonical, (
            f"Persian {persian!r} -> {norm_persian!r}, expected {canonical!r}"
        )
        assert norm_arabic == canonical, (
            f"Arabic-Indic {arabic!r} -> {norm_arabic!r}, expected {canonical!r}"
        )
        assert norm_latin == canonical, (
            f"Latin {latin!r} -> {norm_latin!r}, expected {canonical!r}"
        )
        assert norm_persian == norm_arabic == norm_latin

    @given(canonical=st.text(alphabet=LATIN_DIGITS, min_size=0, max_size=20))
    @settings(max_examples=200)
    def test_normalize_for_match_canonical_across_scripts(self, canonical: str):
        """watchlist.matching.normalize_for_match canonicalizes all three scripts identically."""
        persian = _render(canonical, _TO_PERSIAN)
        arabic = _render(canonical, _TO_ARABIC)
        latin = canonical

        norm_persian = normalize_for_match(persian)
        norm_arabic = normalize_for_match(arabic)
        norm_latin = normalize_for_match(latin)

        assert norm_persian == norm_arabic == norm_latin == canonical, (
            f"Mismatch: persian={norm_persian!r}, arabic={norm_arabic!r}, "
            f"latin={norm_latin!r}, expected={canonical!r}"
        )
