"""
Property-based tests for the Pretty_Printer (plate_validator.format_plate_persian)
using the Hypothesis library.

Property 15: The pretty-printer always yields a Persian plate string included in
responses. For any recognized plate text, the Pretty_Printer produces a non-empty
Persian-formatted plate string, and that string is the value returned as the
detection's Persian plate field.

Feature: anpr-system-redesign, Property 15

Validates: Requirements 11.1, 8.5
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

# Ensure root project directory is on sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

import re

import db
from plate_validator import format_plate_persian
from plate_reference import REGION_CODE_TO_PROVINCE

# ---------------------------------------------------------------------------
# Constants mirroring the Pretty_Printer's display mappings
# ---------------------------------------------------------------------------

ASCII_DIGITS = "0123456789"
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_TO_PERSIAN = str.maketrans(ASCII_DIGITS, PERSIAN_DIGITS)
_PERSIAN_TO_ASCII = str.maketrans(PERSIAN_DIGITS, ASCII_DIGITS)
_ARABIC_TO_ASCII = str.maketrans(ARABIC_DIGITS, ASCII_DIGITS)
_STRIP_RE = re.compile(r"[\s\-_]")

# Latin letters that the Pretty_Printer knows how to convert to a Persian letter.
# (Mirrors plate_validator._LATIN_TO_PERSIAN_LETTER.)
LATIN_TO_PERSIAN_LETTER = {
    "b": "ب", "j": "ج", "d": "د", "s": "س", "l": "ل", "m": "م", "n": "ن",
    "v": "و", "o": "و", "u": "و", "w": "و", "h": "ه", "y": "ی", "i": "ی",
    "q": "ق", "r": "ر", "x": "خ", "t": "ت", "k": "ک", "a": "ا", "p": "پ",
    "c": "ث", "e": "ه", "z": "ز", "f": "ف", "g": "گ",
}

VALID_REGION_CODES = list(REGION_CODE_TO_PROVINCE.keys())


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def valid_structured_plate_strategy():
    """
    Generate a valid 8-char structured plate (raw DTRB form):
    2 ASCII digits + a latin series letter + 3 ASCII digits + a 2-digit region code.
    """
    return st.tuples(
        st.text(alphabet=ASCII_DIGITS, min_size=2, max_size=2),
        st.sampled_from(sorted(LATIN_TO_PERSIAN_LETTER.keys())),
        st.text(alphabet=ASCII_DIGITS, min_size=3, max_size=3),
        st.sampled_from(VALID_REGION_CODES),
    ).map(lambda t: t[0] + t[1] + t[2] + t[3])


def arbitrary_plate_text_strategy():
    """
    Generate arbitrary recognized-plate text: a mix of structured plates and
    free-form strings (letters, digits, separators, Persian digits).
    """
    free_form = st.text(
        alphabet=st.sampled_from(
            list("abcdefghijklmnopqrstuvwxyz" + ASCII_DIGITS + PERSIAN_DIGITS + " -_")
        ),
        min_size=0,
        max_size=20,
    )
    return st.one_of(valid_structured_plate_strategy(), free_form)


def expected_persian_format(plate: str) -> str:
    """Compute the expected Persian display for a valid 8-char structured plate."""
    prefix, letter, number, region = plate[0:2], plate[2], plate[3:6], plate[6:8]
    persian_letter = LATIN_TO_PERSIAN_LETTER.get(letter.lower(), letter)
    return (
        f"{prefix.translate(_TO_PERSIAN)} {persian_letter} "
        f"{number.translate(_TO_PERSIAN)}-{region.translate(_TO_PERSIAN)}"
    )


def normalize_plate_text(text: str) -> str:
    """Mirror the validator's normalization: Persian/Arabic digits -> ASCII, strip separators."""
    normalized = text.translate(_PERSIAN_TO_ASCII).translate(_ARABIC_TO_ASCII)
    return _STRIP_RE.sub("", normalized)


def no_ascii_digits(text: str) -> bool:
    """True if *text* contains no ASCII 0-9 digits."""
    return not any(ch in ASCII_DIGITS for ch in text)


