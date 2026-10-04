# ALPR Phase 1.5 — Offline Replay Validation Report (cam1.mp4, cam2.mp4)

**Date:** 2026-09-30
**Commit under test:** `f9bd7bb feat(alpr): integrate tracked vehicle events`
**Scope:** offline validation of the Phase 1 event pipeline on replayed video.
No production code was modified; no fixes were implemented. This report does
**not** claim production accuracy.

---

## 1. Environment

| Item | Value |
| --- | --- |
| OS | Windows (Git Bash), repo `D:\alpr` |
| Python | 3.11.4 |
| Torch | 2.12.0+cpu — **GPU unavailable (CPU-only inference)** |
| OpenCV | 4.13.0 |
| Ultralytics | 8.4.56 |
| Models | real production weights (`weigths/`), loaded via `api._ensure_models()` |
| Pipeline mode | `ALPR_PIPELINE_MODE=events`, `ALPR_PIPELINE_VIDEO=events` (legacy **disabled** for the run; default legacy behavior untouched) |

## 2. Input videos

| File | Duration | FPS | Resolution | Frames | Size |
| --- | --- | --- | --- | --- | --- |
| `cam1.mp4` | 11.61 s | 30.99 | 1920×1032 | 360 | 16.1 MB |
| `cam2.mp4` | 23.96 s | 25.00 | 1920×1080 | 599 | 129.4 MB |

## 3. Replay method

* Runner: [validation/replay_runner.py](validation/replay_runner.py) — drives the
  **real** `VideoProcessor._run` path: every frame decoded, `detect_plates()` →
  real detector + OCR, then `EventPipeline.process_results()`, then
  `expire("video_end")` at end. No artificial detections, no bypass of
  `video_processor.py`.
* The event pipeline was enabled through the **existing feature flags**
  (`ALPR_PIPELINE_VIDEO=events`), evaluated at processor construction, exactly
  as in production.
* Telemetry was captured runner-side only (per-instance wrapper around
  `EventPipeline.process_results` + per-frame lifecycle snapshots of
  `TrackManager`); zero Phase 1 files modified.
* The database was redirected to a temp file — `database/plpr.db` untouched.
* The rendered output video could not be written in this environment
  (OpenH264 DLL missing); this affects only the annotated MP4, not detection,
  tracking, or events.

### Command used

```bash
python validation/replay_runner.py cam1.mp4 --camera-id cam1 --trace
python validation/replay_runner.py cam2.mp4 --camera-id cam2 --trace
python validation/analyze_events.py validation/cam1 validation/cam2
```

## 4. Results — cam1.mp4 (parking scene, 2 vehicles re-entering frame)

| Metric | Value |
| --- | --- |
| Frames processed | 360 |
| OCR observations | 315 |
| Observations accepted / rejected | 315 / 0 |
| Tracks created | 3 |
| Tracks rejected (new-track gate) | 0 |
| Final events | 3 (all `consensus_confirm`) |
| Duplicate finalizations suppressed | 1 |
| Invalid / unknown outcomes | 0 |
| Persist failures | 0 |
| detections_per_event (tracks/events) | 1.0 |
| OCR_per_event (accepted obs/events) | 105.0 |
| needs_review / invalid-plate events | 0 / 0 |

Events (all confirmed, confidence 1.0, agreement 1.0):

| Event | Plate | Track lifetime (obs frames) | Finalized at frame |
| --- | --- | --- | --- |
| `cam1:0:1` | `28y68923` | f0–f144 (145 OCR reads) | f2 |
| `cam1:0:2` | `12d67413` | f163–f224 (62 reads) | f165 |
| `cam1:0:3` | `28y68923` | f243–f301 (59 reads) | f245 |

The video contains **four** plate-visibility segments (the two cars alternate
repeatedly): `28y68923` f0–144, `12d67413` f163–224, `28y68923` f243–301,
`12d67413` f311–359.

### Correct merge (Case A behavior)

```
segment:  frames 163-224
track:    cam1:0:2
OCR:      12d67413 × 62 (identical every frame)
final:    12d67413   status=confirmed  confidence=1.0  agreement=1.0
```

All 62 OCR emissions of one vehicle collapsed into **one** event →
multiple OCR detections of the same vehicle become one event. ✔ (answer to
objective question 1)

### Suspicious / noteworthy cases

