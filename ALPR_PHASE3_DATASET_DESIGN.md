# ALPR Phase 3 — Dataset Design

**Date:** 2026-10-04 · **Status:** DESIGN + IMPLEMENTATION
**Design goal:** a *neutral* evaluation dataset strong enough to
falsify current assumptions — not one tuned to any prior
benchmark result.

## 1. Design principles

1. **Physical instances, not OCR strings.** A vehicle visible
   in N frames is ONE vehicle instance with N frame
   observations. Frame-level metrics never count a vehicle
   twice; instance-level metrics are the primary unit.
2. **GT is independent of measurement.** Detector boxes, OCR
   crops and expanded crops are *measurements*, stored
   separately from human-annotated GT. A detector box is never
   copied into a GT field.
3. **Annotation status is explicit.** Every annotation carries
   `annotation_status` ∈ {`verified`, `pending_human_review`,
   `provisional_programmatic`}. Only `verified` feeds
   accuracy metrics.
4. **Honest emptiness over fabricated breadth.** Where the
   evidence does not exist (cam2 text, all box GT), the field
   is null and the metric is `NOT_AVAILABLE`.
5. **Reproducible sampling.** Fixed interval, fixed seeds,
   documented frame selection.

## 2. Canonical hierarchy

```text
benchmarks/dataset/phase3/
  manifest.json                 dataset-level manifest
  cameras/
    cam1.json                   camera record (resolution, fps, …)
    cam2.json
  sessions/
    cam1_s001.json              one continuous recording
    cam2_s001.json
  gt/
    vehicles.jsonl              one record per physical vehicle instance
    plates.jsonl                one record per annotated plate frame
    frames.jsonl                one record per sampled frame
  splits/
    train.json  validation.json  test.json   instance-level split
  hard_cases.jsonl              curated difficult examples
benchmarks/results/phase3/      benchmark outputs (JSON + diagnostics)
benchmarks/audit/phase3/        visual diagnostic artifacts
```

Record relationships:

```text
camera (cam1)
  └── session (cam1_s001)
       └── vehicle_instance (cam1_s001_v001)   ← split unit
            ├── plate_instance (1 plate per vehicle here)
            │    ├── frame observation 180  (annotation row)
            │    ├── frame observation 185
            │    └── …
```

## 3. Schema

### 3.1 Camera record (`cameras/camN.json`)

```json
{"camera_id": "cam1", "source": "cam1.mp4",
 "width": 1920, "height": 1032, "fps": 30.99,
 "frame_count": 360, "sha256": "E3FD570F…",
 "role": "production-camera-1",
 "diversity_notes": "fixed roadside camera, daylight"}
```

### 3.2 Vehicle instance (`gt/vehicles.jsonl`)

```json
{"vehicle_instance_id": "cam1_s001_v001",
 "camera_id": "cam1", "session_id": "cam1_s001",
 "split": "test",
 "first_frame": 0, "last_frame": 144,
 "plate_instances": ["cam1_s001_v001_p001"],
 "annotation_status": "verified_text_pending_box"}
```

### 3.3 Plate annotation (`gt/plates.jsonl`) — the core record

```json
{
  "annotation_id": "cam1_s001_v001_p001_f000180",
  "camera_id": "cam1",
  "session_id": "cam1_s001",
  "vehicle_instance_id": "cam1_s001_v001",
  "plate_instance_id": "cam1_s001_v001_p001",
  "frame_id": 180,

  "plate_bbox": null,              // human-annotated visible plate
  "box_annotation_status": "pending_human_annotation",

  "plate_text_raw": "۱۲د۶۷۴۱۳",   // human transcription, never altered
  "plate_text_normalized": "۱۲د۶۷۴۱۳",
  "plate_text_ascii": "12D67413",  // canonical comparison form
  "plate_type": "civilian",
  "region_code": "13",

  "readability": "GOOD",           // EXCELLENT|GOOD|FAIR|POOR|UNREADABLE
  "quality_bucket": "GOOD",        // from measurable properties
  "occluded": false,
  "truncated": false,

  "measurements": {                // measured properties (NOT GT)
    "plate_width_px": null, "plate_height_px": null,
    "aspect_ratio": null, "blur_score": null,
    "brightness": null, "contrast_std": null
  },

  "annotation_status": "verified", // verified|pending_human_review|provisional_programmatic
  "annotator": "phase2b_human_visual_review",
  "verified_at": "2026-09-30",
  "notes": "letter glyph ambiguous ی/ع recorded as production charset y"
}
```