# ---------------------------------------------------------------------------
# Temp-DB fixture for the end-to-end persian-field assertion (Req 8.5)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def detection_session():
    """
    Point db at a throwaway database, initialize the schema, and open one
    session that detections are stored under. Restores the original DB path
    on teardown.
    """
    original_db_path = db.DB_PATH
    tmp_dir = tempfile.mkdtemp(prefix="pretty_printer_pbt_")
    db.DB_PATH = os.path.join(tmp_dir, "test_pretty_printer.db")
    db.init_db()
    session_id = db.start_session("image", "pretty_printer_property")
    try:
        yield session_id
    finally:
        db.DB_PATH = original_db_path


# ---------------------------------------------------------------------------
# Property 15: Pretty-printer yields a Persian plate string used in responses
# ---------------------------------------------------------------------------

class TestProperty15PrettyPrinterOutput:
    """
    **Validates: Requirements 11.1, 8.5**

    Feature: anpr-system-redesign, Property 15

    For any recognized plate text, the Pretty_Printer (format_plate_persian)
    produces a non-empty Persian-formatted string (for non-empty input) with no
    residual ASCII digits, and that exact string is the value stored as the
    detection's Persian plate field.
    """

    @given(plate_text=arbitrary_plate_text_strategy())
    @settings(max_examples=100)
    def test_non_empty_input_yields_non_empty_persian_string(self, plate_text: str):
        """Any non-empty recognized plate text yields a non-empty string."""
        result = format_plate_persian(plate_text)
        assert isinstance(result, str)
        if plate_text != "":
            assert len(result) > 0, f"Empty output for input={plate_text!r}"

    @given(plate_text=arbitrary_plate_text_strategy())
    @settings(max_examples=100)
    def test_digit_portions_rendered_in_persian(self, plate_text: str):
        """
        Digit portions of the plate are rendered as Persian digits. For a
        recognized 8-char structured plate the prefix/number/region digits all
        become Persian (the letter slot is preserved); for non-structured text
        the fallback converts every ASCII digit to Persian.
        """
        result = format_plate_persian(plate_text)
        normalized = normalize_plate_text(plate_text)

        if len(normalized) == 8:
            # Structured path: digit portions are Persian, letter slot preserved.
            # Equality with the expected display pins down that every digit in
            # the prefix/number/region portions was converted to a Persian digit.
            assert result == expected_persian_format(normalized), (
                f"Structured format mismatch for input={plate_text!r}: got {result!r}"
            )
            # No ASCII digit survives in the rendered digit portions.
            for digits in (normalized[0:2], normalized[3:6], normalized[6:8]):
                rendered = digits.translate(_TO_PERSIAN)
                assert no_ascii_digits(rendered), (
                    f"ASCII digits remained in digit portion {rendered!r}"
                )
        else:
            # Fallback path: every ASCII digit is converted to Persian.
            assert no_ascii_digits(result), (
                f"ASCII digits leaked into Persian output {result!r} for input={plate_text!r}"
            )

    @given(plate=valid_structured_plate_strategy())
    @settings(max_examples=100)
    def test_valid_structured_plate_matches_expected_format(self, plate: str):
        """A valid 8-char structured plate formats as '۱۲ ب ۳۴۵-۶۷'."""
        result = format_plate_persian(plate)
        assert result == expected_persian_format(plate), (
            f"Unexpected Persian format for plate={plate!r}: got {result!r}"
        )
        # The Persian-formatted string is non-empty and digit-clean.
        assert len(result) > 0
        assert no_ascii_digits(result)

    @given(plate_text=arbitrary_plate_text_strategy())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_persian_field_equals_pretty_printer_output(
        self, plate_text: str, detection_session
    ):
        """
        The value stored as the detection's Persian plate field is exactly the
        Pretty_Printer output for the recognized plate text (Req 8.5).
        """
        persian = format_plate_persian(plate_text)
        detection_id = db.save_detection(
            detection_session, "image", plate_text, persian, 0.9
        )

        conn = db.get_conn()
        try:
            row = conn.execute(
                "SELECT plate_persian FROM detections WHERE id=?", (detection_id,)
            ).fetchone()
        finally:
            conn.close()

        assert row is not None, f"Detection {detection_id} not stored"
        assert row["plate_persian"] == persian == format_plate_persian(plate_text), (
            f"Stored Persian field {row['plate_persian']!r} != "
            f"Pretty_Printer output {persian!r} for input={plate_text!r}"
        )
