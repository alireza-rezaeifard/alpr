"""
Property-based test for plate parse/format round-trip (task 12.4).

Feature: anpr-system-redesign, Property 17

Property 17: Plate parse/format round-trip preserves components.
    For all recognized plates, parsing a plate string, then formatting it with
    the Pretty_Printer, then parsing the result again yields equivalent plate
    components (round-trip property).

Validates: Requirements 11.7

Mechanism under test:
    * ``plate_metadata.normalize_plate`` parses a raw plate string into
      ``(prefix_2, letter, region_2)`` or ``None``.
    * ``plate_validator.format_plate_persian`` formats a plate into the Persian
      display string (converting Latin series letters to Persian script and
      ASCII digits to Persian digits).

Equivalence definition:
    ``format_plate_persian`` deliberately converts the Latin series letter to
    its Persian equivalent, so the letter component changes *script* across the
    round-trip. Equivalence is therefore defined as:
      * the 2-digit prefix is exactly preserved, and
      * the 2-digit region code is exactly preserved, and
      * the re-parsed letter equals the Persian form of the original Latin
        letter (per ``_LATIN_TO_PERSIAN_LETTER``).

No mocks are used: the real parser and formatter are exercised directly.
"""
from __future__ import annotations

import os
import sys

from hypothesis import given, settings
from hypothesis import strategies as st

# Ensure the project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plate_metadata import normalize_plate
from plate_validator import _LATIN_TO_PERSIAN_LETTER, format_plate_persian

# Known Latin series letters emitted by the DTRB recognizer. Every entry has a
# defined Persian equivalent in ``_LATIN_TO_PERSIAN_LETTER``.
_LATIN_SERIES_LETTERS = sorted(_LATIN_TO_PERSIAN_LETTER.keys())

# Strategies for structurally valid plate components.
_two_digits = st.integers(min_value=0, max_value=99).map(lambda n: f"{n:02d}")
_three_digits = st.integers(min_value=0, max_value=999).map(lambda n: f"{n:03d}")
_letters = st.sampled_from(_LATIN_SERIES_LETTERS)


@settings(max_examples=200)
@given(prefix=_two_digits, letter=_letters, number=_three_digits, region=_two_digits)
def test_parse_format_parse_round_trip(prefix, letter, number, region):
    """parse -> format -> parse preserves digit components and letter identity."""
    plate = f"{prefix}{letter}{number}{region}"

    # First parse: the generated plate is structurally valid, so it must parse.
    parse1 = normalize_plate(plate)
    assert parse1 is not None
    assert parse1 == (prefix, letter, region)

    # Format with the Pretty_Printer (Latin letter -> Persian, ASCII -> Persian digits).
    formatted = format_plate_persian(plate)

    # Second parse of the formatted (Persian) string must also succeed.
    parse2 = normalize_plate(formatted)
    assert parse2 is not None

    prefix2, letter2, region2 = parse2

    # Digit components round-trip exactly.
    assert prefix2 == parse1[0]
    assert region2 == parse1[2]

    # The letter component is equivalent: parse2's letter is the Persian form
    # of parse1's Latin letter.
    expected_persian_letter = _LATIN_TO_PERSIAN_LETTER[parse1[1].lower()]
    assert letter2 == expected_persian_letter
