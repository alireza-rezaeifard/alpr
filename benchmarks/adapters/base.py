"""Common adapter interface for every OCR model in the benchmark (task §4).

All adapters receive the EXACT SAME plate crop (BGR numpy array or file path)
and return a uniform result dict so metric computation is model-agnostic.
Adapters must never modify the input image in place.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root (D:\alpr)
BENCH_DIR = ROOT / "benchmarks"
if str(BENCH_DIR) not in sys.path:
    sys.path.insert(0, str(BENCH_DIR))

from normalization import normalize_plate_text  # noqa: E402


class AdapterUnavailable(Exception):
    """Raised when a model cannot be loaded/run; carries the exact reason."""


class PlateOCRAdapter:
    """Base class: benchmark-facing OCR interface.

    Subclasses implement ``_load()`` (may raise AdapterUnavailable with the
    exact blocking reason) and ``_predict_raw(crop_bgr)`` returning the raw
    model output (str, or list of str). The public ``predict`` wraps it into
    the uniform result schema and is timing-instrumented.
    """

    id: str = "base"
    project: str = "base"

    def __init__(self) -> None:
        self.load_time_s: float | None = None
        self._loaded = False
        self._unavailable_reason: str | None = None

    # -- lifecycle ---------------------------------------------------------
    def load(self) -> None:
        if self._loaded:
            return
        if self._unavailable_reason:
            raise AdapterUnavailable(self._unavailable_reason)
        t0 = time.perf_counter()
        try:
            self._load()
        except AdapterUnavailable:
            raise
        except Exception as exc:  # record exact runtime error, never swallow
            raise AdapterUnavailable(f"{type(exc).__name__}: {exc}") from exc
        self.load_time_s = time.perf_counter() - t0
        self._loaded = True

    def is_available(self) -> bool:
        try:
            self.load()
            return True
        except AdapterUnavailable as exc:
            self._unavailable_reason = str(exc)
            return False

    @property
    def unavailable_reason(self) -> str | None:
        return self._unavailable_reason

    # -- inference ---------------------------------------------------------
    def predict(self, plate_image) -> dict:
        """Run OCR on ONE plate crop (BGR ndarray or file path).

        Returns the uniform schema:
          {id, raw_text, text (normalized), confidence, latency_ms, error}
        """
        crop = self._to_bgr(plate_image)
        if crop is None:
            return self._result("", error="empty_or_invalid_input")
        t0 = time.perf_counter()
        try:
            self.load()
            raw = self._predict_raw(crop)
            raw_text, conf = self._split_raw(raw)
        except AdapterUnavailable as exc:
            return self._result("", latency=None, error=f"unavailable: {exc}")
        except Exception as exc:
            return self._result("", latency=None,
                                error=f"{type(exc).__name__}: {exc}")
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return self._result(raw_text, confidence=conf, latency=latency_ms)

    # -- helpers for subclasses -------------------------------------------
    def _load(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def _predict_raw(self, crop_bgr: np.ndarray):  # pragma: no cover - abstract
        raise NotImplementedError

    def _split_raw(self, raw) -> tuple[str, float | None]:
        """Extract (raw_text, confidence|None) from a raw model output.

        Handles: None, dict, dataclass outputs (hezar ModelOutput objects
        expose ``.text``/``.confidence`` attributes), and plain strings.
        """
        if raw is None:
            return "", None
        if isinstance(raw, (list, tuple)):
            first = raw[0] if raw else ""
            return self._split_raw(first)
        if isinstance(raw, dict):
            return str(raw.get("text", "")), raw.get("confidence")
        # dataclass / object output (hezar Image2TextOutput etc.)
        text = getattr(raw, "text", None)
        if text is not None:
            return str(text), getattr(raw, "confidence", None)
        return str(raw), None

    def _result(self, raw_text: str, confidence: float | None = None,
                latency: float | None = None, error: str | None = None) -> dict:
        return {
            "id": self.id,
            "raw_text": raw_text,
            "text": normalize_plate_text(raw_text),
            "confidence": confidence,
            "latency_ms": latency,
            "error": error,
        }

    @staticmethod
    def _to_bgr(plate_image) -> np.ndarray | None:
        import cv2
        if plate_image is None:
            return None
        if isinstance(plate_image, np.ndarray):
            if plate_image.size == 0:
                return None
            return plate_image
        if isinstance(plate_image, (str, os.PathLike)):
            img = cv2.imread(str(plate_image))
            return img
        return None
