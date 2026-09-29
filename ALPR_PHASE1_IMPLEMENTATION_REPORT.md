# Phase 1 Implementation Report — Tracking, Consensus & Single Vehicle Events

**Project:** `D:\alpr`
**Phase:** 1 of 5 — *Event pipeline integration behind an explicit feature flag* (`ALPR_ARCHITECTURE_DESIGN.md` §8, Phase 1 row)
**Date:** 2026-09-29
**Base commit:** `3f16f270a8abbaf2f30d017693d5a72a1dc3bd65` (branch `main`)
**Commit / push:** **none** — everything below is uncommitted working tree.

---

## 1. Initial Git state (recorded before any Phase 1 edit)

```
M   database/plpr.db                      # Phase 0 report §1.2: pre-existing-test side effect
??  .freebuff/  ALPR_ARCHITECTURE_DESIGN.md  ALPR_AUDIT_REPORT.md
??  ALPR_PHASE0_BASELINE.md  ALPR_PHASE0_IMPLEMENTATION_REPORT.md
??  eval/  pipeline/  tests/test_consensus_*.py  tests/test_pipeline_*.py
??  tests/test_track_*.py  weigths/MODELS.md  weigths/manifest.json
```

`database/plpr.db` was restored via `git checkout -- database/plpr.db` — the
Phase 0 report explicitly documents the modification as a test-suite side effect
(same 294 912-byte size, binary churn from `init_db()` writes), so restoration
could not destroy user data. The file was restored again after the Phase 1 full
test run for the same reason.

## 2. Files changed and why

### 2.1 Modified (tracked) files — minimal, additive only

| File | Change | Why |
|---|---|---|
| `alpr_engine.py` | `AlprResult` gains 3 defaulted fields (`plate_det_conf`, `char_conf`, `vehicle_boxes`); `run()` populates them from data it already computes | The event pipeline needs the raw plate-detector confidence, mean char confidence, and vehicle boxes for track association. No new inference, no interface change: legacy callers see identical behaviour. |
| `db.py` | Minimal M1/M2 migration: `vehicle_events` table (UNIQUE `event_key`) + 2 indexes + `detections.event_key` nullable column (via existing `_ensure_column`); new `upsert_vehicle_event()` and `get_vehicle_event_stats()` | The UNIQUE constraint is the **durable idempotency boundary** (task §6): repeated finalization of the same track — across threads and process restarts — can never create a second row. |
| `video_processor.py` | `RTSPStreamProcessor` / `VideoProcessor` optionally construct an `EventPipeline` (flag-gated); feed it after each `detect_plates()` call in the **same** inference loop; flush on `stop()` / end-of-video | Actual integration point (task §4): no second inference loop, no new thread. When the flag is off the object is never constructed and every legacy line is byte-identical. |
| `camera_manager.py` | Pass `camera_id` / `camera_name` into `RTSPStreamProcessor` | Track keys and persisted events are camera-scoped (§2.3, §2.5). |
| `routers/detection.py` | `GET /api/detect/rtsp/{task_id}` gains one additive `pipeline` key (nullable metrics dict) | Observability (task §8); old clients ignore unknown keys. |

### 2.2 New files

| File | Purpose |
|---|---|
| `pipeline/integration.py` | `EventPipeline`: the §1.1 wiring for one source — ByteTracker (vehicle + plate-kind) → TrackManager lifecycle → containment-first observation attachment → pure consensus → §4.6 stopping rules → event build → durable upsert. One instance per processor, never shared (task §4 isolation requirement). |
| `tests/test_event_pipeline_integration.py` | 12 tests: one-visit-one-event, idempotent re-finalization, OCR correction, later genuine visit, camera isolation, key non-collision, rejection policy, low-conf rejection, durable upsert (restart, cross-camera), migration idempotency. |
| `tests/test_phase1_flag_wiring.py` | 8 tests: legacy default (RTSP+video), opt-in, per-source override, invalid flag fail-safe, wiring-error fail-safe, disable-restores-legacy, status-shape additive-only. |
| `eval/baselines/phase1-latency.json` | Generated Phase 1 latency record (same harness/flags as Phase 0 baseline). |
| This report + `ALPR_PHASE1_TEST_REPORT.md` + `ALPR_PHASE1_BENCHMARK.md` | Deliverables (task §13). |

**Not touched:** Flutter (`flutter_app/**`, zero Dart changes), models/weights,
`plate_validator.py` / `plate_metadata.py` / `plate_reference.py` / `plates.json`
contracts, auth, the image endpoint's validation logic, legacy dedup path
behaviour when the flag is off.

## 3. Actual execution path integrated

The integration rides the **existing** inference loops — it creates no second
loop and no new thread:

