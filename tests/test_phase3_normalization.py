"""Phase 3 tests — normalization (task §17/§37)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmarks.metrics import canonical as phase2_canonical  # noqa: E402
from benchmarks.phase3_normalization import (  # noqa: E402
    canonical_forms, extract_region_code,
    normalize_to_ascii, normalize_to_persian)


def test_task_example_spells_converge():
    """۱۲د۶۷۴۱۳ / 12د67413 / 12د67413 must have one
    deterministic canonical representation."""
    a = canonical_forms("۱۲د۶۷۴۱۳")
    b = canonical_forms("12د67413")
    c = canonical_forms("12د67413")
    assert a["plate_text_normalized"] == \
        b["plate_text_normalized"] == \
        c["plate_text_normalized"]
    assert a["plate_text_ascii"] == \
        b["plate_text_ascii"] == \
        c["plate_text_ascii"] == "12D67413"


def test_persian_arabic_latin_digits_equivalent():
    p = normalize_to_ascii("۱۲")
    a = normalize_to_ascii("١٢")
    l = normalize_to_ascii("12")
    assert p == a == l == "12"


def test_persian_letter_variants_folded():
    assert normalize_to_persian("ي") == "ی"   # Arabic yeh
    assert normalize_to_persian("ك") == "ک"   # Arabic kaf
    assert normalize_to_persian("أ") == "ا"   # alef variants
    assert normalize_to_persian("إ") == "ا"
    assert normalize_to_persian("آ") == "ا"


def test_raw_is_preserved_verbatim():
    raw = " ۱۲د۶۷۴۱۳ "
    forms = canonical_forms(raw)
    assert forms["plate_text_raw"] == raw
    assert forms["plate_text_raw"] is raw


def test_normalization_is_idempotent():
    for text in ("۱۲د۶۷۴۱۳", "12د67413", "۲۸ی۶۸۹۲۳"):
        once = normalize_to_persian(text)
        assert normalize_to_persian(once) == once
        once_a = normalize_to_ascii(text)
        assert normalize_to_ascii(once_a) == once_a


def test_separators_and_zero_width_removed():
    assert normalize_to_ascii("۱۲-د۶۷-۴۱۳") == "12D67413"
    assert normalize_to_ascii("۱۲ د۶۷۴۱۳") == "12D67413"
    assert normalize_to_ascii("۱۲‍د۶۷۴۱۳") == "12D67413"


def test_empty_and_none():
    assert normalize_to_persian(None) == ""
    assert normalize_to_ascii("") == ""
    assert canonical_forms(None)["plate_text_ascii"] == ""


def test_phase2_canonical_consistency():
    """The Phase 3 ascii form must equal the Phase 2
    canonical comparison form so cross-phase metrics
    stay comparable."""
    for text in ("۱۲د۶۷۴۱۳", "۲۸ی۶۸۹۲۳", "12d67413",
                 "۲۵ه۲۸۹۹۹"):
        assert normalize_to_ascii(text) == \
            phase2_canonical(text)


def test_latin_output_uppercased_deterministically():
    assert normalize_to_ascii("12d67413") == "12D67413"
    assert normalize_to_ascii("12D67413") == "12D67413"


def test_region_code_extraction():
    assert extract_region_code("12D67413") == "13"
    assert extract_region_code("28Y68923") == "23"
    assert extract_region_code("25H28999") == "99"


def test_region_code_none_for_non_civilian_patterns():
    assert extract_region_code("") is None
    assert extract_region_code("12D") is None
    assert extract_region_code("taxi") is None


def test_noise_characters_removed():
    assert normalize_to_ascii("۱۲د۶۷۴۱۳!!!") == "12D67413"
    assert normalize_to_ascii("??۱۲د۶۷۴۱۳##") == "12D67413"
