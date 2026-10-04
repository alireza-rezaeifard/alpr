"""Crop preprocessing variants (task §6), applied IDENTICALLY to every OCR
model — variants are named and recorded; results are never mixed unlabelled.

Variants:
  original      pass-through (control)
  up2x          cubic 2x upscale
  up3x          cubic 3x upscale
  gray          grayscale replicated to 3 channels
  clahe         CLAHE contrast equalization on the L channel
  sharpen       unsharp mask
  persp         perspective rectification (quad detection; falls back to
                'skipped' when no plausible quad is found — recorded, never
                silently substituted)
"""
from __future__ import annotations

import cv2
import numpy as np

VARIANTS = ["original", "up2x", "up3x", "gray", "clahe", "sharpen", "persp"]


def _gray3(bgr: np.ndarray) -> np.ndarray:
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def _upscale(bgr: np.ndarray, f: float) -> np.ndarray:
    return cv2.resize(bgr, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)


def _clahe(bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


def _sharpen(bgr: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(bgr, (0, 0), 3)
    return cv2.addWeighted(bgr, 1.6, blur, -0.6, 0)


def _perspective(bgr: np.ndarray):
    """Rectify the plate quad to a frontal rectangle.

    Best-effort: threshold -> largest contour -> minAreaRect -> 4-point warp.
    Returns None when no plausible quad exists (caller records 'skipped').
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 0, 255,
                          cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    cnt = max(contours, key=cv2.contourArea)
    if cv2.contourArea(cnt) < 0.35 * bgr.shape[0] * bgr.shape[1]:
        return None
    rect = cv2.minAreaRect(cnt)
    box = cv2.boxPoints(rect).astype("float32")
    (w, h) = rect[1]
    if w < 8 or h < 4:
        return None
    if w < h:  # ensure landscape orientation
        w, h = h, w
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]],
                   dtype="float32")
    m = cv2.getPerspectiveTransform(order_points(box), dst)
    out = cv2.warpPerspective(bgr, m, (int(w), int(h)))
    return out if out.size else None


def order_points(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as [top-left, top-right, bottom-right, bottom-left]."""
    pts = np.asarray(pts, dtype="float32")
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")


def apply_variant(bgr: np.ndarray, variant: str):
    """Return the preprocessed crop, or None when the variant is not
    applicable to this crop (currently only 'persp')."""
    if variant == "original":
        return bgr
    if variant == "up2x":
        return _upscale(bgr, 2.0)
    if variant == "up3x":
        return _upscale(bgr, 3.0)
    if variant == "gray":
        return _gray3(bgr)
    if variant == "clahe":
        return _clahe(bgr)
    if variant == "sharpen":
        return _sharpen(bgr)
    if variant == "persp":
        return _perspective(bgr)
    raise ValueError(f"unknown preprocessing variant: {variant}")
