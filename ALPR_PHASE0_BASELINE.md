# Phase 0 Baseline — pre-change measurements and behaviour

**Project:** `D:\alpr`
**Commit:** `3f16f270a8abbaf2f30d017693d5a72a1dc3bd65` ("update some changes"), branch `main`
**Captured:** 2026-09-29, **before** any Phase 0 file was added (the `pipeline/` and `eval/` packages did not exist yet)
**Purpose:** record the pre-change state so Phase 0/1/2 changes are provable, not asserted.

> Every number below comes from a command that was actually run on this machine.
> Nothing here is estimated. Where a measurement was not possible (GPU,
> accuracy), it is marked **not measured**.

---

## 1. Environment

| Item | Value | Command |
|---|---|---|
| Python | 3.11.4 | `python --version` |
| pytest | 9.0.3 | `pytest --version` |
| torch | **2.12.0+cpu**, `cuda_available = False` | `python -c "import torch; print(torch.__version__, torch.cuda.is_available())"` |
| torch threads | 6 | `torch.get_num_threads()` |
| OpenCV | 4.13.0 | `python -c "import cv2; print(cv2.__version__)"` |
| Ultralytics | 8.4.56 | `python -c "import ultralytics; print(ultralytics.__version__)"` |
| NumPy | 2.4.6 | `python -c "import numpy; print(numpy.__version__)"` |
| scipy / hypothesis / psutil | 1.15.3 / 6.155.2 / present | `importlib.util.find_spec` |
| ruff | **not installed** locally (CI installs it — `.github/workflows/ci.yml`) | `importlib.util.find_spec("ruff")` |
| Flutter / Dart | 3.44.1 / 3.12.1 | `flutter --version` |
| GPU | **none available** (CPU-only wheel) | same torch probe |

**GPU statement:** no GPU measurement appears anywhere in this phase, because
`torch.cuda.is_available()` is `False` on this machine.

---

## 2. Existing test suite — baseline (before Phase 0)

### 2.1 Python

```
python -m pytest tests -q
```

| Metric | Result |
|---|---|
| Tests collected | **275** (`python -m pytest tests --collect-only -q`) |
| Passed | **272** |
| Failed | **3** |
| Warnings | 123 |
| Wall time | **214.26 s** (0:03:34) |

Pre-existing failures — all three exist **before** any Phase 0 change and are
environment-related:

```
FAILED tests/test_detection_pipeline_integration.py::TestImageDetectionWiring::test_valid_image_creates_session_and_detections
FAILED tests/test_detection_pipeline_integration.py::TestAtomicStorageFailure::test_detection_storage_failure_propagates_error
FAILED tests/test_detection_pipeline_integration.py::TestRTSPTaskLifecycle::test_rtsp_status_returns_processor_state
```

Forensic evidence from the same run's stderr — the FFmpeg/OpenH264 video writer
cannot initialize on this machine, which is exactly what those three tests drive:

```
[libopenh264 @ ...] Incorrect library version loaded
[ERROR:0@0.174] global cap_ffmpeg_impl.hpp:3514 open Could not open codec libopenh264
[ERROR:0@0.217] global cap_ffmpeg_impl.hpp:3531 open VIDEOIO/FFMPEG: Failed to initialize VideoWriter
```

### 2.2 Flutter

```
cd flutter_app; flutter test
```

| Metric | Result |
|---|---|
| Tests | **83 passed**, 0 failed ("All tests passed!") |

---

## 3. Current duplicate behaviour (what Phase 1 must fix)

| Observation | Evidence |
|---|---|
| One vehicle ⇒ one DB row **per emission**, gated only by a 60 s in-memory text cooldown | `video_processor.py:355` (`_DEDUP_WINDOW_SECONDS = 60.0`), `:485-487`, `:875-877`; `db.py:146-184` (plain `INSERT`) |
| Cooldown key is the OCR **string**, never a vehicle identity | same lines: `_recent_emit_times[dtrb_text]` |
| Cooldown state dies with the processor (restart/reconnect ⇒ immediate re-emission) and its entries never expire | `video_processor.py:379`, `:636` |
| History de-dup increments `count`, but the cooldown above it makes `count` effectively always 1 | `:873-878` (gate) vs `:1007-1037` (count) |
| Real duplicate volume in the repository's own OCR log | `log_demo_result.txt`: 1863 recognition lines; plate `28i68923` appears **176×**, its one-character variant `28i68973` **19×** — two rows for one physical car. Low-confidence garbage also present: `1499 @ 0.0496`, `34992 @ 0.0220`, `7819 @ 0.0455` |
| No vehicle identity exists to prevent any of this | `AlprResult` has no id (`alpr_engine.py:65-77`); `detections` has no track/event column (`db.py:37-48`) |

