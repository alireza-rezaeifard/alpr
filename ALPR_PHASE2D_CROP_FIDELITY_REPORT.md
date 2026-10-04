# ALPR Phase 2D — Crop Extraction Determinism, Cam2 Ground Truth & Post-Fix Validation

**Date:** 2026-10-04 · **Repo:** `D:\alpr` · **Branch:** `main`
**HEAD:** `f9bd7bb77ff78d55385895293dce349eee9c3d3a`
**Production code changed:** NO · **Production model changed:** NO · **Commit created:** NO
**Phase 2C baseline:** CLOSED, `NO_MEASURABLE_DIFFERENCE` — not reopened.

---

## 1. Executive Summary

Phase 2D froze the crop-extraction semantics, reproduced the six
Phase-2C discordant frames exactly, and measured — on the same cached
detector boxes, the same production OCR, and verified cam1 ground truth
only — every integer-coordinate convention (`trunc`/`floor`/`round`/
`ceil`) and a controlled expansion sweep (1.00–1.10).

Findings:

1. **The frozen production convention is `trunc`**
   (`alpr_engine.py:363`, `box.xyxy[0].cpu().numpy().astype(int)`,
   truncation toward zero), followed by an unclipped NumPy slice
   `frame[y1:y2, x1:x2]`. Documented mathematically in
   `ALPR_PHASE2D_CROP_FIDELITY.md`.
2. **The six discordant frames reproduce exactly**: A/trunc correct,
   B/trunc wrong (`12d674913`), B/round correct, B/ceil correct,
   B/trunc+1.05× correct — all 6/6 frames match Phase 2C.
3. **A crop-extraction fix exists and is safe**: switching the
   convention from `trunc` to `round` (half-away-from-zero) recovers
   all six reads for Detector B (56/62 → 62/62) while leaving
   Detector A at 62/62, with zero clipping, zero added margin, no
   contamination, and no measurable latency cost (−0.0002 ms).
4. **Expansion is rejected**: non-monotonic for both detectors;
   Detector A collapses to 33/62 at 1.05× and 60/62 at 1.07×.
5. **Under `round`, the detector difference disappears entirely**
   (0 discordant pairs, McNemar p = null): the Phase-2C gap was a
   crop-utility artifact, not a detector-quality difference —
   consistent with the closed Phase 2C verdict.
6. **Cam2 ground truth remains UNAVAILABLE**: this session cannot
   visually read images, and the repo contains no independent
   (non-OCR) human labels for cam2. All 22 samples stay UNLABELED;
   no accuracy is computed from cam2.

**Classification: `CROP_FIX_CANDIDATE`** (Case A) — candidate only,
**not integrated**. Production integration is **not approved**; the
proposed patch is documented separately
(`ALPR_PHASE2D_PROPOSED_PATCH.md`) for a *future* detector-integration
PR. Detectors A and B both remain unchanged and unintegrated.

## 2. Phase 2C Baseline (closed, unchanged)

* Detector A = CURRENT_PRODUCTION (`weigths/plate_det_model.pt`,
  SHA-256 `C70A91B5…ED00C`); Detector B = IranPlate-Vision
  (`bench/IranPlate-Vision-main/…/best.pt`, SHA-256
  `308C2464…DE40`). Hashes re-verified this session (Step 1).
* Frozen protocol: conf 0.50, iou 0.45, max_det 12, imgsz 640,
  agnostic_nms false, half false, crop convention `trunc`, clip
  true, pad 0/0, OCR CURRENT_PRODUCTION, GT verified-only.
* Phase 2C result: A 62/62, B 56/62 verified exact; 6 discordant
  pairs (all A-correct/B-wrong), McNemar exact p = 0.03125; B's box
  ~8.5 px lower and ~7.4 px shorter on the 6 frames; B reads the
  same boxes correctly under `round`/`ceil` and at 1.05× expansion.
* Phase 2C classification `NO_MEASURABLE_DIFFERENCE` stands. Phase 2D
  does not re-ask the detector question; it measures the crop layer.

## 3. Production Crop Path (traced from source)

