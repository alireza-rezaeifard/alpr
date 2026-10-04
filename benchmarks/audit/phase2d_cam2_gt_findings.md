# Phase 2D — cam2 ground-truth attempt: findings

**Status: `CAM2_GT_UNAVAILABLE` — all 22 cam2 samples remain UNLABELED.
No accuracy, recall, or superiority claim is made from cam2.**

## What was attempted (2026-10-04)

1. **Sample set identified.** The "22 cam2 samples" are the original
   Phase-2B cam2 crops (frames 205, 210, 300, 305, 315, 320, 325, 330,
   335, 340, 345, 350, 355, 485, 495, 500, 505, 510, 530, 540, 545,
   555), confirmed against `benchmarks/dataset/ground_truth.jsonl`
   (84 rows = 62 cam1 verified + 22 cam2 UNLABELED).
2. **Review assets produced.** `benchmarks/audit/cam2_gt/` now holds, for
   every sample: the native-resolution crop, a 4x nearest-neighbor zoom
   (no interpolation blur), a full-frame context sheet with the detector
   box drawn, and `manifest.json` with exact float/integer bbox, crop
   geometry, confidence and clipping flag. Detector inference used the
   frozen protocol (conf 0.5, iou 0.45, max_det 12, imgsz 640).
3. **Searched the repo for independent labels.** `validation/cam2/*`
   (raw_events.jsonl, tracks.jsonl, summary.json) contains only
   OCR-derived hypotheses from the replay pipeline — every event is
   `status: unconfirmed`, `needs_review: true`, with low agreement
   ratios (0.18–0.64). Those are model outputs, not ground truth, and
   are excluded by the task's "do NOT use OCR output as ground truth"
   rule. `benchmarks/dataset/gt_labels.json` records the same candidates
   (production `25H28999`, hezar `25H28499`, yolo11 `25H28494`) with
   `verified: false`.
4. **Visual review attempted and blocked.** This session's reviewer
   model does not accept image input, so the required visual glyph
   comparison against the raw video cannot be performed in-session.

## Why no label was forced

The task rules are explicit: only visually verified labels count as GT;
`verified: false` must be recorded when a plate cannot be read
conclusively; OCR output must never become GT. The cam2 plates are
66–119 px wide (≈8 px per glyph) at 1920×1080 — below the resolution
at which the middle/trailing digits can be read conclusively without a
human reviewer. The existing cross-model candidates disagree
(`25H28999` vs `25H28499` vs `25H28494` vs track-level
`235h284999`), which is itself evidence of ambiguity, not of a label.

## What would unblock cam2

A vision-capable human reviewer with ~1 hour, using the prepared PNGs in
`benchmarks/audit/cam2_gt/` (native crop + 4x zoom + context per
sample) against the restored raw `cam2.mp4` (SHA-256
`237E30A0…D77D64F1`, 599 frames, 1920×1080 @ 25 fps). Labels should
be appended to `benchmarks/dataset/gt_labels.json` with
`verified: true` and frame ranges; until then every cam2 number in this
phase is diagnostic-only.

## Impact on Phase 2D conclusions

None of the Phase 2D accuracy figures involve cam2. Cam1 (62 verified
frames, 2 plates) carries all accuracy claims. The crop-fix decision
below rests on cam1 only; cam2 contributes invalid/failed rates, crop
geometry, OCR-output stability and clipping diagnostics — none of which
are accuracy.