**Baseline metric for Phase 1's exit gate:** `events_per_visit` = emitted
vehicle events / physical visits. Today it is not measurable (no identity) and
by construction reaches ≥ 2 whenever the OCR string wobbles or a visit exceeds
60 s. Phase 1 target: `== 1.0` on the replay set and one live hour.

---

## 4. Current detection / event behaviour summary

| Aspect | Baseline state | Evidence |
|---|---|---|
| Pipeline shape | frame-based: detect → OCR → save row | `video_processor.py:438-560` (video), `:824-922` (RTSP ML worker), `routers/detection.py:106-158` (image) |
| Frame skipping | RTSP only (modulo); **video files ignore it entirely** | `video_processor.py:47-54`, `:944` vs `:397-449` |
| Queueing | one latest-frame slot; `_ml_busy` written but never read | `:820-834`, `:839-840` |
| Inference instances | one process-wide `AlprEngine`; no batching, no semaphore | `api.py:30-52` |
| Event model | none — "unique plates" = `COUNT(DISTINCT plate_dtrb)` | `db.py:210-228` |
| Vehicle attributes | make/colour computed per vehicle box **per frame** | `alpr_engine.py:319-322` |
| Client polling | 100 ms `/frame` per camera + 3 s full status | `camera_poll_controller.dart:49-55`, `routers/detection.py:355-383` |

---

## 5. Performance baseline (pre-change)

Machine-readable: **`eval/baselines/v1-latency.json`** (written by
`eval/bench_latency.py`). Input conditions match the audit: `car_a.jpg`,
1280×960, CPU only.

```
python eval/bench_latency.py --image car_a.jpg --iterations 20 --warmup 3 \
    --out eval/baselines/v1-latency.json
```

### 5.1 Full pipeline

| Metric | Value |
|---|---|
| `AlprEngine.run()` avg | **103.67 ms** |
| p50 | **101.28 ms** |
| p95 | **113.96 ms** |
| max | **130.05 ms** |
| n | 20 |

This independently reproduces the audit's 105–124 ms band on the same machine.

### 5.2 Per-stage attribution (measured, same run)

| Stage | n | avg ms | p50 | p95 | max |
|---|---|---|---|---|---|
| `vehicle_detector_yolo` (`car_det_model.pt`, 80-class, imgsz 640) | 20 | **25.16** | 24.32 | 32.28 | 35.40 |
| `plate_detector_yolo` (`plate_det_model.pt`, 1-class, imgsz 640) | 20 | **24.32** | 23.97 | 27.64 | 28.09 |
| `ocr_char_detector` (`_assemble_chars` incl. char model) | 20 | **8.73** | 8.90 | 10.05 | 10.06 |
| ↳ `ocr_char_yolo` (inner char-model call) | 20 | 8.66 | 8.81 | 9.98 | 9.99 |
| `resnet_car_type` (`car_name_model.pth`, per vehicle box) | **40** | **11.30** | 11.59 | 14.43 | 19.17 |
| `resnet_color` (`color_model.pt`, per vehicle box) | **40** | **11.23** | 11.49 | 13.64 | 14.31 |

Attribution check: 25.16 + 24.32 + 8.73 + 2×11.30 + 2×11.23 = **103.27 ms**,
matching the measured total of 103.67 ms — the whole cost is accounted for by
these five models, two of which run twice per frame.

### 5.3 CPU load during measurement

| Metric | Value |
|---|---|
| Process CPU seconds | 16.391 |
| Wall seconds | 2.083 |
| **Process CPU: 787 % of one core** (i.e. ~7.9 cores busy) | psutil process cpu_times delta |
| Logical cores | 12 |
| torch threads | 8 (this run) / 6 (audit run) — thread count differs between runs and is recorded in the JSON |

**Implication captured for Phase 2:** a single camera already saturates ~8 cores
on this box, which is why the design's `max_concurrent_inference = 2` semaphore
and event-level ResNet18 gating are P0 items.

---

## 6. What the baseline does **not** contain (honest gaps)

1. **Accuracy numbers** — no labelled Iranian held-out set exists in the
   repository. `python eval/run_eval.py --split heldout-manifest` prints
   "dataset missing" and exits 0. The `heldout` set is a Phase 1 deliverable
   (design §6.3).
2. **Live multi-camera soak numbers** — needs real RTSP sources; unavailable here.
3. **`ruff check` output** — ruff is not installed locally (CI runs it). The
   Phase 0 change set was verified with `py_compile` on every new module plus
   the test run.

---

## 7. Reproduce this baseline

```powershell
cd D:\alpr
python --version
python -m pytest tests -q                     # 275 collected; 3 pre-existing failures
cd flutter_app; flutter test; cd ..           # 83 passed
python eval/bench_latency.py --image car_a.jpg --iterations 20 --warmup 3 `
    --out eval/baselines/v1-latency.json      # regenerate the latency baseline
python eval/run_eval.py --split heldout-manifest   # prints "dataset missing"
python eval/run_eval.py --self-test               # metric sanity checks
```

