"""
test_plate_validator.py
Unit tests for validate_iranian_plate() and format_plate_persian().
Requirements: 5.1, 5.2, 5.3, 5.5, 5.8, 5.9, 5.10, 5.11
"""
import pytest
import sys
import os

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plate_validator import validate_iranian_plate, format_plate_persian


# ── Valid plates ──────────────────────────────────────────────────────────────


class TestValidPlates:
    """Requirement 5.11 — valid plates return is_valid=True with metadata."""

    def test_valid_private_plate_letter_b(self):
        """Valid private plate with letter 'b' and region 11 (Tehran)."""
        result = validate_iranian_plate("12b34511", confidence=0.9)
        assert result.is_valid is True
        assert result.plate_text == "12b34511"
        assert result.metadata is not None
        assert result.metadata.classified is True
        assert result.metadata.category == "Private"
        assert result.metadata.color_scheme == "white"
        assert result.metadata.region_code == "11"

    def test_valid_private_plate_letter_j(self):
        """Valid private plate with letter 'j' and region 22 (Tehran)."""
        result = validate_iranian_plate("99j12322", confidence=0.8)
        assert result.is_valid is True
        assert result.metadata.category == "Private"
        assert result.metadata.region_code == "22"

    def test_valid_private_plate_letter_d(self):
        """Valid private plate with letter 'd' and region 38 (Alborz)."""
        result = validate_iranian_plate("45d67838", confidence=0.5)
        assert result.is_valid is True
        assert result.metadata.category == "Private"
        assert result.metadata.region_code == "38"

    def test_valid_private_plate_letter_s(self):
        """Valid private plate with letter 's' and region 13 (Isfahan)."""
        result = validate_iranian_plate("11s99913", confidence=0.7)
        assert result.is_valid is True
        assert result.metadata.category == "Private"

    def test_valid_taxi_plate(self):
        """Valid taxi plate with letter 't' — yellow color."""
        result = validate_iranian_plate("12t34511", confidence=0.85)
        assert result.is_valid is True
        assert result.metadata.category == "Taxi"
        assert result.metadata.color_scheme == "yellow"

    def test_valid_government_plate(self):
        """Valid government plate with letter 'a' — red color."""
        result = validate_iranian_plate("12a34511", confidence=0.9)
        assert result.is_valid is True
        assert result.metadata.category == "Government"
        assert result.metadata.color_scheme == "red"

    def test_valid_police_plate(self):
        """Valid police plate with letter 'p' — green color."""
        result = validate_iranian_plate("12p34511", confidence=0.75)
        assert result.is_valid is True
        assert result.metadata.category == "Police"
        assert result.metadata.color_scheme == "green"

    def test_valid_plate_region_63_fars(self):
        """Valid plate with region 63 (Fars)."""
        result = validate_iranian_plate("10b10063", confidence=0.6)
        assert result.is_valid is True
        assert "فارس" in result.metadata.region_name

    def test_valid_plate_exact_threshold(self):
        """Confidence exactly at threshold (0.4) should be accepted."""
        result = validate_iranian_plate("12b34511", confidence=0.4)
        assert result.is_valid is True


# ── Invalid length (Requirement 5.3) ─────────────────────────────────────────


class TestInvalidLength:
    """Requirement 5.3 — normalized text length != 8 is rejected."""

    def test_too_short(self):
        """Plate text shorter than 8 chars is rejected."""
        result = validate_iranian_plate("12b345", confidence=0.9)
        assert result.is_valid is False
        assert "length" in result.rejection_reason.lower()

    def test_too_long(self):
        """Plate text longer than 8 chars is rejected."""
        result = validate_iranian_plate("12b345678", confidence=0.9)
        assert result.is_valid is False
        assert "length" in result.rejection_reason.lower()

    def test_empty_string(self):
        """Empty string is rejected for invalid length."""
        result = validate_iranian_plate("", confidence=0.9)
        assert result.is_valid is False
        assert "length" in result.rejection_reason.lower()

    def test_single_character(self):
        """Single character is rejected."""
        result = validate_iranian_plate("a", confidence=0.9)
        assert result.is_valid is False
        assert result.rejection_reason is not None


# ── Invalid letter position (Requirement 5.5) ────────────────────────────────


