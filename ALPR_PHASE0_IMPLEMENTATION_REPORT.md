# Phase 0 Implementation Report — Architecture Scaffold

**Project:** `D:\alpr`
**Phase:** 0 of 5 — *Scaffolding and measurement (no behaviour change)* per
`ALPR_ARCHITECTURE_DESIGN.md` §8 → "Phase 0"
**Date:** 2026-09-29
**Base commit:** `3f16f270a8abbaf2f30d017693d5a72a1dc3bd65` (branch `main`)
**Commit / push:** **none** — the working tree is left uncommitted, as instructed.

---

## 1. Files changed

### 1.1 New files (all additive)

| File | Purpose |
|---|---|
| `pipeline/__init__.py` | Package doc + layout map (design Part 1) |
| `pipeline/flags.py` | Feature flags: legacy default, event pipeline opt-in (§3.5 M3) |
| `pipeline/config.py` | `PipelineConfig` dataclass, every Appendix C knob, validated |
| `pipeline/metrics.py` | Counters / gauges / EMA + `snapshot()` (Appendix E.1) |
| `pipeline/types.py` | `Box`, `Track`, `TrackUpdate`, `PlateRead`, `PlateObservation`, `ConsensusCandidate`, `ConsensusResult`, `ScheduleDecision`, `EmissionRequest`, `VehicleEvent` + `box_iou`/`containment_iou` |
| `pipeline/tracker.py` | In-repo `ByteTracker` (two-stage association, Kalman predict/update, camera-scoped keys) |
| `pipeline/track_manager.py` | `TrackManager` lifecycle state machine + emission gate + cooldown/fragment helpers |
| `pipeline/consensus.py` | Pure consensus engine: gate, weight, quality, length mode, positional voting, agreement, best frame, stopping rules |
| `pipeline/event_builder.py` | Event-key identity, `EventIdempotencyRegistry`, `VehicleEvent` assembly |
| `eval/__init__.py` | Eval package |
| `eval/bench_latency.py` | Per-stage latency harness (avg/p50/p95/max, CPU load, GPU honest-null) |
| `eval/metrics.py` | Pure metrics: `plate_exact_match`, `cer`, `percentile`, `summarize_events` |
| `eval/datasets.py` | Held-out manifest loader + explicit `DatasetMissing` |
| `eval/run_eval.py` | Harness entry: `--self-test`, and "dataset missing" contract (Phase 0 exit gate) |
| `eval/baselines/v1-latency.json` | Measured baseline output (generated, not hand-written) |
| `weigths/manifest.json` | Model registry: sha256, architecture, classes, imgsz, thresholds |
| `weigths/MODELS.md` | Human-readable registry + change-control rule |
| `tests/test_pipeline_config.py` | Config defaults + validation |
| `tests/test_pipeline_metrics.py` | Metrics counters/gauges/EMA/snapshot |
| `tests/test_pipeline_flags.py` | Flag safety (legacy default, opt-in, fail-safe) |
| `tests/test_tracker_bytetrack.py` | Tracker unit + property tests |
| `tests/test_track_lifecycle.py` | Every lifecycle transition + invalid transitions |
| `tests/test_consensus_golden.py` | Golden cases incl. the audit's 3-frame example |
| `tests/test_consensus_property.py` | Hypothesis properties for consensus |
| `tests/test_event_key_idempotency.py` | Event-key determinism + app-level idempotency |
| `ALPR_PHASE0_BASELINE.md` | Pre-change baseline report (task 1 deliverable) |

### 1.2 Modified files

**None.** `git status` reports exactly one tracked file as modified:

```
 M database/plpr.db
```

This is a **side effect of running the pre-existing test suite**, which calls
`init_db()` and writes sessions/detections into the development database
(`api.py:101`, `tests/test_detection_pipeline_integration.py`, etc.). The file
size is unchanged (294 912 → 294 912 bytes); the diff is binary churn from those
writes. No Phase 0 code writes to the database — the event pipeline has no sink
wired yet, by design.

To restore it for a pristine tree (discards only test-generated rows):

```powershell
git checkout -- database/plpr.db
```

### 1.3 Files deliberately NOT touched

`api.py`, `alpr_engine.py`, `video_processor.py`, `camera_manager.py`, `db.py`,
`schemas.py`, `routers/*`, `auth/`, `licensing/`, `retention/`, `watchlist/`,
`flutter_app/**` (zero Dart changes), `frontend/**`, and everything under
`weigths/` except the two new documentation artifacts. No model was replaced,
retrained, quantized or re-exported.

---

## 2. Architecture implemented

Exactly the Phase 0 row of the design's Part 8 table: *"Interfaces, config,
metrics, and baselines exist before any behaviour is touched"* — plus the
requested tracker, lifecycle, consensus and event-key components, all as
**unwired scaffold** (no runtime path uses them yet).