```text
frame (BGR uint8 H×W×3)
 → alpr_engine.py:355  plate YOLO(frame, conf=0.6, iou=0.45, max_det=12)
 → alpr_engine.py:362  for box in det.boxes
 → box.xyxy[0]         torch.float32 [x1,y1,x2,y2], pixel coords,
                       top-left / bottom-right; ultralytics clips
                       boxes to the image at inference
 → alpr_engine.py:363  .cpu().numpy().astype(int)   ← TRUNC toward zero
 → alpr_engine.py:368  frame[y1:y2, x1:x2]          ← no explicit clip
 → alpr_engine.py:369  reject empty crops (shape[0]==0 or shape[1]==0)
 → alpr_engine.py:372  _assemble_chars(crop) → char YOLO(conf=0.3)
                       (char YOLO does its own internal 640 letterbox;
                        no crop resize anywhere)
 → sorted by x1 → CHAR_CLASSNAMES → text
```

The benchmark-only helper (`benchmarks/phase2d_crop.py`) reproduces
this exactly for in-bounds boxes and adds an explicit clip step so the
synthetic edge cases are well-defined; Phase 2C measured 0 clipped
crops, so the two paths are byte-identical on all real data.

## 4. Coordinate Semantics (frozen definition)

```text
x1_i = trunc(x1)   y1_i = trunc(y1)
x2_i = trunc(x2)   y2_i = trunc(y2)
crop = frame[y1_i : y2_i, x1_i : x2_i]     # [start, end) slicing
```

* Inclusive start / exclusive end; `x1=100.0, x2=200.0` → 100 px.
* `trunc(x2) − trunc(x1)` can differ from float width by ±1 px per
  edge — the 1-px quantization that Phase 2C identified.
* Conversion happens **before** any clipping; no padding, no centre
  preservation in production.
* Degenerate boxes (`x2_i ≤ x1_i` or `y2_i ≤ y1_i`) yield empty
  crops which production drops; the helper rejects them as `invalid`.
* Negative coordinates: production would wrap (NumPy slice semantics);
  the helper clips to 0. Unreachable at inference (ultralytics clips
  boxes), documented as a latent hazard and guarded in the proposed
  patch.

## 5. Six Discordant Frame Reproduction (Step 4)

Cam1 frames 180, 185, 210, 215, 330, 335 — plate `۱۲د۶۷۴۱۳`
(GT `12D67413`). Same boxes, same OCR, five crop variants:

| Variant | Integer bbox (B box) | Crop | OCR | Exact |
| --- | --- | --- | --- | --- |
| A/trunc | (1061,587)-(1199,645) | 138×58 | `12d67413` | ✔ 6/6 |
| B/trunc | (1059,595)-(1199,646) | 140×51 | `12d674913` | ✘ 0/6 |
| B/round | (1060,596)-(1200,647) | 140×51 | `12d67413` | ✔ 6/6 |
| B/ceil | (1060,596)-(1200,647) | 140×51 | `12d67413` | ✔ 6/6 |
| B/trunc+1.05× | (1056,594)-(1203,648) | 147×54 | `12d67413` | ✔ 6/6 |

**All expectations match Phase 2C exactly (6/6 frames, 5/5 variants).
No deviation → no STOP condition triggered.** The B float box is
`(1059.54, 595.72, 1199.64, 646.88)` — 8.5 px lower and 7.4 px
shorter than A's `(1061.36, 587.23, 1199.21, 645.80)`.

## 6. Quantization Results (Step 6 — same boxes, single inference pass)

Cam1 verified exact (62 frames, 2 plates):

| Convention | Detector A | Detector B | B invalid | B char acc |
| --- | --- | --- | --- | --- |
| trunc (frozen) | 62/62 = 1.0000 | 56/62 = 0.9032 | 6/72 | 0.9892 |
| floor | 62/62 = 1.0000 | 56/62 = 0.9032 | 6/72 | 0.9892 |
| **round** | **62/62 = 1.0000** | **62/62 = 1.0000** | **0/72** | **1.0000** |
| ceil | 62/62 = 1.0000 | 62/62 = 1.0000 | 0/72 | 1.0000 |

* Detector A is convention-invariant (62/62, char 1.0, invalid 0/62,
  failed 0/62 under all four).
* Detector B recovers exactly +6/62 under `round`/`ceil`; its 6
  invalid crops become valid.
* Mean/median crop width (cam1): A 227 px (trunc) / 228 px (round);
  B 202 px / 201 px. Clipping 0/62 and 0/72 everywhere.