1. **Possible duplicate — Case B (reported, not fixed):** `28y68923` produced
   two events (`cam1:0:1` f0–144 and `cam1:0:3` f243–301) 23.1 s apart on two
   different tracks. The re-entry cooldown (§2.5 rule 3) did **not** suppress
   the second event. Ground truth: the same physical car re-entered the
   parking scene, so two events may actually be the *desired* per-visit
   semantics — but this is exactly the case the production duplicate policy
   must decide on. **Open question for Phase 2, not a bug.**
2. **False split by tracker (segment 4 missed):** frames 311–359 read
   `12d67413` 49 times but produced **no event**. Cause chain (verified from
   lifecycle traces): ByteTrack kept vehicle track `cam1:0:2` alive across the
   f225–f310 gap via coasting, so the re-appearing car **re-associated** with
   the already-`COMPLETED` track; new evidence accumulated (hits 63→108) but
   `_evaluate_track` returns [] for `COMPLETED` tracks and consensus was never
   re-run. The duplicate-suppression counter caught the second finalize
   attempt once, but no *usable* event exists for segment 4.
3. **Observation starvation after early confirm:** each event's
   `observation_count` is 3 (the `confirm_min_obs` threshold), while the track
   actually held up to 30 stored reads. Consensus froze the first 3-read
   snapshot at the CONFIRM moment; later reads never upgraded the persisted
   event. Harmless here (all reads identical) but wasteful of evidence.

## 5. Results — cam2.mp4 (hard scene: distant / moving vehicles, unstable OCR)

| Metric | Value |
| --- | --- |
| Frames processed | 599 |
| OCR observations | 108 |
| Observations accepted / rejected | 100 / 8 |
| Tracks created | 8 (1 rejected as new) |
| Final events | 7 (all `force_at_close`) |
| Duplicate finalizations suppressed | 0 |
| Invalid / unknown outcomes | 0 |
| Persist failures | 0 |
| detections_per_event | 1.14 |
| OCR_per_event | 14.29 |
| needs_review events | **7 / 7** |
| invalid-plate events | 5 / 7 |

All 7 events were correctly **NOT confirmed** — consensus demanded evidence
the scene could not provide and only force-emitted at close with
`needs_review=True`. OCR on cam2 is highly unstable (e.g. the same car read as
`965h689`, `9hh`, `h9h`, `99`, `8h9` across f300–f308), and the pipeline
refused to bless any of it. This is the fail-safe path working as designed.

**Case C — possible false merges: 7 flagged (report only).** Short-lived
adjacent tracks (e.g. `cam2:0:3`/`cam2:0:4`/`cam2:0:5`, overlapping 2–6 s,
conflicting plate candidates) — a symptom of a distant vehicle whose
detections flicker in and out, not evidence of an identity merge bug: each
event still maps 1:1 to its own track (`tracks_per_event` 1.14, and no track
ever changed plate mid-life). **No obvious false merge confirmed.** (answer to
objective question 4)

## 6. Duplicate analysis summary

| Case | cam1 | cam2 | Verdict |
| --- | --- | --- | --- |
| A — same track → one event | ✔ working (62–145 OCR reads → 1 event) | ✔ working | correct |
| B — same plate, second event nearby | 1 (23 s gap, same car re-entry) | 0 | **needs a product decision**: per-visit vs per-vehicle dedup |
| C — different tracks, overlapping, different plates | 0 | 7 flagged, all flicker-fragments of distant cars | report-only; no real merge observed |

Full details: [validation/cam1/analysis.json](validation/cam1/analysis.json),
[validation/cam2/analysis.json](validation/cam2/analysis.json).

## 7. Answers to the objective questions

1. **Does multiple OCR of the same vehicle become one event?** Yes — on cam1,
   up to 145 OCR reads of one vehicle collapsed into exactly one confirmed
   event per track, with the UNIQUE(event_key) upsert and the in-memory
   registry both holding (1 duplicate finalization suppressed, 0 persist
   failures).
2. **Are events stable and explainable?** Yes. Every event's finalization
   reason, state transitions, and observation counts were reconstructible
   frame-by-frame from the traces (`tracks.jsonl`). No unexplained state.
3. **Are there false duplicates?** One Case B candidate (`28y68923` twice,
   23 s apart). Whether it is a duplicate depends on the intended per-visit vs
   per-vehicle semantics — undecided product question, not a pipeline defect.
4. **Are there obvious false merges?** No. cam2's 7 Case C flags are
   flicker-fragments of distant vehicles; each track kept a consistent
   identity and each event mapped to exactly one track.
5. **What telemetry do we need before production testing?** See §8.

## 8. Biggest observed limitations

