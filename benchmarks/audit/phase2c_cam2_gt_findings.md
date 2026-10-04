# Phase 2C — cam2 ground-truth recovery: findings

**Status: `CAM2_GT_UNAVAILABLE` — no verified cam2 labels exist for Phase 2C.
No accuracy, recall, or superiority claim is made from cam2.**

## What was tried

1. **Frame extraction for human review.** `benchmarks/build_cam2_review.py` was
   written to dump the 120 sampled cam2 frames (interval 5 of 599) plus every
   detected crop into a review sheet. `benchmarks/dataset/2c/cam2/` currently
   holds 709 files (sampled frames + A/B crops), and the fidelity page
   (`benchmarks/audit/phase2c_crop_fidelity.html`, 62 tiles) covers the paired
   cam1/cam2 crop comparison visually. This material exists but **no human
   read of the cam2 plates was completed**, so none of it is ground truth.
2. **Delegated labelling (`cam2-labeler` agent).** Launched twice; both attempts
   died on network errors with only partial work. No labels were committed.
3. **Source-video incident.** On 2026-10-03 16:43–16:44 a Cline checkpoint
   restore deleted the gitignored `cam2.mp4` (129,390,859 B raw). It was
   recovered on 2026-10-04 from an unreachable blob in the Cline stash pack
   (`028148c5…`, verified: 599 frames, 1920×1080 @ 25 fps, frame-210
   NCC = 0.99991 vs the surviving processed copy). The raw video is back in
   place, so labelling is *possible* — it is simply *not done*.

## What cam2 contributes to Phase 2C today

Diagnostic counts only (no labels, §15 of the report):

| | A | B |
| --- | ---: | ---: |
| frames with detection | 39/120 | 12/120 |
| median width (px) | 83 | 97 |
| OCR invalid | 33/39 | 9/12 |
| OCR failed | 13/39 | 0/12 |

With n = 39 vs n = 12 and zero labels, none of these differences is
interpretable as detector quality. They are reported so the asymmetry is
visible, not so it can be ranked.

## What would unblock cam2

A human read of the ≤ 51 detected cam2 crops (39 A + 12 B, heavy overlap)
against the restored `cam2.mp4`, recorded as `gt_labels.json`-style verified
ranges. Estimated effort: under an hour of labelling. Until then the Phase 2C
classification rests on the 62 verified cam1 crops alone, and Limitation 1
(zero verified coverage of the sub-100 px regime) stands as written.
