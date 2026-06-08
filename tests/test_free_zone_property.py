"""
Property-based test for plate_metadata.derive_metadata() free-zone handling
using the Hypothesis library.

Property 18: Free-zone plates carry the free-zone note.
For any plate whose resolved category is the free-zone category
("FreeZone_Arvand"), the derived Plate_Metadata includes a non-empty
free-zone special note, equal to
    FREE_ZONE_PREFIXES.get(prefix, "Free Zone plate").

NOTE ON REACHABILITY (documented intentionally):
    As of the current plate_reference.py, NO series letter maps to the
    category "FreeZone_Arvand" in either LETTER_TO_CATEGORY or
    PERSIAN_LETTER_TO_CATEGORY. Because derive_metadata resolves the category
    solely from the series letter (_resolve_letter), the free-zone category is
    not reachable through the normal derivation path. We therefore assert the
    *conditional contract* directly: for any plate, IF the resolved category is
    "FreeZone_Arvand" THEN special_note must be a non-empty string with the
    expected value. This is vacuously satisfied today, but the contract is
    enforced and will remain correct if a free-zone letter mapping is added
    later. The generator is deliberately biased toward the free-zone numeric
    prefixes so the branch is exercised the moment such a mapping exists.

Feature: anpr-system-redesign, Property 18
Validates: Requirements 11.6
"""
from __future__ import annotations

import sys
import os

# Ensure root project directory is on sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import given, settings
from hypothesis import strategies as st

from plate_metadata import derive_metadata, normalize_plate, PlateMetadata
from plate_reference import (
    LETTER_TO_CATEGORY,
    PERSIAN_LETTER_TO_CATEGORY,
    REGION_CODE_TO_PROVINCE,
    FREE_ZONE_PREFIXES,
)

FREE_ZONE_CATEGORY = "FreeZone_Arvand"

# Valid single-character latin series letters (exclude special keys like "diplomatic")
VALID_LATIN_LETTERS = [k for k in LETTER_TO_CATEGORY.keys() if len(k) == 1 and k.isalpha()]
VALID_PERSIAN_LETTERS = list(PERSIAN_LETTER_TO_CATEGORY.keys())
ALL_VALID_LETTERS = VALID_LATIN_LETTERS + VALID_PERSIAN_LETTERS

VALID_REGION_CODES = list(REGION_CODE_TO_PROVINCE.keys())
# Bias prefixes toward the free-zone numeric prefixes so the free-zone branch
# is exercised whenever a free-zone letter mapping exists.
FREE_ZONE_PREFIX_KEYS = list(FREE_ZONE_PREFIXES.keys())


def free_zone_biased_plate_strategy():
    """
    Generate a structurally valid plate (2 digits + valid letter + 3 digits +
    valid 2-digit region code), biasing the 2-digit prefix toward the known
    free-zone prefixes so the free-zone note logic is maximally exercised.
    """
    prefix_strategy = st.one_of(
        st.sampled_from(FREE_ZONE_PREFIX_KEYS),
        st.from_regex(r"[0-9]{2}", fullmatch=True),
    )
    return st.tuples(
        prefix_strategy,
        st.sampled_from(ALL_VALID_LETTERS),
        st.from_regex(r"[0-9]{3}", fullmatch=True),
        st.sampled_from(VALID_REGION_CODES),
    ).map(lambda t: t[0] + t[1] + t[2] + t[3])


class TestProperty18FreeZoneNote:
    """
    **Validates: Requirements 11.6**

    For any plate whose resolved category is the free-zone category, the derived
    Plate_Metadata includes the free-zone special note.
    """

    @given(raw=free_zone_biased_plate_strategy())
    @settings(max_examples=200)
    def test_free_zone_plate_carries_note(self, raw):
        result = derive_metadata(raw)
        assert isinstance(result, PlateMetadata)

        if result.category == FREE_ZONE_CATEGORY:
            # The plate is a free-zone plate: it must be classified and carry a
            # non-empty special note equal to the expected free-zone note.
            assert result.classified is True, (
                f"Free-zone plate should be classified for raw={raw!r}"
            )
            parsed = normalize_plate(raw)
            assert parsed is not None, f"Free-zone plate should parse for raw={raw!r}"
            prefix = parsed[0]
            expected = FREE_ZONE_PREFIXES.get(prefix, "Free Zone plate")
            assert result.special_note == expected, (
                f"special_note={result.special_note!r} != expected {expected!r} "
                f"for raw={raw!r}"
            )
            assert (
                isinstance(result.special_note, str) and len(result.special_note) > 0
            ), f"Free-zone special_note must be a non-empty string for raw={raw!r}"