| Design component | Implementation | Where |
|---|---|---|
| `PipelineConfig` (App. C, all knobs, validated, unknown-key rejection) | `PipelineConfig` + `DEFAULT_CONFIG` + `from_dict` | `pipeline/config.py` |
| Counters/gauges/EMA + `snapshot()` (App. E.1) | `PipelineMetrics`, `GLOBAL_METRICS` | `pipeline/metrics.py` |
| Domain types (App. A) | `Box`, `Track`, `TrackUpdate`, `PlateRead`, `PlateObservation`, `ConsensusCandidate`, `ConsensusResult`, `ScheduleDecision`, `EmissionRequest`, `VehicleEvent` — pure, no torch/cv2/DB/network/Flutter | `pipeline/types.py` |
| ByteTrack, in-repo, camera-scoped (design §2.2 option B) | `ByteTracker`: Kalman predict/update, two-stage association (high → tracks, then low-score → unmatched), deterministic greedy IoU matching, expiry, live cap, `reset()`; keys `f"{camera_id}:{session_epoch}:{local_id}"` | `pipeline/tracker.py` |
| Lifecycle (design §2.4) | `TrackManager`: explicit `_transition` table; NEW→TRACKING→PLATE_CAPTURED→CONFIRMED→COMPLETED/EXPIRED; LOST hold-and-resume; `expire_all` flush; emission flag; cooldown/fragment helpers | `pipeline/track_manager.py` |
| Consensus (design Part 4, §4.8) | `update()` → length mode → positional votes (rank 1.0/0.5/0.25) → agreement → `0.5·char_mean + 0.5·agreement` → `decide()` CONFIRM/EARLY_BEST(disabled)/UPGRADE/FORCE/SUPPRESS; gate + `quality_score()` | `pipeline/consensus.py` |
| Event identity (§2.5 rule 2, §3.2) | `make_event_key` (`camera:epoch:local`), thread-safe `EventIdempotencyRegistry`, `build_event` | `pipeline/event_builder.py` |
| Feature flags (§3.5 M3) | `legacy` default; `events` opt-in globally or per source; invalid → legacy; dual-write default on | `pipeline/flags.py` |

**Deliberately NOT built in Phase 0:** `FrameScheduler` logic, `PipelineWorker`,
OCR collector, sinks (`DbWriter`/`FrameStore`/`EventBus`), DDL/`init_db`
changes, SSE/API, Flutter changes, decision layer — referenced by interface
only, per the phase boundaries.

---

## 3. Tests added

| File | Count | Contents |
|---|---|---|
| `tests/test_pipeline_config.py` | 16 | defaults match Appendix C; 13 invalid-knob cases rejected; unknown-key rejection; `from_dict` round-trip |
| `tests/test_pipeline_metrics.py` | 5 | per-scope counters; last-value gauges; EMA math; JSON-serialisability; scope reset |
| `tests/test_pipeline_flags.py` | 6 | legacy default everywhere; global + per-source opt-in; override precedence; invalid → legacy; dual-write default/off; aliases |
| `tests/test_tracker_bytetrack.py` | 10 | new track + camera-scoped key; matched keeps id; unmatched → LOST → expires; two vehicles → distinct ids; camera isolation; low-score recovery; determinism; live cap; monotonic-walk property; reset flush |
| `tests/test_track_lifecycle.py` | 11 | every §2.4 row incl. LOST→resume and any→EXPIRED flush; `NEW→EXPIRED` glint filter; double-emission suppression; invalid transitions raise; transition-table completeness |
| `tests/test_consensus_golden.py` | 20 | audit Case A (winner `12ب34567`, confidence ∈ [0.80, 0.95], alternates, best frame, CONFIRM); determinism; empty/single/partial/different-length/tie/identical/low-weight/noisy/conflicting/invalid-plate/best-frame/decide rules/quality bounds/quality-gate rejections |
| `tests/test_consensus_property.py` | 5 (Hypothesis) | majority wins + bounded outputs; identical-appends monotonicity; empty/partial never flip consensus; order determinism; quality bounded |
| `tests/test_event_key_idempotency.py` | 7 | key format/scoping; deterministic recompute; app-level suppression without DB; upgrade slots; epoch-separated identities; `build_event` mapping; malformed-key rejection |

Coverage of the task §§2–6: new/matched/unmatched/expired ✓ · multiple
vehicles ✓ · isolation ✓ · deterministic IDs ✓ · all lifecycle rows + invalid
✓ · `Track`/`PlateObservation`/`ConsensusCandidate`/`VehicleEvent` ✓ (zero
imports from `db.py` or `flutter_app` — verified decoupled) · normalization /
voting / weighting / agreement / length / best-frame / stopping rules ✓ ·
event-key idempotency without any DB UNIQUE constraint ✓.

