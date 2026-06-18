"""
alpr_engine.py
Multi-model ALPR inference engine wrapping reference project logic.

Loads 5 models (plate_det, char, car_det, car_name, color) + city CSV at
startup. Exposes a single ``run(frame)`` method that returns structured
detection results.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from torchvision import models, transforms

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CHAR_CLASSNAMES: list[str] = [
    "0", "9", "b", "d", "a", "ein", "g", "gh", "h", "n", "s", "1",
    "malul", "n", "s", "sad", "t", "ta", "v", "y",
    "2", "3", "4", "5", "6", "7", "8",
]

CAR_CLASSES: list[str] = [
    "Arisan", "Atlas", "Dena", "L90", "Mazda vanet", "Megan", "Neissan",
    "Pars", "206", "206 SD", "207", "405", "Peykan", "Pride", "Pride vanet",
    "Pride 111", "Quik", "Rana", "Rio", "Saina", "Samand", "Shahin", "Soren",
    "Tara", "Tiba", "Tiba 2", "Zantia",
]

COLOR_CLASS_NAMES: list[str] = [
    "Black", "Blue", "Brown", "Crismon", "Gray", "Green",
    "Orange", "Purple", "Red", "Silver", "White", "Yellow",
]

VEHICLE_CLASS_IDS: list[int] = [2, 3, 5, 7]  # car, motorcycle, bus, truck

PLATE_DET_CONF = 0.6
CHAR_DET_CONF = 0.3
CAR_DET_CONF = 0.6
CAR_NAME_THRESH = 0.65
COLOR_THRESH = 0.7

# Detection caps to stop YOLO from emitting hundreds of garbage boxes per frame
# (the "256 LicensePlates" over-detection seen in the logs). NMS IoU keeps a
# single tight box per real object.
PLATE_MAX_DET = 12
CAR_MAX_DET = 20
NMS_IOU = 0.45

IMG_SIZE = (220, 165)


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class AlprResult:
    """Single plate detection result with vehicle info."""

    plate_text: str
    plate_bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    confidence: float
    car_bbox: tuple[int, int, int, int] | None = None
    car_color: str | None = None
    car_type: str | None = None
    city: str | None = None
    char_bboxes: list[tuple[int, int, int, int]] = field(default_factory=list)


# ── Engine ───────────────────────────────────────────────────────────────────

class AlprEngine:
    """Singleton-style ALPR engine that loads all models once at init.

    Usage::

        engine = AlprEngine("weigths")
        results = engine.run(frame_bgr)
    """

    def __init__(self, model_dir: str = "weigths") -> None:
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._model_dir = Path(model_dir)

        # YOLO models (None if load fails)
        self._plate_model = None
        self._char_model = None
        self._car_model = None

        # ResNet18 classifiers (None if load fails)
        self._car_name_model = None
        self._car_name_transform = None
        self._color_model = None
        self._color_transform = None

        # City lookup data
        self._city_data: list[dict] = []

        self._load_all()

    # ── Model loading ────────────────────────────────────────────────────

    def _load_all(self) -> None:
        """Load every model with independent try/except for graceful fallback."""
        self._plate_model = self._load_yolo("plate_det_model.pt")
        self._char_model = self._load_yolo("char_model.pt")
        self._car_model = self._load_yolo("car_det_model.pt")
        self._car_name_model, self._car_name_transform = self._load_resnet(
            "car_name_model.pth", len(CAR_CLASSES)
        )
        self._color_model, self._color_transform = self._load_resnet(
            "color_model.pt", len(COLOR_CLASS_NAMES)
        )
        self._load_city_data()

        loaded = sum(
            x is not None
            for x in [
                self._plate_model,
                self._char_model,
                self._car_model,
                self._car_name_model,
                self._color_model,
            ]
        )
        logger.info("ALPR engine loaded %d/5 models", loaded)

    def _load_yolo(self, filename: str):
        """Load a YOLO model. Returns None on failure."""
        try:
            from ultralytics import YOLO

            path = str(self._model_dir / filename)
            model = YOLO(path)
            logger.info("Loaded YOLO model: %s", filename)
            return model
        except Exception as exc:
            logger.warning("Failed to load YOLO model %s: %s", filename, exc)
            return None

    def _load_resnet(self, filename: str, num_classes: int):
        """Load a ResNet18 classifier. Returns (model, transform) or (None, None)."""
        try:
            path = str(self._model_dir / filename)
            model = models.resnet18(weights=None)
            model.fc = torch.nn.Linear(model.fc.in_features, num_classes)
            model.load_state_dict(
                torch.load(path, map_location=self._device, weights_only=True)
            )
            model = model.to(self._device).eval()

            transform = transforms.Compose([
                transforms.Resize(IMG_SIZE),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ])
            logger.info("Loaded ResNet18 model: %s", filename)
            return model, transform
        except Exception as exc:
            logger.warning("Failed to load ResNet18 model %s: %s", filename, exc)
            return None, None

    def _load_city_data(self) -> None:
        """Load city_plateinfo.txt CSV."""
        try:
            csv_path = self._model_dir / "Plates" / "city_plateinfo.txt"
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                self._city_data = list(reader)
            logger.info("Loaded %d city plate entries", len(self._city_data))
        except Exception as exc:
            logger.warning("Failed to load city_plateinfo.txt: %s", exc)
            self._city_data = []

    # ── Inference helpers ─────────────────────────────────────────────────

    def _predict_car(self, vehicle_img: np.ndarray) -> str | None:
        """Classify car brand from vehicle crop. Returns name or None."""
        if self._car_name_model is None or self._car_name_transform is None:
            return None
        try:
            pil = Image.fromarray(cv2.cvtColor(vehicle_img, cv2.COLOR_BGR2RGB))
            tensor = self._car_name_transform(pil).unsqueeze(0).to(self._device)
            with torch.no_grad():
                pred = self._car_name_model(tensor)
                probs = torch.softmax(pred, dim=1)
                cls_idx = pred.argmax(1).item()
                prob = probs[0, cls_idx].item()
            if prob >= CAR_NAME_THRESH:
                return CAR_CLASSES[cls_idx]
            return None
        except Exception as exc:
            logger.debug("predict_car failed: %s", exc)
            return None

    def _predict_color(self, vehicle_img: np.ndarray) -> str | None:
        """Classify car color from vehicle crop. Returns color or None."""
        if self._color_model is None or self._color_transform is None:
            return None
        try:
            pil = Image.fromarray(cv2.cvtColor(vehicle_img, cv2.COLOR_BGR2RGB))
            tensor = self._color_transform(pil).unsqueeze(0).to(self._device)
            with torch.no_grad():
                pred = self._color_model(tensor)
                probs = torch.softmax(pred, dim=1)
                cls_idx = pred.argmax(1).item()
                prob = probs[0, cls_idx].item()
            if prob >= COLOR_THRESH:
                return COLOR_CLASS_NAMES[cls_idx]
            return None
        except Exception as exc:
            logger.debug("predict_color failed: %s", exc)
            return None

    def _find_city(self, letter: str, number: str) -> str | None:
        """Lookup city from plate letter + region number."""
        for row in self._city_data:
            if row.get("letter") == letter and row.get("number") == str(number):
                return row.get("city")
        return None

    def _assemble_chars(
        self, plate_crop: np.ndarray
    ) -> tuple[str, float, list[tuple[int, int, int, int]]]:
        """Run char detection on plate crop, sort by x1, assemble text.

        Returns (text, avg_confidence, char_bboxes).
        """
        if self._char_model is None:
            return "", 0.0, []

        try:
            output = self._char_model(
                plate_crop, conf=CHAR_DET_CONF, iou=NMS_IOU, verbose=False
            )
            boxes = output[0].boxes
            if boxes is None or len(boxes) == 0:
                return "", 0.0, []

            xyxy = boxes.xyxy
            cls = boxes.cls
            confs = boxes.conf

            if len(cls) == 0:
                return "", 0.0, []

            keys = cls.cpu().numpy().astype(int)
            x1_coords = xyxy[:, 0].cpu().numpy().astype(int)
            conf_vals = confs.cpu().numpy().astype(float)

            sorted_indices = sorted(range(len(keys)), key=lambda i: x1_coords[i])
            chars = []
            bboxes = []
            total_conf = 0.0

            for idx in sorted_indices:
                k = keys[idx]
                if 0 <= k < len(CHAR_CLASSNAMES):
                    chars.append(CHAR_CLASSNAMES[k])
                    bx = xyxy[idx].cpu().numpy().astype(int)
                    bboxes.append((int(bx[0]), int(bx[1]), int(bx[2]), int(bx[3])))
                    total_conf += float(conf_vals[idx])

            avg_conf = total_conf / len(chars) if chars else 0.0
            return "".join(chars), avg_conf, bboxes

        except Exception as exc:
            logger.debug("_assemble_chars failed: %s", exc)
            return "", 0.0, []

    # ── Main pipeline ────────────────────────────────────────────────────

    def run(self, frame: np.ndarray) -> list[AlprResult]:
        """Run the full ALPR pipeline on a single BGR frame.

        Steps:
            1. Car detection YOLO → filter vehicle classes → crop each vehicle
            2. Car name (ResNet18, only for class_id==2) + color (all vehicles)
            3. Plate detection YOLO → crop each plate
            4. Char detection YOLO on plate crop → sort by x1 → assemble text
            5. City lookup from plate text

        Returns a list of ``AlprResult`` — one per detected plate.
        """
        if self._plate_model is None:
            return []

        results: list[AlprResult] = []

        # Step 1+2: Car detection + vehicle classification
        car_info: dict[int, dict] = {}  # index -> {car_type, car_color, bbox}
        if self._car_model is not None:
            try:
                car_detections = self._car_model(
                    frame, show=False, conf=CAR_DET_CONF,
                    iou=NMS_IOU, max_det=CAR_MAX_DET, verbose=False,
                )
                for det in car_detections:
                    if det.boxes is None:
                        continue
                    for box in det.boxes:
                        class_id = int(box.cls[0])
                        if class_id not in VEHICLE_CLASS_IDS:
                            continue
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                        vehicle_crop = frame[y1:y2, x1:x2]
                        if vehicle_crop.shape[0] == 0 or vehicle_crop.shape[1] == 0:
                            continue

                        car_type = None
                        if class_id == 2:  # car only
                            car_type = self._predict_car(vehicle_crop)
                        car_color = self._predict_color(vehicle_crop)

                        car_info[len(car_info)] = {
                            "car_type": car_type,
                            "car_color": car_color,
                            "bbox": (int(x1), int(y1), int(x2), int(y2)),
                        }
            except Exception as exc:
                logger.warning("Car detection failed: %s", exc)

        # Find the best car info (prefer class_id==2, otherwise first)
        best_car: dict | None = None
        for ci in car_info.values():
            if ci["car_type"] is not None:
                best_car = ci
                break
        if best_car is None and car_info:
            best_car = next(iter(car_info.values()))

        # Step 3+4: Plate detection + character recognition
        try:
            plate_detections = self._plate_model(
                frame, show=False, conf=PLATE_DET_CONF,
                iou=NMS_IOU, max_det=PLATE_MAX_DET, verbose=False,
            )
            for det in plate_detections:
                if det.boxes is None:
                    continue
                for box in det.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    # Confidence of the plate-detection box itself. This is the
                    # meaningful "is this a plate" score (typically 0.85+ for a
                    # real plate) and is what we report to the UI.
                    plate_det_conf = float(box.conf[0])
                    plate_crop = frame[y1:y2, x1:x2]
                    if plate_crop.shape[0] == 0 or plate_crop.shape[1] == 0:
                        continue

                    plate_text, char_conf, char_bboxes = self._assemble_chars(plate_crop)
                    if not plate_text:
                        continue

                    # Step 5: City lookup
                    city = None
                    if len(plate_text) >= 8:
                        letter_part = plate_text[2].lower().strip()
                        number_part = plate_text[6:8]
                        city = self._find_city(letter_part, number_part)

                    # Report the plate-detection confidence as the primary
                    # score (high & meaningful). Blend in the OCR character
                    # confidence so a clean, fully-read plate scores highest.
                    if char_conf > 0:
                        reported_conf = 0.7 * plate_det_conf + 0.3 * char_conf
                    else:
                        reported_conf = plate_det_conf

                    results.append(AlprResult(
                        plate_text=plate_text,
                        plate_bbox=(int(x1), int(y1), int(x2), int(y2)),
                        confidence=float(reported_conf),
                        car_bbox=best_car["bbox"] if best_car else None,
                        car_color=best_car["car_color"] if best_car else None,
                        car_type=best_car["car_type"] if best_car else None,
                        city=city,
                        char_bboxes=char_bboxes,
                    ))
        except Exception as exc:
            logger.warning("Plate detection failed: %s", exc)

        return results