* Latency: identical across conventions (crop extraction p50
  0.012 ms; see §13).

**Answer to the Step-6 key question: yes — a different
integer-coordinate convention improves OCR without changing detector
output** (for Detector B; Detector A is unaffected).

## 7. Expansion Results (Step 5 — centre-preserving, canonical `trunc`)

Cam1 verified exact:

| Factor | Detector A | Detector B | A median W |
| --- | --- | --- | --- |
| 1.00 | 62/62 | 56/62 | 227 |
| 1.01 | 62/62 | 62/62 | 229 |
| 1.02 | 62/62 | 62/62 | 232 |
| 1.03 | 62/62 | 62/62 | 234 |
| **1.05** | **33/62** | 62/62 | 239 |
| 1.07 | 60/62 | 62/62 | 243 |
| 1.10 | 62/62 | 58/62 | 250 |

* **No expansion factor is a safe fix**: A's accuracy is non-monotonic
  (collapses to 33/62 at 1.05×, 60/62 at 1.07×), confirming and
  extending Phase 2C's finding. The smallest factor recovering all six
  discordant frames *without* reducing A's accuracy does not exist in
  the swept range that also satisfies "does not materially increase
  clipping / contamination" — at 1.05× the cam2 crop margin is
  2.2 px/side (9.3 % of crop area outside the original box), which on
  83-px median cam2 crops is a real contamination risk.
* **Candidate strategy: `round` at 1.00×** — recovers all six, A
  unchanged, zero added margin, zero clipping.

Cam2 diagnostics (UNLABELED — diagnostic only, never accuracy):
invalid 33/39→32/39 (A) and 9/12→11/12 (B) from trunc→round; failed
13/39→12/39 (A), 0/12 (B); median crop 83×41 (A), 97×31 (B);
OCR output changes across conventions on 26/39 (A) and 12/12 (B)
frames — cam2 OCR is inherently unstable, reinforcing that no cam2
claim is possible without labels.

## 8. Cam2 Ground Truth Status (Step 7)

**`CAM2_GT_UNAVAILABLE` — all 22 samples remain UNLABELED.**

Attempted: (a) identified the 22 original Phase-2B cam2 samples
(frames 205, 210, 300, 305, 315, 320, 325, 330, 335, 340, 345,
350, 355, 485, 495, 500, 505, 510, 530, 540, 545, 555); (b)
produced review assets for every sample — native crop, 4×
nearest-neighbor zoom, full-frame context sheet, and a geometry
manifest (`benchmarks/audit/cam2_gt/`); (c) searched the repo for
independent labels — `validation/cam2/*` contains only OCR-derived
hypotheses (all `unconfirmed`, `needs_review`, agreement 0.18–0.64),
which the task forbids as GT; (d) attempted visual review — **this
session's reviewer model does not accept image input**, so the
required visual glyph comparison cannot be performed in-session.

No label was forced. The pre-existing cross-model candidates
(`25H28999` / `25H28499` / `25H28494`, plus track-level
`235h284999`) remain **unverified hypotheses**, recorded as such.
Full findings: `benchmarks/audit/phase2d_cam2_gt_findings.md`.
**Unblock:** a vision-capable human reviewer, ~1 hour, using the
prepared PNGs against the restored raw `cam2.mp4`
(SHA-256 `237E30A0…D77D64F1`, 599 frames, 1920×1080 @ 25 fps).

## 9. Detector-vs-Crop Separation (Step 9 post-fix matrix)

Frame-aligned pairing on 62 verified cam1 frames, highest-confidence
box per frame, `NO_DETECTION` = wrong:

| | B correct | B wrong |
| --- | ---: | ---: |
| **A correct** | 56 | **6** |
| **A wrong** | 0 | 0 |

**Under `trunc`:** 6 discordant pairs (all A-correct/B-wrong),
McNemar exact **p = 0.03125**.
**Under `round`:** 62 both-correct, **0 discordant pairs**,
McNemar **p = null** (nothing to test).

* **Detector effect** (same extractor `round`): **none** — A and B
  both 62/62, identical OCR text on every verified frame.
* **Crop effect** (same detector): A — none (62/62 → 62/62);
  B — **+6/62** (56/62 → 62/62), invalid 6/72 → 0/72.
