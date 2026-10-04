"""Extract the common plate-crop dataset from cam1.mp4 / cam2.mp4 using the
CURRENT production detector only (task §7). Every OCR model later receives
these exact crops — no per-model alteration.

Also emits benchmarks/dataset/ground_truth.jsonl with all samples marked
UNLABELED (verified=false): accuracy metrics require manual verification.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "benchmarks" / "dataset"
CROPS_DIR = OUT_DIR / "crops"

SAMPLE_INTERVAL = {"cam1.mp4": 5, "cam2.mp4": 5}   # frames between samples
MAX_CROP_W = 640                                    # keep crops bounded


def blur_score(gray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def quality_metrics(crop) -> dict:
    h, w = crop.shape[:2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return {
        "width": int(w),
        "height": int(h),
        "area": int(w * h),
        "aspect_ratio": round(w / max(1, h), 3),
        "blur_score": round(blur_score(gray), 1),
        "brightness": round(float(gray.mean()), 1),
        "contrast": round(float(gray.std()), 1),
    }


def main() -> None:
    from api import _ensure_models
    engine = _ensure_models()
    if engine is None:
        raise SystemExit("production engine failed to load")

    CROPS_DIR.mkdir(parents=True, exist_ok=True)
    metadata = []
    # CAM2_FAILURE_TARGETS: frames whose production OCR produced the suspect
    # strings listed in the task — matched post-hoc by (video, frame).
    n = 0
    for video_name, interval in SAMPLE_INTERVAL.items():
        path = ROOT / video_name
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise SystemExit(f"cannot open {video_name}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % interval == 0:
                try:
                    results = engine.run(frame)
                except Exception as exc:
                    print(f"[warn] engine.run failed f{frame_idx}: {exc}")
                    results = []
                for r in results:
                    if not r.plate_text:
                        continue
                    x1, y1, x2, y2 = r.plate_bbox
                    crop = frame[y1:y2, x1:x2]
                    if crop.size == 0:
                        continue
                    if crop.shape[1] > MAX_CROP_W:
                        scale = MAX_CROP_W / crop.shape[1]
                        crop = cv2.resize(crop, (MAX_CROP_W,
                                                 max(1, int(crop.shape[0] * scale))),
                                          interpolation=cv2.INTER_AREA)
                    sid = f"{Path(video_name).stem}_f{frame_idx:05d}_{n:04d}"
                    crop_path = f"crops/{sid}.png"
                    cv2.imwrite(str(OUT_DIR / crop_path), crop)
                    metadata.append({
                        "id": sid,
                        "source_video": video_name,
                        "frame": frame_idx,
                        "time_s": round(frame_idx / fps, 3),
                        "track_id": None,
                        "crop_path": crop_path,
                        "detector": "current_production",
                        "production_ocr_raw": r.plate_text,
                        "production_confidence": round(float(r.confidence), 4),
                        "quality": quality_metrics(crop),
                    })
                    n += 1
            frame_idx += 1
        cap.release()

    with open(OUT_DIR / "metadata.jsonl", "w", encoding="utf-8") as f:
        for m in metadata:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    # ground-truth workflow: all UNLABELED until manually verified
    with open(OUT_DIR / "ground_truth.jsonl", "w", encoding="utf-8") as f:
        for m in metadata:
            f.write(json.dumps({
                "sample_id": m["id"],
                "plate_text": None,
                "plate_type": "unknown",
                "verified": False,
                "status": "UNLABELED",
            }, ensure_ascii=False) + "\n")

    print(f"extracted {n} crops -> {OUT_DIR}")
    by_video = {}
    for m in metadata:
        by_video[m["source_video"]] = by_video.get(m["source_video"], 0) + 1
    print("per video:", by_video)


if __name__ == "__main__":
    main()