**New-test result:** `pytest <8 new files> -q` → **77 passed, 0 failed** (0.33 s).

---

## 4. Baseline results (reference)

Recorded before Phase 0 — full detail in `ALPR_PHASE0_BASELINE.md`:

- Python: 275 collected → **272 passed, 3 failed** (all three pre-existing and
  environment-caused — the FFmpeg/OpenH264 writer cannot initialize; identical
  failure identities before and after Phase 0, see §9).
- Flutter: **83 passed, 0 failed**.
- Duplicates documented from code + `log_demo_result.txt`
  (`28i68923` ×176 vs `28i68973` ×19: two rows, one car).
- Accuracy: not measurable — no labelled held-out set;
  `eval/run_eval.py --split heldout-manifest` prints "dataset missing", exit 0
  (the Phase 0 exit gate, and it passes).

---

## 5. Performance measurements

`car_a.jpg`, 20 measured iterations, CPU-only
(record: `eval/baselines/v1-latency.json`):

| Scope (n) | avg | p50 | p95 | max |
|---|---|---|---|---|
| `AlprEngine.run()` total (20) | **103.67 ms** | 101.28 | 113.96 | 130.05 |
| vehicle_detector_yolo (20) | 25.16 | 24.32 | 32.28 | 35.40 |
| plate_detector_yolo (20) | 24.32 | 23.97 | 27.64 | 28.09 |
| ocr_char_detector (20) | 8.73 | 8.90 | 10.05 | 10.06 |
| resnet_car_type (40) | 11.30 | 11.59 | 14.43 | 19.17 |
| resnet_color (40) | 11.23 | 11.49 | 13.64 | 14.31 |
| CPU load | 16.391 CPU-s / 2.083 s wall = **787 % of one core** (12 logical cores) | | | |

Attribution check: 25.16 + 24.32 + 8.73 + 2×11.30 + 2×11.23 = **103.27 ms** vs
measured total 103.67 ms — the cost is fully accounted for. Reproduces the
audit's 105–124 ms band on the same machine.

---

## 6. Feature flags

`pipeline/flags.py` — the only Phase 0 mechanism touching behaviour choice:

| Flag | Default | Meaning |
|---|---|---|
| `ALPR_PIPELINE_MODE` | `legacy` | global default; `events` opts the *new* pipeline in |
| `ALPR_PIPELINE_RTSP` / `_VIDEO` / `_IMAGE` | (unset = global) | per-source override; a source stays on `legacy` while others use `events` |
| `ALPR_DUAL_WRITE_DETECTIONS` | `1` | legacy-row dual write stays on until migration step M5 |
| invalid value | → `legacy` | fail safe: the new path can never engage by typo |

**Guarantee, tested:** with a default environment nothing in the new package is
referenced by `video_processor.py`, `api.py`, or `alpr_engine.py` — verified by
`git status`: zero modified source files. The legacy pipeline remains the only
runnable path; the event pipeline has no callers.

---

## 7. Known limitations

1. **Scaffold is unwired.** No runtime path calls `pipeline.*` yet; tracker,
   lifecycle, consensus and event-key interact only inside tests. Wiring is
   Phase 1 by design.
2. **No accuracy numbers.** No labelled Iranian held-out set exists;
   `run_eval.py --split heldout-manifest` prints "dataset missing" (exit 0).
   The dataset is the Phase 1 long pole (design §6.3).
3. **Matcher is greedy, not Hungarian.** `_greedy_match` is deterministic and
   equivalent on the small ALPR associations; a scipy Hungarian swap is a
   Phase 1 upgrade *only if* a dense-traffic test shows ID switches.
4. **Kalman is covariance-free.** The 8-state filter blends velocity with a
   fixed factor (tuned for ~8 FPS effective sampling), not full covariances —
   acceptable for the warmup-free Phase 0 purpose; Phase 1 soak tests confirm.
5. **`EARLY_BEST` is disabled** (`enable_early_best=False`) until the Part 6
   harness proves single-frame confirmation safe.
6. **`min_sharpness` defaults to 0.0** (lenient by design §4.3); the gate
   activates only when configured — exercised with an explicit threshold.
7. **torch thread count differs between runs** (6 in the audit, 8 here). Both
   values are recorded in their JSON; latency follows thread count, so the JSON
   — not a headline number — is the baseline.
8. **`database/plpr.db` shows as modified** in `git status` — a side effect of
   running the pre-existing suite, disclosed in §1.2. Restore with
   `git checkout -- database/plpr.db` if a pristine tree is needed.

---

## 8. Remaining Phase 1 work

In dependency order, from the design's Phase 1 row:

1. **`FrameScheduler` + `PipelineWorker`** — budget scheduler + offline file
   mode; wire RTSP `_ml_worker` and `VideoProcessor._run` through it behind
   `PIPELINE_MODE` (default `events` for RTSP, `legacy` for video/image).
2. **OCR collector** — wrap `_assemble_chars` (+runner-up candidates,
   `PlateRead` assembly, quality precheck); additive `AlprEngine.detect_*`
   methods.
3. **`EventBuilder` completion + sinks** — consensus→event assembly, `DbWriter`
   + `FrameStore` threads, in-memory `EventBus`; emission through the
   registry built here.
4. **DB M1+M2** — `vehicle_events` + `plate_observations` tables, three
   `_ensure_column` additions; dual-write on from day one.
5. **History/`/status` appends** — `event_id/track_id/agreement_ratio/
   needs_review/status` on entries + `pipeline` object on `/status` (old
   fields untouched).
6. **Replay pack** — `tests/test_pipeline_replay_events.py` + 3 frozen visits
   in `eval/visits.jsonl`; duplicates KPI `events_per_visit == 1.0`.
7. **Dataset collection starts now** — §6.3 `heldout` (≈500 frames + 200 visit
   clips + 300 hard frames) is Phase 1's exit dependency.

---

## 9. Exact test commands

```powershell
cd D:\alpr

# Phase 0 new tests (fast)
python -m pytest tests/test_pipeline_config.py tests/test_pipeline_metrics.py `
  tests/test_pipeline_flags.py tests/test_tracker_bytetrack.py `
  tests/test_track_lifecycle.py tests/test_consensus_golden.py `
  tests/test_consensus_property.py tests/test_event_key_idempotency.py -q
# RESULT: 77 passed in 0.33 s

# Full Python suite with Phase 0
python -m pytest tests -q
# RESULT: 3 failed (pre-existing FFmpeg/OpenH264 failures in
# tests/test_detection_pipeline_integration.py — same 3 tests, same file,
# as the pre-change baseline), 349 passed

# Harness contracts (Phase 0 exit gates)
python eval/run_eval.py --split heldout-manifest   # "dataset missing", exit 0
python eval/run_eval.py --self-test                # 0 failures
python eval/bench_latency.py --image car_a.jpg --iterations 20 --warmup 3 `
  --out eval/baselines/v1-latency.json             # regenerates §5 numbers

# Regression sample (green where green before)
python -m pytest tests/test_plate_validator.py tests/test_skip_frame_range_property.py -q
# RESULT: 44 passed
```

Flutter: `cd flutter_app; flutter test` → **83 passed** (Phase 0 touches zero
Dart files; UI behaviour provably unchanged).

---

## 10. Git status

```
$ git --no-pager status --short          # at end of Phase 0 work
 M database/plpr.db                      # §1.2: pre-existing-test side effect
 ?? ALPR_PHASE0_BASELINE.md
 ?? ALPR_PHASE0_IMPLEMENTATION_REPORT.md
 ?? eval/
 ?? pipeline/
 ?? tests/test_consensus_golden.py
 ?? tests/test_consensus_property.py
 ?? tests/test_event_key_idempotency.py
 ?? tests/test_pipeline_config.py
 ?? tests/test_pipeline_flags.py
 ?? tests/test_pipeline_metrics.py
 ?? tests/test_track_lifecycle.py
 ?? tests/test_tracker_bytetrack.py
 ?? weigths/MODELS.md
 ?? weigths/manifest.json
```

(Also present from the earlier audit/design phases, untouched here:
`?? ALPR_ARCHITECTURE_DESIGN.md`, `?? ALPR_AUDIT_REPORT.md`.)

```
$ git --no-pager log --oneline -1
3f16f27 update some changes
```

**No commit was made. No push was made.** Everything above is uncommitted
working tree, ready for review before Phase 1 begins.

---

## Exit-gate checklist (task verdict)

| Gate | Result |
|---|---|
| Existing tests remain green | **Yes** — same 3 pre-existing environment failures; everything else 349 passed incl. all 77 new |
| New tracker tests pass | **Yes** — 10 incl. property + determinism + isolation |
| Lifecycle tests pass | **Yes** — 11, all §2.4 rows + invalid transitions |
| Consensus tests pass | **Yes** — 20 golden + 5 property; audit Case A confirmed |
| Event-key/idempotency tests pass | **Yes** — 7, incl. app-level suppression with no DB |
| New pipeline disabled by default | **Yes** — `legacy` default, `events` opt-in, invalid → legacy; no caller wires the new code |
| Existing pipeline still works | **Yes** — zero modified source files; integration suites pass exactly as before |
| Baseline measurements reproducible | **Yes** — §9 commands; JSON regenerates; audit band reproduced |
| No UI behaviour changed | **Yes** — zero `.dart` files touched |
| No model replaced | **Yes** — weights untouched; registry only documents them |