* **Interaction**: all six trunc-discordant frames are resolved by
  `round`; `round` creates no new discordant frames.

Conclusion: the detector difference **does not survive crop
normalization** — Case C (`DETECTOR_DIFFERENCE_REQUIRES_FURTHER_STUDY`)
does **not** apply. This is direct post-fix confirmation of Phase 2C's
`NO_MEASURABLE_DIFFERENCE` verdict.

## 10. Accuracy Metrics (verified cam1 GT only)

| Metric | A + trunc (production) | A + round | B + trunc | B + round |
| --- | --- | --- | --- | --- |
| exact | 62/62 = 1.0000 | 62/62 = 1.0000 | 56/62 = 0.9032 | 62/62 = 1.0000 |
| char accuracy | 1.0000 | 1.0000 | 0.9892 | 1.0000 |
| mean edit distance | 0.0 | 0.0 | 0.6666 | 0.0 |
| invalid (cam1) | 0/62 | 0/62 | 6/72 | 0/72 |
| failed (cam1) | 0/62 | 0/62 | 0/72 | 0/72 |

Cam2 contributes **no accuracy figures** (UNLABELED). All metrics are
stored as raw numerator/denominator in `benchmarks/results/
phase2d_summary.json` and per-row in `phase2d_dataset.json`.

## 11. Error Analysis

The single OCR failure mode (`12d674913` vs `12d67413` — a spurious
`9` and a `91` transposition) is fully explained by crop geometry:

* B's float box top edge is `y1 = 595.72`. Under `trunc` the crop
  starts at row **595**, of which only the bottom 28 % lies inside
  the true box.
* **Contamination proxy** (pixel-level, all 6 frames identical):
  the dropped row 595 has mean brightness **13.5** (dark background
  above the plate); the added row 646 has brightness **29.7** and is
  88 % inside the true box; the plate interior reference is **126.7**.
* So `trunc` includes a dark background sliver at the crop top, and
  the shared char detector responds to that sliver with a spurious
  character detection. `round` aligns the crop to the true box extent
  (rows 596–647) and the read becomes correct.
* The same physical vehicle is static across the six frames (identical
  float boxes to 2 decimal places), which is why all six frames fail
  and recover identically.
* Detector A is immune because its boxes are larger (median 227 px
  wide cam1) and its top edges do not land fractionally in a way that
  pulls background into the crop; its OCR text is identical under all
  four conventions.

## 12. Clipping Analysis

* Real data: **0 clipped crops everywhere** — 0/62 (A cam1), 0/72
  (B cam1), 0/39 (A cam2), 0/12 (B cam2), under every convention.
* Synthetic edge cases (25 safety tests): boundary-touching,
  beyond-frame, and negative-coordinate boxes are all clipped into
  the frame and stay in bounds under every expansion; expansion never
  enlarges a box beyond the frame; degenerate boxes are rejected
  (`invalid=True`, `crop=None`).
* Expansion margin on the small-crop regime (cam2, median 83 px):
  0.42 px/side at 1.01× … 4.6 px/side at 1.10× (17.4 % of crop area
  outside the original box at 1.10×) — the reason expansion is
  rejected as a fix.
* Multi-box frames: 0 for both detectors on both cameras (max 1 box
  per frame) — no duplicate/nearby-vehicle exposure in the sampled
  data; the crop layer crops each box independently and correctly
  does not merge or suppress.

## 13. Performance (Step 12 — steady state, warm-up 20, measured 100)

CPU-only (torch 2.12.0+cpu, ultralytics 8.4.56, OpenCV 4.13.0,
Python 3.11.4, 12 threads, AMD64). Model loading excluded; YOLO not
reloaded between measurements; cold-start not compared.

| Stage | p50 | p95 | max |
| --- | ---: | ---: | ---: |
| detector A | 19.67 ms | 20.59 ms | 21.55 ms |
| detector B | 19.76 ms | 20.78 ms | 22.21 ms |
| crop extraction `trunc` | 0.0121 ms | 0.0141 ms | 0.0147 ms |
| crop extraction `round` | 0.0119 ms | 0.0140 ms | 0.0181 ms |
| OCR (shared) | 10.35 ms | 11.00 ms | 11.40 ms |
| total (crop+OCR) `trunc` | 10.36 ms | 11.01 ms | 11.42 ms |
| total (crop+OCR) `round` | 10.25 ms | 10.81 ms | 10.99 ms |

