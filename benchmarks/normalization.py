"""Single normalization layer applied to EVERY OCR model output before
comparison (task §9). Rules are explicit and documented; nothing that changes
a meaningful plate character is folded away.

Rules (applied in order):

  R1  Unicode NFC normalization.
  R2  Remove zero-width characters: U+200B, U+200C, U+200D, U+FEFF.
  R3  Remove separators: space, dash/underscore/dot, Unicode dash variants
      (U+2010..U+2015), and the '|' divider used inside Iranian plate photos.
  R4  Convert Arabic-Indic and Extended Arabic-Indic digits (U+06F0..U+06F9,
      U+0660..U+0669) to ASCII digits.
  R5  Convert Arabic/Urdu presentation variants to canonical Persian forms:
      ي (U+064A) -> ی (U+06CC), ك (U+0643) -> ک (U+06A9),
      ه‍ (heh + ZWNJ) handled by R2 + R3; Arabic ه (U+0647) is KEPT distinct
      from ی and و (never folded together).
  R6  Uppercase Latin letters (plate letters like B/D/S from Latin-output
      models map to the same Persian letter only through the transliteration
      table, NOT here — case folding is safe and applied: 'b' -> 'B').
  R7  Keep Persian plate letters exactly as produced: ب پ ت ث ج چ ح خ د ذ ر ز
      ژ س ش ص ض ط ظ ع غ ف ق ک گ ل م ن و ه ی.  Do NOT transliterate them to
      Latin here (that would erase model-specific differences for confusion
      analysis). Latin transliteration is a separate, explicitly-labelled
      mapping in the adapters that need it.

Everything else (noise characters, HTML entities, control chars) is removed.
"""
from __future__ import annotations

import unicodedata

ZERO_WIDTH = "\u200b\u200c\u200d\ufeff"
SEPARATORS = " -_.\u2010\u2011\u2012\u2013\u2014\u2015|/\u00a0\t"

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"

CHAR_MAP = {
    "\u064a": "\u06cc",  # Arabic yeh -> Persian yeh
    "\u0643": "\u06a9",  # Arabic kaf -> Persian keheh
}

_ALLOWED_EXTRA = set("?!*#")  # removed, but tracked for debugging


def normalize_plate_text(text: str | None) -> str:
    """Normalize one OCR output string per rules R1-R6 (R7 = no-op here)."""
    if not text:
        return ""
    s = unicodedata.normalize("NFC", str(text))
    out = []
    for ch in s:
        if ch in ZERO_WIDTH:
            continue
        if ch in SEPARATORS:
            continue
        if ch in _ALLOWED_EXTRA:
            continue
        if ch in PERSIAN_DIGITS:
            out.append(str(PERSIAN_DIGITS.index(ch)))
            continue
        if ch in ARABIC_DIGITS:
            out.append(str(ARABIC_DIGITS.index(ch)))
            continue
        ch = CHAR_MAP.get(ch, ch)
        if ch.isalpha() or ch.isdigit():
            if ch.isascii() and ch.isalpha():
                out.append(ch.upper())
            else:
                out.append(ch)
        # anything else: dropped (noise)
    return "".join(out)


def normalize_dtrb(text: str | None) -> str:
    """Normalize the production DTRB romanized output (e.g. '12d67413').

    The DTRB/production charset is ASCII digits + lowercase letters where
    d/s/t/h/etc. stand for Persian letters (see video_processor.DTRB_TO_PERSIAN).
    We uppercase ASCII letters so comparisons against Persian outputs go
    through a documented transliteration table (see adapters.translate_fa_to_ascii)
    and never silently.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFC", str(text))
    return "".join(ch.upper() if ch.isascii() and ch.isalpha() else ch
                   for ch in s if ch.isalnum())


# Documented Persian-letter -> production-ASCII transliteration (used only in
# explicitly-labelled cross-charset comparisons, never silently).
FA_TO_ASCII = {
    "الف": "A", "ب": "B", "پ": "P", "ت": "T", "ث": "G", "ج": "J", "چ": "C",
    "ح": "E", "خ": "X", "د": "D", "ذ": "Z", "ر": "R", "ز": "Z", "ژ": "W",
    "س": "S", "ش": "U", "ص": "A", "ض": "D", "ط": "X", "ظ": "Z", "ع": "I",
    "غ": "Q", "ف": "F", "ق": "Q", "ک": "K", "گ": "G", "ل": "L", "م": "M",
    "ن": "N", "و": "V", "ه": "H", "ی": "Y",
}


def edit_distance(a: str, b: str) -> int:
    """Plain Levenshtein distance (iterative, two-row)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def normalized_edit_distance(a: str, b: str) -> float:
    """Levenshtein distance normalized by the longer string's length (0..1)."""
    if not a and not b:
        return 0.0
    return edit_distance(a, b) / max(len(a), len(b))
