"""
plate_validator.py
Validates detected plate text against Iranian license plate formats and returns metadata.
Acts as a filter gate — only plates conforming to valid Iranian formats pass through.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from plate_metadata import PlateMetadata, derive_metadata
from plate_reference import (
    LETTER_TO_CATEGORY,
    PERSIAN_LETTER_TO_CATEGORY,
    REGION_CODE_TO_PROVINCE,
)

# Persian digit → ASCII digit mapping
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
# Arabic-Indic digits
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Characters to strip when normalising (spaces, dashes, underscores)
_STRIP_RE = re.compile(r"[\s\-_]")

# ASCII digit → Persian digit mapping (for display formatting)
_TO_PERSIAN = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

# Latin letter → Persian letter mapping (for display formatting)
_LATIN_TO_PERSIAN_LETTER: dict[str, str] = {
    "b": "ب",
    "j": "ج",
    "d": "د",
    "s": "س",
    "l": "ل",
    "m": "م",
    "n": "ن",
    "v": "و",
    "o": "و",
    "u": "و",
    "w": "و",
    "h": "ه",
    "y": "ی",
    "i": "ی",
    "q": "ق",
    "r": "ر",
    "x": "خ",
    "t": "ت",
    "k": "ک",
    "a": "ا",
    "p": "پ",
    "c": "ث",
    "e": "ه",
    "z": "ز",
    "f": "ف",
    "g": "گ",
}


@dataclass
class ValidationResult:
    """Result of Iranian plate validation."""

    is_valid: bool
    plate_text: str  # normalized plate text
    metadata: PlateMetadata | None = None
    rejection_reason: str | None = None


def _normalize_digits(text: str) -> str:
    """Convert Persian/Arabic digits to ASCII digits."""
    return text.translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)


def _strip_separators(text: str) -> str:
    """Remove spaces, dashes, and underscores."""
    return _STRIP_RE.sub("", text)


def _is_valid_plate_letter(letter: str) -> bool:
    """Check if the letter is a recognized Iranian plate series letter."""
    lo = letter.lower()
    if lo in LETTER_TO_CATEGORY:
        return True
    if letter in PERSIAN_LETTER_TO_CATEGORY:
        return True
    if lo in PERSIAN_LETTER_TO_CATEGORY:
        return True
    return False


def validate_iranian_plate(
    dtrb_text: str, confidence: float, min_confidence: float = 0.4
) -> ValidationResult:
    """
    Validate a DTRB-recognized plate string against Iranian plate formats.

    Steps:
    1. Check minimum confidence threshold
    2. Normalize text (strip spaces, convert Persian/Arabic digits)
    3. Check length == 8 characters
    4. Validate structure: [2 digits][1 letter][3 digits][2 digits]
    5. Validate letter is a known Iranian plate series letter
    6. Validate region code exists in REGION_CODE_TO_PROVINCE
    7. Return metadata via derive_metadata() if valid

    Preconditions:
    - dtrb_text is a string (not None)
    - 0.0 <= confidence <= 1.0
    - 0.0 <= min_confidence <= 1.0

    Postconditions:
    - Returns ValidationResult with is_valid=True iff ALL checks pass
    - When is_valid=True: metadata is non-null and metadata.classified=True
    - When is_valid=False: rejection_reason is a non-empty string, metadata is None
    """
    # Step 1: Confidence gate
    if confidence < min_confidence:
        return ValidationResult(
            is_valid=False,
            plate_text=dtrb_text,
            rejection_reason=f"Below confidence threshold ({confidence:.2f} < {min_confidence})",
        )

    # Step 2: Normalize text
    normalized = _normalize_digits(dtrb_text)
    normalized = _strip_separators(normalized)

    # Step 3: Length check
    if len(normalized) != 8:
        return ValidationResult(
            is_valid=False,
            plate_text=normalized,
            rejection_reason=f"Invalid length: expected 8 characters, got {len(normalized)}",
        )

    # Step 4: Structure validation
    prefix = normalized[0:2]  # positions 0-1: digits
    letter = normalized[2]  # position 2: letter
    number = normalized[3:6]  # positions 3-5: digits
    region = normalized[6:8]  # positions 6-7: digits

    if not prefix.isdigit():
        return ValidationResult(
            is_valid=False,
            plate_text=normalized,
            rejection_reason=f"Invalid digit positions: positions 0-1 ('{prefix}') are not digits",
        )

    if not number.isdigit():
        return ValidationResult(
            is_valid=False,
            plate_text=normalized,
            rejection_reason=f"Invalid digit positions: positions 3-5 ('{number}') are not digits",
        )

    if not region.isdigit():
        return ValidationResult(
            is_valid=False,
            plate_text=normalized,
            rejection_reason=f"Invalid digit positions: positions 6-7 ('{region}') are not digits",
        )

    # Step 5: Series letter validation
    if not _is_valid_plate_letter(letter):
        return ValidationResult(
            is_valid=False,
            plate_text=normalized,
            rejection_reason=f"Unknown series letter: '{letter}'",
        )

    # Step 6: Region code validation
    if region not in REGION_CODE_TO_PROVINCE:
        return ValidationResult(
            is_valid=False,
            plate_text=normalized,
            rejection_reason=f"Unknown region code: '{region}'",
        )

    # Step 7: Derive full metadata
    metadata = derive_metadata(normalized)

    return ValidationResult(
        is_valid=True,
        plate_text=normalized,
        metadata=metadata,
        rejection_reason=None,
    )


def format_plate_persian(dtrb_text: str) -> str:
    """
    Format a plate string into Persian display format like "۱۲ ب ۳۴۵-۶۷".

    Accepts raw DTRB text (latin letters, mixed digit formats).
    If the text cannot be parsed into 8-char plate structure, returns
    the original text with Persian digit conversion applied.
    """
    # Normalize digits and strip separators
    normalized = _normalize_digits(dtrb_text)
    normalized = _strip_separators(normalized)

    if len(normalized) != 8:
        # Cannot format as standard plate; return with Persian digits
        return dtrb_text.translate(_TO_PERSIAN)

    prefix = normalized[0:2]
    letter = normalized[2]
    number = normalized[3:6]
    region = normalized[6:8]

    # Convert letter to Persian if it's a latin letter
    persian_letter = _LATIN_TO_PERSIAN_LETTER.get(letter.lower(), letter)

    # Convert digits to Persian
    persian_prefix = prefix.translate(_TO_PERSIAN)
    persian_number = number.translate(_TO_PERSIAN)
    persian_region = region.translate(_TO_PERSIAN)

    # Format: "۱۲ ب ۳۴۵-۶۷"
    return f"{persian_prefix} {persian_letter} {persian_number}-{persian_region}"
