"""Concrete OCR adapters for every runnable model discovered in the audit.

Each adapter is ISOLATED (never edits external repos in place); where a
wrapper is needed it imports/copies the model definition, not the repo code
path around it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

from .base import AdapterUnavailable, PlateOCRAdapter

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root (D:\alpr)
BENCH_DIR = ROOT / "benchmarks"

HEZAR_BENCH_DIR = ROOT / "bench"  # local hezar weights (model.pt + configs)


# ---------------------------------------------------------------------------
# 1. CURRENT_PRODUCTION baseline: AlprEngine._assemble_chars on a plate crop
# ---------------------------------------------------------------------------
class ProductionOCRAdapter(PlateOCRAdapter):
    id = "current_production"
    project = "production (alpr_engine.py)"

    def _load(self) -> None:
        import sys as _sys
        root = str(ROOT)
        if root not in _sys.path:
            _sys.path.insert(0, root)
        try:
            from api import _ensure_models
            self.engine = _ensure_models()
        except Exception as exc:
            raise AdapterUnavailable(f"model load failed: {exc}") from exc
        if self.engine is None:
            raise AdapterUnavailable("api._ensure_models() returned None")

    def _predict_raw(self, crop_bgr: np.ndarray):
        text, conf, _boxes = self.engine._assemble_chars(crop_bgr)
        return text, float(conf or 0.0)


# ---------------------------------------------------------------------------
# 2. Hezar CRNN V2 from the local bench weights (offline, no hub download)
# ---------------------------------------------------------------------------
class HezarCRNNV2Adapter(PlateOCRAdapter):
    id = "hezar_crnn_v2"
    project = "hezarai/crnn-fa-license-plate-recognition-v2 (local bench/ weights)"

    def _load(self) -> None:
        if not (HEZAR_BENCH_DIR / "model.pt").exists():
            raise AdapterUnavailable(
                f"local weights missing: {HEZAR_BENCH_DIR / 'model.pt'}")
        try:
            from hezar.models import Model
            from hezar.preprocessors import ImageProcessor, ImageProcessorConfig
            import yaml
        except Exception as exc:
            raise AdapterUnavailable(f"hezar import failed: {exc}") from exc
        path = str(HEZAR_BENCH_DIR.resolve())
        try:
            self.model = Model.load(path, load_preprocessor=False)
        except Exception as exc:
            raise AdapterUnavailable(f"hezar load failed: {exc}") from exc
        pre_cfg = yaml.safe_load(
            open(os.path.join(path, "image_processor_config.yaml"),
                 encoding="utf-8"))
        skip = {"name", "config_type"}
        fields = ImageProcessorConfig.__dataclass_fields__
        cfg = ImageProcessorConfig(**{k: v for k, v in pre_cfg.items()
                                      if k in fields and k not in skip})
        self.model.preprocessor = ImageProcessor(config=cfg)

    def _predict_raw(self, crop_bgr: np.ndarray):
        import cv2
        # hezar predict() accepts a path or PIL/numpy via preprocessor; the
        # 1.0.0 path expects a path-like or ndarray — pass ndarray directly.
        try:
            out = self.model.predict(crop_bgr)
        except Exception:
            # fall back to a temp PNG (grayscale, 1-channel config)
            ok, buf = cv2.imencode(".png", crop_bgr)
            if not ok:
                return ""
            import tempfile as _tf
            with _tf.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(buf.tobytes())
                tmp = f.name
            try:
                out = self.model.predict(tmp)
            finally:
                os.unlink(tmp)
        return out

    def _split_raw(self, raw):
        # hezar returns [{'text': ...}, ...] — handled by base; but the base
        # str() of a dict leaks into raw_text when nested differently, so
        # unwrap explicitly here.
        if isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], dict):
            return str(raw[0].get("text", "")), None
        return super()._split_raw(raw)


# ---------------------------------------------------------------------------
# 3. PersianLicensePlateRecognition CRNN (weights + class def, isolated)
# ---------------------------------------------------------------------------
from .base import ROOT as _ROOT  # noqa: E402

_PLR_DIR = ROOT / "bench" / "PersianLicensePlateRecognition-main" / \
    "PersianLicensePlateRecognition-main"


class PLRCRNNAdapter(PlateOCRAdapter):
    id = "plr_crnn"
    project = "PersianLicensePlateRecognition (CRNN, weights-only reuse)"

    def _load(self) -> None:
        w = _PLR_DIR / "OCRModel" / "crnn_weights.pth"
        if not w.exists():
            raise AdapterUnavailable(f"weights missing: {w}")
        import torch
        import torch.nn as nn
        # Rebuild the CRNN exactly as backend.py defines it (33+1 classes,
        # imgH=32, nc=3, nh=256) WITHOUT importing the repo module (it loads
        # YOLO at import time — isolation requirement).
        class CRNN(nn.Module):
            def __init__(self, imgH, nc, nclass, nh, dropout_prob=0.3):
                super().__init__()
                self.cnn = nn.Sequential(
                    nn.Conv2d(nc, 64, 3, 1, 1), nn.ReLU(True), nn.MaxPool2d(2, 2),
                    nn.Dropout(dropout_prob),
                    nn.Conv2d(64, 128, 3, 1, 1), nn.ReLU(True), nn.MaxPool2d(2, 2),
                    nn.Dropout(dropout_prob),
                    nn.Conv2d(128, 256, 3, 1, 1), nn.ReLU(True),
                    nn.Dropout(dropout_prob),
                    nn.Conv2d(256, 256, 3, 1, 1), nn.ReLU(True), nn.MaxPool2d((2, 1), (2, 1)),
                    nn.Dropout(dropout_prob),
                    nn.Conv2d(256, 512, 3, 1, 1), nn.BatchNorm2d(512), nn.ReLU(True),
                    nn.Dropout(dropout_prob),
                    nn.Conv2d(512, 512, 3, 1, 1), nn.BatchNorm2d(512), nn.ReLU(True), nn.MaxPool2d((2, 1), (2, 1)),
                    nn.Dropout(dropout_prob),
                    nn.Conv2d(512, 512, 2, 1, 0), nn.ReLU(True),
                )
                self.rnn1 = nn.LSTM(512, nh, bidirectional=True)
                self.rnn2 = nn.LSTM(nh * 2, nh, bidirectional=True)
                self.dropout_rnn = nn.Dropout(dropout_prob)
                self.embedding = nn.Linear(nh * 2, nclass)

            def forward(self, x):
                conv = self.cnn(x)
                b, c, h, w_ = conv.size()
                assert h == 1
                conv = conv.squeeze(2).permute(2, 0, 1)
                r, _ = self.rnn1(conv)
                r, _ = self.rnn2(r)
                r = self.dropout_rnn(r)
                return self.embedding(r)

        # char order from backend.py 'indexes' (ASCII abbreviations)
        chars = ['0','1','2','3','4','5','6','7','8','9','B','D','I','H','E','J',
                 'L','M','N','P','Q','A','S','T','X','V','Y','Z','U','G','W',' ']
        self.chars = chars
        self.blank = len(chars)  # CTC blank is last index (=31 in repo mapping)
        try:
            self.model = CRNN(32, 3, len(chars) + 1, 256)
            self.model.load_state_dict(
                torch.load(str(w), map_location="cpu"))
            self.model.eval()
        except Exception as exc:
            raise AdapterUnavailable(f"CRNN load failed: {exc}") from exc

    def _predict_raw(self, crop_bgr: np.ndarray):
        import torch
        import cv2
        img = cv2.resize(crop_bgr, (100, 32))
        x = torch.from_numpy(img.astype("float32") / 255.0).permute(2, 0, 1).unsqueeze(0)
        with torch.no_grad():
            out = self.model(x)  # (T, 1, C)
        pred = out.argmax(dim=2).squeeze(1).tolist()
        # CTC collapse
        text, prev = "", self.blank
        for p in pred:
            if p != self.blank and p != prev:
                text += self.chars[p] if p < len(self.chars) else ""
            prev = p
        return text


# ---------------------------------------------------------------------------
# 4. persian-lpr-yolov11: char DETECTOR as OCR (reads chars from plate crop)
# ---------------------------------------------------------------------------
_CHAR_ORDER = ["0","1","2","3","4","5","6","7","8","9","b","d","h","v","t",
               "ta","y","n","s","sad","l","j","m","g","e","wh"]
# transliteration of Persian chars to the repo's ASCII abbreviations
_FA_TO_REPO = {"الف": "A", "ب": "B", "د": "D", "ع": "EIN", "ه": "H", "ح": "HE",
               "ج": "J", "ل": "L", "م": "M", "ن": "N", "پ": "P", "ق": "Q",
               "ص": "SAD", "س": "SIN", "ت": "T", "ط": "TA", "و": "V", "ی": "Y",
               "ز": "Z", "ش": "SH", "ث": "TH", "ژ": "ZH", "س": "SAD"}


class PersiaLPRYOLO11Adapter(PlateOCRAdapter):
    """persian-lpr-yolov11 '2nd version modified dataset' char detector.

    Runs the YOLO char detector on the SAME plate crop and assembles text
    left-to-right by character-box x-coordinate (repo behaviour)."""
    id = "persian_lpr_yolo11"
    project = "persian-lpr-yolov11 (OCR_YOLO 2nd version weights)"

    def _load(self) -> None:
        w = ROOT / "bench" / "persian-lpr-yolov11-master" / \
            "persian-lpr-yolov11-master" / "OCR_YOLO" / \
            "2nd version modified dataset" / "weights" / "best.pt"
        if not w.exists():
            raise AdapterUnavailable(f"weights missing: {w}")
        try:
            from ultralytics import YOLO
            self.model = YOLO(str(w))
        except Exception as exc:
            raise AdapterUnavailable(f"YOLO load failed: {exc}") from exc
        if len(self.model.names or {}) != 26:
            raise AdapterUnavailable(
                f"unexpected class count {len(self.model.names or {})}")

    def _predict_raw(self, crop_bgr: np.ndarray):
        res = self.model.predict(crop_bgr, verbose=False, conf=0.25)[0]
        if res.boxes is None or len(res.boxes) == 0:
            return ""
        chars = []
        for box in res.boxes.data:
            x1, y1, x2, y2, conf, cls = box.tolist()
            chars.append((x1, _CHAR_ORDER[int(cls)], float(conf)))
        chars.sort()
        return "".join(c for _, c, _ in chars)


# ---------------------------------------------------------------------------
# 5. IranPlate-Vision plate detector (separate DETECTOR adapter, Benchmark B)
# ---------------------------------------------------------------------------
class IranPlateDetectorAdapter:
    id = "iranplate_vision_yolo"
    project = "IranPlate-Vision best.pt (YOLO plate detector)"

    def __init__(self) -> None:
        self.load_time_s = None
        self._reason = None

    def is_available(self) -> bool:
        try:
            self.load()
            return True
        except AdapterUnavailable as exc:
            self._reason = str(exc)
            return False

    @property
    def unavailable_reason(self):
        return self._reason

    def load(self) -> None:
        w = ROOT / "bench" / "IranPlate-Vision-main" / "IranPlate-Vision-main" / "best.pt"
        if not w.exists():
            raise AdapterUnavailable(f"weights missing: {w}")
        try:
            from ultralytics import YOLO
            self.model = YOLO(str(w))
        except Exception as exc:
            raise AdapterUnavailable(f"YOLO load failed: {exc}") from exc

    def detect(self, frame_bgr: np.ndarray, conf: float = 0.25):
        import time
        t0 = time.perf_counter()
        res = self.model.predict(frame_bgr, verbose=False, conf=conf)[0]
        ms = (time.perf_counter() - t0) * 1000.0
        boxes = []
        if res.boxes is not None:
            for b in res.boxes.data.tolist():
                x1, y1, x2, y2, c, cls = b
                boxes.append({"bbox": [x1, y1, x2, y2], "conf": c})
        return boxes, ms


# ---------------------------------------------------------------------------
# 6. PersianLicensePlateRecognition YOLO plate detector (Benchmark B)
# ---------------------------------------------------------------------------
class PLRYOLODetectorAdapter(IranPlateDetectorAdapter):
    id = "plr_yolo_plate"
    project = "PersianLicensePlateRecognition YoloModel/best.pt (plate detector)"

    def load(self) -> None:
        w = _PLR_DIR / "YoloModel" / "best.pt"
        if not w.exists():
            raise AdapterUnavailable(f"weights missing: {w}")
        try:
            from ultralytics import YOLO
            self.model = YOLO(str(w))
        except Exception as exc:
            raise AdapterUnavailable(f"YOLO load failed: {exc}") from exc


ALL_OCR_ADAPTERS = [
    ProductionOCRAdapter,
    HezarCRNNV2Adapter,
    PLRCRNNAdapter,
    PersiaLPRYOLO11Adapter,
]

ALL_DETECTOR_ADAPTERS = [
    IranPlateDetectorAdapter,
    PLRYOLODetectorAdapter,
]
