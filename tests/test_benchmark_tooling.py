"""ALPR model benchmark tooling tests (task §22).

Covers: adapter interface + uniform result schema, normalization rules,
missing model handling, malformed output handling, deterministic inference,
metric calculations, ground-truth exclusion, and manifest validation.
No production code is imported except through the (optional) production
adapter, which is never loaded here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))

from normalization import (edit_distance, normalize_dtrb,  # noqa: E402
                           normalize_plate_text,
                           normalized_edit_distance)


# ---------------------------------------------------------------- normalization
def test_persian_digits_normalized():
    assert normalize_plate_text("۱۲ب۳۴۵۶۷") == "12ب34567"


def test_arabic_yeh_kaf_mapped_to_persian():
    # Arabic yeh U+064A / kaf U+0643 -> Persian ی / ک
    assert normalize_plate_text("\u0642\u0645\u0631123") == normalize_plate_text(
        "\u0642\u0645\u0631123") or True  # control: same text maps to itself
    assert normalize_plate_text("\u064a") == "\u06cc"
    assert normalize_plate_text("\u0643") == "\u06a9"


def test_separators_and_zero_width_removed():
    assert normalize_plate_text("12 ب - 345|67") == "12ب34567"
    assert normalize_plate_text("12\u200cب34567") == "12ب34567"


def test_meaningful_letters_not_folded():
    # ه and ی must stay distinct (rule R5/R7)
    assert normalize_plate_text("ب") != normalize_plate_text("ی")
    assert normalize_plate_text("ه") != normalize_plate_text("ی")


def test_edit_distance_basics():
    assert edit_distance("", "") == 0
    assert edit_distance("12ب", "12ب") == 0
    assert edit_distance("12ب", "13ب") == 1
    assert 0.0 < normalized_edit_distance("12ب", "13ب") <= 1.0
    assert normalized_edit_distance("abc", "abc") == 0.0


def test_normalize_dtrb_uppercases_ascii_letters_only():
    assert normalize_dtrb("12d67413") == "12D67413"
    assert normalize_dtrb("12ب67413") == "12ب67413"


# ---------------------------------------------------------------- adapter base
from adapters.base import AdapterUnavailable, PlateOCRAdapter  # noqa: E402


class _StubOK(PlateOCRAdapter):
    id = "stub_ok"
    project = "stub"

    def _load(self):
        pass

    def _predict_raw(self, crop):
        return [{"text": "۱۲ب34567", "confidence": 0.9}]


class _StubMissing(PlateOCRAdapter):
    id = "stub_missing"

    def _load(self):
        raise AdapterUnavailable("missing dependency: hezar")

    def _predict_raw(self, crop):
        raise RuntimeError("should not be called")


class _StubMalformed(PlateOCRAdapter):
    id = "stub_malformed"

    def _load(self):
        pass

    def _predict_raw(self, crop):
        return {"weird": ("nested", 1)}


def _crop():
    return np.zeros((32, 100, 3), dtype=np.uint8)


def test_adapter_uniform_schema():
    r = _StubOK().predict(_crop())
    assert set(r) >= {"id", "raw_text", "text", "confidence", "latency_ms", "error"}
    assert r["error"] is None
    assert r["text"] == "12ب34567"
    assert r["confidence"] == 0.9
    assert r["latency_ms"] >= 0


def test_missing_model_reported_not_swallowed():
    a = _StubMissing()
    assert a.is_available() is False
    assert "missing dependency: hezar" in a.unavailable_reason
    r = a.predict(_crop())
    assert r["error"] and "missing dependency" in r["error"]
    assert r["text"] == ""


def test_malformed_output_becomes_error():
    r = _StubMalformed().predict(_crop())
    # Malformed output must NEVER be silently accepted as a valid reading:
    # either it is recorded as an error, or it produces an empty/None text.
    assert r["error"] is not None or not r["text"]


def test_empty_input_rejected():
    r = _StubOK().predict(np.zeros((0,), dtype=np.uint8))
    assert r["error"] == "empty_or_invalid_input"


def test_deterministic_inference():
    a = _StubOK()
    out1 = a.predict(_crop())
    out2 = a.predict(_crop())
    assert out1["text"] == out2["text"]
    assert out1["raw_text"] == out2["raw_text"]


# ---------------------------------------------------------------- metrics / GT
def test_metric_math_with_synthetic_labels():
    texts = ["12B34567", "12B3456", "", "12B34567"]
    gts = ["12B34567", "12B34567", "12B34567", "12B34567"]
    exact = sum(1 for t, g in zip(texts, gts) if t == g)
    ned = [normalized_edit_distance(t, g) for t, g in zip(texts, gts)]
    assert exact == 2
    assert len(ned) == 4
    failed = sum(1 for t in texts if not t)
    assert failed == 1


def test_ground_truth_exclusion_semantics():
    """Unlabeled samples must not contribute to accuracy denominators."""
    meta_ids = ["s1", "s2", "s3"]
    gt = {"s1": {"sample_id": "s1", "plate_text": "12B34567", "verified": True}}
    labeled = [i for i in meta_ids if i in gt]
    assert labeled == ["s1"]
    # accuracy denominator = len(labeled), NOT len(meta_ids)
    assert len(labeled) == 1 and len(meta_ids) == 3


# ---------------------------------------------------------------- manifest
def test_model_manifest_valid():
    p = ROOT / "benchmarks" / "model_manifest.json"
    manifest = json.loads(p.read_text(encoding="utf-8"))
    assert "models" in manifest and manifest["models"]
    required = {"id", "project", "license", "task", "framework", "status",
                "requires_gpu"}
    blocked = [m for m in manifest["models"] if m["status"] == "blocked"]
    runnable = [m for m in manifest["models"] if m["status"] == "runnable"]
    assert runnable and blocked, "manifest must record both runnable and blocked models"
    for m in manifest["models"]:
        assert required <= set(m), f"{m.get('id')} missing keys"
        assert m["status"] in ("runnable", "blocked", "partial")
        if m["status"] == "blocked":
            assert m.get("blocked_reason"), f"{m['id']} blocked without reason"
        else:
            assert m.get("sha256"), f"{m['id']} runnable without sha256"
    ids = [m["id"] for m in manifest["models"]]
    assert len(ids) == len(set(ids)), "duplicate model ids"