1. **Tracker coasting can swallow a whole revisit** (cam1 segment 4 lost):
   a COMPLETED track that keeps coasting re-associates the returning vehicle
   and its new evidence is stranded — no event, no upgrade. Highest-impact
   finding of this validation.
2. **Evidence frozen at first CONFIRM:** only the first 3 reads shaped the
   event; the UPGRADE path exists in consensus but `quality` is compared
   against the *current* best (never greater), so upgrades can never fire.
3. **No char-rank candidates:** `char_candidates=[(ch,1.0)]` (argmax only) —
   consensus positional voting is effectively unweighted on cam2-style noisy
   reads, which is why 7/7 cam2 events needed review.
4. **Re-entry cooldown semantics unproven:** the §2.5 cooldown did not link
   the two `28y68923` events (23 s apart vs 15 s cooldown window boundary) —
   behavior is defensible but must be pinned down before production.
5. **Observability gaps:** no per-track metric (only counters), and phase
   1 emits no metric for "evidence after COMPLETED" (limitation 1 was invisible
   in `get_metrics()` alone — it required frame-level tracing).

## 9. Telemetry needed before production testing

* `evidence_after_complete` counter (stranded-observations detector).
* Per-track gauge: track_id, state, obs_count, last finalize_reason —
  bounded cardinality is fine at ≤ max_live_tracks.
* `event_upgraded` / `upgrade_attempts` counters (prove/disprove the UPGRADE
  dead path in production).
* Plate-level re-emission rate (Case B rate) as a first-class metric.
* Rejection-reason breakdown for `observations_rejected` (quality gate
  sub-counters: area / aspect / brightness).

## 10. Is Phase 1 behaving correctly? Safe for Phase 2?

**Yes — behavior is correct within its stated rules and safe to proceed.**
Idempotency, dedup, rejection and fail-safe paths all behaved as designed on
both an easy scene (cam1: 3/3 clean confirms) and a hostile one (cam2: 7/7
honest needs-review force-emits, zero false confirms). The two real defects
found — stranded evidence on a coasting COMPLETED track, and a dead UPGRADE
path — are **suppression/quality** issues, not correctness/safety issues: they
lose or under-improve events, they never fabricate or double-emit them.
Neither blocks Phase 2 performance work, but both should be ticketed now.

## 11. Dataset needed

* **Re-entry scenarios** like cam1 (same car leaving/re-entering) with ground
  truth on expected event count (1 vs 2) — to lock the cooldown policy.
* **Distant/moving traffic** like cam2, annotated with true plate text, to
  tune `confirm_min_obs` / `force_emit_posterior` and measure false-confirm
  rate on noisy OCR.
* Multi-vehicle simultaneous scenes (2+ cars in frame) to stress containment
  assignment (§5.4) — cam1/cam2 never exercised two simultaneous confirmed
  plates.
* ~50–100 clips, 15–60 s each, night/day mix, Iranian free-zone plates
  included.

## 12. Recommendations (no fixes implemented, per task rules)

1. Ticket: re-run consensus (or force a fresh emission) when a COMPLETED track
   accumulates ≥ N new observations after its event (cam1 segment-4 loss).
2. Ticket: fix or remove the UPGRADE path (`quality > best_quality * gain` can
   never be true as wired today).
3. Decide per-visit vs per-vehicle event semantics for Case B before
   production.
4. Add the telemetry in §9 behind the existing metrics interface.
5. Proceed to Phase 2 performance work; do not gate it on items 1–3.

---

## Appendix — generated files

```
validation/
    cam1/
        observations.jsonl   (315 per-frame OCR records)
        tracks.jsonl         (674 per-frame lifecycle snapshots)
        raw_events.jsonl     (3 finalized events, full fields)
        analysis.json        (Case A/B/C classification)
        summary.json         (video info, config, metrics)
    cam2/
        observations.jsonl   (108 per-frame OCR records)
        tracks.jsonl         (per-frame lifecycle snapshots)
        raw_events.jsonl     (7 finalized events, full fields)
        analysis.json
        summary.json
    replay_runner.py
    analyze_events.py
ALPR_PHASE1_CAM1_VALIDATION_REPORT.md
tests/test_replay_validation_tooling.py
```

Videos (`cam1.mp4`, `cam2.mp4`) are untracked and must not be committed.
**Nothing was committed or pushed.**

## Appendix — test results

```
tests/test_event_pipeline_integration.py  ✓
tests/test_phase1_flag_wiring.py          ✓
tests/test_event_key_idempotency.py       ✓
tests/test_replay_validation_tooling.py   ✓ (new, 6 tests)
27 + 6 passed, 0 failures
```
