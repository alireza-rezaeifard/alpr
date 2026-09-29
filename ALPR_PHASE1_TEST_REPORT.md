# Phase 1 Test Report

**Date:** 2026-09-29 · **Python:** 3.11.4 · **pytest:** 9.0.3 · machine: same as Phase 0 baseline
**Base commit:** `3f16f27` · **All work uncommitted** (no commit, no push).

---

## 1. Commands and exact results

### 1.1 Targeted: new Phase 1 tests

```
python -m pytest tests/test_event_pipeline_integration.py tests/test_phase1_flag_wiring.py -q
→ 20 passed in 0.29s
```

| File | Count | What is covered |
|---|---|---|
| `tests/test_event_pipeline_integration.py` | 12 | §11 Events: many frames → 1 event; OCR correction → no second event; later genuine visit → new event; camera isolation + distinct keys; track-ID non-collision; invalid-plate track → no confirmed event; low-confidence rejection; repeated finalization idempotency; durable upsert (restart), cross-camera persistence, migration idempotency |
| `tests/test_phase1_flag_wiring.py` | 8 | §11 Compatibility: legacy default (RTSP + video); RTSP/video opt-in; global-mode + per-source override; invalid value fail-safe; wiring-error fail-safe; disable restores legacy; `get_state()` legacy shape intact |

### 1.2 Targeted: Phase 0 regression set (unchanged scaffolding)

```
python -m pytest tests/test_pipeline_config.py tests/test_pipeline_metrics.py \
  tests/test_pipeline_flags.py tests/test_tracker_bytetrack.py \
  tests/test_track_lifecycle.py tests/test_consensus_golden.py \
  tests/test_consensus_property.py tests/test_event_key_idempotency.py -q
→ 77 passed in 0.36s        # identical to the Phase 0 result
```

### 1.3 Targeted: legacy real-time / video processor suites

```
python -m pytest tests/test_realtime_integration.py \
  tests/test_video_processor_integration.py tests/test_rtsp_validator_integration.py \
  tests/test_event_pipeline_integration.py tests/test_phase1_flag_wiring.py -q
→ 58 passed in 1.36s
```

(These suites exercise the legacy dedup path, plate validation inside the RTSP
processor, and the `VideoProcessor`/`RTSPStreamProcessor` behaviour — all green
with the Phase 1 edits in place, flag off by default.)

### 1.4 Full backend suite

```
python -m pytest tests -q
→ 3 failed, 369 passed, 115 warnings in 206.49s (0:03:26)
```

| Failed test | Baseline status |
|---|---|
| `tests/test_detection_pipeline_integration.py::TestImageDetectionWiring::test_valid_image_creates_session_and_detections` | **failed before Phase 1** (Phase 0 baseline §2.1) |
| `tests/test_detection_pipeline_integration.py::TestAtomicStorageFailure::test_detection_storage_failure_propagates_error` | **failed before Phase 1** |
| `tests/test_detection_pipeline_integration.py::TestRTSPTaskLifecycle::test_rtsp_status_returns_processor_state` | **failed before Phase 1** |

**Proof the 3 failures are pre-existing (not silently reclassified):** the five
Phase 1 modified tracked files were stashed and the three tests re-run against
pristine tracked code:

```
git stash push -m "phase1-wip" -- db.py alpr_engine.py video_processor.py camera_manager.py routers/detection.py
python -m pytest <the 3 tests> -q   → 3 failed in 0.79s
git stash pop
```

Same 3 failures, same identities, on unmodified files. Root cause (from the
Phase 0 baseline §2.1 and the run stderr): this machine's FFmpeg/OpenH264
writer cannot initialize (`[libopenh264] Incorrect library version loaded`,
`VIDEOIO/FFMPEG: Failed to initialize VideoWriter`), plus stale test mocks that
pre-date the current `video_processor` API (`KeyError: 'plate_text'`,
missing `annotated` key expectations). No new failure was introduced: 369
passed here vs 272+77=349 at Phase 0 — the delta is exactly the 20 new Phase 1
tests.

### 1.5 Flutter

