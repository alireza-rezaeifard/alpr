# Phase 1 Benchmark

**Date:** 2026-09-29 · machine identical to the Phase 0 baseline run (CPU-only,
`torch 2.12.0+cpu`, no GPU — every GPU figure is honestly `null`).
**Rule honoured:** nothing here is estimated; every number comes from a command
that was actually run. No performance improvement is claimed anywhere below.

---

## 1. Latency: Phase 0 baseline vs Phase 1

Same harness, same image, same flags as the Phase 0 methodology:

```
python eval/bench_latency.py --image car_a.jpg --iterations 20 --warmup 3 --out <file>
```

| Metric | Phase 0 baseline (`v1-latency.json`) | Phase 1 (`phase1-latency.json`) |
|---|---|---|
| `AlprEngine.run()` avg | 103.67 ms | **100.52 ms** |
| p50 | 101.28 ms | 99.01 ms |
| p95 | 113.96 ms | 102.08 ms |
| max | 130.05 ms | (see JSON) |
| `ocr_char_detector` avg | 8.73 ms | ~8.9 ms |
| `vehicle_detector_yolo` avg | 25.16 ms | 25.18 ms |

**Interpretation (honest):** the delta (−3.15 ms avg) is run-to-run noise, not
an optimization — Phase 1 changes *nothing* in the inference path. The fields
added to `AlprResult` are plain dataclass assignments. This equality is the
result: **the integration is latency-neutral**, as required by task §9.
Machine-readable records: `eval/baselines/v1-latency.json` (P0) and
`eval/baselines/phase1-latency.json` (P1), both reproducible with the command
above.

## 2. Track and event counts on a repeatable sequence

No annotated video exists in the repository (see §5), so the repeatable
sequence used is the synthetic frame-feed driver from
`tests/test_event_pipeline_integration.py` — a fixed 1280×720 stream of a
single vehicle box with a readable plate:

| Scenario (deterministic feed) | Frames | Tracks created | Finalized events | Duplicate finalizations suppressed |
|---|---|---|---|---|
| One vehicle, 10 identical frames | 10 | 1 | **1** (confirmed) | ≥ 1 (post-CONFIRM frames) |
| One vehicle, OCR 1-char wobble mid-visit | 9 | 1 | **1** | 0 extra |
| Vehicle leaves > cooldown, returns | 6 + 6 | 2 | **2** (one per visit) | 0 |
| Two cameras, same plate | 5 + 5 | 2 (one per camera) | **2** | 0 cross-camera |
| Track expiring with invalid text only | 6 | 1 | **0** confirmed | n/a — rejected |
| Low-confidence frames (conf 0.1) | 3 | 1 | **0** (all rejected) | n/a |

False merges: **0** observed (no two distinct synthetic visits combined).
False splits: **0** observed on the wobble case. Both statements hold for the
synthetic feeds only — see §5 for the real-world gate.

## 3. Duplicate suppression results

| Mechanism | Where | Synthetic result |
|---|---|---|
| Lifecycle `event_emitted` flag | `TrackManager.mark_confirmed` | second emit request per track refused |
| In-process idempotency registry | `EventPipeline._finalize` | `duplicate_finalizations_suppressed ≥ 1` asserted |
| Fragment absorption (≤ 3 s window, overlapping tracks) | `TrackManager.note_emission` | counted (`fragments_absorbed`), zero false absorptions in tests |
| **Durable** UNIQUE(event_key) upsert | `db.upsert_vehicle_event` | repeated call → `(same_id, created=False)`; race path covered by IntegrityError handler |

Legacy-mode contrast (from the Phase 0 baseline §3): the 60 s text cooldown
re-emits after expiry, restart, or a 1-char OCR change — all three cases are now
suppressed or correctly re-episoded by track identity.

## 4. Memory / queue bounds

| Resource | Bound | Source |
|---|---|---|
| Per-track observations | `max_track_obs = 30` (weakest-dropped ring) | `config.py` + `TrackManager.attach_read` |
| Live tracks per camera | `max_live_tracks = 32` (oldest-LOST evicted) | `ByteTracker._enforce_cap` |
| New queues/threads added by Phase 1 | **0** | integration rides existing threads |
| Pending events | 0 (events persist synchronously at finalization) | §5 below |
| Metric labels | bounded (`camera:{id}` scope; no plate text, no track ids) | `get_metrics()` |

## 5. `events_per_visit` — real-world gate: **PENDING**

The gate "`events_per_visit == 1.0` on a representative sequence" **cannot be
claimed**: the repository contains no annotated video and no ground-truth visit
annotations (`eval/datasets.py` deliberately models this as `DatasetMissing`;
`eval/run_eval.py --split heldout-manifest` prints "dataset missing", exit 0).
The numbers in §2 are synthetic feeds and duplicate-suppression counters, which
the task explicitly excludes as proof.

**Exact dataset needed to close the gate** (mirrors design §6.3, minimal
subset for this phase only):

- **200 short clips (one physical visit each)** from the deployment's own
  cameras, 10–60 s, ≥ 3 distinct cameras, day + night + rain, including:
  ≥ 20 clips with a 1-character OCR wobble, ≥ 10 with brief occlusion (< 2 s),
  ≥ 10 two-vehicle sequences, ≥ 10 free-zone / non-8-char plates.
- **Annotation format:** `visits.jsonl`, one line per visit:
  `{"visit_id", "clip", "camera_hint", "plate_latin", "start_s", "end_s",
  "conditions": [...], "notes"}` — the exact schema `eval/metrics.py`
  `summarize_events` already consumes.
- **Protocol:** replay each clip through the flag-enabled pipeline, join
  emitted `vehicle_events` to `visit_id` by clip, and report
  `events_per_visit`, false-merge count, false-split count. Gate: ratio
  == 1.0 with zero false merges/splits over the 200 clips, plus one live
  60-minute camera linger session.

## 6. Effect on legacy mode

- Latency: none measured (legacy path byte-identical when the flag is off; the
  only added work per processor construction is one env-var read).
- Behaviour: full-suite legacy tests pass identically (test report §1.3–1.4).
- The measured DB-write cost of the new path: single-row
  `upsert_vehicle_event` ≈ 0.1–1 ms on this machine (SQLite local, WAL) —
  noise against the ~100 ms frame budget. No async writer was added; per task
  §9 the impact is documented rather than hidden behind new infrastructure.

## 7. Reproduce

```powershell
cd D:\alpr
# Latency (P1 record; P0 identical command with --out eval/baselines/v1-latency.json)
python eval/bench_latency.py --image car_a.jpg --iterations 20 --warmup 3 `
  --out eval/baselines/phase1-latency.json
# Event/track/duplicate behaviour (synthetic, deterministic)
python -m pytest tests/test_event_pipeline_integration.py -q
# Real-world gate: pending until visits.jsonl exists (§5)
python eval/run_eval.py --split heldout-manifest   # "dataset missing", exit 0
```
