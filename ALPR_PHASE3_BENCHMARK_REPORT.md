# ALPR Phase 3 — Benchmark Report

**Date:** 2026-10-04 · **HEAD:** `f9bd7bb`
**Production code changed:** NO · **Production model changed:** NO
**Commit created:** NO · **Classification:** `MORE_DATA_REQUIRED`
**Command:** `python benchmarks/run_phase3.py`
**Results:** `benchmarks/results/phase3/` (8 JSON files +
`phase3_crop_cells.json`) · **Diagnostics:**
`benchmarks/audit/phase3/` (overlays, crop strips, OCR
examples, `diagnostics.html`; review status pending).

---

## Executive Summary

Phase 3 built the neutral evaluation infrastructure the
later phases need — instance-level dataset schema with
automated validation, canonical normalization, deterministic
IoU matching, leakage-proof splits, OCR/crop/temporal
metrics, a human annotation server, visual diagnostics,
and a one-command runner — and populated it with everything
honestly verifiable today: 2 verified cam1 plate instances
(62 frames), 9 provisional cam2 clusters (42 frames), and
**zero** box GT. On the verified set the results reproduce
Phases 2C/2D exactly (A 62/62 under every convention;
B 56/62 under `trunc`, 62/62 under `round`; paired table
56/6/0/0, McNemar p=0.03125). Detector precision/recall/F1
and IoU are reported as **NOT_AVAILABLE** (no box GT) —
they are not approximated by counts. No detector, OCR, crop
convention, or pipeline change is recommended. The dataset
is too small and too narrow for cross-camera or final
detector conclusions: **MORE_DATA_REQUIRED**.

## Dataset Composition

2 cameras · 2 sessions · 11 vehicle instances (2 verified,
9 provisional) · 104 annotations (62 verified text, 0
verified boxes) · 192 sampled frames (72 cam1 + 120 cam2)
· splits train 0 / validation 0 / test 11 (single
evaluation set; instance-level; leakage-free). Full
tables: `ALPR_PHASE3_DATASET_REPORT.md`.

## Ground Truth Methodology

cam1 text GT inherited from Phase 2B human visual review
with provenance preserved (raw kept verbatim; normalized +
ascii derived; types/regions recorded). cam2 staged as
provisional spatiotemporal clusters, text null, review
pending. Box GT absent by honest omission. Annotation
server (`benchmarks/phase3_annotate.py`) implements the
§15 workflow and passed a 10/10 end-to-end smoke test
(UI, all endpoints, save/edit/validation/resume; dataset
restored byte-identical).

## Annotation Quality

Dataset validation `valid=True` (104/104 records);
leakage check `leakage_free=True`; 82 Phase 3 unit tests
pass (schema, coordinates, normalization incl. the
۱۲د۶۷۴۱۳/12د67413 convergence case and Phase-2
canonical consistency, matching determinism, IoU,
splits, metrics, malformed handling).

## Camera Breakdown

| Camera | Frames | A detected | B detected | Verified instances |
| --- | ---: | ---: | ---: | ---: |
| cam1 (1920×1032, daylight) | 72 | 62 | 72 | 2 |
| cam2 (1920×1080, dusk) | 120 | 42 | 12 | 0 |

Counts are diagnostic-only, never recall (no box GT).

## Plate-Instance Breakdown

| Instance | Frames | A\|trunc exact | Dominant OCR | Dominant ratio |
| --- | ---: | ---: | ---: | ---: |
| `cam1_s001_v001` (28Y68923) | 41 | 41/41 | `28y68923` | 1.0000 |
| `cam1_s001_v002` (12D67413) | 21 | 21/21 | `12d67413` | 1.0000 |
| cam2 v001–v009 (provisional) | 1–11 each | n/a (unverified) | unstable (2–8 unique outputs) | 0.25–1.00 |

## Plate-Size Distribution

Measured crop widths (px): min 66 · p25 99 · median 138 ·
p75 227 · max 230. Observed buckets: 64–96, 96–128,
128–192 (plate B: 21 frames), 192–256 (plate A: 41
frames). The `lt64` and `ge256` buckets are **empty** —
the small-object regime the task targets has no verified
coverage, and cam2's sub-100-px plates are unverified.

## Detector Results

Detection counts (diagnostic): A 62/72 cam1, 42/120 cam2;
B 72/72 cam1, 12/120 cam2. Paired A/B on verified frames
(production OCR, `trunc`): both-correct 56,
A-correct/B-wrong 6, McNemar exact **p=0.03125** —
identical to Phase 2C. Only detectors with usable local
weights are evaluated (A, B); no third candidate exists
on disk. Fair-comparison parameters frozen and identical
(conf 0.50, iou 0.45, max_det 12, imgsz 640, CPU,
warm-up excluded). License: production assets under repo
LICENSE; IranPlate-Vision has no LICENSE file in the
checkout — evaluation-only use, recorded in its model
card.

## Localization Results

**NOT_AVAILABLE.** No plate-box GT exists, so IoU@0.5 /
IoU@0.75, mean/median/percentile IoU, precision, recall
and F1 cannot be computed. The matching layer
(`phase3_matching.py`: total-order greedy one-to-one IoU
matching) is unit-proven on synthetic boxes (13 tests)
and the runner reports `localization_available: false`
with an explicit diagnostic-only note wherever counts
appear. This is the single largest evidence gap and the
top Phase 4 prerequisite.

## Crop Results