class TestInvalidLetterPosition:
    """Requirement 5.5 — position 2 must be a recognized series letter."""

    def test_digit_at_position_2(self):
        """Digit at position 2 instead of letter is rejected."""
        result = validate_iranian_plate("12334511", confidence=0.9)
        assert result.is_valid is False
        assert "letter" in result.rejection_reason.lower() or "digit" in result.rejection_reason.lower()

    def test_unknown_character_at_position_2(self):
        """Unknown character '!' at position 2 is rejected."""
        result = validate_iranian_plate("12!34511", confidence=0.9)
        assert result.is_valid is False

    def test_number_symbol_at_position_2(self):
        """Number symbol at position 2 is rejected."""
        result = validate_iranian_plate("12234511", confidence=0.9)
        assert result.is_valid is False


# ── Unknown region codes (Requirement 5.8) ────────────────────────────────────


class TestUnknownRegionCode:
    """Requirement 5.8 — region code not in registry is rejected."""

    def test_region_00(self):
        """Region code '00' does not exist."""
        result = validate_iranian_plate("12b34500", confidence=0.9)
        assert result.is_valid is False
        assert "region" in result.rejection_reason.lower()

    def test_region_01(self):
        """Region code '01' does not exist."""
        result = validate_iranian_plate("12b34501", confidence=0.9)
        assert result.is_valid is False
        assert "region" in result.rejection_reason.lower()

    def test_region_02(self):
        """Region code '02' does not exist."""
        result = validate_iranian_plate("12b34502", confidence=0.9)
        assert result.is_valid is False
        assert "region" in result.rejection_reason.lower()


# ── Low confidence rejection (Requirement 5.9) ────────────────────────────────


class TestLowConfidenceRejection:
    """Requirement 5.9 — confidence < 0.4 always rejected."""

    def test_confidence_below_threshold(self):
        """Valid plate format but confidence 0.3 is rejected."""
        result = validate_iranian_plate("12b34511", confidence=0.3)
        assert result.is_valid is False
        assert "confidence" in result.rejection_reason.lower()

    def test_confidence_zero(self):
        """Zero confidence is rejected."""
        result = validate_iranian_plate("12b34511", confidence=0.0)
        assert result.is_valid is False
        assert "confidence" in result.rejection_reason.lower()

    def test_confidence_just_below_threshold(self):
        """Confidence 0.39 (just below 0.4) is rejected."""
        result = validate_iranian_plate("12b34511", confidence=0.39)
        assert result.is_valid is False
        assert "confidence" in result.rejection_reason.lower()

    def test_invalid_plate_with_low_confidence(self):
        """Invalid plate text with low confidence — rejected for confidence first."""
        result = validate_iranian_plate("abc", confidence=0.1)
        assert result.is_valid is False
        assert "confidence" in result.rejection_reason.lower()


# ── Persian/Arabic digit normalization (Requirement 5.1) ──────────────────────


class TestDigitNormalization:
    """Requirement 5.1 — Persian/Arabic digits normalized to ASCII."""

    def test_persian_digits_valid_plate(self):
        """Persian digits '۱۲b۳۴۵۱۱' normalized to '12b34511'."""
        result = validate_iranian_plate("۱۲b۳۴۵۱۱", confidence=0.9)
        assert result.is_valid is True
        assert result.plate_text == "12b34511"

    def test_all_persian_digits(self):
        """Fully Persian-encoded digits with latin letter."""
        result = validate_iranian_plate("۹۹j۱۲۳۲۲", confidence=0.8)
        assert result.is_valid is True
        assert result.plate_text == "99j12322"

    def test_arabic_indic_digits(self):
        """Arabic-Indic digits (٠١٢...) normalized to ASCII."""
        # ١٢b٣٤٥١١ → 12b34511
        result = validate_iranian_plate("١٢b٣٤٥١١", confidence=0.9)
        assert result.is_valid is True
        assert result.plate_text == "12b34511"

    def test_mixed_persian_ascii_digits(self):
        """Mix of Persian and ASCII digits normalized correctly."""
        result = validate_iranian_plate("1۲b3۴۵11", confidence=0.9)
        assert result.is_valid is True
        assert result.plate_text == "12b34511"


# ── Separator stripping (Requirement 5.2) ─────────────────────────────────────


