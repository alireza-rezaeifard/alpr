# ALPR Phase 3 — Dataset Report

**Date:** 2026-10-04 · **Dataset:** `phase3` v3.0.0
**HEAD:** `f9bd7bb` · **Production changed:** NO
**Command:** `python benchmarks/run_phase3.py`
**Manifest:** `benchmarks/dataset/dataset_manifest.json`

## 1. Composition

| Dimension | Value |
| --- | --- |
| Cameras | 2 (`cam1` 1920×1032 @31fps, 360 frames; `cam2` 1920×1080 @25fps, 599 frames) |
| Sessions | 2 (`cam1_s001`, `cam2_s001` — one continuous recording each) |
| Vehicle instances | 11 (2 verified + 9 provisional) |
| Verified vehicle instances | 2 (`cam1_s001_v001` plate A, `cam1_s001_v002` plate B) |
| Annotations (`gt/plates.jsonl`) | 104 (62 verified text + 42 pending review) |
| Verified text labels | 62 (41× plate A `۲۸ی۶۸۹۲۳`, 21× plate B `۱۲د۶۷۴۱۳`) |
| Verified plate boxes | **0** (pending human annotation) |
| Readable frames (human-rated) | 0 (all `PENDING_HUMAN_REVIEW`) |
| Unreadable frames (human-rated) | 0 (same reason) |
| Sampled frames | 192 (72 cam1 + 120 cam2, interval 5) |
| Splits | train 0 / validation 0 / test 11 (single evaluation set; rationale recorded) |
| GT version | `phase2b_labels_v1+phase3_build_v1` |

Plate width (measured, px): min 66 · p25 99 · median 138 ·
p75 227 · max 230.

## 2. Ground-truth methodology

* **cam1 text GT is inherited, not invented.** The two plate
  texts come from `benchmarks/dataset/gt_labels.json` (Phase 2B
  human/agent visual review: review sheet + glyph zooms,
  digits cross-checked against multi-frame consensus). The
  Phase 3 builder carries them with provenance
  `annotator=phase2b_human_visual_review`, adds the raw /
  normalized / ascii triple, the `civilian` type, and the
  region codes (`23`, `13`) derived from the ASCII form.
  Nothing about the transcription was altered.
* **cam2 has no GT.** Its 9 vehicle instances are
  *provisional programmatic clusters* (spatiotemporal
  grouping of Detector-A detections, parameters documented
  in `phase3_dataset.cluster_detections`). All 42 cam2
  annotations are `pending_human_review` with null text.
* **Box GT does not exist.** Every `plate_bbox` is null with
  `box_annotation_status=pending_human_annotation`. Detector
  boxes are stored under `measurements` / frame `detections`
  and are never copied into GT fields.
* **Readability is never guessed.** Every annotation is
  `PENDING_HUMAN_REVIEW`; the objective `quality_bucket`
  (from width/blur/brightness/contrast) is the measurable
  proxy and is stored separately.
* **Annotation workflow exists and works:**
  `python benchmarks/phase3_annotate.py` serves
  frame display, zoom, box drawing, transcription,
  type, readability, instance assignment, quality
  flags, server-side validation, atomic save,
  reopen/edit, and resume. Smoke-tested end-to-end
  (10/10 checks: UI, dataset/frames/annotations/
  frame endpoints, valid save, persistence across
  restart, edit-by-id, invalid-record rejection;
  dataset restored byte-identical). No human
  annotation has been performed through it yet.

## 3. Annotation quality

* `validate_dataset`: **valid=True**, 0 records with errors
  (104 records checked against the §16 rule set).
* `check_leakage`: **leakage_free=True** — no instance in two
  splits, no frame under two instances, every annotated
  instance has a split.
* 82 unit tests cover schema, validation, normalization,
  matching, splits, leakage, and metrics
  (`tests/test_phase3_*.py`), all passing.
* Duplicate frame/instance assignments, inverted/negative/
  out-of-frame boxes, empty verified text, malformed boxes,
  and impossible dimensions are all rejected by tests;
  difficult plates (poor quality, occlusion, unusual types)
  are accepted by tests.

## 4. Plate-instance breakdown (verified)

| Instance | Plate (raw / ascii) | Type | Region | Frames | Width bucket |
| --- | --- | --- | --- | --- | --- |
| `cam1_s001_v001` | `۲۸ی۶۸۹۲۳` / `28Y68923` | civilian | 23 | 41 | 192–256 |
| `cam1_s001_v002` | `۱۲د۶۷۴۱۳` / `12D67413` | civilian | 13 | 21 | 128–192 |

Notes: plate A carries the documented ی/ع glyph ambiguity
(recorded in `notes`, surfaced as a hard case). Both
instances exceed the preferred 10–20 frames/instance
(41 and 21 temporally spread observations).

## 5. Cam2 provisional clusters (NOT GT)

9 clusters from 42 Detector-A detections (120 sampled
frames). Centres/widths/frame-ranges are in
`gt/vehicles.jsonl` + `phase3_temporal_consistency.json`.
The +2 clusters vs the pre-run estimate (7) come from 3
threshold-boundary detections (frames 200/255/430,
confidences 0.501–0.504) — see the benchmark report's
reproducibility section. Clusters are evidence for a
human to confirm, not instances to measure from.

## 6. What is missing (explicit)

1. Third (and further) genuine camera sources — cross-camera
   conclusions are impossible.
2. ≥10 verified plate instances per camera (have 2, one camera).
3. Human plate-box annotations (have 0) → no localization metrics.
4. Human cam2 text verification (have 0) → no cam2 accuracy.
5. Human readability ratings (have 0) → breakdowns use the
   objective quality bucket.
6. Additional runnable detector/OCR weights (only A, B, and
   production OCR exist on disk).

## 7. Reproducibility

`python benchmarks/run_phase3.py` rebuilds the dataset and
all benchmark artifacts from the raw videos + frozen
protocol. Verified-layer outputs are exactly reproducible
across processes (integer bboxes 62/62 identical, verified
OCR 62/62 + 56/62 identical); threshold-boundary detection
counts on unlabeled frames jitter by ±frames at conf≈0.50
(documented in the benchmark report §16).