Detector × convention × expansion × size-bucket × camera
× instance matrix (8 configs, 1504 records). Verified
cam1 exact: A is 62/62 under all conventions and at
1.00/1.03/1.10, collapsing to 32/62 at 1.05× and 60/62 at
1.07× (the collapse is entirely plate A: 11/41 at 1.05×);
B is 56/62 under `trunc`/`floor`, 62/62 under
`round`/`ceil` and at 1.03–1.07×, 58/62 at 1.10×.
Per-cell table: `phase3_crop_cells.json`. The matrix
demonstrably shows expansion making performance worse —
as required, it does not assume expansion helps.
Production baseline remains `trunc`; `round` was measured
only.

## OCR Results

Production OCR (char-model `08CF1BB9…`, conf 0.3) on 62
verified crops: exact 62/62 (A, all conventions),
56/62→62/62 (B, trunc→round); char accuracy 1.0 / 0.9892→1.0;
invalid 0/62 (A), 6/72→0/72 (B); failed 0 everywhere
verified. No second OCR candidate has runnable weights
(hezar/PLR/yolo11 weights absent), so the "future OCR"
dimension is infrastructure-only in this phase.
Breakdowns recorded by camera, instance, width bucket,
readability (single `PENDING_HUMAN_REVIEW` bucket —
honest), convention, detector, and objective quality
bucket.

## Temporal Consistency

Per-instance evidence rows (`phase3_temporal_consistency.json`),
the exact input a future consensus engine (and Imajev-4B)
would consume: cam1 v001 — 41 frames, 41 valid, 1 unique
output, dominant ratio 1.0, 41 exact, best frame 0;
v002 — 21/21/1/1.0/21/best 165. cam2 clusters show the
opposite regime (e.g. v005: 11 frames, 8 unique outputs,
dominant `235h284999` at 0.36) — precisely the ambiguity
a consensus layer must resolve, with no verdict imposed
here. Event-level readiness: structures ready, no
consensus and no Imajev-4B implemented (per scope).

## Hard Cases

83 curated entries (`hard_cases.jsonl` + results copy):
23 tiny plates (<96 px), 6 verified wrong reads, 25
invalid-grammar outputs, 5 confusing-character frames
(plate-A ی/ع ambiguity), 22 unverified cam2 samples, 0
B-misses on verified cam1 (B detects all 62). Each entry
carries its evidence and no verdict — the future
Imajev-4B evaluation set seed.

## Statistical Analysis

* Sample sizes reported with every rate (numerator +
  denominator, never bare percentages).
* Wilson 95% intervals on exact rates (e.g. 62/62 →
  [0.94, 1.00] — wide by construction at n=62).
* Paired A/B comparison on identical frames + McNemar
  exact (p=0.03125 at `trunc`; the `round` pairing is
  62/62 with 0 discordant pairs).
* No superiority is declared: n=2 instances on 1 camera
  cannot support one, and the report does not try.

## Failure Analysis

The only verified failure mode remains the six
`12d674913` reads (B under `trunc`/`floor`, plate B only),
mechanistically explained in Phase 2D (dark background
row pulled in by truncation). New in Phase 3: the 1.05×
expansion collapse is localized to plate A (11/41) while
plate B stays 21/21 — expansion harms the *larger* plate,
consistent with margin content (vehicle body/lighting
gradient) entering the crop. cam2 failures are
uninterpretable without GT and are catalogued, not
explained.

## Reproducibility

`python benchmarks/run_phase3.py` regenerates dataset +
all artifacts. Verified-layer outputs are exactly
reproducible across processes: integer bboxes 62/62
identical, verified OCR 62/62 and 56/62 identical.
**New measured finding:** float-level detector outputs
jitter ≈0.006 px across processes (torch CPU threaded
reduction nondeterminism; decode proven byte-identical
4/4; model proven deterministic on frozen bytes 13/13
and 6/6). Consequence: integer crops and all verified
metrics are unaffected (0.006 px ≪ 1 px quantization
step), but detection *counts* flip for scores within
≈0.005 of the 0.50 cutoff (3 cam2 frames at
0.501–0.504 differed between runs; A@1.05 read 32/62 vs
33/62 across runs). All affected data is unlabeled and
diagnostic-only; no verified conclusion moves. This
validates the design (stable integer-crop + verified-text
measurement layer; counts never treated as recall) and
is recorded as a standing caveat for count-based
diagnostics.

## Limitations

1. Two cameras only — no cross-camera conclusions.
2. Two verified instances — no meaningful splits, no
   significance claims.
3. No box GT — no localization metrics (top gap).
4. No cam2 text GT (in-session unverifiable; review
   assets staged).
5. No human readability ratings.
6. One physical plate drives the entire A/B gap.
7. Only 2 detectors + 1 OCR runnable (weight availability).
8. Empty `lt64`/`ge256` verified buckets.
9. Single-machine CPU latency; count diagnostics carry
   threshold-boundary jitter.
10. Visual diagnostics generated but not human-reviewed
    (no image input in-session).

## Production Impact

**None.** Production source, weights, crop convention,
thresholds, preprocessing, API, DB, and Flutter are
untouched (verified by `git diff` at start and end).
`round` was measured and remains unintegrated; Detector
B remains unintegrated. Phase 3 is evaluation-only and
leaves no runtime footprint.

## Recommendation for Phase 4

Do not begin Phase 4 implementation. Evidence-ranked
options: **Phase 4A (detector benchmark with proper box
GT)** is the correct next phase — but it is *blocked on
human annotation*, not on code: the blocker list is (1)
a vision-capable reviewer annotating plate boxes (+ cam2
text + readability) via `phase3_annotate.py`, (2) a third
genuine camera source, (3) ≥10 verified instances/camera.
Phase 4B (OCR robustness) becomes meaningful once the
`lt64` bucket has verified samples; 4C (temporal
consensus) once ≥5 multi-frame verified instances exist;
4D (Imajev-4B) once hard cases have verified labels.
Concretely: run the annotation pass first; re-run
`run_phase3.py`; only then scope 4A.