**Coordinate convention (frozen):** integer pixel coordinates,
`x1 <= x2`, `y1 <= y2`, `x1,y1 >= 0`, `x2 <= image_width`,
`y2 <= image_height`. Start-inclusive / end-exclusive
(`[x1, x2)` × `[y1, y2)`), identical to NumPy slicing and to
the Phase 2D frozen crop semantics. No normalized coordinates
are stored; pixel coordinates are canonical.

### 3.4 Frame record (`gt/frames.jsonl`)

```json
{"camera_id": "cam1", "session_id": "cam1_s001", "frame_id": 180,
 "sampling": "interval_5", "in_verified_range": true,
 "detections": {"detector_a_current": {...}, "detector_b_iranplate": {...}}}
```

### 3.5 Splits (`splits/*.json`)

```json
{"split": "test", "vehicle_instance_ids": ["cam1_s001_v001", "cam1_s001_v002"],
 "rationale": "…"}
```

**Split strategy:** split at the *vehicle-instance* level
(never the frame level) so no physical plate appears in two
splits. With only 2 verified instances a 60/20/20 split is
not statistically meaningful, so **all verified instances are
assigned to the single evaluation (`test`) split**; `train`
and `validation` exist and are empty, with the rationale
recorded. No significance is manufactured.

## 4. Plate taxonomy (extensible)

`plate_type` ∈ {`civilian`, `taxi`, `government`, `military`,
`diplomatic`, `police`, `motorcycle`, `free_zone`, `other`,
`unknown`}. Unknown plates are **never** forced into
`civilian`. `region_code` is the two-digit registration block
where legible.

## 5. Quality buckets

`readability` (human): `EXCELLENT` / `GOOD` / `FAIR` /
`POOR` / `UNREADABLE`, plus `PENDING_HUMAN_REVIEW` until a
human rates it. `quality_bucket` is derived from measurable
properties (plate width, blur, brightness, contrast, occlusion,
truncation) so subjective quality is never the only metric.
Both are stored; metrics may break down by either.

## 6. Sampling

Every 5th frame of each raw video (interval 5) — identical to
Phase 2B/2C/2D, keeping cross-phase comparability. Within each
cam1 verified instance this yields temporally spread
observations spanning early/middle/late of the instance's
range (plate A: 41 sampled frames; plate B: 23 sampled frames
— both above the preferred 10–20 per instance). Cam2 keeps
all 120 sampled frames so its provisional clusters are
observable; the 22 Phase-2B samples are flagged
`phase2b_sample: true`.

## 7. Detection matching policy (deterministic)

1. Score every (prediction, GT) pair by IoU.
2. Sort candidate pairs by (IoU desc, confidence desc,
   x1, y1, x2, y2 asc) — total order, no randomness.
3. Greedy one-to-one assignment: a prediction matches at most
   one GT and vice versa.
4. Matched pairs with IoU ≥ τ (τ = 0.5 default; 0.75 also
   reported) are TP; unmatched predictions are FP; unmatched
   GT are FN.
5. No double TP credit for one plate, ever.

Implemented in `benchmarks/phase3_matching.py`, unit-tested
on synthetic boxes (the real dataset has no box GT yet, so the
detection benchmark reports `NOT_AVAILABLE` and the matching
layer is proven by tests + a synthetic smoke fixture).

## 8. Crop evaluation conventions (benchmark-only)

`trunc` (production baseline, frozen), `floor`, `round`,
`ceil`; expansion ∈ {1.00, 1.03, 1.05, 1.07, 1.10},
centre-preserving, applied in float space before integer
conversion. Production behavior is never modified; these are
measurement transformations of already-detected boxes.

## 9. OCR evaluation rules (kept distinct)

* **exact** — normalized strings equal.
* **character accuracy** — 1 − Levenshtein/max_len over the
  canonical comparison form.
* **edit distance** — raw Levenshtein.
* **invalid** — output violates the Iranian plate grammar
  (production validator, unchanged).
* **failed** — empty OCR output.

## 10. Temporal consistency (per vehicle instance)

`n_frames`, `n_valid_reads`, `unique_ocr_outputs`,
`dominant_output`, `dominant_ratio`, `exact_frame_count`,
`best_frame` (highest-confidence exact read). This is the
evidence base a future event-level consensus engine (and
Imajev-4B ambiguity resolution) would consume; Phase 3
structures it but implements no consensus and no Imajev-4B.

## 11. Data-leakage controls

* Splits at vehicle-instance level only.
* `tests/test_phase3_splits.py` asserts no instance appears in
  two splits and no frame appears under two instances.
* The runner refuses to compute cross-split comparisons.

## 12. What Phase 3 deliberately does NOT do

* No detector/OCR/crop convention is promoted to production.
* No production preprocessing, threshold, or crop change.
* No Imajev-4B, no consensus engine, no tracker changes.
* No fabricated camera diversity, no invented cam2 text, no
  detector-derived GT boxes.