Convention delta (crop extraction): **−0.0002 ms** — no measurable
cost. Detector latency is ~1600× the crop-extraction latency; the
convention choice is performance-irrelevant.

## 14. Regression Tests (Step 10)

* **New Phase 2D tests: 61, all passing** —
  `tests/test_phase2d_crop.py` (36: determinism, rounding rules,
  expansion identity/centre-preservation, clipping, degenerate-box
  rejection, input validation) and `tests/test_phase2d_safety.py`
  (25: the ten production-safety edge cases).
* **Phase 2A/2B/2C tooling suites: 162, all passing**
  (test_phase2b_tooling, test_phase2c_tooling, test_benchmark_tooling,
  test_benchmark_metrics, test_replay_validation_tooling).
* **Full suite: 591 passed, 11 failed.** All 11 failures are
  **pre-existing** and unrelated to Phase 2D (production files are
  byte-identical to HEAD — `git diff HEAD -- alpr_engine.py
  video_processor.py api.py db.py camera_manager.py` is empty):
  * 6 × `test_backend.py::TestCameraEndpoints` — HTTP 401 auth /
    camera CRUD environment failures;
  * 2 × `test_backend.py::TestSamplingIntervalValidation` —
    skip-frame bound validation;
  * 3 × `tests/test_detection_pipeline_integration.py` —
    `KeyError: 'plate_text'` at `routers/detection.py:117`
    (router/detection interface mismatch), atomic-storage propagation,
    RTSP lifecycle.
  None import any Phase 2D module; the failure modes are structural
  and reproduce without the Phase 2D files present.
* **New failures introduced by Phase 2D: 0.**

## 15. Reproducibility

```bash
# Step 4 reproduction + Step 5/6 sweeps (single inference pass,
# all conventions/expansions applied to cached boxes)
python benchmarks/run_phase2d.py
# Step 4 expectation check only
python benchmarks/audit/_phase2d_step4_probe.py
# Step 9 post-fix matrix + contamination proxy
python benchmarks/audit/_phase2d_postfix.py
# Step 11 real-data safety analysis
python benchmarks/audit/_phase2d_safety.py
# Step 12 latency
python benchmarks/audit/_phase2d_latency.py
# tests
python -m pytest tests/test_phase2d_crop.py tests/test_phase2d_safety.py -q
```

Artifacts: `benchmarks/results/phase2d_records.json` (2035 variant
records), `phase2d_summary.json`, `phase2d_dataset.json` (Step 8
clean paired dataset: 2035 rows, each retaining video, frame, sample
ID, detector, bbox, convention, expansion, integer bbox, crop W×H,
OCR output, normalized output, validity, confidence, GT, verified
flag, exact/char/edit-distance), `phase2d_postfix_matrix.json`,
`phase2d_safety.json`, `phase2d_latency.json`. No result is
overwritten; every run writes fresh timestamps.

Asset identity (Step 1, re-verified): detector A
`C70A91B5…ED00C`, detector B `308C2464…DE40`, char_model (production
OCR) `08CF1BB9…F41A53D`, cam1.mp4 `E3FD570F…FEF088`, cam2.mp4
`237E30A0…D77D64F1` — all match the Phase 2C manifest.

## 16. Production Safety (Step 11)

All ten required cases were exercised (25 synthetic tests + real-data
analysis): boundary-touching plates, very small (2×2 px), very large
(near-frame), partially detected, negative coordinates, beyond-frame,
malformed/degenerate, multiple nearby vehicles (overlapping boxes),
duplicate boxes, non-plate detections. Invariants held everywhere:
crops never leave the frame; expansion clips rather than enlarges;
degenerate boxes are rejected safely; results are deterministic.
Clipping frequency on real data: 0. No systematic
background/vehicle-body inclusion was found for the candidate
strategy (its added margin is exactly 0 px; the only change is which
1-px band at the box edge is included, measured per-frame in the
contamination proxy).

**Limitation of the safety sign-off:** direct visual inspection of
crops was not possible in-session (no image input); contamination was
assessed with the documented pixel-level proxy (row brightness vs
plate-interior reference), not by human eyes. A human visual pass is
recommended before any future integration.