class TestSeparatorStripping:
    """Requirement 5.2 — spaces, dashes, underscores stripped."""

    def test_dashes_stripped(self):
        """Plate with dashes '12-b-345-11' normalizes to '12b34511'."""
        result = validate_iranian_plate("12-b-345-11", confidence=0.9)
        assert result.is_valid is True
        assert result.plate_text == "12b34511"

    def test_spaces_stripped(self):
        """Plate with spaces '12 b 345 11' normalizes to '12b34511'."""
        result = validate_iranian_plate("12 b 345 11", confidence=0.9)
        assert result.is_valid is True
        assert result.plate_text == "12b34511"

    def test_underscores_stripped(self):
        """Plate with underscores '12_b_345_11' normalizes to '12b34511'."""
        result = validate_iranian_plate("12_b_345_11", confidence=0.9)
        assert result.is_valid is True
        assert result.plate_text == "12b34511"

    def test_mixed_separators(self):
        """Mixed separators '12-b 345_11' stripped."""
        result = validate_iranian_plate("12-b 345_11", confidence=0.9)
        assert result.is_valid is True
        assert result.plate_text == "12b34511"


# ── Edge cases (Requirement 5.10) ────────────────────────────────────────────


class TestEdgeCases:
    """Requirement 5.10 — rejection reason for all invalid inputs."""

    def test_whitespace_only(self):
        """Whitespace-only input is rejected."""
        result = validate_iranian_plate("   ", confidence=0.9)
        assert result.is_valid is False
        assert result.rejection_reason is not None

    def test_single_char(self):
        """Single character input is rejected."""
        result = validate_iranian_plate("x", confidence=0.9)
        assert result.is_valid is False
        assert result.rejection_reason is not None

    def test_rejection_reason_always_provided(self):
        """All invalid results have a non-empty rejection_reason."""
        invalid_inputs = [
            ("", 0.9),
            ("short", 0.9),
            ("12334511", 0.9),       # digit at letter position
            ("12b34500", 0.9),       # unknown region
            ("12b34511", 0.1),       # low confidence
            ("toolongtext123", 0.9), # too long
        ]
        for text, conf in invalid_inputs:
            result = validate_iranian_plate(text, confidence=conf)
            assert result.is_valid is False, f"Expected invalid for {text!r}"
            assert result.rejection_reason is not None, f"No reason for {text!r}"
            assert len(result.rejection_reason) > 0, f"Empty reason for {text!r}"

    def test_metadata_none_when_invalid(self):
        """Metadata is None for all invalid results."""
        invalid_inputs = ["", "short", "12334511", "12b34500", "toolong123"]
        for text in invalid_inputs:
            result = validate_iranian_plate(text, confidence=0.9)
            assert result.is_valid is False
            assert result.metadata is None, f"Metadata should be None for {text!r}"


# ── format_plate_persian() tests ──────────────────────────────────────────────


class TestFormatPlatePersian:
    """Test Persian plate formatting function."""

    def test_valid_8char_plate(self):
        """Valid 8-char plate formats as '۱۲ ب ۳۴۵-۱۱'."""
        result = format_plate_persian("12b34511")
        assert result == "۱۲ ب ۳۴۵-۱۱"

    def test_valid_plate_with_taxi_letter(self):
        """Taxi plate 't' formats as '۱۲ ت ۳۴۵-۱۱'."""
        result = format_plate_persian("12t34511")
        assert result == "۱۲ ت ۳۴۵-۱۱"

    def test_valid_plate_with_separators(self):
        """Plate with separators is normalized then formatted."""
        result = format_plate_persian("12-b-345-11")
        assert result == "۱۲ ب ۳۴۵-۱۱"

    def test_valid_plate_persian_digits_input(self):
        """Persian digits in input are normalized then formatted."""
        result = format_plate_persian("۱۲b۳۴۵۱۱")
        assert result == "۱۲ ب ۳۴۵-۱۱"

    def test_non_standard_length_returns_persian_digits(self):
        """Non-8-char input returns raw text with Persian digits applied."""
        result = format_plate_persian("12345")
        assert result == "۱۲۳۴۵"

    def test_empty_string(self):
        """Empty string returns empty string."""
        result = format_plate_persian("")
        assert result == ""

    def test_short_text_persian_conversion(self):
        """Short text still gets Persian digit conversion."""
        result = format_plate_persian("abc123")
        assert result == "abc۱۲۳"