```
RTSP:  RTSPStreamProcessor._ml_worker (existing thread)
         └─ detect_plates(frame, engine)            [unchanged AlprEngine.run()]
              └─ if flag on: EventPipeline.process_results(frame_idx, w, h, alpr_results)
Video: VideoProcessor._run (existing thread)
         └─ same hook, keyed by frame_idx, flag ALPR_PIPELINE_VIDEO
```

Inside `EventPipeline.process_results` (all state per-source, lock-guarded):

1. `AlprResult`s → normalized `Box` + `PlateRead` (quality-gated by
   `consensus.is_usable`, weighted by `observation_weight`).
2. Vehicle boxes → `ByteTracker.update()` (two-stage ByteTrack, camera-scoped
   keys `camera_id:epoch:local_id`); plates with no vehicle box go through a
   separate plate-kind tracker (§2.3 fallback) in its own id namespace.
3. `TrackUpdate`s → `TrackManager.apply_updates()` (NEW→TRACKING→
   PLATE_CAPTURED→CONFIRMED→COMPLETED/EXPIRED; LOST hold-and-resume; expiry).
4. Each plate read is attached to the vehicle track whose box contains it
   (containment-first, §5.4).
5. Per track: `consensus.update()` → length mode → weighted positional votes →
   agreement → `decide()` stopping rules (§4.6). `CONFIRM` fires
   `TrackManager.mark_confirmed` → exactly one `EmissionRequest`.
6. `_finalize`: consensus text → unchanged `validate_iranian_plate` (validator
   remains the last gate) → `EventIdempotencyRegistry` (in-process guard) →
   fragment-absorption check (§2.5 rule 4) → `db.upsert_vehicle_event`
   (durable guard).
7. Tracks expiring without a usable consensus are **rejected, not fabricated**:
   no plate string is invented, no successful event is created; the outcome is
   counted under `invalid_or_unknown_outcomes` (task §5 policy).

## 4. Architecture / data-flow summary

- **Identity:** `event_key == track_key == "{camera_id}:{session_epoch}:{local_id}"`.
  Camera-scoped by construction; two cameras seeing the same plate produce two
  independent events (task §7 — analytics may link them by `plate_norm`, the
  tracker never crosses cameras).
- **One finalized event per track lifetime**, enforced at three layers:
  1. lifecycle `event_emitted` flag + `EVENT_EMITTED` gate,
  2. `EventIdempotencyRegistry` (thread-safe, in-process),
  3. `vehicle_events.event_key` UNIQUE + `ON CONFLICT DO UPDATE` (durable,
     survives restarts).
- **Bounded memory:** per-track observations capped by `max_track_obs` (30, weakest-dropped
  ring); `max_live_tracks` (32) enforced by the tracker; no queues added; no new
  threads; DB writes remain on the existing worker threads (single-row upsert,
  measured ≤ 1 ms — see benchmark report).
- **Cooldown is a safety net, not identity:** the plate-text re-entry cooldown
  (15 s default) only absorbs track-fragmentation duplicates within
  `fragment_window_s` (3 s) when tracks overlapped in time; it can never merge
  two genuine visits, and there is **no** global long-duration text cooldown in
  the new path (task §7).

## 5. Feature-flag behaviour

| Env var | Default | Effect |
|---|---|---|
| `ALPR_PIPELINE_MODE` | `legacy` | `events` opts RTSP **and** video into the new pipeline |
| `ALPR_PIPELINE_RTSP` | (unset = global) | per-source override |
| `ALPR_PIPELINE_VIDEO` | (unset = global) | per-source override |
| `ALPR_DUAL_WRITE_DETECTIONS` | `1` | legacy `detections` writes unchanged; Phase 1 does not alter this |

- Flag is read **once per processor construction** — a mid-stream env change
  cannot corrupt an active camera; restart applies it.
- Missing/invalid values fail safe to legacy (tested).
- A wiring error (e.g. import failure) degrades to legacy with a warning, never
  crashes the camera (tested).
- Image endpoint: unchanged (no tracks in a still image — §7.1 of the design).

## 6. Database / schema changes

Minimal M1+M2 only (no speculative columns, no `plate_observations` table yet —
the design's full §3.2/§3.3 schema is deliberately deferred; task §6 allows the
smallest safe migration):

```sql
CREATE TABLE IF NOT EXISTS vehicle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,        -- the idempotency boundary
    track_id TEXT NOT NULL,
    camera_id INTEGER, camera_name TEXT, session_id INTEGER,
    source_type TEXT NOT NULL DEFAULT 'rtsp', source_file TEXT,
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
    duration_ms INTEGER DEFAULT 0, frame_count INTEGER DEFAULT 0,
    observation_count INTEGER DEFAULT 0,
    plate_number TEXT NOT NULL, plate_norm TEXT NOT NULL,
    confidence REAL DEFAULT 0, agreement_ratio REAL DEFAULT 0,
    status TEXT DEFAULT 'confirmed', needs_review INTEGER DEFAULT 0,
    finalize_reason TEXT, plate_valid INTEGER DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_camera_time ON vehicle_events(camera_id, last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_events_plate_norm  ON vehicle_events(plate_norm, last_seen DESC);
-- detections gains one nullable linkage column (legacy rows stay NULL):
ALTER TABLE detections ADD COLUMN event_key TEXT   -- via _ensure_column, re-runnable
```