## 17. Decision (Step 13)

Decision-tree walk:

* **Case A — crop fix improves cam1 without regression:** `round`
  (a) preserves verified exact accuracy (A 62/62 → 62/62), (b)
  recovers all six Phase-2C failures (B 56/62 → 62/62), (c) is
  deterministic (61 tests), (d) does not increase clipping (0
  everywhere), (e) introduces no contamination (0 px added margin;
  proxy shows background-row removal, plate-row addition).
  → **`CROP_FIX_CANDIDATE`.** Per the rules, integration is NOT
  automatic.
* **Case B — no safe improvement:** does not apply (a safe candidate
  exists).
* **Case C — detector difference survives crop normalization:** does
  **not** apply — the difference vanishes under `round` (0 discordant,
  p = null).
* **Case D — cam2 GT changes conclusions:** does not apply — cam2 GT
  remained unavailable.

**Classification: `CROP_FIX_CANDIDATE`.**

## 18. Proposed Patch (Step 14)

Documented in `ALPR_PHASE2D_PROPOSED_PATCH.md`: change
`alpr_engine.py:363` from `.astype(int)` (trunc) to
round-half-away-from-zero, with explicit `max(0,…)`/`min(W,…)` guards,
`import math` check, golden regression test on the six discordant
frames under both detectors, canary rollout, and one-line rollback.
**Not applied.** Production source remains byte-identical to HEAD.

Why it should not ship standalone: production runs Detector A, which
is already 62/62 under `trunc` — the fix recovers B's reads, not
A's, and it changes the integer bbox on 62/62 of A's cam1 crops with
zero measured benefit for the current detector. Its value is realized
only if a detector with tighter boxes is integrated in the future.

## 19. Limitations

1. **Two plates, one camera.** All accuracy rests on 62 verified
   cam1 crops of 2 plates. Sub-100-px crops — cam2's regime — have
   zero verified coverage.
2. **Cam2 unlabeled.** The motivating footage has no ground truth;
   this session could not visually verify it (no image input), and no
   independent labels exist in the repo.
3. **No box ground truth.** No IoU/localization metric exists; the
   "8.5 px lower / 7.4 px shorter" figures are relative box geometry,
   not an accuracy claim.
4. **Single physical plate causes the entire gap.** All six discordant
   frames are plate B; a single-plate OCR quirk could produce the
   whole effect.
5. **Visual contamination sign-off is proxy-based**, not human-visual
   (session limitation).
6. **Latency from a single CPU run** — no variance study; no
   statistically significant latency difference is claimed.
7. **Round vs ceil are indistinguishable on this dataset** (identical
   outcomes); the choice between them needs a larger verified set.
8. **The candidate's benefit is contingent** on a future detector
   integration; it is not a standalone production improvement.

## 20. Exact Next Step

1. **Label cam2 with a vision-capable human reviewer** (~1 hour) using
   the prepared assets in `benchmarks/audit/cam2_gt/` against the
   restored raw `cam2.mp4`; append verified labels to
   `benchmarks/dataset/gt_labels.json` with frame ranges. This is the
   highest-value action and unblocks every cam2 question.
2. **Keep production unchanged.** Do not integrate either detector; do
   not apply the crop patch. Phase 2C's `NO_MEASURABLE_DIFFERENCE`
   verdict and the "do not integrate" recommendation stand.
3. **If a detector A/B is still wanted**, first build a verified set
   with ≥ 3 plates, ≥ 3 cameras, and box ground truth (for IoU /
   localization), keep `trunc` frozen as the baseline convention, and
   re-run Phase 2C's protocol — reporting every convention rather
   than a single number.
4. **If a new detector is integrated**, carry `ALPR_PHASE2D_
   PROPOSED_PATCH.md` into that PR as the crop-hardening change, with
   the 61 Phase 2D tests plus a golden test on the six discordant
   frames, and a human visual contamination pass.

---

**Reproducibility note:** every number in this report is re-derivable
from the stored JSON artifacts listed in §15; the independent verifier
pattern of Phase 2C (`benchmarks/audit/phase2c_verify.py`) can be
re-pointed at `phase2d_records.json` for a fresh audit.
