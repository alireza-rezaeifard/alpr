# ALPR System Audit Report

**Project:** `D:\alpr` — Persian/Iranian License Plate Recognition (backend + Flutter client)
**Audit type:** Read-only architectural, performance, model, and UX audit
**Audit date:** 2026-09-29
**Code state:** `git` HEAD = `3f16f27` ("update some changes"), branch `main`
**Rule followed:** no code was modified. All findings cite file paths and line numbers. All timing numbers were produced by executing the repository code on this machine.

---

### Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture (Phase 1)](#2-current-architecture-phase-1)
3. [Current ALPR Pipeline (Phase 2)](#3-current-alpr-pipeline-phase-2)
4. [Performance Audit (Phase 5)](#4-performance-audit-phase-5)
5. [Duplicate Detection — Root Cause (Phase 3)](#5-duplicate-detection--root-cause-phase-3)
6. [AI Model Evaluation (Phase 4)](#6-ai-model-evaluation-phase-4)
7. [Flutter UI/UX Review (Phase 6)](#7-flutter-uiux-review-phase-6)
8. [Competitor Comparison (Phase 7)](#8-competitor-comparison-phase-7)
9. [Missing Features](#9-missing-features-consolidated-backlog-input)
10. [Recommended Roadmap (P0–P3)](#10-recommended-roadmap)
- [Appendix A — Methodology](#appendix-a--methodology-and-reproducibility) · [Appendix B — Model probes](#appendix-b--raw-model-probe-output) · [Appendix C — Risk register](#appendix-c--risk-register-things-that-will-bite-during-the-p0p1-work) · [Appendix D — Limitations](#appendix-d--audit-limitations-stated-explicitly)

---


## 1. Executive Summary

The project is a **two-tier ALPR system**: a Python/FastAPI inference backend (`api.py`, `alpr_engine.py`, `video_processor.py`) and a Flutter desktop/web client (`flutter_app/`). The recognition stack is a **5-model CPU PyTorch pipeline** (3 × YOLO detectors + 2 × ResNet18 classifiers) driven by OpenCV frame capture. There is **no vehicle tracking layer, no multi-frame voting, and no GPU acceleration path in practice**.

### Top-line verdicts (all measured, not estimated)

| Question | Answer | Evidence |
|---|---|---|
| Is the same vehicle emitted multiple times? | **Yes.** De-duplication is a single text-keyed `60 s` in-memory cooldown plus a history `count` field. There is no object identity, so any OCR wobble (or a new visit) creates a new record. | `video_processor.py:355`, `:485`, `:875`, `:1007-1037`; `db.py:146-184` |
| Measured inference cost | **~105–124 ms per frame** for one 1280×960 frame on CPU (≈ **8–9 FPS** ceiling for one camera, before HTTP/JPEG overhead) | benchmark of `AlprEngine.run()` (Appendix A) |
| Is frame skipping implemented? | **Only for RTSP.** Video files ignore `skip_frames` completely and run inference on **every** frame. | `video_processor.py:397-449` (unused `skip_frames`), `:944` (RTSP only) |
| GPU usage | **None in this environment.** `torch.cuda.is_available() == False`, `torch 2.12.0+cpu`; the Dockerfile also builds CPU-only torch. | local probe; `Dockerfile:28-31`, `docker-compose.yml:8` |
| Model efficiency | 2 of 5 models are **fp32 ResNet18 with ~45 MB weights each**; no ONNX/TFLite/FP16/quantization anywhere; plate crops are upscaled to the default `imgsz=640`. | `alpr_engine.py:154-167`, `:242-244`, `:343-345`; Appendix B |
| UI/UX | Functional but **design-system inconsistent**: hardcoded colors in 10 files, Fluent + Material mixed in one tree, no light mode, no theme toggle, no map/timeline/dashboard-level operations screens. | `theme.dart`, `app.dart:22`, `dashboard_view.dart`, `camera_live_monitor.dart` |
| Biggest immediate risk | **Unauthenticated legacy endpoints duplicated next to the secured routers**, including the camera PATCH the Flutter client actually uses, plus an unauthenticated MJPEG video stream. | `api.py:188-344`, `:521-560`; `routers/detection.py:386` |

### The three sentences that explain the project's status

1. The **detection/OCR quality problem is an architecture problem, not a model problem**: recognition happens per frame on independent detections with no notion of "this is the same car as 200 ms ago".
2. The **performance problem is a redundancy problem**: ~50 % of each frame's inference budget is spent on vehicle classification (make/color) that the operator rarely needs in real time, and plate crops are processed at 640 px instead of ~256 px.
3. The **UX problem is a design-system problem**: the visual language is re-invented per screen, so the app cannot be lifted to "modern ALPR console" quality by polishing widgets alone — it needs one token system, one component library, and the missing operational screens.

---

## 2. Current Architecture (Phase 1)

### 2.1 Repository structure

```
D:\alpr\
├─ api.py                     FastAPI app: lifespan, legacy REST endpoints, router includes, model singleton
├─ alpr_engine.py             AlprEngine: 5-model inference pipeline (the real recognizer)
├─ video_processor.py         VideoProcessor + RTSPStreamProcessor (threading, dedup, overlays, history)
├─ camera_manager.py          CameraManager: concurrency slots, FIFO queue, session lifecycle
├─ db.py                      SQLite access layer (sessions, detections, cameras, users, licenses, alerts…)
├─ plate_validator.py         Iranian plate format gate (8-char structure, region codes, metadata)
├─ plate_metadata.py          Category/colour-scheme/region derivation
├─ plate_reference.py         Letter→category and region→province lookup tables
├─ schemas.py, error_handler.py, conftest.py, test_backend.py, verification.py, ui.py (legacy Gradio)
├─ main.py                    Legacy single-image CLI (YOLO + DTRB, upstream README path)
├─ routers/                   auth, users, licenses, cameras, detection, scanner, watchlists, alerts,
│                             reports, export, audit, retention  (secured API surface)
├─ auth/                      JWT auth, RBAC, dependencies (current_user, require_permission, require_license)
├─ licensing/ audit/ retention/ watchlist/    Cross-cutting services
├─ database/plpr.db           SQLite (WAL)  +  license_plate_recognition.db (legacy)
├─ weigths/                   5 model files + Plates/city_plateinfo.txt (2 weight dirs are empty placeholders)
├─ flutter_app/               Flutter client (lib/{app,core,data,features,shared}), windows + web targets
├─ frontend/                  Secondary React 19 + Vite client (components: Dashboard, Detection, Analytics…)
├─ websit/                    Static marketing site (HTML/JS assets)
├─ deep_text_recognition_benchmark/   DTRB reference implementation (not wired into the live engine)
├─ tests/ + flutter_app/test/ Property/integration/widget tests
├─ .kiro/specs/              4 spec folders (requirements/design/tasks) — the authoritative design intent
└─ .github/workflows/ci.yml   ruff + flutter analyze + pytest + flutter test + Docker build
```

### 2.2 Technology stack (confirmed)

| Layer | Component | Version / detail | Evidence |
|---|---|---|---|
| Inference runtime | PyTorch (CPU build here) | `torch 2.12.0+cpu`, `cuda False` | local probe |
| Detectors | Ultralytics YOLO (YOLO11n) | `ultralytics 8.4.56` | `weigths/*.pt`, Appendix B |
| Classifiers | torchvision ResNet18 (fp32) | 11.18 M / 11.20 M params | `alpr_engine.py:154-155` |
| Frame I/O | OpenCV 4.13 + FFmpeg (TCP, `nobuffer`) | `cv2 4.13.0` | `video_processor.py:8-13` |
| Backend | FastAPI + Uvicorn, threaded workers | `requirements.txt` | `api.py:133-137`, `:828-836` |
| Storage | SQLite (WAL), one connection per call | `database/plpr.db` | `db.py:5-12` |
| Frontend (main) | Flutter + Riverpod + go_router + Dio + Fluent UI + PlutoGrid + Syncfusion | Flutter SDK `>=3.3.0`; installed **3.44.1 / Dart 3.12.1** | `flutter_app/pubspec.yaml:7-37`; CI pins **3.24.0** (`ci.yml`) |
| Frontend (secondary) | React 19 + Vite 6 + Recharts | `frontend/package.json` | — |
| Video playback | `media_kit` (Windows) / HTML `<video>` (web) | `pubspec.yaml:40-42` | `shared/playback/` |
| CI/CD | GitHub Actions → ghcr.io image | ruff, analyze, tests, docker | `.github/workflows/ci.yml` |

**Platform gap:** `flutter_app/` contains only `windows/` and `web/` targets (plus `assets/`). There is **no `android/`, `ios/`, or `linux/` folder**, and `pubspec.yaml` has **no camera plugin** — the "mobile AI" goal has no implementation yet; all inference is server-side.

### 2.3 Main modules and entry points

| Entry point | Purpose | File |
|---|---|---|
| `api:app` (uvicorn) | Production API; `lifespan` calls `init_db()`, `bootstrap_default_admin()`, `restore_cameras()`, `_load_models()` | `api.py:81-137`, `:826-836` |
| `AlprEngine(model_dir)` | Loads all 5 models once, exposes `run(frame) -> list[AlprResult]` | `alpr_engine.py:90-108`, `:282-392` |
| `VideoProcessor` | Background thread for uploaded video (open → per-frame detect → annotate → write) | `video_processor.py:350-590` |
| `RTSPStreamProcessor` | 3 threads: reader, ML worker, display/JPEG loop | `video_processor.py:609-982` |
| `CameraManager` | Camera CRUD, concurrency slots, FIFO promotion, sessions | `camera_manager.py:38-455` |
| `flutter_app/lib/main.dart` | `ProviderScope → PlprApp → GoRouter` | `main.dart:9-12`, `app/router.dart:72-177` |

### 2.4 Data flow (as implemented)

```
                    ┌─────────────────────────── Flutter client (windows/web) ───────────────────────────┐
                    │ Riverpod controllers ── Dio (ApiClient) ── poll timers                             │
                    └───┬───────────────┬──────────────────┬────────────────┬──────────────────────────┘
                        │ POST /api/detect/image            │ POST /api/detect/video  (multipart, skip_frames)
                        │ POST /api/detect/rtsp (url)       │ GET  /api/detect/*/{id}      (1 s poll)
                        │ GET  /api/detect/rtsp/{id}/frame  (100 ms poll)   │ GET .../mjpeg (MJPEG stream)
                        v                                   v
┌──────────────────────────────────────── FastAPI (api.py, routers/*) ────────────────────────────────────┐
│ auth (JWT/RBAC/license) → handler → AlprEngine (single process-wide instance, lazy-loaded)               │
│  • image: synchronous, in-request inference, one session, N save_detection rows                          │
│  • video: VideoProcessor thread per task (unbounded), writes annotated MP4 to io/output, polls state     │
│  • rtsp : CameraManager grants a slot (default limit 4) → RTSPStreamProcessor per camera                 │
└───────────────┬─────────────────────────────────────────────────────────────────────────────────────────┘
                v
        Camera / file frames (OpenCV BGR ndarray)
                │
                ├─ (video) every frame → detect_plates()
                └─ (rtsp)  should_sample(frame_count, skip_frames) → latest-frame slot → ML thread
                v
        AlprEngine.run(frame) = car_det(YOLO11n@640) → per-box {car_name ResNet18, color ResNet18}
                                → plate_det(YOLO11n@640) → char_det(YOLO11n@640 on crop) → text sort by x1
                v
        plate_validator.validate_iranian_plate(text, conf)   → gate: exactly 8 chars, letter, region
                v
        60 s in-memory text cooldown → plate_history (count) + live_detections + save_detection() → SQLite
                v
        overlays: draw_plate_template / draw_plate_overlay_fast → JPEG (RTSP: ~30 FPS, q50, ≤960 px)
                v
        UI: Image.network(MJPEG) on web, Image.memory(base64) fallback; history list from /status
```

**Two client generations coexist.** `frontend/` (React) and `flutter_app/` (Flutter) both target the same API, and `ui.py` (Gradio) is a third, older client; the FastAPI app even mounts `frontend/dist` at `/` (`api.py:821-823`). This triples the surface that must be kept in sync with API changes.

### 2.5 Networking / storage / state summary

- **Networking:** Dio with 10 s connect/receive defaults, 60 s upload timeout, JWT `AuthInterceptor` that clears the session and raises a re-auth signal on 401 (`core/api_client.dart:36-50`, `core/auth_interceptor.dart`, `app/router.dart:80-90`).
- **Storage:** SQLite WAL, `PRAGMA journal_mode=WAL`, one connection opened/closed per call (`db.py:8-12`). `detections` has **no unique constraint and no vehicle/track identity column** (`db.py:37-48`) — the schema itself cannot express "one row per vehicle".
- **State management (Flutter):** Riverpod 2.5.1 — `StateNotifier` controllers per feature (`data/controllers/*`), `FutureProvider` for dashboards, `StateNotifierProvider.family` per camera task for polling (`features/cameras/camera_poll_controller.dart:123-131`).
- **Camera implementation:** no device camera. Sources are RTSP/uploaded files handled by the backend; the client displays MJPEG (`Image.network`) or polls base64 JPEG frames.
- **Inference framework:** PyTorch + Ultralytics, models as `.pt` (Ultralytics checkpoints) and `.pth` (raw ResNet18 `state_dict`). **No ONNX, no TFLite, no TensorRT, no OpenVINO, no CoreML, no NNAPI.**

---

## 3. Current ALPR Pipeline (Phase 2)

### 3.1 Stage-by-stage trace with code anchors

| # | Stage | Implementation | Notes |
|---|---|---|---|
| 1 | Camera input | `cv2.VideoCapture` with FFmpeg TCP/low-delay options (`video_processor.py:8-13`, `:404`, `:779-787`) | Reader thread for RTSP; direct `cap.read()` loop for files |
| 2 | Frame processing | RTSP: sequence-tagged raw slot, `sleep(0.005)` when no new frame (`:928-939`). Video: blocking read loop (`:438-441`) | No resize before inference |
| 3 | Object (vehicle) detection | `car_det_model.pt` YOLO11n, `conf=0.6`, `max_det=20`, COCO 80-class, filtered to classes `[2,3,5,7]` (`alpr_engine.py:45`, `:300-328`) | 80-class model for 4 needed classes |
| 4 | Plate detection | `plate_det_model.pt` YOLO11n, 1 class, `conf=0.6`, `max_det=12`, `iou=0.45` (`:47`, `:56-58`, `:343-346`) | Runs on the **full frame** |
| 5 | Image preprocessing | Plate crop → char model (no explicit resize; Ultralytics default `imgsz=640`) (`:242-244`); vehicle crop → `Resize((220,165))` + ImageNet norm (`:161-165`) | Non-standard 220×165 resize for a 224×224 network |
| 6 | OCR | `char_model.pt` YOLO11n, 27 classes, `conf=0.3`; boxes sorted by `x1`, class index mapped through the hardcoded `CHAR_CLASSNAMES` list (`:27-31`, `:260-274`) | Character **detection**, not a text recognizer: no CTC/attention, no language model, no dictionary |
| 7 | Result processing | `validate_iranian_plate` (8 chars, letter, region) → `best_plate_text` → 60 s cooldown → history/metadata (`video_processor.py:454-551`, `:840-915`) | City lookup only when `len(text) >= 8` and letter/number are latin (`alpr_engine.py:364-369`) |
| 8 | Storage / UI | `save_detection()` per emission (`db.py:146-184`); overlays drawn and JPEG-encoded for the client; `plate_history` serialized by `/status` (`video_processor.py:1039-1052`, `routers/detection.py:355-383`) | UI never receives `track_id` because none exists |

### 3.2 Answers to the eight pipeline questions

1. **How many frames per second are processed?**
   **RTSP:** sampled frames are submitted at `1 / skip_frames` of the stream rate (`should_sample`, `video_processor.py:47-54`, `:944`) but the ML worker only consumes the *latest* pending frame, so effective inference rate = `min(stream_fps / skip_frames, 1 / inference_time)`. With the measured `105–124 ms/frame`, that is **≈ 8–9 FPS max**, i.e. `skip_frames=15` on a 25 FPS stream is silently capped by inference speed, not by the configured skip.
   **Video files:** every frame (see #3 below).
   **Display:** ~30 FPS JPEG production independent of inference (`:951-973`).

2. **Is inference executed on every camera frame?**
   For RTSP, **no** — only sampled frames enter the ML slot. For video files, **yes** — `detect_plates()` is called inside the untimed read loop for every decoded frame (`video_processor.py:447-449`).

3. **Is frame skipping implemented?**
   Partially and inconsistently. `skip_frames` is a real gate only for RTSP (`:944`). `VideoProcessor._run(input_path, skip_frames, fast_mode)` receives the parameter and **never uses it** (`:397-449`); a repository-wide search shows the only uses of `skip_frames` in `video_processor.py` are definition, plumbing, and the RTSP branch. The project's own design document states the intent: *"inside the frame loop, gate with `should_sample`"* (`.kiro/specs/realtime-plate-recognition/design.md:286`) — the video path violates that requirement.

4. **Is there any queue/buffer system?**
   A **single-slot latest-frame buffer** for RTSP (`_ml_pending_frame`, `:820-834`) with a `_ml_busy` flag that is written but never read; the display loop overwrites the pending frame whenever a newer sampled frame exists. Uploaded videos are processed by one thread per task with **no queue and no global concurrency limit** (`routers/detection.py:201-232`), so N simultaneous video uploads spawn N full inference loops. Camera concurrency is capped only for RTSP (`CameraManager`, default limit **4**, `db.py:get_concurrency_limit`).

5. **Is processing blocking the UI thread?**
   The backend runs inference on worker threads (`VideoProcessor._run`, `RTSPStreamProcessor._ml_worker`), so FastAPI's event loop is not blocked by inference. However, the **image endpoint performs inference synchronously inside the request** (`routers/detection.py:94-161`) and each `/frame` or `/status` poll takes the processor lock while reading shared state (`routers/detection.py:367-371`), so concurrent requests on a busy camera queue up behind the ML thread's lock.

6. **Are inference tasks asynchronous?**
   Partially. Tasks are thread-based, not `async`; `AlprEngine.run()` is a blocking synchronous call. There is exactly **one shared `AlprEngine` instance** (`api.py:30-52`) with no locking around model invocation — PyTorch is thread-safe for inference but the two ResNet18 models and three YOLO models are serialized by the GIL/CPU scheduler when several cameras run at once.

7. **Are there isolates/workers?**
   No Dart isolates anywhere in `flutter_app/`; no Python multiprocessing either. All parallelism is `threading.Thread` (reader, ML, display per camera) plus `ThreadPoolExecutor` for the IP scanner (`api.py:490`) and stream probing (`api.py:787`).

8. **Is GPU acceleration used correctly?**
   Not used at all in practice. `alpr_engine.py:91` selects CUDA only if `torch.cuda.is_available()`; on this machine it is `False` (`torch 2.12.0+cpu`), and the Docker image is explicitly CPU-only (`Dockerfile:28-31`, `docker-compose.yml:8`). Even with a GPU, the pipeline never sets `half=True`, `device=`, `imgsz=`, or uses CUDA graphs/TensorRT, so a GPU would be under-used. The `_device` is honored for ResNet18 (`:159`, `:192`) but YOLO calls never pass `device`, so YOLO would silently use its own default.

---

## 4. Performance Audit (Phase 5)

### 4.1 Measured baseline (this machine: CPU-only, 6 PyTorch threads, 1280×960 test frame `car_a.jpg`)

Full pipeline benchmark of `AlprEngine.run()` (instrumented, repository code unmodified):

| Stage | Calls / frame | Measured cost |
|---|---|---|
| `car_det_model` (YOLO11n@640, full frame) | 1 | ≈ 24 ms (standalone measurement) |
| `car_name_model` (ResNet18, per vehicle box) | **2** | 24.5 ms/frame (12.3 ms per call) |
| `color_model` (ResNet18, per vehicle box) | **2** | 23.5 ms/frame (11.7 ms per call) |
| `plate_det_model` (YOLO11n@640, full frame) | 1 | ≈ 24 ms (standalone measurement) |
| `char_model` (YOLO11n@640 on plate crop) | 1 | 9.5 ms/frame |
| **Total `AlprEngine.run()`** | — | **105 / 107 / 108 / 111 / 124 ms** (5 runs) |

Ultralytics resolution sweep, same frame:

| Model | `imgsz=640` | `imgsz=320` |
|---|---|---|
| `plate_det_model.pt` | 24 ms | **12 ms** |
| `car_det_model.pt` | 24 ms | **11 ms** |
| `char_model.pt` | 23 ms | **11 ms** |

**Consequences**

- Single camera: **≈ 8–9 FPS** inference ceiling; the display path still draws 30 FPS, so the UI shows smooth video with stale boxes — which is what an operator perceives as "detection is slow".
- Default `concurrency_limit = 4` (`db.py:get_concurrency_limit`) allows 4 cameras × ~110 ms of CPU work per frame on the same box → CPU saturation long before 4 cameras are useful. Scaling is additive because there is no batching and no resolution reduction.
- Because the same plate is re-recognized 8–9 times per second, the wasted inference is also the **root enabler of duplicates** (Section 5).

### 4.2 Findings by severity

#### CRITICAL

| # | Finding | Evidence | Why it matters |
|---|---|---|---|
| C1 | **Vehicle make/colour classification consumes ~48 ms/frame (≈ 45 % of inference), for every vehicle box, on every frame.** `_predict_car` runs for `class_id == 2`, `_predict_color` for *all* vehicle classes, inside the per-box loop. | `alpr_engine.py:319-322`, `:186-222`; measured 24.5 + 23.5 ms | Nearly half the CPU budget produces data (make/colour) that changes once per vehicle, yet is recomputed ~8×/second per camera. |
| C2 | **Plate crops are upscaled to the Ultralytics default `imgsz=640`.** No `imgsz` is passed for any YOLO call. | `alpr_engine.py:242-244`, `:300-306`, `:343-346` | A ~200×60 crop is letterboxed to 640, costing the same 23 ms as a full frame and adding interpolation artefacts. `imgsz=256/320` measures ~11 ms with equal or better character recall in the sweep. |
| C3 | **Video-file processing ignores frame skipping entirely.** | `video_processor.py:397-449` (parameter unused); spec intent at `.kiro/specs/realtime-plate-recognition/design.md:286` | A 60 s 30 FPS clip = 1800 full pipelines ≈ 3+ minutes of pure inference on this CPU, with 1800 opportunities to emit the same plate. |
| C4 | **No model optimization path anywhere:** no FP16, no ONNX Runtime, no OpenVINO, no TensorRT, no quantization, no `half=True`, no `device=` on YOLO calls. | repo-wide search for `imgsz\|half\|onnx\|tflite\|quantiz` → only `torch.no_grad()` at `alpr_engine.py:193`, `:212` | Every available 2–6× speedup (ONNX/OpenVINO CPU, FP16/TensorRT GPU, int8 for edge) is left unused. |
| C5 | **Client polls a 100 ms timer per camera for frames plus a 3 s full-status poll, and the full status includes the entire history and live-detection list.** | `camera_poll_controller.dart:49-55`, `:93-111`; `routers/detection.py:355-383`; `video_processor.py:1039-1052` | 10 HTTP round-trips/s/camera, each rebuilding Riverpod state, each returning growing JSON, each creating a new `Image.memory` (JPEG decode) on the fallback path (`camera_live_monitor.dart:372-374`). UI-thread CPU burn proportional to camera count. |
| C6 | **The display loop JPEG-encodes every ~33 ms per camera at up to 960 px width, independently of inference.** | `video_processor.py:949-973` | ~30 encodes/s/camera of a 960-px frame; with 4 cameras that is a large, avoidable slice of the same CPU inference needs. |

#### HIGH

| # | Finding | Evidence | Why it matters |
|---|---|---|---|
| H1 | `car_det_model.pt` is an 80-class COCO detector used to find 4 vehicle classes; `max_det=20` means the per-box classifier loop can run up to 20 times per frame in a crowded scene (theoretical 20 × 12 ms ≈ 240 ms). | `alpr_engine.py:33-38`, `:45`, `:56-57`, `:300-328` | A 1-class vehicle detector (or `classes=[2,3,5,7]` at the Ultralytics call) removes a large tail-latency risk. |
| H2 | No pre-inference downscale. A 1920×1080 or 4K stream is fed to YOLO whole; only the *display* copy is resized. | `video_processor.py:960-968` (display resize only) | Inference cost scales with input; a 720p working resolution is standard practice. |
| H3 | `plate_det` and `char_det` run on every frame regardless of vehicle presence; the vehicle boxes computed in the same call are not used as a region of interest for the plate search. | `alpr_engine.py:295-346` | Plate search could be restricted to vehicle crops instead of the full frame. |
| H4 | `_ml_busy` is written but never checked; the pending-frame slot is overwritten, so work is discarded invisibly and no metric records "frames skipped". | `video_processor.py:822`, `:839-840`, `:920-922` | No observability into the real processing rate; `skip_frames` settings cannot be validated operationally. |
| H5 | Every DB call opens a new SQLite connection; `save_detection` also runs watchlist matching and possibly alert inserts synchronously on the caller thread. | `db.py:8-12`, `:146-184`, `:187-207`; `video_processor.py:906-915` | Per-detection write amplification; alert writes can block the inference pipeline. |
| H6 | `video_status` re-encodes a JPEG on every poll although the RTSP path already keeps an encoded frame. | `routers/detection.py:250-258` vs `:366-376` | One extra encode per second per task on the request thread. |
| H7 | IP scanner: up to 50 threads × (IPs × ports), plus a separate 10-thread RTSP probe pool, each probe with 0.8–3 s socket timeouts. | `api.py:484-515`, `:749-805` | Saturates CPU/network and starves inference on the same host; no rate limit or CPU budget. |

#### MEDIUM

| # | Finding | Evidence | Why it matters |
|---|---|---|---|
| M1 | ResNet18 inputs are resized to **220×165** (non-square, non-standard) although the network expects 224×224. | `alpr_engine.py:60`, `:161-165` | Slight accuracy loss plus a redundant resize; a square 224 (or 160) input is faster and better matched to the ImageNet normalization already applied. |
| M2 | `_find_city` linearly scans the CSV for every detected plate. | `alpr_engine.py:224-229` | Trivial today (small CSV) but O(n) per detection; a dict index is free. |
| M3 | Overlays are drawn with PIL and the "fast" path is selected by comparing the lengths of two parallel lists. | `video_processor.py:119-273`, `:951-958` | CPU-heavy on the display path and a correctness trap if the lists desynchronize. |
| M4 | `get_state()` copies the full history and live-detection lists on every status poll while holding the processor lock. | `video_processor.py:1039-1052` | Lock contention with the ML thread grows with session length. |
| M5 | `withOpacity` (deprecated) and `withValues` are mixed across 10 UI files. | `dashboard_view.dart:371-427` vs `camera_live_monitor.dart` | `flutter analyze` noise and a signal of inconsistent hygiene. |
| M6 | CI runs `flutter analyze` on Flutter **3.24.0** while the local toolchain is **3.44.1** and `pubspec.yaml` allows `>=3.3.0`. | `.github/workflows/ci.yml` vs `flutter --version` | CI green does not prove the developer's build is clean, and vice versa. |

#### LOW

| # | Finding | Evidence |
|---|---|---|
| L1 | `log_demo_result.txt` (547 KB) and `io/output/*.mp4` (≈ 36 MB of processed clips plus leftover `input_*.mp4` uploads) remain on disk. | repository listing; `.gitignore` excludes `io/output/` but the files are present |
| L2 | Duplicate route definitions and two camera implementations (legacy `api.py` handlers vs maintained `routers/cameras.py`). | `api.py:261-341` vs `routers/cameras.py` |
| L3 | Legacy `database/license_plate_recognition.db` still sits next to the live `plpr.db`. | `database/` listing |
| L4 | `weigths/dtrb-recoginzer/` and `weigths/yolov8-detector/` contain only `.gitkeep`, but `.gitignore` references the DTRB `.pth` and a yolov8-s plate detector; `main.py:30` and `ui.py:20` point at a non-existent recognizer path. | `.gitignore:1-2`; `main.py:30`; `ui.py:20` |

---

## 5. Duplicate Detection — Root Cause (Phase 3)

### 5.1 What exists today

| Capability | Present? | Location / detail |
|---|---|---|
| Object tracking (SORT / DeepSORT / ByteTrack / any Kalman filter) | **No** | repo-wide search for `track|SORT|ByteTrack|Kalman` finds only `group_detections` (a y-aware grouping heuristic, `video_processor.py:86-117`) and unrelated strings (`sorted`, `tracking` in doc comments) |
| Vehicle/plate identity (track id) | **No** | `AlprResult` has no id field (`alpr_engine.py:65-77`); `detections` table has no track column (`db.py:37-48`) |
| Temporal aggregation / voting across frames | **No** | every frame's OCR result is judged alone |
| Duplicate prevention | **Partially:** in-memory 60 s cooldown keyed on the exact plate string | `video_processor.py:355` (`_DEDUP_WINDOW_SECONDS = 60.0`), `:485-487` (video), `:875-877` (RTSP) |
| History de-duplication | **Yes, by exact text with a `count` field** | `_add_to_history`, `video_processor.py:1007-1037` |
| Per-session unique-plate counting | Yes — `len({p["dtrb_text"] ...})` | `camera_manager.py:369`, `:411`; `routers/detection.py:222`, `:449` |
| DB-level uniqueness / upsert | **No** | `db.py:146-184` is a plain `INSERT` |

### 5.2 Why the same vehicle is reported multiple times

Observed input pattern (the user's example):

```
Frame 1: 12ب34567     Frame 2: 12ب34567     Frame 3: 12ب34567
```

The system produces multiple records because **there is no object identity between frames**. Four independent mechanisms each break de-duplication:

1. **Text-keyed cooldown is fragile by construction.** The key is the *recognized string*, so anything that changes one character creates a new "vehicle" for the system. The repository's own OCR log shows exactly this:
   - `/log_demo_result.txt` (1863 recognition lines): plate `28i68923` appears **176×**, its single-character variant `28i68973` appears **19×**, and `12i25614` appears alongside `12i2561` and `12i2561`-with-low-confidence (`0.6122`). Same physical car, several distinct DB rows.
   - The same log is full of low-confidence garbage (`1499` @ 0.0496, `34992` @ 0.0220, `7819` @ 0.0455) — the OCR emits unstable strings, and each stable-looking variant is a new identity.
2. **The cooldown is time-based, not event-based.** `60 s` is a guess at "visit length". A car waiting at a gate for 61 s, a slow pass, or a re-approach after a U-turn legitimately re-emits — with no `track_id` the system cannot distinguish "same vehicle, still here" from "new vehicle".
3. **The cooldown is per processor instance and in memory only.** `_recent_emit_times` lives on the object (`:379`, `:636`) and dies with it; a backend restart, a reconnect, a camera restart, or a second camera viewing the same car re-emits immediately. The dictionary also never expires entries (unbounded growth over a long session).
4. **The gating is applied at the wrong layer.** The cooldown decides whether to *write to the DB*, but the underlying recognition is still executed on every sampled frame, and **the overlay/history/inference work is duplicated even when the write is suppressed** (`:880-886` still rebuilds overlay state each frame). Also, because `_add_to_history` is only reached when the cooldown passes, the `count` field it maintains is effectively always `1` — the "detection count" feature the spec asks for (`.kiro/specs/iranian-plate-recognition-upgrade/requirements.md:52`) is neutralized by the cooldown above it.

**Summary of the chain:**

```
per-frame independent detection
   → per-frame OCR (char-detection; no language model; unstable on blur/angle)
      → string changes by 1 char  OR  60 s elapses  OR  processor restarts
         → cooldown key mismatches
            → new history entry + new DB row for the SAME vehicle
```

### 5.3 The correct architecture

```
Camera frames
   │
   ├─ 1. DETECTION  (YOLO plate + vehicle)                        [exists]
   │
   ├─ 2. TRACKING   (ByteTrack / SORT on plate boxes)             [MISSING]
   │        • assigns track_id, keeps Kalman state, tolerates short
   │          occlusions and low-confidence frames
   │        • provides vehicle-level identity: one car = one track
   │
   ├─ 3. MULTI-FRAME CONSENSUS per track_id                       [MISSING]
   │        • collect (text, char_conf, plate_det_conf, sharpness,
   │          area, aspect, bbox) for each observation of the track
   │        • keep a per-character belief vector, not a string
   │        • accept when (a) N_of_M frames agree  OR  (b) the
   │          character-wise posterior exceeds a threshold
   │        • prefer the sharpest / largest / most frontal frame
   │          (proxy: Laplacian variance and plate area)
   │
   ├─ 4. SINGLE VEHICLE EVENT                                     [MISSING]
   │        • emit exactly one event per track lifecycle
   │          (on "track confirmed" + "best-shot update"), with a
   │          per-camera cooldown as a safety net only
   │        • store track_id, first_seen, last_seen, frame_count,
   │          agreement_ratio, best_frame_path in `detections`
   │
   └─ 5. DOWNSTREAM: alerts / watchlists / analytics keyed on event_id
```

**Minimum schema/API changes implied (not implemented here):** `detections.track_id`, `detections.event_id`, `detections.agreement_ratio`, `detections.frame_count`, `detections.best_frame_path`, plus a `plate_observations` table if per-frame evidence must be auditable. The API/UI then show one row per vehicle instead of one row per recognition.

---

## 6. AI Model Evaluation (Phase 4)

### 6.1 Inventory (files verified on disk; parameter counts and architectures probed by loading them)

| Model | File / size | Framework | Architecture | Classes | Input resolution | Device support |
|---|---|---|---|---|---|---|
| Plate detector | `weigths/plate_det_model.pt` — 5,477,267 B (5.2 MB) | Ultralytics PyTorch | **YOLO11n** (`yaml_file: yolo11n.yaml`), 2,590,035 params | 1 (`LicensePlate`) | default **640** (never overridden) | CPU here; CUDA if available (not passed) |
| Vehicle detector | `weigths/car_det_model.pt` — 5,613,764 B (5.4 MB) | Ultralytics PyTorch | **YOLO11n**, 2,624,080 params | **80 (COCO)**, filtered at runtime to 4 | default **640** | as above |
| Character detector (OCR) | `weigths/char_model.pt` — 6,218,616 B (5.9 MB) | Ultralytics PyTorch | YOLO detector, 3,016,113 params | **27**, but class **names are `"1"…"27"`** (label indices, not characters) | default **640** applied to a plate crop | as above |
| Vehicle make classifier | `weigths/car_name_model.pth` — 44,841,766 B (42.8 MB) | torchvision | **ResNet18 fp32 `state_dict`**, 11,199,983 params, `fc` = 27 classes | 27 Iranian makes | 220×165 + ImageNet norm (`Resize((220,165))`) | CPU/CUDA honored (`_device`) |
| Vehicle colour classifier | `weigths/color_model.pt` — 44,811,614 B (42.7 MB) | torchvision | **ResNet18 fp32 `state_dict`**, 11,182,668 params, `fc` = 12 classes | 12 colours | 220×165 + ImageNet norm | CPU/CUDA honored |
| (unused) Text recognizer | `weigths/dtrb-recoginzer/` — **empty** (`.gitkeep`) | — | DTRB (TPS-ResNet-BiLSTM-CTC) referenced by `main.py:30`, `ui.py:20` | — | 100×32 | **dead path** |

Total resident weight footprint ≈ **100 MB** of model files, of which ~86 MB is the two ResNet18s.

### 6.2 Comparison table

| Model | Accuracy (assessed) | Speed (measured, CPU) | Memory | Recommendation |
|---|---|---|---|---|
| `plate_det_model` (YOLO11n, 1 class) | Likely the healthiest component (single-class, modern backbone); README quotes 0.7219 mAP-era numbers for the upstream model, so **current accuracy is unverified** — no evaluation harness or dataset in the repo | 24 ms @640, **12 ms @320** | ~5 MB + activations | Keep. Add `imgsz=960` for plate detection *only if* needed for small plates, otherwise 640 stays; export to ONNX/OpenVINO for 1.5–3× on CPU |
| `car_det_model` (YOLO11n, 80 class) | Adequate but wasteful — the pipeline only needs `car, motorcycle, bus, truck` | 24 ms @640, 11 ms @320 | ~5 MB | Retrain/export as **4-class** or pass `classes=[2,3,5,7]`; drop to `imgsz=480/320` |
| `char_model` (YOLO, 27 classes) | **Highest risk of the five.** Class names are indices (`'1'..'27'`) while the code maps class index → `CHAR_CLASSNAMES`, a 28-entry list that contains **duplicated letters** (`"n"` at index 9 and 13, `"s"` at 10 and 14) and multi-character tokens (`"ein"`, `"gh"`, `"sad"`, `"ta"`, `"malul"`) that cannot survive an 8-character plate check | 23 ms @640, 11 ms @320 | ~6 MB | Freeze the class↔character contract in one place (a single JSON/spec), evaluate on a labelled Iranian plate set, add a temperature/conf gate, consider a CTC recognizer (DTRB/CRNN/ParseQ) instead of per-character detection |
| `car_name_model` (ResNet18) | Unknown; `CAR_NAME_THRESH = 0.65` silently returns `None` below threshold | ~12 ms / call | 43 MB fp32 | **Demote to on-demand**: compute once per confirmed vehicle event, or drop from the real-time path entirely. Export int8/FP16 or replace with a small mobile net |
| `color_model` (ResNet18) | 12 classes; `COLOR_THRESH = 0.7` | ~12 ms / call | 43 MB fp32 | Same as above; colour is a slow-changing attribute — one inference per vehicle event is enough |

### 6.3 Optimization checks requested

| Check | Result |
|---|---|
| Models unnecessarily large? | **Yes.** 86 MB of the 100 MB is two fp32 ResNet18s used for make/colour, computed per box per frame. |
| Quantization present? | **No.** No `torch.quantization`, no `dynamic_quant`, no int8 anywhere. |
| ONNX / TFLite export present? | **No.** Models load as `.pt` / `.pth` only. |
| TensorRT / CoreML / NNAPI possible? | Technically yes: YOLO11n and ResNet18 both have mature TensorRT/CoreML/NNAPI/OpenVINO paths, but the current architecture is **server-side inference over HTTP**, so on-device acceleration is only relevant once the "mobile ALPR" goal is pursued (no `android/`/`ios/` target exists today). |
| Batching used? | **No.** One frame, one call, per camera. Ultralytics supports batch inference; the code never builds a batch. |
| FP16 / half precision? | **No** (`half=True` never passed). |

---

## 7. Flutter UI/UX Review (Phase 6)

Scope: `flutter_app/lib/` (31 200+ lines of Dart across `app/`, `core/`, `data/`, `features/`, `shared/`). Verdicts only — no redesign proposals in this section.

### 7.1 Widget organisation

- Structure is clean at the folder level (`features/<feature>/<feature>_view.dart`, `shared/widgets/`, `data/{models,repositories,controllers}`), and shared primitives exist (`ScreenShell`/`ScreenHeader`/`ToolbarButton` in `shared/widgets/screen_shell.dart`, `AppDataGrid`, `ChartCard`, `PlateDetailCard`, `PermissionGate`, `ConnectivityBadge`).
- **But the components are used inconsistently.** `dashboard_view.dart` and `history_view.dart` use `ScreenHeader`; `detection_view.dart`, `camera_live_monitor.dart`, and `scanner_view.dart` hand-roll their own headers, cards, tab bars (`_ModernTabBar`, `_ModernButton`, `_PlateStrip`, `_StatusDot`) inside the feature files. There is no single button/card/table component set — each screen reinvents them.
- Duplicated helper functions live per file: `_sourceLabel` and `_errorMessage` are copy-pasted in `dashboard_view.dart:403-442`, `history_view.dart:430-441`, `:512-515`, and elsewhere. Any copy change must be made N times.
- File sizes are a symptom: `camera_live_monitor.dart` 26.5 KB / `scanner_view.dart` 26.3 KB / `cameras_view.dart` 23.7 KB / `watchlists_view.dart` 24.0 KB in single files with 10–17 `setState` calls each.

### 7.2 Theme system

- `AppTheme` defines a real token set (`theme.dart:11-21`) but **the app only ever uses `AppTheme.fluentDark`** (`app.dart:22`); `fluentLight` (`theme.dart:48`) is dead code and there is **no `themeMode`, no theme switch, and no settings entry for appearance** (`settings_view.dart` covers only concurrency + retention).
- Most feature screens do not read the theme at all: 143 hardcoded `withOpacity(...)` / `withValues(...)` colour usages across 10 files (`video_sub_view` 28, `image_sub_view` 24, `license_view` 21, `rtsp_sub_view` 19, `settings_view` 15 …), plus literal colours like `Color(0xFF111113)`, `Color(0xFF3B82F6)`, `Color(0xFFEF4444)` baked into cards, borders, and text (`rtsp_sub_view.dart:62-68`, `dashboard_view.dart:371-433`). The visible "dark console" look is therefore **hardcoded, not themeable**.
- Two design languages coexist in one widget tree: Fluent (`NavigationView`, `PaneItem`, `FluentIcons`) and Material (`Scaffold`, `AppBar`, `Card`, `AlertDialog`, `SnackBar`, `TabBar`, `TextField`, `CircularProgressIndicator`). `app.dart:39-46` has to inject a `Material` + `ScaffoldMessenger` wrapper just to keep Material widgets alive inside `FluentApp`. Result: mixed corner radii, elevations, focus rings, and hover behaviour between screens.

### 7.3 Navigation

- `go_router` with a redirect guard is well-implemented and tested (`router.dart:43-90`, `test/app/routing_test.dart`), and routes exist for dashboard, history, analytics, sessions, detection, cameras, live-monitor, watchlists, users, audit, license, settings.
- Weaknesses: every route is a `CustomTransitionPage` with **no transition at all** (`_noTransition`, `router.dart:202-208`) → navigation feels abrupt; the nav pane is a single flat list of 8 items with role-gated items appended in the footer (`shell_scaffold.dart:107-139`) → no grouping, no breadcrumbs, no deep-linking from a detection to its camera/session; `ShellScaffold` mounts only the selected pane body to avoid a Flutter/Fluent IndexedStack bug (`shell_scaffold.dart:98-105`) — a workaround that discards per-screen state on navigation.

### 7.4 State handling

- Riverpod is used correctly at the plumbing level (providers per repo/controller, `autoDispose` families for polling, `ref.onDispose` cancelling timers — `health_controller.dart:26-29`, `rtsp_poll_controller.dart:125-129`).
- Problems: (a) **polling drives UI state** — 100 ms (`camera_poll_controller.dart:49`) and 1 s (`rtsp_poll_controller.dart:93`, `video_task_controller.dart:119`) timers push a whole new state object each tick, so every camera tile rebuilds 10×/s; (b) state shapes are duplicated — `DetectionController`, `RTSPPollController`, `VideoTaskController`, and the newer `CameraPollController` overlap heavily (three ways to do the same task-status polling); (c) `setState` is used for page-level state in views that also hold Riverpod controllers (17 in `scanner_view.dart`, 8 in `video_sub_view.dart`), which is inconsistent with the rest of the app; (d) no error-boundary/`AsyncValue.error` pattern at the shell level — errors are rendered per screen.

### 7.5 Responsive design, dark mode, animation, accessibility

| Aspect | Assessment | Evidence |
|---|---|---|
| Responsive | Partial. Two `LayoutBuilder` breakpoints at 900 px in `dashboard_view.dart:56-85` and one in `analytics_view.dart:47`; the camera grid has a manual column picker (`camera_live_monitor.dart:72-99`). Everything else is fixed-size padding/font assumptions (`EdgeInsets.all(24)`, fixed 300×400 dialogs at `camera_live_monitor.dart:124-127`). No breakpoint constants, no adaptive typography, no tablet/phone layout. | `dashboard_view.dart`, `camera_live_monitor.dart`, `analytics_view.dart` |
| Dark mode | **Effectively dark-only.** One dark theme is hardcoded; no toggle, no `MediaQuery.platformBrightness` handling, no light-token coverage. | `app.dart:22`, `theme.dart:48` |
| Animation | Minimal and inconsistent: `flutter_animate` fade-ins in `detection_view.dart:79`, `:160`; `AnimatedContainer` in the tab bar; `NavigationPaneThemeData.animationDuration: 200 ms`. No transitions on route changes, no live-detection flash/highlight on new plate, no chart/table entrance animation, no skeleton loaders (only `CircularProgressIndicator`, used in 17 files). | `detection_view.dart`, `router.dart:202-208` |
| RTL / Persian | Good: app-level `Directionality.rtl` (`app.dart:18-19`), Vazirmatn font, `PersianFormat` helpers with Jalali (`Shamsi`) dates and Persian digits (`core/persian_format.dart`, `data/models/persian_format.dart`). Mixed-language strings remain, though — screen copy is a mix of Persian (`داشبورد`) and English (`Detection`, `Live Detections`, `No detections yet`, `History (${history.length})` in `rtsp_sub_view.dart:294-321`, `camera_live_monitor.dart:36-38`, `:195-216`). No ARB/`AppLocalizations` layer anywhere; all strings are inline literals. | `app.dart`, `persian_format.dart`, `rtsp_sub_view.dart` |
| Accessibility | Very weak: only **4** matches for `Semantics(`/`Tooltip(`/`ExcludeSemantics`/keyboard-shortcut APIs across the whole `lib/`. Many controls are raw `GestureDetector` on `Container`s (`_ModernButton`, `_PagerBtn`, `_PlateStrip`, tab bar buttons) with no focus ring, no keyboard activation, no screen-reader label, and no `MouseRegion` cursor on several. For a desktop/web console used with a mouse and keyboard, this is a functional gap, not just an a11y checkbox. | grep counts across `flutter_app/lib/**/*.dart` |
| Feedback / states | Empty and error states exist (e.g. `_ErrorBanner` with retry in `dashboard_view.dart:416-437`, per-screen error text), but they are inconsistent in style, and there are **no skeleton loaders, no toast/dialog-free progress affordances for long video jobs beyond a percentage, no "inference lag" indicator** even though the pipeline is demonstrably slower than the display FPS. Live-confidence information is text-only (a colored percentage badge in `history_view.dart:405-413`, a green pill in `dashboard_view.dart:392-396`). | `dashboard_view.dart`, `history_view.dart` |

### 7.6 Missing screens / features (report only — assessed against the existing API surface)

| Missing capability | Status | Note |
|---|---|---|
| Live detection dashboard with **per-camera health, inference FPS, and lag** | Missing | Backend already exposes status strings but no metrics (`video_processor.py:1039-1052`); no screen consumes anything like it |
| Detection history with **vehicle timeline / event grouping** | Partial | History is a flat PlutoGrid of recognition rows (`history_view.dart`); no grouping by vehicle, no track/event concept to display |
| **Confidence visualisation** beyond a percentage badge | Partial | No per-character confidence, no OCR candidate list, no bounding-box confidence overlay in the UI (the backend computes `char_bboxes` but the client never renders them) |
| Plate **image / best-frame** preview with zoom | Missing | `PlateDetailCard` shows text/metadata only; no `InteractiveViewer`, no crop thumbnails, no comparison of frames |
| **Search / filter** across plate, camera, time range, confidence | Partial | Text search + source filter in `history_view.dart`; no time-range picker, no camera filter, no confidence range |
| **Analytics dashboard** (traffic, hourly heatmap, confidence distribution) | Partial | `analytics_view.dart` + Syncfusion charts exist for timeline/letters/sources/confidence |
| **Operations map** (camera locations, lanes) | Missing | No map dependency, no geo fields |
| **Global settings** (theme, language, notifications, inference profile, resolution) | Partial | `settings_view.dart` covers concurrency and retention only |
| **Camera configuration** (zones/ROI, plate-region, exposure, stream profile, per-camera model settings) | Missing | Only name/URL/skip_frames (`camera_model.dart`, `cameras_view.dart`) |
| **Watchlist hit alerting UX** (real-time banner, sound, acknowledge workflow) | Partial | Alerts exist as data (`data/models/alert.dart`, `alerts_repo.dart`, `alerts_controller.dart`) but there is no live alert surface in the nav (watchlists/alerts share one screen) and no acknowledgement flow in the UI |
| **Export/report** (PDF report, plate audit trail) | Partial | CSV export exists (`shared/download/file_saver.dart`, `routers/export.py`); no PDF, no scheduled reports |
| **Login/user management polish** (profile, password change) | Partial | `login_screen.dart`, `users_view.dart` exist; no profile screen |

---

## 8. Competitor Comparison (Phase 7)

Sources verified during this audit: OpenALPR repository README (openalpr/openalpr, AGPLv3, C++/Tesseract/OpenCV lineage), Plate Recognizer documentation (docs.platerecognizer.com — Snapshot/Stream/ParkPow, on-prem SDK, Android SDK), ByteTrack paper (arXiv:2110.06864), and the video-ALPR efficiency paper (arXiv:2501.04750). Commercial closed systems (Rekor, Vaxtor, Genetec-class LPR) are described at the capability level only, which is what their public material supports.

### 8.1 Architecture

| Dimension | This project | OpenALPR (OSS) | Plate Recognizer–class service | Modern edge appliance class |
|---|---|---|---|---|
| Deployment shape | FastAPI + threaded workers on one host; Flutter desktop/web thin client | C++ library + CLI + `alprd` daemon for streams | Cloud API + on-prem SDK (local HTTP, `/v1/plate-reader/`) | Appliance/edge box or mobile SDK doing inference at the camera |
| Model hosting | 5 PyTorch models, ~100 MB, CPU | CNN detectors + Tesseract OCR | Proprietary engines, **region-selectable** (`regions=mx`, `regions=us-ca`) | Optimized runtime (TensorRT/OpenVINO/NNAPI/CoreML) |
| Scale-out | Thread per camera/task, default 4 cameras | Multi-stream daemon | Horizontally scaled API/park-based | Per-device |
| Clients | Flutter (windows/web) + legacy React + Gradio | Multi-language bindings (C#/Java/Node/Go/Python) | REST/webhooks/SDKs incl. Android | Vendor SDKs |

### 8.2 Performance approach

| Dimension | This project | Industry practice | Evidence |
|---|---|---|---|
| Work per frame | **5 inferences/frame incl. 2 ResNet18 per vehicle**; every frame for files | Detection + optional tracking; recognition on selected/best frames | measured Stage table (§4.1); arXiv:2501.04750 reports extracting one frame per vehicle gives **comparable accuracy at ~3× faster processing** |
| Resolution strategy | full-resolution frames → `imgsz=640` YOLO; plate crop also letterboxed to 640 | tiered resolution (detect coarse, verify fine), ROI from vehicle/track | §4.2 C2/H2/H3 |
| Acceleration | none (CPU PyTorch base weights, Docker CPU torch) | ONNX/OpenVINO/TensorRT, FP16/int8, NNAPI/CoreML on device | §4.2 C4; `Dockerfile:28-31` |
| Frame drop policy | RTSP keeps only latest pending frame (no metrics); files process everything | tracking-based frame gating with explicit skip counters | `video_processor.py:820-834`, `:397-449` |
| Throughput guarantee | none published; ~8–9 FPS measured | FPS/stream budgets published per tier | §4.1 |

### 8.3 Tracking and multi-frame decisions

| Dimension | This project | OpenALPR | Plate Recognizer / ParkPow | Interpretation |
|---|---|---|---|---|
| Vehicle/plate identity | **none** | frame-level; daemon-oriented per stream | stream product built around vehicle events and webhooks | The audited project is below even the OSS baseline on identity |
| Multi-frame decision | 60 s text cooldown + history `count` | top-N candidate plates per image with confidence, then consumer-side filtering | per-vehicle best result surfaced through webhooks | Candidate lists ("top 10 results") are a first-class output in OpenALPR (`alpr -n <topN>`); this project returns **one string**, discarding exactly the alternatives a voting layer needs |
| Low-confidence handling | hard cutoffs: `plate_det ≥ 0.6`, `char ≥ 0.3`, then an 8-char format gate; everything else silently dropped | candidate list retains ambiguity | score retained per candidate | ByteTrack's central result — associating *low-score* boxes recovers occluded objects and reduces track fragmentation (**IDF1 +1…+10** across 9 trackers; 80.3 MOTA / 77.3 IDF1 / 63.1 HOTA on MOT17 @ 30 FPS) — argues directly against discarding low-confidence observations per frame |
| Occlusion/blur robustness | none (frames independent) | — | engine-level handling + region models | §5 |

### 8.4 OCR pipeline

| Dimension | This project | OpenALPR | Plate Recognizer class |
|---|---|---|---|
| Recognizer type | 27-class **character detection** (YOLO), boxes sorted by x-position, no sequence model, no dictionary | CNN + Tesseract + pattern post-processing | trained per region, plate-pattern aware |
| Region/pattern constraint | one hardcoded Iranian structure (8 chars) + region-code table; city lookup from CSV | `-c us/eu`, `-p <pattern>` (e.g. Maryland/California patterns) | `regions=` selection with per-region engines |
| Output | single string + blended confidence `0.7*plate_conf + 0.3*char_conf` (`alpr_engine.py:374-377`) | **top-N list with per-candidate confidence** | per-candidate score and details |
| Vehicle attributes | make + colour per frame via ResNet18; make limited to 27 Iranian models | not core | `mmc=true` returns **make/model/colour** as an optional service |
| Custom zones | none | — | **Detection zones** to exclude overlay text/signs (documented feature) |

### 8.5 User experience and operations

| Dimension | This project | Professional systems |
|---|---|---|
| Operator console | Flutter desktop/web: dashboard, history grid, analytics, sessions, cameras, live monitor, watchlists, users, audit, license, settings | Web consoles with map + event timeline, live wall, per-camera health/throughput, alert acknowledgement |
| Live view | MJPEG (`/mjpeg`) or 100 ms base64 polling per camera; grid layout selectable | WebRTC/HLS/low-latency streams with server-side overlays and per-stream FPS/lag telemetry |
| Event semantics | one row per recognition; `unique_plates` counts only distinct text | one event per vehicle with best-shot image, plate crop, vehicle crop, attributes, confidence, dwell time |
| Alerting | watchlist matching → `alerts` table; UI has no live alert surface or acknowledgement flow | real-time webhooks/push, alert workflow with acknowledgement and audit |
| Integration | REST + CSV export; OpenAPI docs | REST + webhooks + integrations (park management, VMS/NVR connectors) |
| Observability | `/api/health`, error store (`error_handler.py`), audit log | metrics dashboards (FPS, queue depth, inference latency, error rate per camera) |

### 8.6 Gap summary (what competitors have that this project does not)

1. **Vehicle event identity** (track/event id, dwell time, best frame) — the core reason duplicates appear.
2. **Candidate/confidence list at the OCR level** — enables voting, human review, and honest confidence reporting.
3. **Region/pattern-selectable engines** with per-region post-processing grammar.
4. **Tracking-based frame selection** instead of per-frame recognition or naive `skip_frames`.
5. **Detection zones / ROI** to ignore signage and overlay text.
6. **Optimized runtimes** (ONNX/OpenVINO/TensorRT/int8, mobile NNAPI/CoreML) and published throughput tiers.
7. **Streaming UX + telemetry** (latency, FPS, queue depth per camera) instead of polling JPEGs.
8. **Webhook/integration surface** and an acknowledgement workflow for alerts.
9. **An evaluation harness and dataset** — the project has no accuracy benchmark to defend any model choice; the README's `yolov8 0.7219` / `DTRB 73.918` numbers describe the upstream demo, not the current 5-model engine.

---

## 9. Missing Features (consolidated backlog input)

Derived from the code/API surface actually present in this repository (not from a wish list).

**Recognition core**
1. Plate/vehicle tracking (ByteTrack or SORT) with stable `track_id`.
2. Multi-frame consensus per track (per-character voting, best-frame selection by sharpness/area).
3. OCR candidate list / per-character confidences surfaced by the API (needed for voting and review).
4. Graceful handling of low-confidence and partial plates instead of a single hard 8-character gate.
5. Blur/quality scoring to skip unusable frames before spending inference.
6. Region/pattern-aware post-processing (Free Zone formats are only partially handled: `plate_validator.py:213-221`).

**Performance / platform**
7. Frame-skipping honored for uploaded video (parity with RTSP).
8. Inference profile per camera (resolution, model set, make/colour on/off).
9. Model export pipeline (ONNX/OpenVINO; TensorRT/CoreML/NNAPI later) + FP16/int8 variants.
10. Per-camera throughput/latency metrics surfaced to the UI.
11. GPU deployment path (CUDA torch image, device selection, batching).
12. Global concurrency limit + queue for video tasks (currently unbounded threads).

**Data / events**
13. Event-based schema: `track_id`/`event_id`/`agreement_ratio`/`frame_count`/`best_frame_path` on `detections`.
14. Best-frame image retention (plate crop + vehicle crop) with retention policy integration.
15. Dwell-time and repeat-visit analytics (arrival/departure, re-entry) instead of text cooldowns.
16. Watchlist alert workflow (real-time push, acknowledge, escalate) and alert deduplication.

**UX**
17. Live operations dashboard: per-camera FPS/lag/health, alert ticker, queue depth.
18. Vehicle timeline / event detail view with zoomable best-shot image and per-character confidence.
19. Search & filters: time range, camera, confidence, category, watchlist hit.
20. Camera configuration: ROI/detection zones, resolution/FPS profile, per-camera inference settings.
21. Theme system wiring (light + dark + density), a real component library, route transitions.
22. Localization layer (ARB) — remove inline mixed Persian/English strings.
23. Accessibility & keyboard support for the desktop/web console.
24. Notification/preferences screen (sound, popups) and profile screen.

---

## 10. Recommended Roadmap

Ordering rule: P0 contains the work that blocks everything else (duplicate identity + measurement), P1 delivers mainstream ALPR quality and performance, P2 closes UX and operational gaps, P3 is the advanced AI layer the project explicitly wants next. Nothing in this list was implemented during the audit.

### P0 — Must fix before anything else

| # | Item | Why (evidence) | Expected effect | Effort |
|---|---|---|---|---|
| P0-1 | **Add a tracking layer (ByteTrack or SORT) over plate detections, keyed per camera**, with `track_id`, `first_seen`, `last_seen`, `frame_count`. | No identity exists anywhere (`alpr_engine.py:65-77`, `db.py:37-48`); duplicates come from text-keyed cooldowns (§5). ByteTrack's low-score association reduces fragmentation (arXiv:2110.06864). | One DB row per vehicle visit instead of one per recognition; kills the reported duplicate problem at the source. | Medium (tracker + wiring in `RTSPStreamProcessor._ml_worker` and `VideoProcessor._run`). |
| P0-2 | **Multi-frame consensus per track**: per-character voting over observations plus best-frame selection (plate area + Laplacian variance). Emit the event once; allow exactly one "best-shot" update. | Every frame is judged alone; OCR strings wobble (`log_demo_result.txt`: `28i68923` ×176 vs `28i68973` ×19). Representative-frame selection is the documented way to keep accuracy while cutting work (arXiv:2501.04750, ~3× faster). | Higher plate accuracy, fewer unstable strings, fewer "same car, different plate" rows. | Medium. |
| P0-3 | **Honor `skip_frames` in the video path and add a time-budget skip policy for RTSP** (skip by elapsed budget, not only modulo index), with counters exposed in task status. | `video_processor.py:397-449` ignores the parameter; spec `.kiro/specs/realtime-plate-recognition/design.md:286` requires gating. | 3–10× less CPU on video jobs; predictable latency. | Small. |
| P0-4 | **Instrument the pipeline metrics the roadmap depends on**: frames captured / sampled / inferred / dropped, per-stage ms, events per hour, agreement ratio. | Today `_ml_busy` is written but never read (`:822`, `:839-840`); no metric exists to validate tuning. | Makes every later change measurable. | Small. |
| P0-5 | **Set explicit inference resolutions and stop upscaling plate crops** (`imgsz` per model; char model 256–320; run plate detection inside vehicle ROIs). | Measured: `imgsz=320` halves YOLO cost (24 → 11–12 ms); crops are letterboxed to 640 (`alpr_engine.py:242-244`). | ~35–45 % faster per frame, no expected accuracy loss. | Small. |
| P0-6 | **Gate the two ResNet18 classifiers to the event level** (make/colour once per confirmed track; make optional). | Measured 48 ms/frame ≈ 45 % of inference, recomputed ~8×/s/camera (`alpr_engine.py:319-322`). | Nearly halves CPU per camera; direct enabler of more cameras per host. | Small–Medium. |
| P0-7 | **Close the duplicate-route/auth hole**: remove the legacy `/api/stats`, `/api/detections*`, `/api/sessions`, `/api/config/concurrency`, `/api/cameras/{id}` PATCH and `/api/scanner/*` handlers that have **no auth dependency**; keep only the secured routers (the Flutter client currently depends on the legacy camera PATCH). | `api.py:188-344`, `:521-560` (no `Depends` anywhere in `api.py`); MJPEG endpoint with `dependencies=[]` (`routers/detection.py:386`). Out of the original audit scope, but it is a plate/video data-exposure issue. | One API surface, consistent RBAC, no unauthenticated plate/video access. | Small (must be coordinated with the client, so it belongs in P0). |

### P1 — Major improvements

| # | Item | Why | Expected effect | Effort |
|---|---|---|---|---|
| P1-1 | **ONNX/OpenVINO export for all 5 models** (then TensorRT/FP16 where a GPU exists) + a benchmark script recording per-model latency. | Zero optimization exists today (§4.2 C4). | 1.5–3× CPU throughput, more with a GPU; smaller footprint. | Medium. |
| P1-2 | **Replace `car_det_model` with a 4-class vehicle detector** (or restrict classes/resolution at call time). | 80-class COCO model for 4 classes, `max_det=20` (`alpr_engine.py:33-47`). | Removes the worst tail-latency case in crowded scenes. | Small–Medium. |
| P1-3 | **Event-centric schema + API**: `track_id`, `event_id`, `agreement_ratio`, `frame_count`, `best_frame_path`; indexes; `/api/detect/*/history` returns events. | `detections` cannot express a vehicle event (`db.py:37-48`); the UI inherits that flatness. | Duplicate rate becomes a measurable KPI; unlocks all P2 screens. | Medium. |
| P1-4 | **Replace client polling with push/streaming** (SSE/WebSocket for status + events; keep MJPEG only for video) and drop the 100 ms poll. | `camera_poll_controller.dart:49` (10 polls/s/camera) plus a 3 s full-status payload carrying the whole history (`routers/detection.py:355-383`). | Large reduction in client CPU, JSON traffic, and UI jank; events appear instantly. | Medium. |
| P1-5 | **Decouple display JPEG production from inference** and cap it per camera (encode only when a consumer is attached; adaptive size/quality). | ~30 encodes/s/camera at ≤960 px (`video_processor.py:949-973`) alongside ~9 inferences/s. | Frees 10–20 % of a core per camera. | Small. |
| P1-6 | **Evaluation harness + Iranian plate test set**: plate-detection mAP, plate-level exact match, character accuracy, per-condition breakdown (day/night, angle, blur, Free Zone). | No benchmark exists; model quality is unverifiable (README numbers belong to the upstream demo). | Converts "accuracy unknown" into a baseline; prerequisite for any model swap. | Medium (data-dependent). |
| P1-7 | **Make the OCR contract explicit**: one source of truth for `class index → character`; validate `char_model` class names (`'1'…'27'`) against `CHAR_CLASSNAMES` (duplicate `n`/`s`, multi-char tokens `ein`/`gh`/`sad`/`ta`/`malul`). | `alpr_engine.py:27-31`, `:260-274`; the model exposes index-named classes. | Eliminates a silent, systematic OCR failure mode. | Small. |
| P1-8 | **Bounded queues for video tasks and camera slots** (global concurrency, per-task progress; cancellation already exists). | One unbounded thread per upload (`routers/detection.py:201-232`). | Predictable resource use under load. | Small. |

### P2 — Quality improvements

| # | Item | Why | Effort |
|---|---|---|---|
| P2-1 | **Design system**: wire `AppTheme` tokens into every screen, delete hardcoded colours (143 usages in 10 files), unify on Fluent **or** Material (not both), and publish a component library (buttons, cards, tables, badges, dialogs, empty/error/loading states). | `theme.dart` vs `rtsp_sub_view.dart:62-68`, `dashboard_view.dart:371-433`; `app.dart:39-46` Material-inside-Fluent workaround. | Medium–Large. |
| P2-2 | **Light/dark/density theming + appearance settings** and route transitions. | `fluentLight` is dead code; every route uses `_noTransition` (`router.dart:202-208`). | Small–Medium. |
| P2-3 | **Live operations dashboard**: per-camera FPS/lag/last-event, alert ticker, queue depth, inference budget. | Needs P0-4 metrics; nothing like it exists. | Medium. |
| P2-4 | **Vehicle event detail & timeline screens** with zoomable best-shot image, plate/vehicle crops, per-character confidence, session context. | Needs P1-3; today `PlateDetailCard` is text-only. | Medium. |
| P2-5 | **Advanced search/filters** (time range, camera, confidence range, category, watchlist hit) + saved views, PDF/periodic reports. | `history_view.dart` has text + source filter only; CSV export exists. | Medium. |
| P2-6 | **Camera settings screen**: ROI/detection zones, resolution & FPS profile, per-camera `skip_frames` guidance, stream test, credential management. | `camera_model.dart` has name/url/skip_frames only; zones are a documented competitor feature. | Medium. |
| P2-7 | **Localization + accessibility pass**: ARB-based strings, one language per screen, `Semantics`/focus order/keyboard shortcuts/`MouseRegion` cursors. | Mixed Persian/English copy; only 4 semantics/tooltip matches in `lib/`. | Medium. |
| P2-8 | **Housekeeping**: remove legacy endpoints and duplicate clients, retire `database/license_plate_recognition.db`, clean `io/output` uploads, align the CI Flutter version with `pubspec.yaml`. | §4.2 LOW findings; three client generations coexist. | Small. |

### P3 — Advanced AI features (the project's stated next goal)

| # | Item | Rationale |
|---|---|---|
| P3-1 | **AI decision layer over the consensus output**: a lightweight classifier (GBM/small MLP) consuming track features — agreement ratio, per-character confidences, sharpness (Laplacian variance), plate area/aspect, angle proxy, frames observed, dwell time, time of day, camera id — returning `accept / reject / needs-review` plus a calibrated confidence. | Directly requested. It only becomes meaningful *after* P0-1/P0-2 produce track-level features, and it needs P1-6 labels to train and evaluate honestly. |
| P3-2 | **Learn the Iranian plate structure instead of hardcoding it**: sequence recognizer (CRNN / DTRB / ParseQ or a small transformer) with a per-region grammar decoder, trained on standard + Free Zone formats; replaces the 27-class character detector. | Removes the fragile 8-char gate and the ambiguous `CHAR_CLASSNAMES` mapping; competitors ship region-specific engines. |
| P3-3 | **Track-level analytics and re-identification**: dwell time, arrival/departure, re-entry detection, plate + make/colour fusion for ambiguous reads. | Turns make/colour (currently wasted per-frame work) into event-level value. |
| P3-4 | **Anomaly and behaviour detection over detections**: repeated scans, impossible travel between cameras, confidence outliers, watchlist patterns. | Builds on the existing watchlist service (`watchlist/matching.py`), alerts table, and audit log. |
| P3-5 | **On-device/edge inference path for the mobile goal**: export plate detector + recognizer to TFLite/ONNX, add an Android target (NNAPI/GPU delegate) to the Flutter client, keep the server for heavy jobs. | There is no `android/`/`ios/` target and no camera plugin today (§2.2); this is a project-level decision, not a quick task. |
| P3-6 | **Active-learning loop**: persist low-agreement tracks as review candidates, let operators correct them, feed corrections back into training. | Converts the existing audit/history infrastructure into a data flywheel; depends on P1-3 and P2-4. |

### Suggested validation gates for each phase

- **After P0:** one plate must produce exactly one DB row per vehicle visit in a repeatable test (drive/walk a plate through frame, assert `COUNT(*) = 1` per event); measured `frames_inferred / frames_captured` and per-stage ms must be published in task status.
- **After P1:** a fixed test set (images + clips) must yield reproducible plate-level accuracy and per-model latency numbers recorded in the repo; ONNX vs PyTorch outputs must match within tolerance on the same inputs.
- **After P2:** `flutter analyze` clean, zero hardcoded colours in feature files (lint rule or grep gate in CI), and a widget test per new screen.
- **After P3:** the decision layer must beat the rule-based consensus baseline on a held-out labelled set, with a documented false-accept/false-reject trade-off.

---

## Appendix A — Methodology and reproducibility

**Rule:** no repository file was modified, added, or deleted by this audit. Temporary benchmark scripts were written to the OS temp directory (`%TEMP%`), not into `D:\alpr`.

Commands used (from `D:\alpr`):

```powershell
# Environment
python --version                      # Python 3.11.4
python -c "import torch,cv2,ultralytics; print(torch.__version__, torch.cuda.is_available(), cv2.__version__, ultralytics.__version__)"
flutter --version                     # Flutter 3.44.1 - Dart 3.12.1

# Model probes (architecture, class count, parameter count, class names)
python -c "from ultralytics import YOLO; m=YOLO('weigths/plate_det_model.pt'); print(m.model.yaml, sum(p.numel() for p in m.model.parameters()))"
python -c "from ultralytics import YOLO; print(list(YOLO('weigths/char_model.pt').names.values()))"

# Latency sweep (per model, per resolution)          - script kept in %TEMP%
# Full pipeline + per-stage instrumentation          - script kept in %TEMP%

# Structural facts
Select-String -Path *.py,routers\*.py -Pattern 'imgsz|half|torch.no_grad|inference_mode|device=|onnx|tflite|quantiz'
Select-String -Path video_processor.py -Pattern 'skip_frames'
Select-String -Path .kiro\specs\*\*.md -Pattern 'dedup|duplicate|cooldown|tracking|multi-frame|vote'
```

## Appendix B — Raw model probe output

```
torch threads 6   cuda False
image (1280, 960, 3)

weigths/plate_det_model.pt | scale=n | nc=1  | yaml_file=yolo11n.yaml | params=2590035
   imgsz=640  24 ms  boxes=1        imgsz=320  12 ms  boxes=1
weigths/car_det_model.pt   | scale=n | nc=80 | yaml_file=yolo11n.yaml | params=2624080
   imgsz=640  24 ms  boxes=2        imgsz=320  11 ms  boxes=1
weigths/char_model.pt      | scale=None | nc=27 | yaml_file=None       | params=3016113
   imgsz=640  23 ms  boxes=4        imgsz=320  11 ms  boxes=0   (on the full frame)

char_model class names: ['1','10','11','12','13','14','15','16','17','18','19','2','20','21',
                         '22','23','24','25','26','27','3','4','5','6','7','8','9']

color_model.pt      : OrderedDict, 122 entries, fc=(12, 512), params=11182668, fp32 = 44.8 MB
car_name_model.pth  : OrderedDict,             fc=(27, 512), params=11199983, fp32 = 44.8 MB
resnet18 @220x165 batch1: 10.0 ms / inference

AlprEngine.run() end-to-end (5 runs): 111, 124, 108, 107, 105 ms
  resnet_car_type        calls=10  total=122.6 ms  per-frame=24.5 ms
  resnet_color           calls=10  total=117.4 ms  per-frame=23.5 ms
  char_detect_per_plate  calls= 5  total= 47.7 ms  per-frame= 9.5 ms
  (remainder about 50 ms = car_det + plate_det at imgsz 640)
Sample output: plate_text='28y68923', confidence=0.866, car_type='207', car_color=None
```

## Appendix C — Risk register (things that will bite during the P0/P1 work)

| Risk | Why it matters | Evidence |
|---|---|---|
| **Unauthenticated legacy API surface + one unauthenticated stream endpoint.** | Plate records, statistics, camera CRUD/PATCH, concurrency config, and the MJPEG live stream are reachable without a token. CORS is also `allow_origins=["*"]`. | `api.py:139-144`, `:188-344`, `:521-560`; `routers/detection.py:386` (`dependencies=[]`) |
| **Duplicate route definitions silently shadow each other.** | `/api/cameras`, `/api/cameras/{id}/start\|stop`, `/api/cameras/start-all\|stop-all`, `/api/scanner/scan\|status\|stop\|test` exist twice (legacy + router). Routers win because they are registered first, so the legacy copies are dead code that still looks authoritative. | `api.py:261-341` vs `routers/cameras.py`, `routers/scanner.py`; registration order `api.py:168-179` |
| **Client depends on a legacy endpoint.** | `updateCamera` issues `PATCH /cameras/{id}` (`camera_repo.dart:23-31`), which exists only in the unauthenticated legacy `api.py` — removing the legacy code breaks camera editing unless the router gains the route. | `camera_repo.dart`, `api.py:276-286`, `routers/cameras.py` (no PATCH) |
| **OCR class contract is implicit.** | `char_model` class names are indices while `CHAR_CLASSNAMES` is a hand-written 28-entry list with duplicate letters and multi-character tokens; any retraining silently redefines the mapping. | `alpr_engine.py:27-31`, `:260-274` |
| **Cooldown state is per-process and never expires.** | `_recent_emit_times` grows unbounded and resets on restart/stop, so duplicate behaviour is non-deterministic across runs. | `video_processor.py:379`, `:636`, `:485-487`, `:875-877` |
| **`_add_to_history` count is neutered by the cooldown above it.** | The spec asks for a repeated-detection count (`.kiro/specs/iranian-plate-recognition-upgrade/requirements.md:52`), but the count can only increment once per 60 s, so it is effectively always 1. | `video_processor.py:873-878` then `:1007-1037` |
| **No accuracy baseline.** | Any model change or "improvement" claim is unfalsifiable today; the reported `unique_plates` metric counts distinct strings, which the duplicate problem distorts in both directions. | `db.py:213-216`, `README.md:8-11` |
| **Undocumented process-wide singleton.** | One `AlprEngine` for the whole process, no locking, no device/batch configuration; scaling decisions are implicit. | `api.py:30-52` |
| **Two client generations.** | `frontend/` (React), `flutter_app/` (Flutter), and Gradio `ui.py` all speak to the same API; feature work must be duplicated or a client abandoned. | `api.py:821-823`, `frontend/`, `ui.py` |

## Appendix D — Audit limitations (stated explicitly)

1. **No live-stream run was performed.** Timing was measured on still images (`car_a.jpg`, 1280×960) with the repository's own models; real streams add decode, JPEG encode, network, and multi-camera contention costs that are described qualitatively.
2. **Accuracy was not measured**, because the repository ships no labelled Iranian test set and no evaluation script for the current 5-model engine. Statements about accuracy are explicitly framed as unverified.
3. **Commercial competitor internals are closed.** Section 8 compares documented capabilities (OpenALPR README/CLI options, Plate Recognizer docs) and published research (ByteTrack, video-ALPR frame selection), not proprietary architectures.
4. **The security findings in §4.2 / P0-7 / Appendix C are incidental** to the requested performance/duplicate/UX/model scope. They are included because a plate-recognition system that stores vehicle data is currently exposed, and omitting them would make the audit misleading.
5. **Line numbers refer to the audited commit** `3f16f27` on `main`; they will drift after any edit.

---

*End of report. No code was modified: only this file (`D:\alpr\ALPR_AUDIT_REPORT.md`) was created.*

