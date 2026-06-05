"""
plate_metadata.py
Derives Iranian license plate metadata (category, color, region) from a recognized plate string.
Accepts both Persian and latin (dtrb) encoded plates. Never raises — always returns PlateMetadata.
Requirements: 14.1, 14.3, 14.4, 14.5, 14.6, 14.8
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re

from plate_reference import (
    LETTER_TO_CATEGORY,
    PERSIAN_LETTER_TO_CATEGORY,
    CATEGORY_TO_COLOR,
    CATEGORY_DISPLAY,
    REGION_CODE_TO_PROVINCE,
    FREE_ZONE_PREFIXES,
)

# Persian digit → ASCII digit mapping
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
# Arabic-Indic digits
_ARABIC_DIGITS  = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Characters to strip when normalising a formatted plate (spaces, dashes)
_STRIP_RE = re.compile(r"[\s\-_]")


@dataclass
class PlateMetadata:
    classified: bool
    category: str | None = None
    category_display: str | None = None
    color_scheme: str | None = None       # one of white|yellow|green|red|blue|black
    region_code: str | None = None        # 2-digit string e.g. "11"
    region_name: str | None = None        # province name or "Unknown"
    special_note: str | None = None
    reason: str | None = None             # populated only when classified is False


def _normalise_digits(text: str) -> str:
    return text.translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)


def _strip_separators(text: str) -> str:
    return _STRIP_RE.sub("", text)


def _resolve_letter(letter: str) -> str | None:
    """Return the canonical category key for a letter, trying latin then Persian lookup."""
    lo = letter.lower()
    if lo in LETTER_TO_CATEGORY:
        return LETTER_TO_CATEGORY[lo]
    if letter in PERSIAN_LETTER_TO_CATEGORY:
        return PERSIAN_LETTER_TO_CATEGORY[letter]
    # Try normalised lowercase Persian
    if lo in PERSIAN_LETTER_TO_CATEGORY:
        return PERSIAN_LETTER_TO_CATEGORY[lo]
    return None


def normalize_plate(raw: str | None) -> tuple[str, str, str] | None:
    """
    Parse a raw plate string (Persian or latin) into (prefix_2, letter, suffix_5).
    Returns (prefix_digits_2, series_letter, region_code_2) tuple or None.

    Steps:
      1. Reject None / empty / whitespace-only.
      2. Normalise Persian/Arabic digits → ASCII digits.
      3. Strip formatting separators (spaces, dashes).
      4. Validate token shape: [0-9]{2}[letter][0-9]{5}  (total 8 chars)
         where the letter may be Latin a-z or any single Persian/Arabic letter.
    """
    if not raw or not raw.strip():
        return None

    text = _normalise_digits(raw.strip())
    text = _strip_separators(text)

    # Must be exactly 8 chars
    if len(text) != 8:
        return None

    prefix = text[:2]
    letter = text[2]
    number = text[3:6]
    region = text[6:8]

    # Validate digits
    if not (prefix.isdigit() and number.isdigit() and region.isdigit()):
        return None

    # Validate letter: latin a-z (ASCII) or a single Unicode non-digit/non-ASCII char
    is_latin_letter = letter.isascii() and letter.isalpha()
    is_persian_letter = not letter.isascii() and not letter.isdigit()
    if not (is_latin_letter or is_persian_letter):
        return None

    return (prefix, letter, region)


def derive_metadata(raw: str | None) -> PlateMetadata:
    """
    Derive full metadata from a raw plate string. Always returns a PlateMetadata; never raises.
    Returns classified=False with a reason for all invalid/malformed/null/empty inputs.
    Requirements: 14.1, 14.3, 14.4, 14.5, 14.6, 14.8
    """
    try:
        return _derive(raw)
    except Exception as exc:  # pragma: no cover — safety net
        return PlateMetadata(classified=False, reason=f"Internal error: {exc}")


def _derive(raw: str | None) -> PlateMetadata:
    # Step 1: reject empty / whitespace-only
    if raw is None:
        return PlateMetadata(classified=False, reason="Plate value is null")
    stripped = raw.strip()
    if not stripped:
        return PlateMetadata(classified=False, reason="Plate value is empty or whitespace")

    # Step 2: try to parse
    parsed = normalize_plate(stripped)
    if parsed is None:
        return PlateMetadata(
            classified=False,
            reason=(
                f"Plate '{stripped}' does not conform to the standard Iranian plate "
                "structure (2 digits + 1 letter + 3 digits + 2-digit region code)"
            ),
        )

    prefix, letter, region_code = parsed

    # Step 3: resolve letter to category
    category = _resolve_letter(letter)
    if category is None:
        category = "Unknown"

    color_scheme = CATEGORY_TO_COLOR.get(category, "white")
    category_display = CATEGORY_DISPLAY.get(category, category)

    # Step 4: resolve region code
    region_name = REGION_CODE_TO_PROVINCE.get(region_code)
    if region_name is None:
        region_name = f"Unknown (code {region_code})"

    # Step 5: free-zone special note
    special_note: str | None = None
    if category == "FreeZone_Arvand":
        special_note = FREE_ZONE_PREFIXES.get(prefix, "Free Zone plate")

    return PlateMetadata(
        classified=True,
        category=category,
        category_display=category_display,
        color_scheme=color_scheme,
        region_code=region_code,
        region_name=region_name,
        special_note=special_note,
    )
