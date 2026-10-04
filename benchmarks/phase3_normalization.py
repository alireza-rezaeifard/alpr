"""Phase 3 — canonical plate-text normalization.

Three explicitly-labelled forms are produced from every human
transcription or OCR output:

  plate_text_raw        — the original string, NEVER altered.
  plate_text_normalized — canonical Unicode form: Persian
                          letters canonicalized, ALL digits
                          (Persian U+06F0-06F9, Arabic-Indic
                          U+0660-0669, Latin 0-9) rendered as
                          PERSIAN digits, separators and
                          zero-width characters removed. This is
                          the human-readable canonical form.
  plate_text_ascii      — canonical comparison form for scoring:
                          ASCII digits + ASCII letters via the
                          documented FA_TO_ASCII table. This is
                          identical to benchmarks.metrics.canonical
                          applied to the normalized form, so
                          Phase 3 metrics stay comparable with
                          Phase 2A/2B/2C/2D.

Rules (order matters):
  N1  Unicode NFC.
  N2  Remove zero-width: U+200B, U+200C, U+200D, U+FEFF.
  N3  Remove separators: space, dash, underscore, dot, Unicode
      dash variants (U+2010..U+2015), '|', '/', NBSP, tab.
  N4  Digit unification to Persian digits (normalized form) or
      ASCII digits (ascii form).
  N5  Letter-variant folding to canonical Persian forms:
        ي (Arabic yeh, U+064A)      -> ی (U+06CC)
        ك (Arabic kaf, U+0643)       -> ک (U+06A9)
        أ إ آ ا (alef variants)      -> ا (U+0627)
        ۀ (U+06C0)                   -> ه (U+0647)
      ه (U+0647) is KEPT distinct from ی and و.
  N6  Latin letters: uppercased in the ascii form.
  N7  Anything else (noise, control chars, HTML entities) is
      removed.

The transformation is deterministic and idempotent:
normalize(normalize(x)) == normalize(x).
"""
from __future__ import annotations

import unicodedata

# Reuse the Phase 2 documented transliteration table so the
# ascii comparison form stays byte-identical to Phase 2 scoring.
from benchmarks.normalization import FA_TO_ASCII  # noqa: E402

ZERO_WIDTH = "​‌‍﻿"

SEPARATORS = " -_.\u2010\u2011\u2012\u2013\u2014\u2015|/\u00a0\t"

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
LATIN_DIGITS = "0123456789"

# Persian letter -> index (canonical plate alphabet order used by
# the production DTRB charset; only folding matters here, the
# order is irrelevant to correctness).
LETTER_VARIANT_MAP = {
    "ي": "ی",   # Arabic yeh -> Persian yeh
    "ك": "ک",   # Arabic kaf -> Persian keheh
    "أ": "ا",   # alef variants -> alef
    "إ": "ا",
    "آ": "ا",
    "ا": "ا",
    "ۀ": "ه",   # heh with hamza above -> heh
}

# Characters that may appear in a canonical normalized plate:
# Persian digits, canonical Persian letters, and (ascii form
# only) Latin letters/digits.
PERSIAN_LETTERS = set("ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی")


def _fold_variants(ch: str) -> str:
    return LETTER_VARIANT_MAP.get(ch, ch)


def _digit_to_persian(ch: str) -> str | None:
    if ch in PERSIAN_DIGITS:
        return ch
    if ch in ARABIC_INDIC_DIGITS:
        return PERSIAN_DIGITS[ARABIC_INDIC_DIGITS.index(ch)]
    if ch in LATIN_DIGITS:
        return PERSIAN_DIGITS[LATIN_DIGITS.index(ch)]
    return None


def _digit_to_ascii(ch: str) -> str | None:
    if ch in PERSIAN_DIGITS:
        return str(PERSIAN_DIGITS.index(ch))
    if ch in ARABIC_INDIC_DIGITS:
        return str(ARABIC_INDIC_DIGITS.index(ch))
    if ch in LATIN_DIGITS:
        return ch
    return None


def normalize_to_persian(text: str | None) -> str:
    """Canonical human-readable form (Persian letters + Persian
    digits). Deterministic; idempotent."""
    if not text:
        return ""
    s = unicodedata.normalize("NFC", str(text))
    out = []
    for ch in s:
        if ch in ZERO_WIDTH or ch in SEPARATORS:
            continue
        d = _digit_to_persian(ch)
        if d is not None:
            out.append(d)
            continue
        folded = _fold_variants(ch)
        if folded in PERSIAN_LETTERS:
            out.append(folded)
            continue
        if ch.isascii() and ch.isalpha():
            # Latin-output models: keep Latin letters out of the
            # Persian-normalized form is NOT desired — the three
            # example spellings must converge. Latin letters are
            # carried through so downstream transliteration can
            # map them; they are uppercased for determinism.
            out.append(ch.upper())
    return "".join(out)


def normalize_to_ascii(text: str | None) -> str:
    """Canonical comparison form (ASCII digits + ASCII letters).

    Identical to benchmarks.metrics.canonical applied to
    normalize_to_persian(text) — asserted by the test suite.
    """
    if not text:
        return ""
    norm = normalize_to_persian(text)
    out = []
    for ch in norm:
        d = _digit_to_ascii(ch)
        if d is not None:
            out.append(d)
            continue
        if ch in FA_TO_ASCII:
            out.append(FA_TO_ASCII[ch])
            continue
        if ch.isascii() and ch.isalpha():
            out.append(ch.upper())
    return "".join(out)


def canonical_forms(raw: str | None) -> dict:
    """Return all three forms plus derived fields.

    The raw string is preserved verbatim (never mutated).
    """
    normalized = normalize_to_persian(raw)
    ascii_form = normalize_to_ascii(raw)
    return {
        "plate_text_raw": raw if raw is not None else "",
        "plate_text_normalized": normalized,
        "plate_text_ascii": ascii_form,
    }


def extract_region_code(plate_text_ascii: str) -> str | None:
    """Two-digit region block of a civilian Iranian plate
    (the last two digits of the 5-digit numeric suffix).

    Civilian pattern: DDLDDD (2 digits, 1 letter, 2 digits,
    3 digits) e.g. 12D67413 -> region '13'.
    Returns None when the pattern does not match.
    """
    if not plate_text_ascii:
        return None
    import re
    m = re.fullmatch(r"(\d{2})([A-Z])(\d{2})(\d{3})",
                     plate_text_ascii)
    if not m:
        return None
    return m.group(4)[-2:]


def is_persian_plate_like(text: str | None) -> bool:
    """True when the normalized form is non-empty and contains
    only canonical plate characters."""
    norm = normalize_to_persian(text)
    if not norm:
        return False
    return all(
        ch in PERSIAN_DIGITS or ch in PERSIAN_LETTERS
        or (ch.isascii() and ch.isalnum())
        for ch in norm)
