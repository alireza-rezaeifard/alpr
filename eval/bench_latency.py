"""Latency benchmark harness (design Phase 0 / Part 6.1).

Measures the CURRENT models exactly as the live engine uses them, with
per-stage instrumentation. No fabricated numbers: whatever the machine
produces is what gets written to ``eval/baselines/``.

Device facts (torch version, thread count, CUDA availability) are recorded.
GPU numbers are NEVER synthesised — when CUDA is unavailable the report
stores ``gpu: null``.

Usage:
  python eval/bench_latency.py --image car_a.jpg --iterations 20 \
      --out eval/baselines/v1-latency.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _percentile(values: list, pct: float) -> float:
    """Nearest-rank percentile (no numpy dependency needed)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = max(0, min(len(ordered) - 1,
                     int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def _summarise(samples_ms: list) -> dict:
    return {
        "n": len(samples_ms),
        "avg_ms": round(statistics.fmean(samples_ms), 2) if samples_ms else 0.0,
        "p50_ms": round(_percentile(samples_ms, 50), 2),
        "p95_ms": round(_percentile(samples_ms, 95), 2),
        "max_ms": round(max(samples_ms), 2) if samples_ms else 0.0,
    }


class _TimedYolo:
    """Thin proxy that times Ultralytics ``__call__`` without touching it."""

    def __init__(self, model, stage: str, stages: dict) -> None:
        self._model = model
        self._stage = stage
        self._stages = stages

    def __call__(self, *a, **k):
        t0 = time.perf_counter()
        try:
            return self._model(*a, **k)
        finally:
            self._stages.setdefault(self._stage, []).append(
                (time.perf_counter() - t0) * 1000.0)

    def __getattr__(self, item):
        return getattr(self._model, item)


def _stage_timer(name: str, stages: dict):
    def decorator(fn):
        def inner(*a, **k):
            t0 = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                stages.setdefault(name, []).append(
                    (time.perf_counter() - t0) * 1000.0)
        return inner
    return decorator


def _cpu_times() -> tuple:
    """(process cpu seconds, system cpu percent) — best effort via psutil."""
    try:
        import psutil
        proc = psutil.Process()
        cpu = proc.cpu_times()
        return (cpu.user + cpu.system), psutil.cpu_percent(interval=None)
    except Exception:                      # psutil missing: no CPU numbers
        return None, None


def _cpu_load(cpu_before, wall_before) -> dict:
    """Convert cpu-time deltas into an honest, measured load summary."""
    try:
        import psutil
        import multiprocessing
        after, _ = _cpu_times()
        wall = max(time.perf_counter() - wall_before, 1e-9)
        if cpu_before[0] is None:
            return {"available": False}
        cpu_seconds = after - cpu_before[0]
        return {
            "available": True,
            "process_cpu_seconds": round(cpu_seconds, 3),
            "wall_seconds": round(wall, 3),
            "process_cpu_percent_of_one_core": round(100.0 * cpu_seconds / wall, 1),
            "logical_cores": multiprocessing.cpu_count(),
        }
    except Exception:                      # pragma: no cover - guarded above
        return {"available": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="ALPR per-stage latency benchmark")
    parser.add_argument("--image", default="car_a.jpg")
    parser.add_argument("--model-dir", default="weigths")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    import cv2
    import torch

    logging.disable(logging.CRITICAL)      # silence per-call ultralytics logs
    from alpr_engine import AlprEngine

    image_path = (args.image if os.path.isabs(args.image)
                  else os.path.join(ROOT, args.image))
    frame = cv2.imread(image_path)
    if frame is None:
        print(f"[bench] cannot read image: {image_path}")
        return 2

    print(f"[bench] loading models from {args.model_dir} ...")
    engine = AlprEngine(args.model_dir)

    stages: dict = {}
    totals: list = []

    # Wrappers are local to this process; alpr_engine.py is NOT modified.
    engine._predict_car = _stage_timer("resnet_car_type", stages)(engine._predict_car)
    engine._predict_color = _stage_timer("resnet_color", stages)(engine._predict_color)
    engine._assemble_chars = _stage_timer("ocr_char_detector", stages)(
        engine._assemble_chars)
    engine._plate_model = _TimedYolo(engine._plate_model, "plate_detector_yolo", stages)
    engine._car_model = _TimedYolo(engine._car_model, "vehicle_detector_yolo", stages)
    if engine._char_model is not None:
        engine._char_model = _TimedYolo(engine._char_model, "ocr_char_yolo", stages)

    print(f"[bench] warmup {args.warmup}, measure {args.iterations} on "
          f"{os.path.basename(image_path)} {frame.shape}")
    for _ in range(args.warmup):
        engine.run(frame)
    for bucket in stages.values():         # discard warmup samples
        bucket.clear()

    plates_last = []
    cpu_before = _cpu_times()
    wall_before = time.perf_counter()
    for _ in range(args.iterations):
        t0 = time.perf_counter()
        results = engine.run(frame)
        totals.append((time.perf_counter() - t0) * 1000.0)
        if results:
            plates_last = [(r.plate_text, round(r.confidence, 4)) for r in results]

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "image": os.path.relpath(image_path, ROOT),
        "image_shape": list(frame.shape),
        "iterations": args.iterations,
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "torch_threads": torch.get_num_threads(),
            "cuda_available": torch.cuda.is_available(),
            "gpu": (torch.cuda.get_device_name(0)
                    if torch.cuda.is_available() else None),
            "device_used": "cuda" if torch.cuda.is_available() else "cpu",
        },
        "notes": [
            "gpu is null when torch.cuda.is_available() is False — no GPU "
            "numbers are synthesised.",
            "per-stage n = calls across measured iterations (several per "
            "iteration when multiple objects are present).",
            "wrappers exist only in this process; alpr_engine.py is untouched.",
        ],
        "total_run": _summarise(totals),
        "cpu_load_during_measurement": _cpu_load(cpu_before, wall_before),
        "per_stage_ms": {name: _summarise(samples)
                         for name, samples in sorted(stages.items())},
        "plates_last_run": plates_last,
    }

    print(json.dumps(report, indent=2))
    if args.out:
        out_path = (args.out if os.path.isabs(args.out)
                    else os.path.join(ROOT, args.out))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"[bench] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