**Migration / rollback procedure**

- Forward: none required by operators — `init_db()` (already called at app
  startup, `api.py:101`) creates the table and column idempotently on first
  boot. Verified re-run safe by test.
- Rollback: flip `ALPR_PIPELINE_MODE=legacy` (or unset it) and restart. The
  legacy pipeline resumes exactly as before; the `vehicle_events` table simply
  stops receiving rows and the nullable `detections.event_key` stays NULL.
  Dropping the table is optional and safe (`DROP TABLE vehicle_events;` — it is
  additive and unreferenced by legacy readers).

## 7. Compatibility

- **Legacy default:** with no env vars set, `EventPipeline` is never constructed
  and `git diff` shows the legacy code paths are logically unchanged (all edits
  are guarded by `if self.event_pipeline is not None` or additive fields with
  defaults). Tested.
- **API contracts:** every legacy response field is preserved; the only change
  is the additive nullable `pipeline` key on the RTSP status endpoint. The
  `/api/detect/video/*`, `/api/detect/image`, and history field names
  (`dtrb_text`, `count`, …) are untouched.
- **Full suite:** 369 passed, 3 failed — the identical 3 FFmpeg/OpenH264
  failures as the Phase 0 baseline (proven pre-existing by re-running them on
  stashed pristine files; see test report).

## 8. Known limitations

1. **No physical vehicle re-identification.** Identity is per-camera motion
   tracking. The same vehicle seen by two cameras yields two events; a track ID
   switch during heavy occlusion can split one visit into two events (mitigated
   by the 3 s fragment window + 15 s re-entry cooldown, not eliminated).
2. **Single-candidate voting.** The char detector interface is unchanged, so
   `PlateRead.char_candidates` currently carries only the argmax character per
   position (weight 1.0). Ranked runner-up voting (§4.5) becomes active the
   moment a small `_assemble_chars` extension exposes alternates — deferred to
   Phase 2 to keep this integration minimal. Positional/length/agreement voting
   is fully active.
3. **Quality inputs are partial.** `brightness_ok=True` and `sharpness=0.0` are
   neutral defaults; the crop-statistics collection point is Phase 2 (the
   quality-gate structure, weights, and rejection counters are all live and
   tested).
4. **No async DB writer.** Persistence stays on the existing worker thread
   (design §5.6 DbWriter is Phase 2). Measured impact: single-row upsert ≈
   0.1–1 ms — noise against a ~100 ms frame (see benchmark report §3).
5. **`events_per_visit` real-world gate is pending** — no annotated dataset
   exists (see benchmark report §5).
6. **`UPGRADE` is a no-op refinement path** in Phase 1: the durable row is
   written once at CONFIRM; best-frame upgrades will land with the FrameStore
   in Phase 2.

## 9. Remaining work for Phase 2 (not started)

FrameScheduler + inference semaphore; ROI plate detection; `imgsz` pinning;
attribute (make/colour) once-per-event gating; runner-up char candidates from
`_assemble_chars`; crop-quality stats (sharpness/brightness); DbWriter/FrameStore
threads + `plate_observations` table; `/api/events*` read API; replay-pack
fixture tests with ground-truth visits.

## 10. Exit-gate status

| # | Gate | Status |
|---|---|---|
| 1 | Legacy pipeline default + regression tests | ✅ default on both paths; 369 passed / 3 pre-existing failures identical to baseline |
| 2 | Opt-in pipeline runs through the actual video-processing path | ✅ hooked inside `_ml_worker` / `_run`, same inference loop |
| 3 | Track/lifecycle state camera-isolated | ✅ one `EventPipeline` per processor; keys namespaced; tested |
| 4 | Multiple observations → at most one finalized event | ✅ three-layer idempotency, tested |
| 5 | Event identity idempotent at persistence boundary | ✅ UNIQUE(event_key) upsert, tested incl. restart + race handler |
| 6 | API/history contracts compatible | ✅ additive-only; legacy shape test green |
| 7 | Targeted tests pass | ✅ 20 new + 77 Phase 0 |
| 8 | Full suite vs Phase 0 baseline | ✅ same 3 failures, proven pre-existing |
| 9 | No model replaced/retrained | ✅ weights untouched (manifest hashes unchanged) |
| 10 | No Flutter redesign / VLM | ✅ zero Dart changes, zero new models |
| 11 | Benchmark + limitations documented | ✅ see `ALPR_PHASE1_BENCHMARK.md` |
| 12 | `git diff` contains only intentional Phase 1 changes | ✅ 5 tracked files, all listed in §2.1 |
| 13 | No commit / push | ✅ |
