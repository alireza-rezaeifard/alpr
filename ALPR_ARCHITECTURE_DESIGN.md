# ALPR Architecture Design — Frame-Based → Event-Based

**Project:** `D:\alpr` (Persian/Iranian ALPR: FastAPI backend + Flutter client)
**Document type:** Design phase only. No code was modified, no commits, no dependency installs.
**Baseline:** `ALPR_AUDIT_REPORT.md` (same repository, commit `3f16f27`) — this design answers its findings.
**Audience:** the developer who will implement it.

---

### Contents

- [0. Scope, Principles, Non-Goals](#0-scope-principles-non-goals)
- [1. Target Architecture (Part 1)](#1-target-architecture-part-1)
- [2. Tracking Design (Part 2)](#2-tracking-design-part-2)
- [3. Event Model Design (Part 3)](#3-event-model-design-part-3)
- [4. Multi-Frame Consensus Engine (Part 4)](#4-multi-frame-consensus-engine-part-4)
- [5. Performance Optimization Plan (Part 5)](#5-performance-optimization-plan-part-5)
- [6. AI Model Strategy (Part 6)](#6-ai-model-strategy-part-6)
- [7. API and Flutter Impact (Part 7)](#7-api-and-flutter-impact-part-7)
- [8. Implementation Roadmap (Part 8)](#8-implementation-roadmap-part-8)
- [Appendix A — Interfaces (signatures)](#appendix-a--interfaces-signatures)
- [Appendix B — SQL DDL and migration](#appendix-b--sql-ddl-and-migration)
- [Appendix C — Configuration knobs](#appendix-c--configuration-knobs)
- [Appendix D — Test matrix and definition of done](#appendix-d--test-matrix-and-definition-of-done)
- [Appendix E — Observability and rollout](#appendix-e--observability-and-rollout)
- [Appendix F — Risks and mitigations](#appendix-f--risks-and-mitigations)

---

## 0. Scope, Principles, Non-Goals

### 0.1 Problem statement (from the audit, with evidence)

| Audit finding | Root cause in code |
|---|---|
| Same vehicle emitted hundreds of times | No identity; de-dup is a 60 s text-keyed in-memory cooldown (`video_processor.py:355`, `:485`, `:875`) plus a history `count` (`:1007-1037`); DB `INSERT` per emission (`db.py:146-184`) |
| No vehicle identity | `AlprResult` has no id (`alpr_engine.py:65-77`); `detections` has no track/event column (`db.py:37-48`) |
| No tracking layer | No tracker anywhere; only a y-overlap heuristic `group_detections` (`video_processor.py:86-117`) |
| OCR not aggregated across frames | Each frame's string is judged alone; only alternatives are discarded (single string returned) |
| High CPU/GPU | 5 inferences/frame: 2 YOLO full-frame @640 + 2 ResNet18 per vehicle box + char YOLO @640 on a crop; measured `AlprEngine.run()` = **105–124 ms/frame** (≈45 % of it is make/colour) |
| Attributes computed too often | `_predict_car` / `_predict_color` inside the per-box loop of every frame (`alpr_engine.py:319-322`) |
| No production ALPR architecture | No frame budget, no queues/metrics, no event model, polling-driven UI, duplicate API surfaces |

### 0.2 Design principles

1. **Identity before accuracy.** Assign identity (track) first; every downstream decision is made about a *vehicle*, not a frame.
2. **Evidence, not verdicts.** The OCR stage emits *evidence* (per-character candidates with confidences and quality), never a final string.
3. **One decision point.** Exactly one component (the Consensus/Event Builder) decides what an operator sees. Deduplication happens there, not in string caches.
4. **Budgeted work.** Every camera has an explicit inference budget (ms/frame and inferences/frame). Work is scheduled against the budget, never against the raw stream rate.
5. **Determinism for testability.** All decision logic (track association, voting, stopping rules, quality scoring) is pure and separately testable; thread/IO code only moves data.
6. **Append-only evidence, upserted events.** Observations may be many; the event is one row that is updated until it closes.
7. **No silent drops.** Every discarded frame/observation increments a counter that is visible in the API and UI.
8. **Backward compatibility by projection, not by duplication.** Legacy consumers are served by a compatibility projection over the new model; legacy write paths are removed, not maintained.

### 0.3 Non-goals (explicitly out of scope for this design)

- No UI redesign (only the data/screen *enablers* are specified — Part 7).
- No model replacement or retraining (Part 6 defines *how* to evaluate, not new weights).
- No change to auth/RBAC/licensing semantics, `CameraManager` FIFO behaviour, or `plate_validator` format rules (the validator stays the last gate; the consensus engine sits before it).
- No cloud/edge topology change; the same in-process architecture is preserved (single host, threaded), with interfaces that allow future process split.
- No new runtime dependency is mandated. ByteTrack is provided by the already-installed `ultralytics` (tracker config) or may be implemented in-repo (~200 LOC) — Part 2 explains both options.

---

## 1. Target Architecture (Part 1)

### 1.1 Pipeline overview

```
                    ONE CAMERA (or one uploaded file) = one PipelineContext
                    ────────────────────────────────────────────────────────

 ┌──────────────┐  raw frames     ┌────────────────────┐  sampled frames
 │ Camera/File  │  (ordered)      │ 1. FRAME SCHEDULER │  + frame_meta
 │ Reader       │ ──────────────► │  (budget + skip)   │ ──────────────┐
 │ (unchanged   │                 │  pure decision fns │               │
 │  OpenCV)     │                 └────────────────────┘               │
 └──────────────┘                                                      ▼
                                                 ┌──────────────────────────────┐
                                                 │ 2. VEHICLE DETECTOR (YOLO11n)│
                                                 │  imgsz 384-480, 4 classes    │
                                                 └───────────────┬──────────────┘
                                                                 │ vehicle boxes
                                                                 ▼
                                                 ┌──────────────────────────────┐
                                                 │ 3. TRACKER (ByteTrack)       │
                                                 │  motion-only, camera-scoped  │
                                                 └───────────────┬──────────────┘
                                                                 │ TrackUpdate[]
        ┌────────────────────────────────────────────────────────┘
        ▼
 ┌──────────────────────────────────────────────┐
 │ 4. TRACK LIFECYCLE MANAGER                   │
 │ NEW → TRACKING → PLATE_CAPTURED → CONFIRMED  │
 │ → COMPLETED / EXPIRED                        │
 │ per-track evidence store · ROI · budget      │
 └───────────────┬──────────────────────────────┘
                 │ ROI requests for tracks wanting a readable plate
                 ▼
 ┌──────────────────────────────────────────────┐
 │ 5. PLATE DETECTOR (YOLO11n, ROI imgsz)       │
 └───────────────┬──────────────────────────────┘
                 │ plate crops (+ plate_conf, area, sharpness)
                 ▼
 ┌──────────────────────────────────────────────┐
 │ 6. OCR CANDIDATE COLLECTOR                   │
 │ char detector (P0) / sequence reader (P3)    │
 │ → PlateRead{ text, char_conf[], alternates,  │
 │              quality }                       │
 └───────────────┬──────────────────────────────┘
                 │ PlateRead appended to owning track
                 ▼
 ┌──────────────────────────────────────────────┐
 │ 7. MULTI-FRAME CONSENSUS ENGINE              │
 │ char voting · weighting · quality scoring    │
 │ best-frame selection · stopping conditions   │
 └───────────────┬──────────────────────────────┘
                 │ ConsensusResult{plate, confidence, agreement, best_frame}
                 ▼
 ┌──────────────────────────────────────────────┐
 │ 8. VEHICLE EVENT BUILDER                     │
 │ one event per track lifetime · dwell ·       │
 │ attribute enrichment (make/colour, 1x)       │
 └───────────────┬──────────────────────────────┘
                 ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ 9. SINKS                                                         │
 │  • SQLite writer (vehicle_events upsert + plate_observations)     │
 │  • Best-frame store (io/events/<camera>/<event_id>/*.jpg)         │
 │  • Watchlist/alert hook (event-based)                            │
 │  • Live event bus (ring buffer + SSE/WebSocket)                  │
 │  • Metrics counters (per stage, per camera)                      │
 └──────────────────────────────────────────────────────────────────┘
```

### 1.2 Component contracts

Signatures are in Appendix A; this table is the responsibility map.

| # | Component (file) | Responsibility | Inputs | Outputs |
|---|---|---|---|---|
| 1 | **Frame Scheduler** `pipeline/frame_scheduler.py` | Decide whether the current frame enters the detection path and at which tier (`track_only` vs `full`). Enforce per-camera ms budget and max inferences/frame. Never blocks the reader. | `frame_index`, `capture_ts`, `queue_depth`, `last_inference_ms`, `pending_track_count`, config | `ScheduleDecision(sample, tier, reason)` + counters |
| 2 | **Vehicle Detector** (`pipeline/detectors.py`, wraps `alpr_engine`) | Detect vehicles (4 classes) at reduced resolution on sampled frames. May be skipped when tracks are healthy and the budget is tight. | frame BGR, `imgsz`, `conf`, `classes` | `list[Box]` (xyxy, conf, cls) |
| 3 | **Tracker** `pipeline/tracker.py` | Associate boxes across frames, keep Kalman state, emit stable `track_id` per camera, retain low-score boxes (ByteTrack). | `list[Box]`, frame timestamp, previous track state | `list[TrackUpdate]` (id, state NEW/TRACKED/LOST, box, age, hits, time_since_update) |
| 4 | **Track Lifecycle Manager** `pipeline/track_manager.py` | Own per-track evidence, state machine, ROI planning, per-track budget, emission triggers, expiry. | `TrackUpdate[]`, `PlateRead[]`, config, `now` | `TrackSnapshot[]`, `EmissionRequest[]`, `RoiRequest[]` |
| 5 | **Plate Detector** `pipeline/detectors.py` | Detect plates inside each track ROI (padded); full-frame scan only as a low-rate fallback. | frame, ROI list, `imgsz` | `list[PlateBox]` (+ owning track_id) |
| 6 | **OCR Candidate Collector** `pipeline/ocr_reader.py` | Turn a plate crop into evidence: text, per-char candidates + confidences, alternatives, quality metrics. Never applies whole-plate validity. | plate crop BGR, precheck thresholds | `PlateRead` |
| 7 | **Consensus Engine** `pipeline/consensus.py` | Pure functions: weighted per-character voting, agreement ratio, calibrated confidence, quality score, best-frame choice, stopping conditions. | `list[PlateRead]`, track meta, config | `ConsensusResult` |
| 8 | **Vehicle Event Builder** `pipeline/event_builder.py` | Decide emit/upgrade; assemble `VehicleEvent`; attribute enrichment once; hand to sinks. | `ConsensusResult`, track meta, camera meta, `now` | `VehicleEvent`, `EventUpdate` |
| 9 | **Sinks** `pipeline/sinks.py`, `db.py`, `routers/events.py` | Persist event + observations, write best frames, raise alerts on the canonical plate, publish live events, expose metrics. | `VehicleEvent`, best-frame bytes | DB rows, files, SSE messages, alert rows |

### 1.3 Data-flow rules (normative — implement exactly)

1. **Ordering.** Frames and their derived `PlateRead`s are processed in capture order per camera. Stages 2–8 execute in exactly one worker thread per camera (`PipelineWorker`); the reader thread only produces frames. Tracker correctness (Kalman + association) depends on ordered input.
2. **Freshness.** Between stage 1 and 2 there is a bounded slot of depth `frame_queue_depth` (default **2**). Overflow drops the **oldest** frame and increments `frames_dropped_stale`. Stages 3–8 never drop.
3. **Back-pressure.** Concurrent inference workers across all cameras are bounded by a process-wide `threading.Semaphore(max_concurrent_inference)` (default **2**). This replaces today's implicit assumption that N cameras can run N full pipelines.
4. **No gratuitous copies.** Today the pipeline copies every frame (`video_processor.py:946`) and serializes whole histories per poll (`:1039-1052`). The new pipeline passes frame references + a monotonic `seq`; copies happen only when a crop must outlive its frame (best-frame storage).
5. **Evidence is append-only, state is small, events are upserted.** `PlateRead` is immutable; track state is a small mutable record under a lock; the event row is updated until the track closes.
6. **Display path is fully decoupled.** The display loop consumes the latest frame + the latest overlay snapshot, never waits on the worker, and never triggers inference.
7. **Every drop is counted**: `frames_dropped_stale`, `roi_skipped_budget`, `ocr_skipped_budget`, `obs_dropped_cap`, `events_emitted`, `events_upgraded`. Counters are exposed on `/api/detect/rtsp/{task_id}` and `/api/events/health`.

### 1.4 Where the new pipeline replaces what

| Existing code | Fate | New owner |
|---|---|---|
| `RTSPStreamProcessor._ml_worker` body (`video_processor.py:824-922`) | **Replaced** by `PipelineWorker` (stages 1–8) | `pipeline/worker.py` |
| `VideoProcessor._run` inference block (`:438-560`) | **Replaced** by `PipelineWorker` in "offline file" mode (no wall-clock budget; budget in frame-equivalents) | `pipeline/worker.py` |
| `_DEDUP_WINDOW_SECONDS` cooldown (`:355`, `:485`, `:875`) | **Deleted**, replaced by track identity + event-level cooldown (safety net only, default now 15 s per `(camera, plate_norm)` for re-entry protection) | `pipeline/event_builder.py` |
| `_add_to_history` text dedup (`:1007-1037`) | **Replaced** by event projection (history = last N events) | `pipeline/sinks.py` |
| `AlprEngine.run()` returning strings (`alpr_engine.py:282-392`) | **Kept for compatibility**, plus a new `AlprEngine.detect_*`/`read_plate` API returning evidence objects | `alpr_engine.py` (extended, not rewritten) |
| `detect_plates()` (`video_processor.py:274-308`) | Thin adapter retained for the image endpoint; new code paths use the stage API | `video_processor.py` |
| `group_detections` (`:86-117`) | **Deprecated** (superseded by real tracking) | `pipeline/tracker.py` |
| `camera_poll_controller` 100 ms frame polling (Flutter) | **Demoted to fallback**; primary path = MJPEG + SSE events | Part 7.3 |

### 1.5 Runtime topology (threads, queues, ownership)

```
Process: uvicorn worker  (single process, as today)
│
├── CameraManager (existing, camera_manager.py)  ── concurrency slots / FIFO unchanged
│
├── Per camera: RTSPStreamProcessor (rewritten internals, same public API)
│    ├── Reader thread           : cap.read() → FrameSlot(seq, frame, ts)        [1 slot, drop-oldest]
│    ├── PipelineWorker thread    : stages 1..8 (scheduler → detector → tracker →
│    │                              lifecycle → plate → OCR → consensus → event)
│    │                              acquires global inference semaphore per inference call
│    └── Display thread          : latest overlay snapshot + frame → JPEG (budgeted, subscriber-gated)
│
├── Per video task: VideoProcessor (same public API, offline mode)
│    ├── Reader loop (existing thread) : decode frames in order
│    └── PipelineWorker (inline or dedicated thread) : stages 1..8 with frame-count budget
│
├── Shared sinks (process-wide)
│    ├── DbWriter        : single thread + queue.Queue(256)  → SQLite writes (events, observations, alerts)
│    ├── FrameStore      : single thread + queue.Queue(64)   → best-frame JPEG encode + file write
│    ├── EventBus        : in-memory ring buffer (N=500) + condition/notify for SSE subscribers
│    └── Metrics         : lock-free counter dict + gauges, read by /api/events/health
│
└── FastAPI request threads: read-only access (event queries), SSE generators, task control
```

**Why dedicated writer threads:** the audit found DB writes (plus watchlist matching and alert inserts) executed on the inference thread (`video_processor.py:906-915`, `db.py:146-207`) and one SQLite connection opened per call (`db.py:8-12`). Moving writes off the inference thread removes that coupling; a single writer thread also removes SQLite write contention. The writer thread may reuse one connection for the whole process lifetime (WAL mode already enabled) — a change that must be validated by the existing DB tests.

### 1.6 Walkthrough — one vehicle crossing the field of view

```
t=0.00s  Reader: frame seq=1000
         Scheduler: budget free, no active tracks → tier=FULL
         Vehicle detector: car box (conf 0.88)
         Tracker: no match → create track_id=17 (state NEW)
         Lifecycle: NEW→TRACKING (hits=1)
         Plate detector on vehicle ROI: 1 plate box (conf 0.91, area 120x32 px)
         OCR: PlateRead(text="12b34587", char_conf=[0.8,0.9,...], quality=0.41)
         Lifecycle: stores 1 observation (usable=1)
         Consensus: not enough evidence → no emission
         Metrics: inferences_this_frame=2 (vehicle+plate+char=3 ops)

t=0.13s  frame seq=1001
         Scheduler: budget ok, track 17 alive → tier=FULL (plate not yet readable)
         Vehicle detector: box IoU 0.92 with track 17 → hits=2
         Plate: conf 0.94, area 132x35 → OCR("12b34567", quality=0.58)
         Lifecycle: usable=2, best_quality=0.58
         Consensus: posterior 0.78 on index 5; agreement 0.5 → no emission (needs ≥3 obs or agreement ≥0.6)

t=0.30s  frame seq=1004 (scheduler skipped 2 frames to stay in budget)
         Plate: conf 0.96, area 141x38 → OCR("12b34567", quality=0.71)  ← new best frame
         Lifecycle: usable=3
         Consensus: per-index votes → "12b34567" (index5 2/3), agreement=0.67, conf=0.89
                    stopping rule CONFIRM satisfied (usable≥3, agreement≥0.6, format valid)
         Event Builder: emit event_id=<uuid> status=CONFIRMED, best_frame=this crop
         Sinks: DB upsert event + 3 observations; enqueue best-frame JPEG; alert hook (no match);
                EventBus.publish(VehicleEvent)

t=0.45s  frame seq=1007
         Lifecycle state CONFIRMED; ROI/OCR now only every `confirmed_ocr_stride` frames (default 5)
         OCR("12b34567", quality=0.83) ← quality delta > 15% → upgrade allowed (once)
         Event Builder: upgrade best_frame + confidence; no new row
         Attributes: make/colour computed ONCE here (event-level), cached on the event

t=2.10s  vehicle left the frame; tracker: time_since_update grows → LOST
t=2.60s  Lifecycle: LOST beyond `track_expiry_s` (default 2.0 s) → COMPLETED
         Event Builder: close event (last_seen, frame_count, duration_ms), publish update
         Metrics: event.duration_ms ≈ 2100, obs_count=11, dropped_from_cap=0
         Re-entry protection: (camera_id, plate_norm) cooldown 15 s prevents an immediate
         second event if the same plate re-appears within the cooldown; after that a NEW event
         is created (a real re-visit is a legitimate second event, unlike today's duplicates)
```

---

## 2. Tracking Design (Part 2)

### 2.1 Tracker comparison

| Criterion | SORT | DeepSORT | **ByteTrack** |
|---|---|---|---|
| Association input | high-score only | high-score only | **all boxes incl. low-score** (two-stage: high → tracks, low → unmatched tracks) |
| Motion model | Kalman + Hungarian on IoU | Kalman + Hungarian on IoU + appearance cosine | Kalman + Hungarian on IoU, no appearance |
| Extra inference cost | none | **one re-ID embedding CNN per box per frame** (~+10–25 ms/box on CPU) | **none** |
| CPU/edge suitability | good | poor (embedding net dominates) | **excellent** — this deployment is CPU-only (`torch 2.12.0+cpu`) |
| Occlusion behaviour | loses track, new id on re-appear | recovers via appearance if embeddings are good | recovers short occlusions via motion of **low-score** boxes (core claim: IDF1 +1…+10 across 9 trackers; MOT17 80.3 MOTA / 77.3 IDF1 @ 30 FPS — arXiv:2110.06864) |
| Multiple vehicles / dense traffic | more ID switches | better separation than SORT | good; appearance is a weak discriminator here anyway (Iranian fleet skews to similar white/grey sedans), motion is stronger |
| Fixed-camera ALPR fit | good | good | **best fit**: static cameras, near-constant velocity, small and often blurred plates → low-score boxes matter |
| Maturity / availability | unmaintained reference code | heavier deps | well-specified; reference code public; **already vendored inside the installed `ultralytics`** (`bytetrack.yaml`/`botsort.yaml`) → no new dependency |
| Tuning knobs | — | appearance threshold, embedding model | `track_high_thresh`, `track_low_thresh`, `new_track_thresh`, `track_buffer`, `match_thresh`, `frame_rate` |

### 2.2 Decision: **ByteTrack, motion-only, camera-scoped**

This deployment is **fixed cameras, CPU-only, dense enough that similar-looking sedans are the norm**. ByteTrack buys occlusion tolerance through low-score association without paying for an embedding network, it needs no new dependency, and its main failure mode (an ID switch) is recoverable because the plate text is a second identity signal available to the consensus layer. DeepSORT's appearance signal is both expensive on this hardware and weakly discriminative for this fleet; SORT throws away exactly the low-confidence detections that a distant, blurred plate depends on.

**Two implementation options — both specified, pick at implementation time:**

| Option | How | Pros | Cons | Verdict |
|---|---|---|---|---|
| A. Ultralytics built-in tracker | `model.track(..., persist=True, tracker="bytetrack.yaml")` | least code, battle-tested association | tracker state lives on the (shared, process-wide) `AlprEngine` → **tracks would cross-contaminate between cameras**; awkward for plate-only tracks | **Reject for multi-camera** |
| **B. In-repo `ByteTracker` (recommended)** | `pipeline/tracker.py`: two-stage association over `Box` lists, one instance per camera inside `PipelineContext` | per-camera isolation; association step is a pure function that can be unit/property tested (`previous_state + boxes → updates`); supports plate-only tracks; no coupling to Ultralytics internals | ~200–250 LOC + tests | **Use B** (keep A as a fallback if B underperforms during Phase 1 testing) |

### 2.3 What gets tracked: vehicle-primary with plate fallback

```
Primary:   track VEHICLE boxes (COCO 2,3,5,7 = car, motorcycle, bus, truck)
           → stable identity through plate blur/occlusion

Fallback:  a plate box with no containing vehicle track (long distance, vehicle
           detector miss) creates a PLATE track (kind="plate")

Merge:     when a vehicle box appears that contains an existing PLATE track's box
           (containment IoU > 0.6), observations TRANSFER to the vehicle track and the
           plate track closes with status="merged" (tombstone, no second event)
```

Safety rules:

- A physical plate can never belong to two live tracks: on merge, observations are **moved**, and the absorbed track records `merged_into`.
- A `PLATE` track may emit its own event if it lives longer than `plate_track_min_lifetime_s` (default 0.6 s) with `usable_obs ≥ plate_track_min_obs` (default 3) — this is how distant plates still become events when the vehicle detector misses.
- Track ids are **camera-scoped**: `track_key = (camera_id, local_track_id, session_epoch)`. `session_epoch` increments on processor start so ids never repeat across restarts; the DB event id is the durable identity.

### 2.4 Track lifecycle state machine

```
                ┌──────────┐   first association (hits = 1)
                │   NEW    │───────────────────────────────┐
                └────┬─────┘                               │ second matching frame
                     │ hits ≥ new_track_min_hits (2)       │ (hits = 2)
                     ▼                                     ▼
                ┌──────────┐   first usable PlateRead  ┌────────────────┐
                │ TRACKING │───────────────────────────►│ PLATE_CAPTURED │
                └────┬─────┘                            └───────┬────────┘
                     │                                          │ consensus CONFIRM rule met
                     │  no plate ever readable                  ▼
                     │  time_since_update > track_expiry_s  ┌───────────┐
                     │                                      │ CONFIRMED │
                     ▼                                      └─────┬─────┘
                ┌────────────────────────────────────────────────────────┐
                │ COMPLETED   normal end: LOST → expiry (CONFIRMED too)   │
                │             event closed with final confidence/duration │
                └────────────────────────────────────────────────────────┘
                ┌────────────────────────────────────────────────────────┐
                │ EXPIRED     abnormal: worker stop/reconnect/exception   │
                │             open events flushed (confirmed/unconfirmed)  │
                └────────────────────────────────────────────────────────┘

  LOST → resumed:  time_since_update ≤ track_expiry_s and IoU match restores the
                   previous state (ByteTrack low-score association at work)
```

| Transition | Condition | Side effects |
|---|---|---|
| `NEW → TRACKING` | `hits ≥ new_track_min_hits` (default **2**) | allocate ROI plan + observation store; `tracks_created` counter |
| `NEW → EXPIRED` | lost before `new_track_min_hits` (glint / single-frame noise) | discard; `tracks_rejected_new` counter — a cheap false-positive filter |
| `TRACKING → PLATE_CAPTURED` | first usable `PlateRead` stored | `plate_first_read_ms` metric |
| `PLATE_CAPTURED → CONFIRMED` | consensus `CONFIRM` rule (Part 4.6) | emit event (`status=confirmed`); enable event-level attribute enrichment; switch OCR cadence to `confirmed_ocr_stride` |
| `TRACKING`/`PLATE_CAPTURED` → `COMPLETED` | `time_since_update > track_expiry_s` (default **2.0 s**) and `lifetime_s ≥ track_min_lifetime_s` (0.4 s) | if `usable_obs ≥ 1` and posterior ≥ `force_emit_posterior` (0.5): emit `status=unconfirmed, needs_review=1`; else discard with `tracks_dropped_no_evidence` |
| `CONFIRMED → COMPLETED` | same expiry rule | close event: `last_seen`, `frame_count`, `duration_ms`, final confidence; publish update |
| any → `EXPIRED` | `stop()` / reconnect / exception | flush open events (confirmed if already emitted, else unconfirmed); persist + publish so a restart never loses a visit |
| LOST → resumed | `time_since_update ≤ track_expiry_s` and IoU match | previous state restored; `occlusion_recoveries` counter |

With a 25 FPS stream sampled at ~8 FPS, a 2.0 s expiry covers ≈16 sampled frames of occlusion — enough for a passing pole or brief plate obstruction, short enough not to merge two different cars.

### 2.5 Creation, update, expiration, duplicate prevention (normative)

**Creation**
- A box unmatched to any live track with `conf ≥ new_track_thresh` (default 0.5) creates a **tentative** track. Tentative tracks never emit events and never request extra OCR budget.
- Tracks are per camera: the same physical car seen by two cameras produces **two events** (two visits on two cameras) linked analytically by plate, not by a cross-camera tracker.

**Update**
- Two-stage association: (1) high-score boxes vs all tracks (IoU + Hungarian); (2) remaining low-score boxes (`track_low_thresh ≤ conf < track_high_thresh`) vs still-unmatched tracks. Stage 2 is what preserves identity through blur.
- Kalman state `[cx, cy, a, h, vx, vy, va, vh]` (SORT/ByteTrack convention). **`frame_rate` must be the effective pipeline FPS, not the stream FPS**, or the motion model over-predicts.
- Thresholds in **normalized** coordinates so one config serves 720p and 4K.
- On match: `hits += 1`, `time_since_update = 0`, `age += 1`. On miss: `time_since_update += 1`.

**Expiration**
- Removal when `time_since_update > ceil(track_expiry_s × effective_fps)`; always routed through the lifecycle manager so open events close — never removed by the tracker alone.
- Bounded memory: `max_live_tracks` (default 32) per camera. Over the cap, expire in order: oldest tentative → oldest with no observations → oldest `LOST`; each forced expiry increments `tracks_forced_expiry`.

**Duplicate prevention (the actual fix for reported problem #1)**
1. **Identity, not text.** One event per track lifetime; later frames update that event (upsert by `event_id`) instead of inserting rows.
2. **Explicit emission.** `EVENT_EMITTED` flag per track; a second emission for the same `track_key` is refused and counted (`double_emit_blocked`).
3. **Cooldown is a safety net only.** `reentry_cooldown_s` (default **15 s**) applies to `(camera_id, plate_norm)` purely to absorb track fragmentation from an ID switch. It is short and bounded, so it cannot hide a genuine second visit — unlike today's 60 s text cache.
4. **Fragmentation absorption.** At close time, if the same `(camera_id, plate_norm)` was emitted within `fragment_window_s` (default 3 s) and the two tracks overlapped in time/space, the second emission folds into the first event (`fragments_absorbed`).
5. **No cross-restart duplicates.** Although `session_epoch` changes on restart, the re-entry cooldown is checked against the DB (last event for `(camera_id, plate_norm)`), so a restart inside the window cannot duplicate.
6. **Merge absorbs plate tracks** (§2.3), so the vehicle-detector fallback path cannot double-count the same car.

### 2.6 Failure modes and their handling

| Failure | Detection | Handling |
|---|---|---|
| ID switch (two cars swap ids) | two tracks with conflicting plate consensus within `switch_window_s` | on close, if a sibling track in the window carries a *different* plate and the boxes overlapped, both events are marked `needs_review=1` and `id_switch_suspect=1`; the consensus layer keeps both plate candidates so a human can resolve |
| Track never gets a readable plate | `usable_obs == 0` at expiry | discarded, counted; optionally saved as `no_plate` metric only (no event row) — avoids polluting history like today |
| Plate read but low length consensus (weather/blur) | `length_mode_weight < 0.6` at expiry | emit `status=unconfirmed, needs_review=1` with the highest-posterior partial text; the review screen lets an operator fix it (P1-3 + P2-4 enabler) |
| Plate is partially outside the frame at entry/exit | plate box truncated (area or aspect out of range) | observation rejected as *quality*, not as *text*; the track waits for the next frame (this is why the tracker matters: today's per-frame pipeline has no "wait") |
| Motorcycle / Free-Zone / temporary plates (5–7 chars) | length mode ∈ {5,6,7} | validator handles the formats (`plate_validator.py:213-221`); the consensus engine treats length as a hypothesis, not an error |
| Camera scene change (PTZ, night mode) | sudden tracker age spike / mass track expiry | after `scene_reset_tracks` (default 5) forced expiries in 1 s, open tracks are flushed and the tracker is reset (`tracker_resets` counter) |

---

## 3. Event Model Design (Part 3)

### 3.1 Principle

`detections` today is an **append-only log of recognitions** (`db.py:37-48`): every emission inserts a row, there is no identity column, and "unique plates" is guessed as `COUNT(DISTINCT plate_dtrb)` (`db.py:213`). The new model separates two things the old schema conflated:

- **`vehicle_events`** — one row per vehicle visit; the object operators, alerts, and analytics use.
- **`plate_observations`** — the per-frame evidence behind an event; auditable, cheap to prune, never rendered in lists.

`detections` is **kept** (nothing breaks) and gains two nullable columns so legacy rows can optionally link to events.

### 3.2 `vehicle_events` (one row per track lifetime)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | DB identity = API/UI `event_id` |
| `event_key` | TEXT NOT NULL UNIQUE | `"{camera_id}:{session_epoch}:{local_track_id}"` — idempotent upsert key, and a DB-level guard against accidental double emission |
| `camera_id` | INTEGER NULL REFERENCES cameras(id) | NULL for image/video-file sources |
| `camera_name` | TEXT NULL | denormalized (cameras get renamed/deleted) |
| `session_id` | INTEGER NULL REFERENCES sessions(id) | reuses the existing session lifecycle (`db.py:124-144`) |
| `source_type` | TEXT NOT NULL | `rtsp` \| `video` \| `image` |
| `source_file` | TEXT NULL | video filename / upload name |
| `track_id` | TEXT NOT NULL | camera-local track id (string form of `track_key`) |
| `track_kind` | TEXT NOT NULL DEFAULT 'vehicle' | `vehicle` \| `plate` |
| `first_seen` | TEXT NOT NULL | ISO-8601, first frame of the track |
| `last_seen` | TEXT NOT NULL | ISO-8601, updated at close |
| `duration_ms` | INTEGER NOT NULL DEFAULT 0 | dwell time |
| `frame_count` | INTEGER NOT NULL DEFAULT 0 | matched frames |
| `observation_count` | INTEGER NOT NULL DEFAULT 0 | usable `PlateRead`s collected |
| `plate_number` | TEXT NOT NULL | canonical latin/DTRB text (equivalent of `plate_dtrb`) |
| `plate_norm` | TEXT NOT NULL | `watchlist.matching.normalize_for_match(...)` result — indexed for search and cooldown lookups |
| `plate_persian` | TEXT NULL | display form (`plate_validator.format_plate_persian`) |
| `confidence` | REAL NOT NULL DEFAULT 0 | calibrated consensus confidence (Part 4.5) |
| `agreement_ratio` | REAL NOT NULL DEFAULT 0 | share of usable observations equal to the consensus text |
| `quality_score` | REAL NOT NULL DEFAULT 0 | quality of the selected best frame (Part 4.4) |
| `char_confidences` | TEXT NULL | JSON array of per-position confidences |
| `alternates` | TEXT NULL | JSON array of runner-up candidate plates |
| `plate_valid` | INTEGER NOT NULL DEFAULT 0 | `plate_validator.validate_iranian_plate` outcome |
| `plate_category` | TEXT NULL | from `PlateMetadata` (military/taxi/…​) |
| `plate_color_scheme` | TEXT NULL | white/yellow/green/red/blue/black |
| `region_code` | TEXT NULL | Iranian region code |
| `region_name` | TEXT NULL | province name |
| `city` | TEXT NULL | `_find_city` result |
| `vehicle_type` | TEXT NULL | car/motorcycle/bus/truck (detector class) |
| `vehicle_make` | TEXT NULL | ResNet18 make prediction, computed **once** per event |
| `vehicle_color` | TEXT NULL | ResNet18 colour prediction, computed **once** per event |
| `attribute_confidence` | REAL NULL | confidence of make/colour prediction (both are thresholded today) |
| `attribute_computed_at` | TEXT NULL | proof that the single attribute inference ran |
| `best_frame_path` | TEXT NULL | relative path under `io/events/...`; served by `/api/events/{id}/best-frame.jpg` |
| `best_frame_plate_path` | TEXT NULL | plate-crop-only image (UI thumbnail) |
| `best_frame_frame_idx` | INTEGER NULL | frame index of the best frame (debug/replay) |
| `status` | TEXT NOT NULL DEFAULT 'confirmed' | `confirmed` \| `unconfirmed` \| `closed_partial` |
| `needs_review` | INTEGER NOT NULL DEFAULT 0 | 1 when emitted by force/uncertainty → review queue |
| `id_switch_suspect` | INTEGER NOT NULL DEFAULT 0 | set by the ID-switch heuristic (§2.6) |
| `fragment_of_event_id` | INTEGER NULL REFERENCES vehicle_events(id) | set when this event absorbed a fragment |
| `alert_count` | INTEGER NOT NULL DEFAULT 0 | denormalized matching-alert count |
| `created_at` | TEXT NOT NULL | insert time |
| `updated_at` | TEXT NOT NULL | last update (upgrade/close) |

Indexes (created in `init_db`, `IF NOT EXISTS`):

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_key         ON vehicle_events(event_key);
CREATE INDEX        IF NOT EXISTS idx_events_camera_time ON vehicle_events(camera_id, last_seen DESC);
CREATE INDEX        IF NOT EXISTS idx_events_plate_norm  ON vehicle_events(plate_norm, last_seen DESC);
CREATE INDEX        IF NOT EXISTS idx_events_time        ON vehicle_events(last_seen DESC);
CREATE INDEX        IF NOT EXISTS idx_events_session     ON vehicle_events(session_id);
CREATE INDEX        IF NOT EXISTS idx_events_review      ON vehicle_events(needs_review, last_seen DESC)
                                                          WHERE needs_review = 1;
```

### 3.3 `plate_observations` (per-frame evidence, append-only)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `event_id` | INTEGER NULL REFERENCES vehicle_events(id) | set when the event is emitted |
| `event_key` | TEXT NOT NULL | lets evidence be written/bound without waiting for the event id |
| `camera_id` | INTEGER NULL | |
| `track_id` | TEXT NOT NULL | |
| `frame_idx` | INTEGER NOT NULL | |
| `ts` | TEXT NOT NULL | ISO-8601 of the frame |
| `plate_text` | TEXT NOT NULL | raw OCR string, unfiltered |
| `plate_det_conf` | REAL NOT NULL | plate-box confidence |
| `char_conf` | REAL NOT NULL | mean character confidence |
| `char_count` | INTEGER NOT NULL | characters read |
| `quality` | REAL NOT NULL | composite quality score (Part 4.4) |
| `sharpness` | REAL NOT NULL | normalized variance of Laplacian |
| `plate_area_px` | INTEGER NOT NULL | plate box area in pixels |
| `aspect_ratio` | REAL NOT NULL | box w/h |
| `bbox` | TEXT NOT NULL | JSON `[x1,y1,x2,y2]` **normalized 0–1** (same convention the client already consumes, `video_processor.py:521-526`) |
| `vehicle_bbox` | TEXT NULL | JSON normalized vehicle box |
| `agreed_with_consensus` | INTEGER NULL | filled at close, for analysis |
| `created_at` | TEXT NOT NULL | |

```sql
CREATE INDEX IF NOT EXISTS idx_obs_event ON plate_observations(event_id);
CREATE INDEX IF NOT EXISTS idx_obs_key   ON plate_observations(event_key, frame_idx);
CREATE INDEX IF NOT EXISTS idx_obs_ts    ON plate_observations(ts);
```

**Write-volume policy (matters):** observations live in the track's in-memory buffer (capped, §5.8) and are flushed **once** at emission inside the same transaction as the event upsert. Only *usable* observations are persisted, capped at `max_persisted_obs` (default 20) selected by quality descending. Result: ≤20 evidence rows per vehicle instead of one row per recognition (today's behaviour), with a full audit trail of the decisive frames.

### 3.4 Links to existing tables

```sql
-- optional linkage for legacy rows (nullable → no backfill required)
ALTER TABLE detections ADD COLUMN event_id INTEGER NULL REFERENCES vehicle_events(id);
ALTER TABLE detections ADD COLUMN track_id TEXT NULL;

-- alerts now hang off events; detection_id stays nullable for legacy rows
ALTER TABLE alerts ADD COLUMN event_id INTEGER NULL REFERENCES vehicle_events(id);
```

`db.py` already provides the repository's safe, idempotent migration primitive: `_ensure_column(conn, table, column, ddl)` (`db.py:15-19`). **Use it** for these three columns — do not hand-roll `PRAGMA` checks again.

### 3.5 Migration strategy

Additive, re-runnable, flag-gated.

| Step | Action | Rollback |
|---|---|---|
| M1 | `init_db()` creates `vehicle_events` + `plate_observations` + indexes (`CREATE TABLE IF NOT EXISTS`). No writer uses them yet. | drop the two empty tables |
| M2 | `_ensure_column` adds `detections.event_id`, `detections.track_id`, `alerts.event_id`. | ignore the empty nullable columns |
| M3 | New write path live **behind flag** `PIPELINE_MODE=events` (default `events` for RTSP, `legacy` for image/video in Phase 1 — Part 8). In `events` mode the pipeline writes events + observations **and keeps the legacy `detections` insert (dual-write)** so all existing readers keep working. | flip flag to `legacy` — old behaviour returns, no schema change |
| M4 | New read APIs (`/api/events*`) ship; legacy endpoints keep reading `detections`. | remove routers |
| M5 | After Flutter migration (Phase 4), dual-write off (`DUAL_WRITE_DETECTIONS=0`); legacy `/api/detections*` becomes a **compatibility projection over `vehicle_events`**. | re-enable dual-write |
| M6 | Retention extended: events pruned by `last_seen`, observations by `ts` on a shorter horizon, best-frame files deleted with their event. | keep files/tables (pruning is time-based, nothing structural) |

**Dual-write (M3), one emission produces:**
1. `INSERT INTO vehicle_events ... ON CONFLICT(event_key) DO UPDATE ...` (idempotent upsert),
2. batched `INSERT INTO plate_observations ...`,
3. the legacy `INSERT INTO detections ...` carrying `event_id`, so `db.get_stats`, `/api/detections`, CSV export, and the Flutter history grid keep working unchanged.

Reconciliation rule: dashboard counters switch to event-based aggregates only in M5, so dashboards do not jump mid-migration.

### 3.6 Backward compatibility

| Consumer | M1–M4 | After M5 |
|---|---|---|
| `db.get_stats()` (`db.py:210-228`) | unchanged (reads `detections`) | reimplemented over `vehicle_events`; response keys kept, new keys added, so `stats_model.dart` keeps parsing |
| `db.get_all_detections` (`:241-260`) | unchanged | kept as a projection over `vehicle_events`: `plate_dtrb←plate_number`, `plate_persian`, `confidence`, `timestamp←last_seen` |
| `/api/detections*` legacy (`api.py:193-226`) | unchanged (dual-write feeds them) | projection; and note these endpoints are also unauthenticated (audit Appendix C) — delete or secure in Phase 3 |
| `/api/reports/*` (`routers/reports.py`) | unchanged | extended with event series (Part 7) |
| CSV export (`routers/export.py`) | unchanged | extended with event columns / second export mode |
| `/status` `history` field | still emitted with the **same field names** (`dtrb_text`, `yolo_text`, `confidence`, `first_seen`, `last_seen`, `count`, `persian_display`, `is_valid_iranian`, `metadata`, `car_color`, `car_type`, `city`) — `EnhancedRtspHistoryEntry.fromJson` keeps working. `count` gains real meaning (`frame_count`); new fields appended (`event_id`, `track_id`, `agreement_ratio`, `needs_review`, `status`) which old clients ignore | `history` deprecated but retained one release |
| Alerts (`db.create_alert`, `watchlist/matching.py:92-102`) | signature unchanged; the hook receives the event id as **both** `detection_id` and `event_id` during M3–M4 so old screens resolve links | call sites cleaned up |

### 3.7 Old-data handling

- **No destructive migration.** Existing `detections` rows — including the duplicates that motivated this work — stay untouched; their `event_id` remains NULL.
- **Optional opt-in backfill** (`scripts/backfill_events.py`, Phase 3, never on the runtime path): groups legacy rows by `(camera_id, plate_dtrb)` with a `gap > 60 s` rule starting a new group; creates one `vehicle_event` per group with `status='closed_partial'`, `needs_review=1`, `event_key='backfill:{camera}:{hash}'`; sets `detections.event_id`. **Idempotent** (skips rows with `event_id`), **reversible** (delete rows with `event_key LIKE 'backfill:%'`), **off by default**.
- **Before/after proof:** compare `COUNT(*)`, `COUNT(DISTINCT plate_norm)`, `COUNT(DISTINCT plate_dtrb)` over the same interval on a **copy** of `database/plpr.db` — never on the live file.
- Legacy file `database/license_plate_recognition.db` is unrelated to `plpr.db` (audit §4.2 L3) and stays untouched.

---

## 4. Multi-Frame Consensus Engine (Part 4)

`pipeline/consensus.py` is pure: no camera, no DB, no threads. Its input is the evidence a track collected; its output is the single plate the operator sees.

### 4.1 Input: `PlateRead`

One `PlateRead` per usable OCR pass. Today's `_assemble_chars` (`alpr_engine.py:231-278`) already produces text + mean confidence + char boxes; this design adds the fields the algorithm needs (no behaviour change to that function — the collector wraps it).

```
PlateRead:
  frame_idx        : int
  ts               : str (ISO-8601)
  text             : str                  # canonical latin form, e.g. "12b34567"
  char_candidates  : list[list[(char, conf)]]   # per position, sorted by conf, top-K (K=3)
  char_count       : int
  plate_det_conf   : float                # the meaningful "is this a plate" score (audit §3.1 #6)
  plate_area_px    : int
  aspect_ratio     : float
  sharpness        : float                # variance of Laplacian of the plate crop, normalized
  brightness_ok    : bool                 # crop mean within [lo, hi], not blown out / pitch dark
  usable           : bool                 # decided by the quality gate (§4.3)
  weight           : float                # computed once, stored (Part 4.2)
```

**Collector rule (§6 is not changed yet):** keep `char_model.pt` in P0–P2. Per-character candidates come from the detector cheaply: today's code sorts boxes by x1 and takes argmax (`alpr_engine.py:260-274`); the extension keeps, per x-sorted position, the runner-up class confidences that also land on the same x-window — a 3-line change inside `_assemble_chars`, producing notes E1/E2 in Part 8.

### 4.2 Observation weight

Each usable observation votes with a weight that combines *read quality* and *image quality*:

```
w_i = plate_det_conf_i × mean_char_conf_i × quality_i
```

where `quality_i` is the composite score of §4.4, and both confidence factors are clipped below by `min_vote_conf` (default 0.2) so a catastrophically poor read contributes noise rather than an infinite zero. Observations that fail the quality gate (weight below `min_obs_weight`, default 0.02) are still **stored** (the track needs to know plates were *attempted*) but do not vote — this keeps garbage like the `1499 @ 0.0496` reads in `log_demo_result.txt` from ever influencing the result.

### 4.3 Quality gate (what counts as evidence)

An observation is **usable** only if all hold:

| Check | Default | Rationale |
|---|---|---|
| `plate_det_conf ≥ plate_gate_conf` | 0.5 (was 0.6: the track accumulates, so individual reads may be weaker — ByteTrack's "keep low-score" argument applied to OCR) | keeps blurry-but-real plates in play |
| plate width `≥ min_plate_width_px` | 48 px on the original frame | below this, even a perfect read is a guess |
| `brightness_ok` | mean ∈ [40, 220] on the plate crop | rejects blackout/whiteout frames (night flash, headlight bloom) |
| `sharpness ≥ min_sharpness` OR `usable_obs < 2` | lenient when evidence is scarce | fast-moving plates always arrive blurred; the *first* reads may be soft and the engine must not deadlock |

Failed checks are counted (`obs_rejected_quality`, `obs_rejected_area`, `obs_rejected_brightness`) so operators see *why* a camera under-reads.

### 4.4 Image quality scoring (best-frame metric)

For each usable observation:

```
sharpness_norm = clamp01( ln(1 + lap_var) / ln(1 + SHARP_REF) ),   SHARP_REF = 300.0
area_norm      = clamp01( plate_area_px / AREA_REF ),              AREA_REF  = 120*40 px
aspect_pen     = 1 - clamp01( |aspect - EXPECT_ASPECT| / EXPECT_ASPECT ), EXPECT_ASPECT = 4.6
conf_norm      = clamp01( (plate_det_conf + mean_char_conf) / 2 )

quality = 0.45·sharpness_norm + 0.25·area_norm + 0.10·aspect_pen + 0.20·conf_norm
```

All constants are config (Appendix C) with these defaults; the eval harness (Part 6) will tune them per condition on the labelled set — the implementer must not hand-tune by eye. Lighting is handled structurally: `brightness_ok` gates blown frames out, and the *preferred* evidence is automatically the best-lit frame because poor lighting kills sharpness (motion bloom) and `conf_norm` together.

### 4.5 Voting, length modes, confidence (the algorithm)

**Step 1 — length consensus.** Group usable observations by `char_count`. Total weight per length; the winner `L*` must command `length_mode_weight ≥ 0.6`. Other lengths are set aside (they are evidence of *partial* plates — §4.7 — not errors to average in). This is the correct handling of unstable reads: 7-char and 9-char variants of one plate no longer fight the 8-char reads; the 8-char mode wins and the rest become alternate context.

**Step 2 — position voting.** For each position `p` in `0..L*-1`, accumulate weighted votes from `L*`-length observations, using **ranked candidates**, not just argmax:

```
votes[p][char] = Σ w_i × (1.0 rank-0, 0.5 rank-1, 0.25 rank-2)
posterior[p][char] = votes[p][char] / Σ_char votes[p][char]
consensus[p] = argmax posterior[p]
conf[p]      = max posterior[p]
```

**Step 3 — agreement and confidence.**

```
consensus_text  = concat(consensus[p])
agreement_ratio = ( Σ w_i where text == consensus_text ) / ( Σ w_i over usable obs )
char_mean       = mean(conf[p])
confidence      = 0.5 × char_mean + 0.5 × agreement_ratio     # 0–1, stored on the event
plate_posterior_min = min(conf[p])                            # weakest char, feeds the review rule
```

**Step 4 — validation.** `consensus_text` passes through the unchanged `validate_iranian_plate` (`plate_validator.py:94-194`); consensus does not validate. An invalid consensus yields `status=unconfirmed, needs_review=1`, never silence.

**Alternates:** the two plates formed by flipping the weakest position to its runner-up candidate; stored on the event for review and the P3 decision layer.

### 4.6 Stopping conditions (normative, first match wins)

| Rule | Condition | Result |
|---|---|---|
| `CONFIRM` | `usable_obs ≥ 3` AND `length_mode_weight ≥ 0.6` AND `agreement_ratio ≥ 0.6` AND `plate_valid` | emit `confirmed`. The audit's example (0.82 / 0.77-with-one-char-diff / 0.91) resolves to `12ب34567` at ~0.9: two agreeing reads outweigh the dissenter, whose weight is further discounted by its quality. |
| `EARLY_BEST` | one read with `plate_det_conf ≥ 0.95` AND `mean_char_conf ≥ 0.95` AND `quality ≥ 0.85` AND `plate_valid` (disabled in the first release; enable after Part 6 proves it) | emit `confirmed` on a single frame (stationary car that yields no more frames) |
| `UPGRADE` | already emitted + later read matches consensus + `quality > best_quality × 1.15`, at most `max_upgrades = 1` per event | update `best_frame_*`, `confidence`, `quality_score`; **no new row**; publish an event update on the bus |
| `FORCE_AT_CLOSE` | track expired, `usable_obs ≥ 1`, `max(char_mean, agreement_ratio) ≥ force_emit_posterior` (0.5) | emit `unconfirmed` + `needs_review=1` |
| `SUPPRESS` | expired with `usable_obs == 0` | no event; counters only |

After `CONFIRM`, track OCR cadence drops to `confirmed_ocr_stride` (default 5) and only `UPGRADE`-eligible reads are collected — the largest inference saving after ROI gating (Part 5.6).

### 4.7 Wrong OCR, partial plates, blur, lighting (specified)

| Case | Detection | Handling |
|---|---|---|
| One wrong character (`12ب34587` vs `12ب34567`) | position vote split 1-vs-N | weighted majority wins; the dissenter lowers `agreement_ratio`, which honestly lowers `confidence` — correct behaviour, not a bug |
| Two stable variants 50/50 across lighting | `char_mean` high but `plate_posterior_min < 0.7` | emit `confirmed` with `needs_review=1` and both variants in `alternates` when `review_on_weak_char` (default 1) |
| Partial plate at entry/exit (7 of 8 chars) | minority `char_count` group | parked, never emitted alone; at close, if the *only* evidence is partial, `FORCE_AT_CLOSE` emits it as `unconfirmed` with the visible chars |
| Blurred frames | low sharpness → low quality → low weight | excluded from voting automatically; still counted in `observation_count` so dashboards explain themselves |
| Lighting changes during a visit | brightness gate + quality mix (§4.4) | best-lit frame is naturally preferred; crossings increment `obs_rejected_brightness` |
| Plate changes mid-track (ID-switch pathology) | two length modes both ≥ 0.4 after ≥ 6 observations | **split evidence at the change point**: emit the first segment if it satisfies `CONFIRM`, open a second segment, flag both `id_switch_suspect=1` |
| Same text, different car, re-entry in cooldown | §2.5 rules 3–4 | cooldown absorbs ≤15 s fragments; genuine revisits correctly create a second event |

### 4.8 Pseudocode (implement verbatim, then property-test)

```
def update(track_state, plate_read, cfg) -> (ConsensusResult | None, EmitAction):
    # 1. append evidence
    track_state.observations.append(plate_read)
    if plate_read.usable: track_state.usable.append(plate_read)
    track_state.best = max_by_quality(track_state.usable)   # best-frame selection
    # 2. length mode
    L_star, mode_weight = length_consensus(track_state.usable, cfg)
    # 3. position votes on the L_star group
    consensus, conf, posterior_min = position_votes(group_of(L_star), cfg)
    agreement  = agreement_ratio(track_state.usable, consensus.text)
    confidence = 0.5 * mean(conf) + 0.5 * agreement
    result = ConsensusResult(track_state.track_key, consensus.text, conf,
                             agreement, confidence, posterior_min,
                             mode_weight, track_state.best)
    # 4. stopping rules in §4.6 order
    return result, decide(track_state, result, cfg)  # HOLD | CONFIRM | EARLY_BEST | UPGRADE | FORCE | SUPPRESS
```

Pure units to test independently: `length_consensus`, `position_votes`, `agreement_ratio`, `quality_score`, `decide`. Property tests to add: *≥3 agreeing reads + 1 dissenter → consensus is the majority and agreement ∈ (0,1)*; *confidence never drops when identical observations are appended*; *empty/partial reads can never flip a confirmed consensus*; *byte-identical evidence always yields byte-identical `ConsensusResult`* (determinism — Appendix D).

---

## 5. Performance Optimization Plan (Part 5)

Targets (measured on the same class of machine the audit used, CPU-only, 1280×960 input):

| Metric | Today (measured) | Target (after Phase 2) | How |
|---|---|---|---|
| `AlprEngine` work per **inferred** frame | ~110 ms, 5 model calls | **≤ 35 ms average, ≤ 3 model calls** | §§5.3–5.6 |
| Inference FPS, 1 camera | ~8–9 FPS | **15–25 FPS effective** (triage by tier; RTSP display stays 25–30 FPS on repeats) | §§5.1–5.4 |
| Cameras on one CPU host | 1–2 before saturation | **4 at 3–5 inferred FPS each** (default `concurrency_limit`) | §5.7 + §5.9 |
| Inferences per event | every sampled frame × 5 models | **3–8 OCR passes per track lifetime + 2 attribute passes** | §§5.2, 5.5, 5.6 |
| Display JPEG work per camera | ~30 encodes/s, ≤960 px, unconditional | **≤ 12 encodes/s, ≤720 px, subscriber-gated** | §5.9 |
| Client per-camera CPU (fallback path) | 10 HTTP polls/s + full-state JSON + JPEG decode | **1 events stream + MJPEG** (no polling) | §5.6-note + Part 7.3 |

### 5.1 Frame skipping

**Current problem.** `skip_frames` is a silent gate for RTSP (`video_processor.py:944`) and silently ignored for video files (`:397-449`); it gates by fixed frame modulo, so at 25 FPS / `skip=15` the pipeline *submits* 1.7 FPS while the display pretends 30 FPS, and when the stream's real FPS or the inference time changes, the setting is meaningless.

**Proposed solution.** `FrameScheduler.should_sample()` combines three rules, in order:
1. **Time budget**: sample iff `now - last_submit_ts ≥ sample_period_s`, where `sample_period_s = max(skip_frames/stream_fps, inference_budget_per_cam / expected_inference_ms × safety)`. The scheduler measures its own `last_inference_ms` (EMA) and widens the period when inference falls behind — this automatically converges to the real sustainable rate.
2. **Track pressure**: with ≥1 live uncon­firmed track, never skip more than `max_gap_tracked` (default 250 ms) — tracks need input to survive.
3. **Video-file mode**: no wall clock; process frame `i` iff `i % sample_modulo == 0` where `sample_modulo = max(skip_frames, ceil(estimated_inference_time × src_fps))`; the **output** video still writes every frame, reusing the last overlay snapshot. This honours the setting *and* keeps smooth output without 1800 inferences per minute.
Counters: `frames_skipped_schedule`, `frames_skipped_budget`, `sample_period_s` (gauge).

**Expected impact.** Video jobs: 3–10× fewer inferences with identical event output (same tracks, same consensus). RTSP: inference rate clamped to what the CPU can sustain instead of the configured illusion; fewer dropped frames overall because the worker is not permanently behind.

### 5.2 Inference frequency control

**Current problem.** Every sampled frame runs the *maximum* stack: vehicle → plate → chars → make → colour. The audit measured ~8 recognitions/second of one parked plate — 100 % of it redundant.

**Proposed solution.** Tier the work by lifecycle state:
- **No live tracks** (`tier=FULL`): vehicle detector only, low-rate full plate scan (`plate_scan_period` = every 3rd sampled frame) to catch appearing plates cheaply.
- **Unconfirmed tracks** (`tier=FULL`): vehicle + ROI plate + OCR every scheduled frame.
- **Confirmed tracks** (`tier=TRACK_ONLY`): vehicle detector only for track continuity; ROI + OCR once per `confirmed_ocr_stride` (default 5) **and** only while an upgrade is still possible (quality still below `quality_saturation` = best observed + 15 %). Plate scan fallback runs once per `confirmed_scan_period` (default 15) to catch *new* cars.
- Global semaphore + `max_inferences_per_frame` (default 4, counting each model call as 1) hard-caps pathological frames before they happen.

**Expected impact.** Steady-state (plate readable, one car): from 3–5 model calls/frame to ≈1.2 averaged (vehicle most frames, ROI+OCR every 5th); the measured per-frame budget drops from ~110 ms toward the 35 ms target. Parked-street cameras — the common case — stop burning CPU.

### 5.3 YOLO input resolution

**Current problem.** No `imgsz` is passed anywhere (`alpr_engine.py` three YOLO calls), so all three models run at the Ultralytics default 640; the audit measured 640 as ~2× the cost of 320 on the same frame.

**Proposed solution.** Pin per-model defaults (config, Appendix C) and choose plate-scan resolution by region of interest:
- vehicle detector: `imgsz=416` (412/416 keeps the 16-stride aligned; tested value stays within the measured 320→640 band),
- plate detector on vehicle ROI: `imgsz=512`; plate detector on *full-frame fallback scans*: `imgsz=640` (large plates are the only fallback target),
- char detector on plate crop: `imgsz=256` (plate crops are 30–60 px tall natively; 640 only adds interpolation artefacts).
The ticket-level gate stays `conf` unchanged, so behaviour changes are resolution-only and A/B-testable.

**Expected impact.** Vehicle ≈ 12–15 ms, ROI plate ≈ 10–14 ms, char ≈ 6–8 ms on the audit machine — ≈35 ms per `FULL` frame vs ≈75 ms for the three-YOLO subset today. Combined with §5.2's cadence reduction, average per-frame cost lands in the 20–35 ms band.

### 5.4 ROI processing

**Current problem.** Plate detection searches the whole frame even though the pipeline already knows where the vehicles are (`alpr_engine.py:295-346` computes both, uses them independently); with `max_det=20` it can also chase dozens of boxes in clutter (audit H1/H3).

**Proposed solution.** Constrain the search: plate detector runs on each vehicle ROI expanded by `roi_pad` (default 12 %, capped at the frame), `(W_roi + 2·pad) × (H_roi + 2·pad)`. Full-frame scans run only at `plate_scan_period` and emit into the plate-fallback track path (§2.3). Within an ROI, `max_det` drops to 3. Containment-first assignment: a plate box belongs to the ROI whose vehicle box contains its centre; cross-ROI plates resolve by highest IoU-containment.

**Expected impact.** Search area shrinks by ~5–10× on typical frames; plate detector drops to its resolution floor; the long tail of 20 detections/frame (with 20 downstream classifier runs) disappears by construction. Second-largest win after attribute gating.

### 5.5 ResNet18 optimization

**Current problem.** Both 11 M-param fp32 ResNets run per vehicle box per inferred frame (`alpr_engine.py:319-322`): measured 48 ms/frame ≈ 45 % of the pipeline, for attributes that change once per visit.

**Proposed solution (three steps, in order).**
1. **Frequency gating (Phase 1, no model change):** make and colour are computed **once per event** — on the best frame, at `CONFIRM` time (make) and on the highest-quality vehicle crop (colour). Result cached on the row (`attribute_computed_at`). Per-frame call sites removed. Expected saving: ~45 ms/frame of the ~110 ms measured.
2. **Resolution + export (Phase 2):** inputs rescaled to square 160 (or the harness-proven minimum) and exported ONNX (CPU) — typical 2–3× on those two calls; then int8 if the accuracy harness (Part 6) accepts it.
3. **Escalation path (P3 decision support):** attributes remain optional per camera (`enable_attributes=true/false`); when disabled, events carry `vehicle_make=null` and the export/stats layers treat the column as nullable (schema already allows NULL).

**Expected impact.** Step 1 alone nearly halves CPU per camera with zero accuracy risk (same models, same best-data input). Steps 2–3 make attributes a negligible background cost.

**Note on Flutter (`§5.6-note`, actually client-side):** the 100 ms `/frame` poll returns the *whole* history JSON per tick and rebuilds Riverpod state 10×/s/camera (`camera_poll_controller.dart:49-55`). That is UI-thread CPU burn proportional to camera count and is obsoleted by the event bus (Part 7.3): after SSE lands, `/frame` reduces to a 5 s metadata heartbeat and the normalised path is MJPEG video + event stream only.

### 5.6 Async pipeline

**Current problem.** Everything after the frame read for one camera executes serially in one thread's critical path, and the request threads contend on the processor lock (`routers/detection.py:367-371`): DB writes, watchlist matching, alert inserts, JPEG encodes, and history copies all happen either inside or fenced by the inference work.

**Proposed solution.** Split work into *ordering-critical* vs *deferrable*:
- Ordering-critical stays in `PipelineWorker` (stages 1–8, single thread/camera): scheduler → detector → tracker → lifecycle → plate → OCR → consensus → event assembly.
- Deferrable moves to bounded shared queues processed by dedicated threads: `DbWriter` (queue 256; batch insert the event + ≤20 observations in one transaction), `FrameStore` (queue 64; best-frame JPEG + file write), `EventBus.publish` (lock-free ring; SSE generators read it), display JPEG encode (existing thread, new budget rules in §5.9).
Queue-full policy: drop the *oldest* queued item of the same category (`events` never dropped before `observations`; best-frame updates supersede each other by event id), every drop counted and exposed on `/api/events/health`.

**Expected impact.** Inference worker latency becomes the pure model-call time; a slow disk or a contended SQLite file no longer inflates per-frame ms or drops tracks. Also directly removes audit H5 (per-detection write amplification on the caller thread).

### 5.7 Queue management

**Current problem.** No queues with semantics exist: RTSP has a 1-slot overwrite (`_ml_pending_frame`, `video_processor.py:820-834`) with a dead `_ml_busy` flag; video tasks have no limit at all (one thread per upload, `routers/detection.py:201-232`); the camera limit (default 4, `db.get_concurrency_limit`) counts cameras, not work.

**Proposed solution.**
- Per camera: reader→worker slot depth `frame_queue_depth=2` (drop-oldest + counter); worker-internal staging is unbounded-by-design but small (tracks ≤ 32, observations ≤ 30/track before pruning to `max_track_obs=30` by quality — §5.8).
- Process-wide: `max_concurrent_inference=2` semaphore wraps every model call; `max_video_tasks=1` global bound with FIFO `video_task_queue` (queued tasks report `status=queued, position=N`); camera slots keep the existing FIFO (`CameraManager`) and gain a per-camera `inference_priority` used only to order semaphore acquisition (starvation-free: FIFO inside each priority).
- Saturation contract: acquisition timeout 3 s → if exceeded, the frame is dropped with `frames_dropped_semaphore` and the camera still reports `streaming` (transient) rather than `error`; only after `semaphore_stall_frames` (default 50) consecutive drops does the processor log a warning and the health endpoint degrade.

**Expected impact.** CPU is bounded by construction: at most 2 inference threads execute model code at any instant regardless of camera count and upload bursts. Four cameras share time instead of each degrading the others; a pathological 20-box frame (audit H1) caps at `max_inferences_per_frame=4` and surfaces the cap in metrics rather than stalling the house.

### 5.8 Memory management

**Current problem.** Copies and unbounded growth everywhere: `frame.copy()` per sampled frame (`video_processor.py:946`), full history + live-detection lists copied per status poll (`:1039-1052`), `live_detections` capped at 500 but `plate_history` unbounded (`:557-560`, `:633`), `_recent_emit_times` never pruned (`:379`, `:636`).

**Proposed solution.**
- Frame passing is by reference + `seq`; `ndarray` copies happen only for (a) crops that outlive the frame (best-frame candidates — and only until a better candidate replaces them), and (b) the display path's working copy (one per camera). Plate read crops use `np.ndarray` *views* where the model wrapper allows it.
- Track observation buffer: ring of `max_track_obs=30` usable reads; beyond that, a new read replaces the current lowest-quality read only if it is better (`obs_dropped_cap`). Memory per track is therefore constant.
- Event history served to UI: at most `history_limit=50` most-recent events per task response with an incremental cursor (`?since_seq=N`) so repeated polls transfer deltas, not the whole list.
- `torch` memory: keep `torch.no_grad()` everywhere (audit found it at `alpr_engine.py:193`, `:212`), add `torch.inference_mode()` around stage calls where supported, and release intermediate YOLO `Results` objects by extracting `xyxy/conf/cls` immediately (today the whole `Results` is retained longer than needed inside `_assemble_chars` iteration).
- The `DbWriter` holding one persistent SQLite connection replaces one-connection-per-call (`db.py:8-12`) for the pipeline paths; read paths keep `get_conn()` unchanged.

**Expected impact.** Steady-state memory per camera becomes O(tracks × 30 observations) with a hard ceiling instead of growing with session length; per-frame allocation rate falls (fewer copies, lighter `Results` retention), which on CPython directly reduces GC pauses that today appear as "jitter".

### 5.9 JPEG streaming optimization

**Current problem.** Every camera encodes a ≤960 px JPEG at ~30/s unconditionally (`video_processor.py:949-973`, quality 50), plus the `/video/{id}` endpoint re-encodes per poll (`routers/detection.py:250-258`) and the MJPEG generator sleeps 25 ms between frames (`:422`) — on top of ~9 inferences/s. Display work competes with inference for the same cores (audit C6/H6).

**Proposed solution.**
- **Subscriber gating:** `CameraSubscriptionRegistry` counts live consumers (MJPEG readers + `/frame` pollers active in the last 10 s). Display encode runs only if `subscribers > 0` and the worker is `streaming`.
- **Adaptive budget:** encode period `display_period_s = max(1/12, encode_cost_ema × 2)` (default floor 12 FPS); width cap 720 px (configurable; 960 only when `display_hd=1`); quality 60; skip encoding when neither the frame seq nor the overlay snapshot changed since the last encode (`display_frames_skipped_idle`).
- **`video_status` serves the cached display JPEG** (same bytes the MJPEG path uses) instead of re-encoding; the cached-at timestamp is part of the response so the client can tell a stale frame from a stream stall.
- Track overlay snapshot is a versioned immutable tuple `(seq, list[OverlayBox])` — the atomic tuple pattern already used (`video_processor.py:880-886`) is kept, extended with `seq` for the idle-skip rule.

**Expected impact.** Display encodes drop from ~30/s to ≤12/s at 72 % of the pixels when watched, and to near zero when nobody watches — on a 4-camera host that returns roughly a core to inference. Latency-visible effects: no change to watchers, and stall detection becomes honest (cached-at age instead of frozen re-encoded frames).

---

## 6. AI Model Strategy (Part 6)

Rule from the request: **no model is replaced in this design.** This part specifies the *evaluation harness* that makes any future change defensible, the *dataset* it needs, and the explicit fork between the current character-detector OCR and sequence OCR — including exactly when the fork may be taken.

### 6.1 What must be measured first (the baselines)

Before Phase 1 code lands, record the current models' numbers on a **frozen held-out set** (§6.3). Never start from the audit's ad-hoc numbers (single still, latency-only); the harness below replaces them.

**Accuracy benchmarks (per current model):**

| Model | Primary metric | Diagnostic metrics | Definition of "correct" |
|---|---|---|---|
| `car_det_model.pt` (vehicle) | mAP@0.5 on the *4 used classes only* (COCO 2,3,5,7) | per-class AP, per-size AP (small/medium/large), false negatives per 100 frames | IoU ≥ 0.5 with a labelled vehicle that is *relevant* (a vehicle whose plate is or could be readable — distant traffic is a separate bucket) |
| `plate_det_model.pt` | mAP@0.5 **and** mAP@0.5:0.95, recall@0.5/0.85/0.95 | recall by plate size (<32 px width, 32–64, >64), by condition (day/night, angle, rain/blur), duplicates-per-image (the over-detection the audit's comment at `alpr_engine.py:53-58` mentions) | IoU ≥ 0.5 *and* the emitted string (with today's char OCR) has the right length |
| `char_model.pt` (OCR) | **plate-level exact match** (the operator metric) | character error rate (CER), per-character confusion matrix (audit's suspected `i/1, o/0, s/5, v/و` and duplicate-`n`/`s` mapping issues are hypotheses to verify, not facts to fix by hand), no-read rate, garbage rate (output the validator rejects) | canonical latin string equality after `_normalize_digits` + separator strip (`plate_validator.py:77-80`) |
| `car_name_model.pth`, `color_model.pt` | top-1 accuracy **on full vehicle crops**, not curated thumbnails | confusion matrix (white/silver/grey cluster; `Samand`/`Soren`/`Dena` cluster), abstention rate (today: `None` below 0.65/0.7 — `alpr_engine.py:198`, `:217`) | exact class match; measured both including and excluding abstentions |
| End-to-end (the only number stakeholders quote) | **event-level exact match**: one frozen clip per visit → one emitted event with the right plate | duplicates-per-visit, latency-to-first-event, `needs_review` rate, attribute correctness conditional on event | a *visit*, not a frame, is the unit |

**Latency benchmarks (same harness, distinct script):**
- p50/p95 per model call on CPU **and** any available GPU, at the pinned `imgsz` values of §5.3, batch=1 (and 2/4 for later ONNX variants), inputs 1280×960 and 1920×1080.
- Full-pipeline p50/p95 per tier (`FULL` vs `TRACK_ONLY`), plus worker loop overhead (non-model time).
- Every number recorded with torch version, device, thread count, ultralytics version, `imgsz`, image size, and the git SHA of `pipeline/`. Anything less is not reproducible.
- Latency gates enter CI as *advisory* thresholds (artifact diff + warning, not a red build) until the hardware fleet is characterized.

### 6.2 Harness design (files to create)

```
eval/
  run_eval.py        # --dataset <dir> --split heldout --models ... → eval_report.json + .md
  bench_latency.py   # --res ... --repeats ... --device ...        → latency_report.json
  metrics.py         # pure: mAP helpers, CER, plate_exact_match, vote agreement
  datasets.py        # COCO-json for boxes; csv/jsonl for texts; split reader
  iranian_eval_set/  # NOT committed here: a MANIFEST with expected counts, hashes, licence notes
  baselines/         # committed JSON: v1 numbers for the 5 current models (the "do not regress" file)
```

- The harness calls models only through the same public interfaces the pipeline uses (`pipeline/detectors.py`, `pipeline/ocr_reader.py`) — never test-only shims. Otherwise the benchmark measures something other than production.
- The plate gold file is `visits.jsonl`: one line per visit `{visit_id, clip, camera_hint, plate_latin, plate_chars, conditions:[day/night/angle/blur/freezone], attributes:{make,color}}`. The track replay test drives `pipeline/` on the clip and asserts the event — the same fixture Phase 1 property tests use (Appendix D).

### 6.3 Dataset requirements (what to collect — the real gating item)

| Split | Size | Contents | Rules |
|---|---|---|---|
| `train_pool` (future retraining only) | ≥ 3 000 plate crops with per-character boxes + text; ≥ 500 full frames with vehicle+plate boxes; make/classifier images only as the confusion matrix demands (measure first, collect second) | day/night/rain, 3+ camera angles, motion blur **from clips, not synthetic**, Free Zone numeric plates at real proportions | every crop traceable to its source frame; no near-duplicates (same car ≤1 s apart) across splits; faces blurred if the deployment requires it |
| `heldout` (frozen: the baseline + every regression gate) | **500 full frames** (vehicle+plate boxes, plate text, condition tags) + **200 clips (one visit each)** + **300 hard-set frames** | hard set: heavy blur, >30° yaw, night, partial entry/exit, signage that looks like plates, Free Zone, motorcycles | **never used for training, tuning, or early stopping**; any change requires a versioned `heldout_vN` + re-baseline commit |
| `calibration` (confidence mapping) | 1 000 reads with model confidences + correctness labels | fits the `0.5·char_mean + 0.5·agreement` weights (§4.5) and the `EARLY_BEST` thresholds | weights are refit and reported, never hand-edited |

Collection order: (1) this deployment's own cameras (observing the retention policy — `retention/service.py`, `db.get_retention_days`), (2) released Iranian plate datasets, (3) synthetic augmentation only for lighting/blur *stress* — never as the held-out truth. The README Drive links (`README.md:18-20`) are *inputs*, not ground truth.

### 6.4 Future path: character-detector OCR vs sequence OCR

The fork is real and must be decided on numbers, not taste:

| Dimension | Current character detector (`char_model.pt`, YOLO 27-class) | Sequence OCR (CRNN / DTRB / ParseQ / small transformer) |
|---|---|---|
| Output | per-char boxes + confidences (needs the hand mapping `CHAR_CLASSNAMES`, `alpr_engine.py:27-31`) | string + per-step logits/beam alternatives — the beam list *is* the candidate list the audit's gap list asks for |
| Fit to the consensus engine | **native**: per-position votes (§4.5) consume exactly this evidence | good but indirect: beams vote as whole strings; per-position posteriors must be derived from attention/CTC alignments (possible, one extra step) |
| Blur / low resolution | brittle: a missing character breaks length and vote | **stronger**: interpolates across gaps — which is also its failure mode (hallucinated characters) |
| Partial plates | emits 7-char reads honestly (good; length-mode handles them) | tends to emit 8-char completions (good for UX, dangerous for `agreement_ratio` honesty — must be verified) |
| Latency (CPU) | one YOLO @256 per crop ≈ 6–8 ms target (§5.3) | CRNN-lite comparable; transformer decoders slower; DTRB-TPS adds a rectification cost |
| Training data | needs per-character boxes (expensive) | needs only crop→text pairs (cheap) — a decisive practical advantage |
| Iranian-script fit | today's tokens include multi-char Persian encodings (`ein`, `gh`, `sad` — audit §6.2) | emits the *canonical latin alphabet* directly; Persian display stays a single pure function (`plate_validator.format_plate_persian`, `:197-242`) |
| Mobile viability | YOLO11n crops are edge-friendly | CRNN-lite is edge-*friendlier*; transformer is not |
| Integration | zero change (it *is* the `PlateRead` producer) | must implement the same `PlateReader.read(crop) -> PlateRead` interface (Appendix A), `char_candidates` real or derived |

**Decision rule (binds the roadmap):** keep the character detector through P0–P2 (it feeds the consensus engine directly; and the DTRB weights folder is empty anyway — `weigths/dtrb-recoginzer/`). In Phase 5 (P3), prototype a sequence reader *behind the `PlateReader` interface*, evaluate both on `heldout` + the 200-visit clips, and switch **only if** all three hold: (a) event-level exact match improves ≥ 2 absolute points, (b) `FORCE_AT_CLOSE`/`needs_review` rate does not increase, (c) p95 crop latency stays ≤ the char-detector budget. The consensus engine, event schema, and review UX are *designed reader-agnostic* — that is why `PlateRead` carries ranked candidates and alternates are first-class.

### 6.5 Model registry and change control (small, high-value)

- `weigths/MODELS.md` + `weigths/manifest.json`: one entry per artifact — filename, sha256, task, classes (+ one `classes.json` per model; no second list in code — audit roadmap §P1-7), heldout exclusion attestation, pinned `imgsz`/`conf`, baseline-metrics pointer into `eval/baselines/`.
- Rule: **no model file changes without a `manifest.json` update + `baselines/` re-record + CI advisory latency check.** This single rule prevents the silent class-map drift (`'1'…'27'` vs `CHAR_CLASSNAMES`) the audit found.
- The empty weight dirs (`dtrb-recoginzer/`, `yolov8-detector/`) drop out of the design: no live path references them (`main.py`/`ui.py` are legacy) and the manifest becomes the source of truth for "which weights exist".

---

## 7. API and Flutter Impact (Part 7)

### 7.1 Backend contract change: detections → vehicle events

The rule from §0.2: *backward compatibility by projection*. The new source of truth is `vehicle_events`; everything old keeps working through projections or dual-write (migration steps M3–M5, §3.5).

**New endpoints** (all under the existing router-level guards: `current_user` + role permission; run/start paths keep `require_license()` — same pattern as `routers/detection.py:58-65`):

| Method + path | Purpose | Query / body | Notes |
|---|---|---|---|
| `GET /api/events` | live event list (the new history) | `camera_ids[]`, `from`, `to` (ISO), `search` (plate, normalised server-side), `min_confidence`, `status` (`confirmed/unconfirmed/closed_partial`), `needs_review` (0/1), `watchlist_hit` (0/1), cursor `before_id`, `limit` (default 50, max 500) | ordered `last_seen DESC, id DESC`; cursor pagination (stable under inserts — the current offset paging in `db.get_all_detections` skips/duplicates rows when rows arrive between pages) |
| `GET /api/events/{event_id}` | event detail | — | full row + `char_confidences`, `alternates`, `observations` (the persisted ≤20, ordered by quality), `alerts[]`, `best_frame_url`, `plate_crop_url` |
| `GET /api/events/{event_id}/best-frame.jpg` | operator image | — | serves `best_frame_path` via FastAPI `FileResponse` scoped to `io/events/` (path-traversal-safe lookup by id, never by raw path) |
| `GET /api/events/{event_id}/plate-crop.jpg` | thumbnail | — | serves `best_frame_plate_path` |
| `GET /api/events/stream` | live event feed (SSE) | `camera_ids[]` optional, `since_id` optional | server-sent events `event-created`, `event-updated`, `event-closed`, plus a 30 s `:heartbeat` comment for proxy keep-alive; backed by the in-memory `EventBus` ring, **not** by DB polling |
| `GET /api/events/review` | review queue | cursor `before_id`, `limit` | `needs_review=1` ordered by `last_seen DESC`; used by the Phase-4 review screen |
| `POST /api/events/{event_id}/acknowledge` | alert/event ack (Operator+) | `{"note": "..."}` | sets `acknowledged_by/at` (columns added via `_ensure_column`), writes an audit row (`audit_log`, same discipline as `audit/service.py`); first version of the alert workflow the audit found missing |
| `GET /api/events/export.csv` | event CSV export | same filters as `GET /api/events` | columns: event_id, camera, first/last_seen, plate, persian, confidence, agreement, status, needs_review, make, colour, category, region, alert_count, best_frame_url |
| `GET /api/events/health` | pipeline telemetry | — | per camera: `frames_captured/sampled/inferred/dropped_stale/semaphore`, `last_inference_ms_ema`, `sample_period_s`, `live_tracks`, `queued_events`, `sse_subscribers`, plus process counters (`events_emitted/upgraded`, `fragments_absorbed`, `double_emit_blocked`, `obs_rejected_*`) |
| `GET /api/reports/events/*` | analytics over events | `days`, `camera_ids[]` | `timeline` (events/hour), `dwell` (duration histogram), `agreement` (distribution), `review` (queue size over time) — the event-native siblings of today's `db.get_detections_timeline` (`db.py:263-291`) and siblings |

**Changed (not new) endpoints:**

| Endpoint | Change | Compatibility |
|---|---|---|
| `GET /api/detect/rtsp/{task_id}` (`routers/detection.py:355-383`) | `history` items gain appended fields (`event_id`, `track_id`, `agreement_ratio`, `needs_review`, `status`); new top-level `pipeline` object (counters + `sample_period_s` + `last_inference_ms`); new `since_seq` cursor for incremental history | old fields untouched; old clients ignore appended keys; `RtspTaskStatus.fromJson` (`rtsp_task_model.dart:45-54`) keeps parsing because every field is nullable with defaults |
| `GET /api/detect/rtsp/{task_id}/frame` | response gains `frame_seq` and `annotated_cached_at`; poll semantics unchanged | additive only |
| `GET /api/detect/video/{task_id}` (`routers/detection.py:237-269`) | `plate_log` items unchanged in shape for Phase 1–3 (video path runs the same event pipeline but projects events to log entries); served from the **cached** display JPEG (removes audit H6 re-encode) | additive only |
| `GET /api/stats` → replaced internally | `get_stats()` gains `total_events`, `events_7d`, `needs_review_open`, `avg_agreement`; old keys (`total_detections`, `unique_plates`, …) remain while dual-write is on (M5 flips their computation to the event aggregate) | `StatsModel.fromJson` keeps parsing (`stats_model.dart:18-25`); new keys nullable |
| `POST /api/detect/image` | unchanged in Phase 1 (no tracks in a still image: image path keeps `detect_plates` + per-plate rows). In Phase 3 it also returns an ephemeral `event_id` (`EVT-IMG-*`, never tracked) so the detail screen can render best-frame/char confidences for images too | additive only |
| Watchlist hook | `save_detection`'s hook (`db.py:177-184`) is joined by an **event hook**: on `CONFIRM`/`FORCE_AT_CLOSE` the canonical `plate_number` is matched (`watchlist/matching.py:59-71` unchanged) and `create_alert` stores **both** `detection_id` (dual-write row) and `event_id` | signature unchanged (`matching.py:92-102`) |

**Deleted at M5 (secure by Phase 3):** the unauthenticated legacy surface the audit flagged (`/api/detections*`, `/api/stats` shadow, `/api/config/concurrency`, legacy `/api/cameras*`, `/api/scanner/probe` — `api.py:188-344`, `:521-560`). The Flutter contract below already names the secured replacements; the client must stop calling the legacy paths in Phase 4.

### 7.2 Example payloads (normative shapes)

`GET /api/events?limit=2` →

```json
{
  "data": [
    {
      "event_id": 41207,
      "event_key": "3:25092901:17",
      "camera_id": 3, "camera_name": "Gate-North",
      "source_type": "rtsp", "session_id": 88,
      "first_seen": "2026-09-29T08:14:02.120Z", "last_seen": "2026-09-29T08:14:04.310Z",
      "duration_ms": 2190, "frame_count": 19, "observation_count": 11,
      "plate_number": "12b34567", "plate_norm": "12b34567",
      "plate_persian": "12 ب 345-67",
      "confidence": 0.91, "agreement_ratio": 0.82, "quality_score": 0.77,
      "char_confidences": [0.96, 0.95, 0.72, 0.93, 0.97, 0.94, 0.90, 0.88],
      "alternates": ["12b34587"],
      "plate_valid": 1, "plate_category": "private", "plate_color_scheme": "white",
      "region_code": "67", "region_name": "Tehran", "city": "Tehran",
      "vehicle_type": "car", "vehicle_make": "207", "vehicle_color": "White",
      "status": "confirmed", "needs_review": 0, "id_switch_suspect": 0,
      "alert_count": 0, "best_frame_url": "/api/events/41207/best-frame.jpg"
    }
  ],
  "next_before_id": 41207
}
```

SSE `GET /api/events/stream` →
```
:heartbeat
event: event-created
data: {"event_id":41207,"camera_id":3,"plate_number":"12b34567","confidence":0.91}

event: event-updated
data: {"event_id":41207,"best_frame_url":"/api/events/41207/best-frame.jpg","confidence":0.94}

event: event-closed
data: {"event_id":41207,"status":"confirmed","duration_ms":2190}
```

### 7.3 Flutter: data changes only (no redesign)

Required data-layer changes and the screens they *enable* — not the UI itself.

**New files (mirroring the existing `data/` layering):**

| File | Contents | Later consumers |
|---|---|---|
| `lib/data/models/vehicle_event.dart` | `VehicleEventModel` + `fromJson` for the §7.2 shape; nullable-with-defaults like the existing models (`detection_model.dart:24-34`, `enhanced_rtsp_history_entry.dart:37-54`). `confidence` now means consensus-calibrated (§4.5), not the old blended score — document on the class | events list, detail, ticker, review queue |
| `lib/data/models/event_observation.dart` | `EventObservationModel` (frame_idx, plate_text, char_conf, quality, bbox, agreed flag) | event detail evidence table |
| `lib/data/models/event_stats.dart` | `EventStatsModel` (total_events, events_7d, needs_review_open, avg_agreement, timeline series) — additive to `StatsModel`, which keeps parsing | dashboards |
| `lib/data/repositories/events_repo.dart` | `listEvents({...filters, beforeId})`, `getEvent(id)`, `listReview({...})`, `acknowledge(id, note)`, `exportEventsCsv({...})`, `getHealth()`; cursor paging (`next_before_id`) — **not** the offset pattern of `detections_repo.dart:9-26` | events + detail + review controllers |
| `lib/data/repositories/event_stream_client.dart` | SSE client over the existing Dio singleton (`ApiClient.instance`): GET `/events/stream` with `ResponseType.stream`, line-protocol parsing, auto-reconnect with backoff + `since_id` resume, subscription `Stream<VehicleEventUpdate>` | live events controller |
| `lib/data/controllers/events_controller.dart` | paginated list + filters state (the `_HistoryController` pattern in `history_view.dart:63-115`, debounce included, is the template) | events screen |
| `lib/data/controllers/live_events_controller.dart` | subscribes to the stream; **batches UI updates to ≤2 Hz** (ring buffer + timer, emit once) — this replaces the 100 ms poll rebuild storm (`camera_poll_controller.dart:49`); keeps last N events in memory, updates in place by `event_id` | live ticker / alert banner |
| `lib/data/controllers/event_detail_controller.dart` | one-event fetch + observations; exposes `bestFrameUrl`/`plateCropUrl` with auth headers for `Image.network` (the MJPEG endpoint is secured in Phase 3, so the token-less `Image.memory` fallback path in `camera_live_monitor.dart:372-374` becomes unnecessary) | event detail screen |

**Retired/changed (client):**
- `camera_poll_controller.dart` `/frame` 100 ms loop → **demoted to fallback** (only when SSE *and* MJPEG both fail); `/frame` otherwise becomes a 5 s metadata heartbeat.
- `rtsp_poll_controller.dart` 1 s poll → status/metadata only (task state, pipeline counters); history payload transfer stops once the events screen is primary (meanwhile `?since_seq=N` keeps it small).
- `detections_repo.dart` `/detections` (today the unauthenticated legacy `api.py:193` path) and `stats_repo.dart` `/stats` family → migrate to `/api/events*` and `/api/reports/events/*` by end of Phase 4; `DetectionModel` stays the projection type during migration (§3.6).
- `camera_repo.dart` PATCH `/cameras/{id}` → moves to the secured router route added in Phase 3 (audit risk: today it hits the legacy unauthenticated handler, `api.py:276-286`).
- `enhanced_rtsp_history_entry.dart` / `enhanced_plate_log_entry.dart` keep parsing (backend keeps those fields), so `rtsp_sub_view.dart`, `video_sub_view.dart`, `camera_live_monitor.dart` need **no changes in Phase 1–3**.

**Screens/features this architecture enables (for the later UI phase):**
1. **Live vehicle ticker** replacing the "Live Detections" text lines (`rtsp_sub_view.dart:285-335`): one row per event, updates in place, plate + confidence + agreement + camera, tappable to detail.
2. **Vehicle event detail**: best-frame + plate crop, per-character confidence strip, observation table (frame/text/quality/agreed), alternates, alerts + acknowledge button.
3. **Review queue** (`needs_review=1`: forced-close, weak-char, ID-switch suspects) — the loop that feeds P3 training data.
4. **Per-camera health panel**: FPS sampled/inferred, dropped counters, `sample_period_s`, live tracks, last-event age — from `/api/events/health` instead of guessing from frozen JPEGs.
5. **Watchlist-hit banner with acknowledge**: live alert ticker + ack flow writing audit rows.
6. **Event-based history/analytics**: real vehicle counts, dwell-time and agreement distributions — replacing `unique_plates`-by-text.

---

## 8. Implementation Roadmap (Part 8)

Hard rule for all phases: **no phase may regress the existing test suite** (`tests/`, `flutter_app/test/`, CI `ruff` + `flutter analyze`) and every phase ships with its own property/replay tests green (Appendix D).

### Phase 0 — Scaffolding and measurement (no behaviour change)

| | |
|---|---|
| Goal | Interfaces, config, metrics, and baselines exist before any behaviour is touched |
| Files (new) | `pipeline/__init__.py`, `pipeline/config.py` (Appendix C dataclass + validation), `pipeline/metrics.py` (counters/gauges + `snapshot()`), `pipeline/types.py` (`Box`, `TrackUpdate`, `PlateRead`, `ConsensusResult`, `ScheduleDecision`, `VehicleEvent` — Appendix A), `eval/run_eval.py`, `eval/bench_latency.py`, `eval/metrics.py`, `eval/datasets.py`, `weigths/manifest.json` + `weigths/MODELS.md` skeleton |
| Files (touched) | none on the runtime path; `db.py` untouched |
| Risk | **Low** — additive only |
| Tests | config validation unit tests; metrics counter tests; harness smoke test on 1 image; record `eval/baselines/v1-*.json` with the current 5 models (Part 6.1) |
| Exit gate | `python eval/run_eval.py --split heldout-manifest` runs and prints "dataset missing" instead of crashing; `pytest tests/` fully green unchanged |

### Phase 1 — Minimum change that removes duplicates

| | |
|---|---|
| Goal | One vehicle visit ⇒ exactly one event row; everything else still behaves as today for the operator |
| Files (new) | `pipeline/tracker.py` (ByteTracker), `pipeline/track_manager.py` (lifecycle), `pipeline/consensus.py` (Part 4), `pipeline/ocr_reader.py` (wraps `_assemble_chars` + quality), `pipeline/event_builder.py`, `pipeline/sinks.py` (DbWriter + EventBus in-memory), `pipeline/worker.py` (`PipelineWorker`), `pipeline/frame_scheduler.py` (modulo + budget v1) |
| Files (touched) | `video_processor.py` (RTSP `_ml_worker` body → `PipelineWorker`; `VideoProcessor._run` gets the same worker in offline mode; reader/display/JPEG left structurally intact); `alpr_engine.py` (**additive**: `detect_vehicles()`, `detect_plates_roi()`, `read_plate_crop()` returning evidence objects — `run()` and `_assemble_chars` untouched); `db.py` (M1+M2 tables/columns only); `schemas.py` (event view models); `routers/detection.py` (append `event_id/track_id/agreement_ratio/needs_review/status` to history entries; add `pipeline` object to `/status`) |
| Risk | **High** — threading + behaviour change in the hot path. De-risked by: flag `PIPELINE_MODE` (default `events` for RTSP, `legacy` for video/image until proven), dual-write (legacy rows continue), pure consensus (unit-tested), and the replay tests below |
| Tests | unit: tracker association (synthetic box streams), lifecycle transitions (scripted), consensus pseudocode cases from §4.8 as golden tests; property: *N same-plate observations → 1 event*; *K distinct plates × M visits → K events*; *identical evidence ⇒ identical ConsensusResult*; replay: `tests/test_pipeline_replay_events.py` driving `PipelineWorker` on 3 frozen visits from `eval/visits.jsonl` (1 car, 2 cars, distant plate), asserting row counts, `agreement_ratio`, `char_confidences`; integration: existing `test_realtime_integration.py`, `test_video_processor_integration.py`, `test_detection_pipeline_integration.py` must pass unmodified; flutter: `models_test.dart`-style parsing test for the appended fields |
| Exit gate | duplicate KPI defined and measured: `events_per_visit == 1.0` on the replay set and on one live hour, with the old 60 s cooldown code path deleted (flag removed after proof) |

### Phase 2 — Performance optimization

| | |
|---|---|
| Goal | Hit the §5 targets: ≤35 ms average inferred frame, ≤3 model calls, 4 cameras per host, display JPEG bounded |
| Files (touched) | `pipeline/frame_scheduler.py` (time-budget rule §5.1, `confirmed_ocr_stride`, tiers §5.2); `pipeline/detectors.py` + `alpr_engine.py` (`imgsz` pins §5.3, ROI gating §5.4, 4-class call path); `pipeline/event_builder.py` (event-level attributes §5.5 step 1); `pipeline/worker.py` (semaphore §5.7, caps §5.8); `video_processor.py` display loop (subscriber gating + adaptive budget + cached JPEG §5.9); `routers/detection.py` (`video_status` serves cached JPEG); `db.py` (persistent `DbWriter` connection — must pass the existing DB/retention tests) |
| Risk | **Medium** — every change is behind a config knob with the old behaviour as default; the danger is silent accuracy loss from `imgsz`/ROI changes, which is why Part 6's baselines exist. Resolution changes land **only** against `eval/baselines` A/B comparison |
| Tests | scheduler property tests: *never exceeds `max_inferences_per_frame`*, *frames processed in capture order*, *sample rate converges within ±20 % of budget on a synthetic load*; latency regression: `bench_latency.py` vs `baselines/` with advisory CI gate; correctness invariance: *same clip at different skip settings yields the same events* (plate + status) within the agreed tolerance; memory: worker RSS flat over a 1 h soak test; flutter: parsing tests for `frame_seq`/`annotated_cached_at` |
| Exit gate | measured numbers table in the PR (audit's Table 4.1 reproduced with the new pipeline) showing per-frame ≤35 ms avg and per-event ≤8 OCR passes on the standard 5-minute 1080p reference clip; all 4-camera soak counters (`frames_dropped_*`) visible on `/api/events/health` |

### Phase 3 — Database / API migration

| | |
|---|---|
| Goal | Events durable, queryable, retained, and secured; legacy surface removed |
| Files (new) | `routers/events.py` (§7.1 endpoints + SSE), `scripts/backfill_events.py` (opt-in, §3.7), `pipeline/frame_store.py` (best-frame files under `io/events/`), event-retention pruning (extend `retention/service.py` + `retention/policy.py` with `prune_vehicle_events()` / `prune_observations()` / file sweep) |
| Files (touched) | `db.py` (event queries: `list_vehicle_events`, `get_vehicle_event`, `get_event_observations`, `get_event_alerts`, `list_review_queue`, `acknowledge_event`, event-aware `get_stats`; keep `detections` projections); `schemas.py` (event envelopes; `ErrorCode` untouched); `routers/retention.py` (observation horizon + event-image retention fields); `api.py` (**deletion wave**: legacy `/api/detections*`, `/api/stats` shadow, `/api/config/concurrency`, legacy `/api/cameras*`, `/api/scanner/probe` — each replaced by a secured router already covered by tests); `watchlist/matching.py` untouched (hook gains event id by caller convention, signature kept) |
| Risk | **High** — data migration + endpoint deletion. De-risked by additive-first M1–M4 (§3.5), opt-in reversible backfill, projections verified by retained frontend tests, and rehearsal on a **copy** of `database/plpr.db` |
| Tests | migration: `init_db` idempotency on existing DB copies, `_ensure_column` no-op, backfill idempotency (run twice ⇒ same rows) and reversibility (`event_key LIKE 'backfill:%'` deletion restores state); API: auth/permission on every new endpoint (the `test_auth_router_*` + `*_property` discipline), cursor-pagination stability under concurrent inserts, SSE test (connect, emit 3 events, assert order + heartbeat); retention: `test_retention_*` siblings for events/observations/files; alerts: `test_detection_watchlist_hook.py` + `test_alert_ordering_property.py` against the event hook |
| Exit gate | `/api/events*` guarded + client-tested; legacy unauthenticated endpoints gone from served routes (`/openapi.json` reviewed in the PR); one documented DB copy migrated with zero errors and a rollback note |

### Phase 4 — Flutter adaptation

| | |
|---|---|
| Goal | Client consumes events; legacy polling retired; data wired for the new screens (their *design* is the later UI phase) |
| Files (new) | `lib/data/models/vehicle_event.dart`, `event_observation.dart`, `event_stats.dart`; `lib/data/repositories/events_repo.dart`, `event_stream_client.dart`; `lib/data/controllers/events_controller.dart`, `live_events_controller.dart`, `event_detail_controller.dart`; route entries in `lib/app/router.dart` for `/events`, `/events/:id`, `/review` (destinations appended, shell untouched) |
| Files (touched) | `camera_poll_controller.dart` (fallback only), `rtsp_poll_controller.dart` + `video_task_controller.dart` (status-only), `detections_repo.dart` + `stats_repo.dart` (endpoint swap at phase end), `camera_repo.dart` (PATCH → secured route), `camera_live_monitor.dart` (`Image.network` with auth headers; base64 fallback removed once SSE is primary), minimal wiring in `detection_view.dart`/`rtsp_sub_view.dart` (event ticker model in place of the "Live Detections" line list — components reused, no restyle) |
| Risk | **Medium** — pure client code, no data-loss path; risk is stream reconnect storms and batching regressions. Pollers stay as automatic fallback, so a broken SSE degrades to today's behaviour |
| Tests | parsing tests for the three models incl. unknown/missing fields (the `test/data/models/models_test.dart` pattern); controller tests with fake repos (5 stream events ⇒ 1 batched state; reconnect ⇒ resume with `since_id`); widget tests: events list renders, detail shows char-confidence strip from fixture JSON, review screen filters `needs_review`; routing tests updated (`test/app/routing_test.dart`); `flutter analyze` clean |
| Exit gate | 100 ms polling code deleted (not just unused); `flutter test` + `flutter analyze` green; one recording of a live camera showing an event in the ticker ≤2 s after the vehicle and *not* duplicating on a 60 s linger test |

### Phase 5 — Advanced AI features

| | |
|---|---|
| Goal | The AI decision layer and reader fork from audit roadmap P3, gated by the harness |
| Scope | (a) **Decision-layer classifier** on per-event features (agreement, char confidences, quality, area, aspect, dwell, time, camera) → `accept/reject/needs-review` + calibrated confidence; trained **only** on `calibration` + review-queue labels, evaluated on `heldout`. (b) **Sequence-reader prototype** behind `PlateReader` (§6.4's three-condition rule). (c) **Event-level analytics** (re-entry, dwell, impossible-travel) reusing `alerts`/`audit`. (d) **Edge-export prototype** (ONNX for the two ResNets first) behind the same interfaces. (e) **Active-learning loop**: review-queue corrections flow into `train_pool`. |
| Files (new) | `pipeline/decision.py`, `eval/calibrate.py`, `eval/compare_readers.py`, `models/` (training code only — never served directly; served weights still go through `weigths/manifest.json`) |
| Risk | **Medium-High scientifically, Low operationally** — everything new runs in *shadow mode* (scores recorded, never acted on) until it beats the baseline on `heldout` per §6.4 |
| Tests | offline eval scripts with frozen seeds; threshold freeze files committed (no magic numbers in code); shadow-vs-live divergence counters on `/api/events/health` (`decision_shadow_agree/disagree`); A/B event sets reproducible byte-for-byte from committed seeds |
| Exit gate | decision layer beats rule-based consensus on `heldout` with a published false-accept/false-reject trade-off; sequence-reader decision recorded (switch or documented keep); `bench_latency.py` budgets unregressed |

Sequencing note: Phases 0–2 may overlap dataset collection (Part 6.3 starts immediately — it is the long pole). Phase 3 must not start before Phase 1's exit gate (event identity proven), because the schema freezes what the pipeline emits. Phase 4 starts only once Phase 3 endpoints exist. Phase 5 runs in shadow from Phase 2 onward.

---

## Appendix A — Interfaces (signatures)

Implement these exact shapes (field names are contractual — API, DB, and Flutter already agree on them in §7.2).

```python
# pipeline/types.py
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Box:                       # normalized 0..1 coords (Part 2.5: one config, any resolution)
    x1: float; y1: float; x2: float; y2: float
    conf: float; cls: int

@dataclass(frozen=True)
class TrackUpdate:
    track_key: str               # f"{camera_id}:{session_epoch}:{local_id}"
    kind: str                    # "vehicle" | "plate"
    box: Box
    state: str                   # NEW | TRACKED | LOST
    hits: int; age: int; time_since_update: int

@dataclass
class PlateRead:                 # immutable once constructed (frozen by builders)
    frame_idx: int; ts: str
    text: str                    # canonical latin, e.g. "12b34567"
    char_candidates: list[list[tuple[str, float]]]   # per position, top-K by conf
    char_count: int
    plate_det_conf: float; plate_area_px: int; aspect_ratio: float
    sharpness: float; brightness_ok: bool
    usable: bool; weight: float
    bbox: Box; vehicle_bbox: Box | None

@dataclass(frozen=True)
class ConsensusResult:
    track_key: str; plate: str; char_conf: list[float]
    agreement_ratio: float; confidence: float; posterior_min: float
    length_mode_weight: float; best: PlateRead | None

@dataclass(frozen=True)
class ScheduleDecision:
    sample: bool; tier: str      # "full" | "track_only" | "skip"
    reason: str                  # counted by metrics, e.g. "budget", "track_pressure", "idle"

@dataclass
class VehicleEvent:              # mirrors vehicle_events (§3.2); to_row()/from_row() in sinks
    event_key: str; camera_id: int | None; camera_name: str | None
    session_id: int | None; source_type: str; source_file: str | None
    track_id: str; track_kind: str
    first_seen: str; last_seen: str; duration_ms: int
    frame_count: int; observation_count: int
    plate_number: str; plate_norm: str; plate_persian: str | None
    confidence: float; agreement_ratio: float; quality_score: float
    char_confidences: list[float]; alternates: list[str]
    plate_valid: bool; plate_category: str | None; plate_color_scheme: str | None
    region_code: str | None; region_name: str | None; city: str | None
    vehicle_type: str | None; vehicle_make: str | None; vehicle_color: str | None
    attribute_confidence: float | None; attribute_computed_at: str | None
    best_frame_path: str | None; best_frame_plate_path: str | None
    best_frame_frame_idx: int | None
    status: str; needs_review: bool; id_switch_suspect: bool
    fragment_of_event_id: int | None; alert_count: int
```

```python
# pipeline contract surface (methods, no implementations shown)
class ByteTracker:                      # pipeline/tracker.py
    def __init__(self, cfg: TrackerConfig): ...
    def update(self, boxes: list[Box], ts: float) -> list[TrackUpdate]: ...

class TrackManager:                     # pipeline/track_manager.py
    def apply_updates(self, updates: list[TrackUpdate], now: float) -> list[EmissionRequest]: ...
    def attach_read(self, track_key: str, read: PlateRead, now: float) -> EmissionRequest | None: ...

class PlateReader:                      # pipeline/ocr_reader.py  (the P3 fork seam, §6.4)
    def read(self, crop_bgr, precheck: dict) -> PlateRead: ...   # char detector today
    # class SequencePlateReader(PlateReader): ...                # CRNN/DTRB/ParseQ later

class EventBuilder:                     # pipeline/event_builder.py
    def on_consensus(self, track_key: str, res: ConsensusResult, action) -> VehicleEvent | EventUpdate | None: ...
    def close_track(self, track_key: str, reason: str) -> VehicleEvent | EventUpdate | None: ...

class FrameScheduler:                   # pipeline/frame_scheduler.py
    def should_sample(self, *, frame_idx: int, now: float, queue_depth: int,
                      live_unconfirmed: int) -> ScheduleDecision: ...

class PipelineWorker:                   # pipeline/worker.py
    def run_forever(self) -> None: ...  # RTSP: wall-clock budget
    def run_file(self, cap) -> dict: ...# video: frame-count budget, same stages
```

Rules for implementers: `consensus.py` and `metrics.py` are importable **without** `torch`/`cv2` (pure) — the test suite must run `pytest tests/test_consensus_*` in the CI lint job with no GPU/CPU-heavy deps. `worker.py`, `sinks.py`, `track_manager.py` own all locks; nothing else locks.

## Appendix B — SQL DDL and migration

The authoritative DDL lives in `db.init_db()` (Phase 3); this appendix is the reviewable text of it.

```sql
CREATE TABLE IF NOT EXISTS vehicle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    camera_id INTEGER NULL REFERENCES cameras(id),
    camera_name TEXT NULL,
    session_id INTEGER NULL REFERENCES sessions(id),
    source_type TEXT NOT NULL,
    source_file TEXT NULL,
    track_id TEXT NOT NULL,
    track_kind TEXT NOT NULL DEFAULT 'vehicle',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    frame_count INTEGER NOT NULL DEFAULT 0,
    observation_count INTEGER NOT NULL DEFAULT 0,
    plate_number TEXT NOT NULL,
    plate_norm TEXT NOT NULL,
    plate_persian TEXT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    agreement_ratio REAL NOT NULL DEFAULT 0,
    quality_score REAL NOT NULL DEFAULT 0,
    char_confidences TEXT NULL,
    alternates TEXT NULL,
    plate_valid INTEGER NOT NULL DEFAULT 0,
    plate_category TEXT NULL,
    plate_color_scheme TEXT NULL,
    region_code TEXT NULL,
    region_name TEXT NULL,
    city TEXT NULL,
    vehicle_type TEXT NULL,
    vehicle_make TEXT NULL,
    vehicle_color TEXT NULL,
    attribute_confidence REAL NULL,
    attribute_computed_at TEXT NULL,
    best_frame_path TEXT NULL,
    best_frame_plate_path TEXT NULL,
    best_frame_frame_idx INTEGER NULL,
    status TEXT NOT NULL DEFAULT 'confirmed',
    needs_review INTEGER NOT NULL DEFAULT 0,
    id_switch_suspect INTEGER NOT NULL DEFAULT 0,
    fragment_of_event_id INTEGER NULL REFERENCES vehicle_events(id),
    alert_count INTEGER NOT NULL DEFAULT 0,
    acknowledged_by TEXT NULL,
    acknowledged_at TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plate_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NULL REFERENCES vehicle_events(id),
    event_key TEXT NOT NULL,
    camera_id INTEGER NULL,
    track_id TEXT NOT NULL,
    frame_idx INTEGER NOT NULL,
    ts TEXT NOT NULL,
    plate_text TEXT NOT NULL,
    plate_det_conf REAL NOT NULL,
    char_conf REAL NOT NULL,
    char_count INTEGER NOT NULL,
    quality REAL NOT NULL,
    sharpness REAL NOT NULL,
    plate_area_px INTEGER NOT NULL,
    aspect_ratio REAL NOT NULL,
    bbox TEXT NOT NULL,
    vehicle_bbox TEXT NULL,
    agreed_with_consensus INTEGER NULL,
    created_at TEXT NOT NULL
);
-- indexes: §3.2 / §3.3 (same statements, all IF NOT EXISTS)
```

Migration order in code: `CREATE TABLE`s → `_ensure_column` calls for §3.4 (all inside `init_db`, which is already called at startup — `api.py:101`, and tested by `tests/test_*persistence*`) → runtime flag `PIPELINE_MODE`. Event upsert statement:

```sql
INSERT INTO vehicle_events (event_key, camera_id, camera_name, session_id, source_type,
    source_file, track_id, track_kind, first_seen, last_seen, duration_ms, frame_count,
    observation_count, plate_number, plate_norm, plate_persian, confidence, agreement_ratio,
    quality_score, char_confidences, alternates, plate_valid, plate_category,
    plate_color_scheme, region_code, region_name, city, vehicle_type, vehicle_make,
    vehicle_color, attribute_confidence, attribute_computed_at, best_frame_path,
    best_frame_plate_path, best_frame_frame_idx, status, needs_review, id_switch_suspect,
    fragment_of_event_id, alert_count, created_at, updated_at)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(event_key) DO UPDATE SET
    last_seen=excluded.last_seen, duration_ms=excluded.duration_ms,
    frame_count=excluded.frame_count, observation_count=excluded.observation_count,
    plate_number=excluded.plate_number, plate_norm=excluded.plate_norm,
    plate_persian=excluded.plate_persian, confidence=excluded.confidence,
    agreement_ratio=excluded.agreement_ratio, quality_score=excluded.quality_score,
    char_confidences=excluded.char_confidences, alternates=excluded.alternates,
    plate_valid=excluded.plate_valid, plate_category=excluded.plate_category,
    plate_color_scheme=excluded.plate_color_scheme, region_code=excluded.region_code,
    region_name=excluded.region_name, city=excluded.city,
    vehicle_type=excluded.vehicle_type, vehicle_make=excluded.vehicle_make,
    vehicle_color=excluded.vehicle_color, attribute_confidence=excluded.attribute_confidence,
    attribute_computed_at=excluded.attribute_computed_at,
    best_frame_path=excluded.best_frame_path,
    best_frame_plate_path=excluded.best_frame_plate_path,
    best_frame_frame_idx=excluded.best_frame_frame_idx, status=excluded.status,
    needs_review=excluded.needs_review, id_switch_suspect=excluded.id_switch_suspect,
    fragment_of_event_id=excluded.fragment_of_event_id,
    alert_count=excluded.alert_count, updated_at=excluded.updated_at;
```

## Appendix C — Configuration knobs

One dataclass, `pipeline/config.py::PipelineConfig`, validated at import and exposed read-only via `/api/events/health` (values, not secrets). Every default below appears in the part that justifies it.

| Knob | Default | Governs |
|---|---|---|
| `pipeline_mode` | `events` (RTSP) / `legacy` (image+video until Phase 1 gate) | M3 flag (§3.5) |
| `dual_write_detections` | `1` until M5 | §3.5 |
| `frame_queue_depth` | `2` | §1.3(2), §5.7 |
| `max_concurrent_inference` | `2` | §1.3(3), §5.7 |
| `max_video_tasks` | `1` | §5.7 |
| `max_inferences_per_frame` | `4` | §5.2 |
| `inference_budget_ms` | `120` | scheduler time budget (§5.1) |
| `imgsz_vehicle` / `imgsz_plate_roi` / `imgsz_plate_full` / `imgsz_char` | `416` / `512` / `640` / `256` | §5.3 |
| `conf_vehicle` / `conf_plate` / `conf_char` | `0.6` / `0.6` / `0.3` (today's values — `alpr_engine.py:47-49`) | unchanged gates |
| `classes_vehicle` | `[2,3,5,7]` (audit §H1 note: pass to the YOLO call, not post-filter) | §5.4 |
| `roi_pad` | `0.12` | §5.4 |
| `plate_scan_period` / `confirmed_scan_period` | `3` / `15` (sampled frames) | §5.2 |
| `confirmed_ocr_stride` | `5` | §§1.6, 4.6, 5.2 |
| `track_high_thresh` / `track_low_thresh` / `new_track_thresh` | `0.6` / `0.3` / `0.5` | §2.5 |
| `new_track_min_hits` | `2` | §2.4 |
| `track_expiry_s` / `track_min_lifetime_s` / `max_live_tracks` | `2.0` / `0.4` / `32` | §§2.4–2.5 |
| `max_gap_tracked_ms` | `250` | §5.1 |
| `plate_gate_conf` / `min_plate_width_px` / `brightness_lo` / `brightness_hi` / `min_sharpness` | `0.5` / `48` / `40` / `220` / lenient (§4.3) | §4.3 |
| `SHARP_REF` / `AREA_REF` / `EXPECT_ASPECT` | `300.0` / `120*40` / `4.6` | §4.4 |
| `min_vote_conf` / `min_obs_weight` | `0.2` / `0.02` | §4.2 |
| `confirm_min_obs` / `confirm_min_agreement` / `confirm_min_length_weight` | `3` / `0.6` / `0.6` | §4.6 |
| `force_emit_posterior` | `0.5` | §§2.4, 4.6 |
| `max_upgrades` / `upgrade_quality_gain` / `review_on_weak_char` | `1` / `1.15` / `1` | §§1.6, 4.6–4.7 |
| `max_track_obs` / `max_persisted_obs` | `30` / `20` | §§5.8, 3.3 |
| `reentry_cooldown_s` / `fragment_window_s` / `switch_window_s` | `15` / `3` / `5` | §2.5, §2.6 |
| `plate_track_min_lifetime_s` / `plate_track_min_obs` | `0.6` / `3` | §2.3 |
| `enable_attributes` | `1` | §5.5 |
| `display_fps_floor` / `display_max_width` / `display_quality` / `display_hd` | `12` / `720` / `60` / `0` | §5.9 |
| `history_limit` | `50` | §5.8 |
| `observation_retention_days` / `event_image_retention_days` | `30` / `90` (proposed; events follow `retention_days`) | §3.5 M6 |
| `semaphore_timeout_s` / `semaphore_stall_frames` | `3` / `50` | §5.7 |
| `scene_reset_tracks` | `5` | §2.6 |

Validation rules (in `PipelineConfig.__post_init__`, unit-tested): `0 ≤ conf ≤ 1`, `min < max` pairs, `imgsz % 32 == 0`, `stride ≥ 1`, expiry > min-lifetime, all seconds > 0, `max_* ≥ 1`. Unknown keys in the JSON config are **rejected**, not ignored (fail-fast beats silent drift).

## Appendix D — Test matrix and definition of done

### D.1 New tests per phase (names are contractual file names)

| File | Kind | Asserts | Phase |
|---|---|---|---|
| `tests/test_pipeline_config.py` | unit | defaults load; every invalid knob rejected; unknown key rejected | 0 |
| `tests/test_pipeline_metrics.py` | unit | counters increment; `snapshot()` shape matches `/api/events/health` contract | 0 |
| `tests/test_tracker_bytetrack.py` | unit + property | synthetic streams: straight line (1 id), crossing pair (2 ids), 1 s occlusion gap (1 id preserved), low-score boxes kept (ids stable where SORT-equivalent would switch); determinism: same input ⇒ same ids | 1 |
| `tests/test_track_lifecycle.py` | unit (scripted transitions) | every row of the §2.4 table, incl. LOST→resume and any→EXPIRED flush | 1 |
| `tests/test_consensus_golden.py` | golden (from §4.8) | worked examples incl. the audit's `12ب34587/12ب34567` triple → `12ب34567`, confidence ≈ 0.9, agreement ∈ (0,1) | 1 |
| `tests/test_consensus_property.py` | property (Hypothesis — the repo already uses it: `tests/test_*_property.py`) | majority rule; confidence monotonicity under identical appends; confirmed consensus immune to empty/partial appends; determinism | 1 |
| `tests/test_pipeline_replay_events.py` | replay (frozen fixtures) | 1-car / 2-car / distant-plate visits → exact event counts, plates, `agreement_ratio`, `char_confidences`; `events_per_visit == 1.0` | 1 |
| `tests/test_events_api.py` | API + auth | 401/403 matrix on every §7.1 endpoint (pattern of `tests/test_auth_router_*`); cursor stability under inserts; SSE order + heartbeat | 3 |
| `tests/test_events_migration.py` | migration | `init_db` idempotency on existing DB copies; `_ensure_column` no-op; backfill idempotency + reversibility | 3 |
| `tests/test_events_retention.py` | retention | events/observations/file sweeps respect horizons (pattern of `tests/test_retention_*`) | 3 |
| `tests/test_scheduler_property.py` | property | never exceeds `max_inferences_per_frame`; capture order preserved; rate converges ±20 % on synthetic load | 2 |
| `tests/test_frame_store.py` | unit | best-frame paths unique per event; traversal-safe (no `..` escapes); retention sweep deletes orphans | 3 |
| `flutter_app/test/data/events_parsing_test.dart` | parsing | fixture JSON (§7.2) ⇒ models; unknown fields ignored; missing fields default | 4 |
| `flutter_app/test/features/events_widget_test.dart` | widget | list + detail + review render from fixtures; char-confidence strip present | 4 |

Existing suites that **must stay green** (call them out in every PR): `tests/test_realtime_integration.py`, `test_video_processor_integration.py`, `test_detection_pipeline_integration.py`, `test_skip_frame_range_property.py` (updated only when the scheduler supersedes it — with a deprecation note, not silent deletion), `test_plate_validator*.py`, the watchlist/alert/retention/auth families, plus `flutter_app/test` in full.

### D.2 Definition of done (applies to every phase)

1. All new tests above for the phase pass; the full existing suites pass; `ruff check`, `ruff format --check`, `flutter analyze` clean (CI stages already exist — `.github/workflows/ci.yml`).
2. The phase's **exit gate** (Part 8) is demonstrated with numbers/artifacts in the PR (replay logs, latency table, migrated-DB copy report, screen recording).
3. `/api/events/health` exposes the phase's new counters; the PR includes a screenshot-equivalent (JSON excerpt) proving they move.
4. No new magic numbers in code: every threshold lives in `PipelineConfig` with the section reference in a comment.
5. Docs updated in-place: the touched module's docstring + this design doc's deviation log (see below) if reality forced a change.
6. Rollback path stated and tested where the phase touches data or deletes endpoints (flag flip, dual-write re-enable, `backfill:%` deletion).

**Deviation log (maintain at the bottom of this document during implementation):** date, section, what changed, why, who approved. A design that cannot absorb measured reality is a wish list.

## Appendix E — Observability and rollout

### E.1 Counter families (names are contractual)

| Family | Counters | Read from |
|---|---|---|
| frames | `captured`, `sampled`, `skipped_schedule`, `skipped_budget`, `dropped_stale`, `dropped_semaphore` | per camera, `/api/events/health` |
| inference | `vehicle_calls`, `plate_roi_calls`, `plate_full_calls`, `ocr_calls`, `attr_make_calls`, `attr_color_calls`, `capped_by_max_per_frame`, `last_inference_ms_ema`, `sample_period_s` | per camera |
| tracker | `tracks_created`, `tracks_rejected_new`, `tracks_merged_plate`, `tracks_forced_expiry`, `occlusion_recoveries`, `tracker_resets`, `live_tracks` (gauge) | per camera |
| consensus | `obs_usable`, `obs_rejected_quality/area/brightness`, `obs_dropped_cap`, `events_emitted`, `events_upgraded`, `events_unconfirmed`, `fragments_absorbed`, `double_emit_blocked`, `id_switch_suspect` | per camera + process totals |
| sinks | `db_write_ms_ema`, `db_queue_depth` (gauge), `db_dropped`, `frame_store_queue_depth` (gauge), `frame_store_dropped`, `sse_subscribers` (gauge), `sse_events_sent` | process-wide |
| alerts | `watchlist_matches`, `alert_acknowledged` | process-wide |

Sampling rule: counters are `int`, gauges are last-value floats, EMAs use α=0.2. `snapshot()` returns plain dicts/JSON — no Prometheus dependency required; a `/metrics` text exposition can be added later without changing the names.

### E.2 Rollout checklist (production order)

1. Deploy with `PIPELINE_MODE=legacy` everywhere + new tables present (M1–M2). Verify: nothing changes, health shows the new counters at zero.
2. Enable `events` for **one** RTSP camera; run the 60 s linger test + `events_per_visit` check; compare dual-write rows (`detections.event_id` linkage).
3. Enable `events` fleet-wide for RTSP; keep image/video on `legacy` until their replay tests land.
4. Land Phase 2 knobs one at a time (scheduler → `imgsz`/ROI → attribute gating → JPEG budget), each with a latency-table PR.
5. Ship `/api/events*` + secure/delete legacy surface (Phase 3); migrate the client (Phase 4); only then flip `DUAL_WRITE_DETECTIONS=0`.
6. Start the P3 shadow scorer. Promote nothing until its divergence report and `heldout` numbers are reviewed.

### E.3 What is deliberately *not* in this design (and why)

- **Cross-camera re-identification.** Two cameras, two events, linked by plate text in analytics. True cross-camera ReID needs embeddings (the cost the tracker choice explicitly avoided) and solves no reported problem.
- **A second inference process/service.** The threaded in-process architecture is kept; the file boundaries (`pipeline/*`), pure functions, and interfaces are drawn so a later split needs no algorithm rewrite.
- **WebRTC/HLS.** MJPEG + cached JPEG + SSE covers the stated clients; the design isolates the transport (`FrameStore`, `EventBus`, subscriber registry) so the stream protocol can change without touching the pipeline.
- **Real-time retraining / online learning.** P3's loop is batched and human-reviewed (review queue → `train_pool` → offline training → manifest-gated deployment), never online.

## Appendix F — Risks and mitigations

| Risk | Likelihood | Blast radius | Mitigation in this design |
|---|---|---|---|
| Tracker frag at long range (plates < 48 px) | Medium | missed distant plates | plate-only tracks (§2.3) + lenient early gate (§4.3) + quality metrics that prove it (`obs_rejected_area`) |
| `imgsz`/ROI change silently loses small plates | Medium | accuracy regression | harness baselines + advisory CI gate (§6.1); resolution changes only via A/B PRs (Phase 2 risk row) |
| SQLite contention from the writer thread | Low–Medium | event lag under burst | single writer + batched upserts (§5.6); queue-depth gauges + drop policy; write path tested by existing DB/retention tests in Phase 2 |
| SSE reconnect storms from many clients | Medium | UI lag, log spam | ≤2 Hz client batching (§7.3), `since_id` resume, heartbeat; `/frame` and pollers remain as automatic fallback |
| ID switches counted as two visits | Medium | inflated vehicle counts | `reentry_cooldown_s` + fragmentation absorption (§2.5) + `id_switch_suspect` review queue (§2.6) |
| Legacy endpoint deletion breaks the React client (`frontend/`) | High if forgotten | second client 404s | Phase 3 enumerates the deletion wave (§7.1); `frontend/src/api.ts` and `flutter_app` call sites are both in the migration checklist; `/openapi.json` reviewed in the PR |
| Scope creep into UI redesign / model retraining | High | design never lands | explicit non-goals (§0.3); Phase 1 is provable without touching a widget or a weight |
| Persian-script edge cases (multi-char tokens, Free Zone) | Medium | wrong plates on special formats | validator untouched as the last gate; length-mode design (§4.5); Free Zone represented in `heldout` + hard set (§6.3) |

---

### Deviation log

| Date | Section | Change | Why | Approved by |
|---|---|---|---|---|
| — | — | *(no deviations yet — design phase)* | — | — |

---

*End of design. No code was modified: only this file (`D:\alpr\ALPR_ARCHITECTURE_DESIGN.md`) was created. Implementation may begin at Phase 0; nothing before the exit gates is production.*

