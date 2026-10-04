"""Phase 3 — visual diagnostic artifact generation.

Produces PNG overlays and crop-comparison sheets plus a
static HTML index so a VISION-CAPABLE human reviewer can
inspect representative evidence. The generator cannot
itself judge readability — every sheet is labelled with
its provenance and the review status stays pending.

Artifacts (benchmarks/audit/phase3/):
  overlays/        frame + detector boxes (GT box drawn when
                   box GT exists; otherwise the sheet is
                   labelled "box GT pending")
  crop_strips/     GT crop | detector crop under each of
                   trunc/floor/round/ceil + expansion
                   examples, per representative frame
  ocr_examples/    correct reads, wrong reads,
                   low-confidence reads, small-plate reads
  diagnostics.html index page
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).resolve().parent / "audit" / "phase3"


def ensure_dirs() -> dict[str, Path]:
    dirs = {name: OUT / name for name in
            ("overlays", "crop_strips", "ocr_examples")}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def draw_box(img: np.ndarray,
             box: tuple[int, int, int, int],
             color: tuple[int, int, int],
             label: str = "",
             thickness: int = 2) -> np.ndarray:
    out = img.copy()
    x1, y1, x2, y2 = box
    cv2.rectangle(out, (x1, y1), (x2, y2), color,
                  thickness)
    if label:
        cv2.putText(out, label, (x1, max(0, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color,
                    2, cv2.LINE_AA)
    return out


def detection_overlay(frame: np.ndarray,
                      gt_box: dict | None,
                      predictions: list[dict],
                      title: str = "") -> np.ndarray:
    """Frame with GT box (green) and detector boxes
    (blue=A, orange=B). When GT is absent the image is
    labelled so nobody mistakes predictions for GT."""
    out = frame.copy()
    h, w = frame.shape[:2]
    if gt_box is not None:
        out = draw_box(
            out, (gt_box["x1"], gt_box["y1"],
                  gt_box["x2"], gt_box["y2"]),
            (0, 255, 0), "GT")
    else:
        cv2.putText(out, "box GT pending — predictions only",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (0, 255, 255), 2, cv2.LINE_AA)
    colors = {"detector_a_current": (255, 0, 0),
              "detector_b_iranplate": (0, 165, 255)}
    for p in predictions:
        b = p["integer_bbox"]
        out = draw_box(
            out, (b[0], b[1], b[2], b[3]),
            colors.get(p["detector"], (255, 255, 255)),
            f"{p['detector'][-1]}:{p['confidence']:.2f}")
    if title:
        band = np.zeros((36, w, 3), dtype=np.uint8)
        cv2.putText(band, title, (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (255, 255, 255), 2, cv2.LINE_AA)
        out = np.vstack([band, out])
    return out


def zoom4x(crop: np.ndarray) -> np.ndarray:
    if crop is None or crop.size == 0:
        return np.zeros((64, 64, 3), dtype=np.uint8)
    h, w = crop.shape[:2]
    return cv2.resize(crop, (w * 4, h * 4),
                      interpolation=cv2.INTER_NEAREST)


def crop_strip(crops: dict[str, np.ndarray],
               labels: list[str]) -> np.ndarray:
    """Horizontal strip of labelled 4x zooms (uniform
    height via padding)."""
    panels = []
    max_h = 0
    rendered = []
    for lab in labels:
        img = zoom4x(crops.get(lab))
        band = np.zeros((28, img.shape[1], 3),
                        dtype=np.uint8)
        cv2.putText(band, lab[:28], (6, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 1, cv2.LINE_AA)
        panel = np.vstack([band, img])
        rendered.append(panel)
        max_h = max(max_h, panel.shape[0])
    for panel in rendered:
        pad = max_h - panel.shape[0]
        if pad:
            panel = np.vstack(
                [panel, np.zeros((pad, panel.shape[1], 3),
                                 dtype=np.uint8)])
        panels.append(panel)
    return np.hstack(panels)


def write_diagnostics_index(sections: list[dict],
                            out_path: Path) -> None:
    """Static HTML index linking every artifact with its
    provenance and review status."""
    items = []
    for sec in sections:
        links = "".join(
            f'<li><a href="{it["path"]}">{it["label"]}</a>'
            f' — {it.get("note", "")}</li>'
            for it in sec.get("items", []))
        items.append(f"<h2>{sec['title']}</h2>"
                     f"<p>{sec.get('description', '')}</p>"
                     f"<ul>{links}</ul>")
    html = ("<html><head><meta charset='utf-8'>"
            "<title>Phase 3 visual diagnostics</title></head>"
            "<body><h1>Phase 3 visual diagnostics</h1>"
            "<p><b>Review status: PENDING human visual review."
            "</b> These artifacts are machine-generated "
            "evidence sheets; no readability judgement is "
            "encoded in them.</p>"
            + "".join(items) + "</body></html>")
    out_path.write_text(html, encoding="utf-8")


def manifest_entry(kind: str, path: Path, label: str,
                   note: str = "") -> dict:
    return {"kind": kind, "path": str(path),
            "label": label, "note": note}