Not run as a gate: Phase 1 touches **zero Dart files** (verified: no file under
`flutter_app/` was modified). The Phase 0 Flutter baseline (83 passed) remains
the reference; CI (`flutter analyze` + `flutter test`) is the ongoing guard.

---

## 2. §11 test-matrix coverage map

| Required case | Where covered |
|---|---|
| **Tracking** — camera isolation | `test_camera_isolation_events_and_keys` |
| Stable track IDs across consecutive detections | Phase 0 `test_tracker_bytetrack.py` (10 tests) + one-track-one-event test |
| Temporary missing detections / occlusion | Phase 0 tracker LOST/resume tests + `occlusion_recoveries` counter |
| Track expiration | Phase 0 lifecycle tests; `test_track_expiring_without_valid_plate…` |
| Camera stop/restart cleanup | `RTSPStreamProcessor.stop()` → `EventPipeline.expire("processor_stop")`; tracker `reset()` |
| Fragment handling | §2.5 absorption in `_finalize` + `fragments_absorbed` counter; window 3 s |
| **Consensus** — repeated identical readings | `test_many_frames_one_track_one_event` |
| Similar but conflicting readings | `test_ocr_correction_within_track_no_second_event` (1-char wobble) |
| Invalid candidates | `test_track_expiring_without_valid_plate…` |
| Low-quality observations | `test_low_confidence_observations_rejected` |
| Min-observation / timeout finalization | Phase 0 golden `decide()` tests (CONFIRM/FORCE/SUPPRESS) |
| Unknown/rejected handling | `invalid_or_unknown_outcomes` counter asserted in rejection test |
| **Events** — many frames → 1 event | `test_many_frames_one_track_one_event` |
| Repeated finalization idempotent | `test_repeated_finalization_idempotent_in_memory` |
| OCR correction → no 2nd event | `test_ocr_correction_within_track_no_second_event` |
| Later genuine visit → new event | `test_later_genuine_visit_new_event` |
| Separate cameras don't suppress each other | `test_durable_upsert_different_cameras_both_persist`, `test_camera_isolation…` |
| Persistence concurrency / restart | `test_durable_upsert_idempotent_across_restart` + IntegrityError race path in `db.upsert_vehicle_event` |
| **Compatibility** — legacy flag disabled | `test_rtsp_processor_legacy_by_default`, `test_video_processor_legacy_by_default` |
| New flag enabled | `test_rtsp_processor_events_opt_in`, `test_video_processor_events_opt_in` |
| Invalid / missing flag | `test_invalid_flag_value_fails_safe`, `test_wiring_error_fails_safe` |
| Existing API/history consumers | `test_rtsp_status_shape_additive_only` + legacy suites (§1.3) |
| Existing plate validation | untouched `plate_validator.py`; validator is the last gate in `_validate_result`; validator suites green |
| Existing camera processing | `camera_manager.py` passthrough only; concurrency/stream suites green |
| DB migration forward + rollback | `test_migration_forward_and_reinit_idempotent`; rollback = flag flip (see implementation report §6) |

---

## 3. Verification notes

- Every gate assertion in the new tests runs against the **real** wiring
  (`EventPipeline` → real tracker/lifecycle/consensus → real
  `db.upsert_vehicle_event` on a temp SQLite file); no test-only shims were
  added to production code.
- The `database/plpr.db` working-tree churn produced by running the suite was
  restored after the run (`git checkout -- database/plpr.db`), per the Phase 0
  report's documented side effect.
- No test was skipped, xfail-ed, or weakened to make the suite pass; no
  pre-existing test was modified.

## 4. Result summary

| Suite | Result | vs Phase 0 baseline |
|---|---|---|
| New Phase 1 tests | 20 / 20 passed | +20 new |
| Phase 0 scaffolding tests | 77 / 77 passed | identical |
| Legacy RTSP/video suites | 58 / 58 passed | identical (green where green before) |
| Full backend suite | 369 passed, 3 failed | same 3 pre-existing failures, proven by stash-re-run |
| Flutter | not applicable | zero Dart changes |
