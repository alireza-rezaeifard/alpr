# Phase 2B Benchmark — Independent Verification Findings (Adversarial Audit)

**Scope:** read-only audit of `benchmarks/results/phase2b_*.json`,
`benchmarks/ab_helpers.py`, `benchmarks/run_phase2b_ab.py`, and
`ALPR_PHASE2B_DETECTOR_CROP_BENCHMARK.md`. **No production or benchmark file
was modified.** Only two new files were added under `benchmarks/audit/`.

**Reproduce:** `python benchmarks/audit/verify_results.py`
(raw output also written to `benchmarks/audit/verify_output.txt`)

The script re-derives, from the raw `records` array of
`phase2b_detector_crop_results.json` (185 records), every published aggregate:
per-detector `overall` / `cam1.mp4` / `cam2.mp4` / `bucket:*` counts, exact
accuracy as raw x/N, char accuracy, mean edit distance, invalid rate, failed
rate, clipping counters and rate, crop width/height percentiles (independently
re-implemented nearest-rank), median area / aspect ratio, detector-confidence
stats, and detector/OCR/total latency p50 + p95.

---

## 1. Recomputation of stored summaries — CLEAN

Every one of the ~570 recomputed values in `detector_summary`
(2 detectors x {overall, cam1, cam2, 5 buckets} = 16 scopes x ~36 fields)
matches the stored value (tolerance 5e-4 for 4-dp rounded fields). Covered:
`n_crops`, `n_verified`, `n_exact`, exact accuracy, char accuracy, mean edit
distance, invalid rate, failed rate, all `clipped_*` counters,
`clipping_rate`, mean/median/p10/p25/p50/p75/p90 crop width, mean/median crop
height, median area, median aspect ratio, confidence mean/median/p10/p90,
detector/OCR/total latency p50 and p95, and `confidence_vs_correctness`.

`phase2b_bucket_results.json.buckets` is identical to the corresponding
`detector_summary` bucket blocks, and bucket `n_crops` sums equal each
detector's `overall.n_crops` (101 and 84).

## 2. UNLABELED (cam2) rule — CLEAN

**No cam2 record contributes to any accuracy figure** (verified
programmatically, not by reading summaries):

* all 51 cam2 records (39 current + 12 IranPlate-Vision) carry
  `exact = char_accuracy = edit_distance = edit_distance_norm = null`,
  `ground_truth = null`, `gt_status = "UNLABELED"`;
* `detector_summary[*]["cam2.mp4"]`: `n_verified = 0`, `exact_accuracy = null`,
  `char_accuracy = null`, `mean_edit_distance = null` — **null, never 0/false**;
* every scope anywhere with `n_verified == 0` (cam2 + the three unverified
  buckets per detector) also has all three accuracy fields `null`;
* cam2 `invalid_rate` (0.8205 / 0.9167) is a *validity* diagnostic over
  unlabeled crops and is labelled as such in the JSON `methodology.note` and in
  report §8;
* the 10 UNLABELED cam1 records (IranPlate-Vision only, frames 145–310) also
  carry `exact = null` and are excluded from the accuracy denominator.

**No invented GT:** `benchmarks/dataset/gt_labels.json` marks only
`cam1_plate_A` and `cam1_plate_B` as `verified: true`; `cam2_plate_X` is
`verified: false` and feeds no accuracy computation.

## 3. Bucket boundaries (task §8) — ONE DEFECT

`ab_helpers.BUCKETS` matches §8 exactly: `(0,80) lt80`, `[80,100) 80-99`,
`[100,150) 100-149`, `[150,200) 150-199`, `[200,inf) ge200`. Boundary probes
all pass: `bucket_for(80)=="80-99"`, `bucket_for(200)=="ge200"`,
`bucket_for(199)=="150-199"`, `bucket_for(100)=="100-149"`,
`bucket_for(79)=="lt80"`.

### DEFECT B-1 (Medium) — bucket assignment inconsistent with the published width
* Record: `current_detector / cam2.mp4 @ frame 585`
* stored `width = 100.0` px, stored `bucket = "80-99"`
* recomputed from the stored width: `bucket_for(int(100.0)) = "100-149"`

Root cause: `run_phase2b_ab.py` computes `bucket_for(int(geo["width"]))` from
the **unrounded float** width (99.6… -> `int()` truncates to 99) while the
published `width` field is `round(geo["width"], 1) = 100.0`. The record is
self-inconsistent, so bucket membership cannot be reproduced from the
artifact's own published fields.

Impact: the crop is counted in `bucket:80-99` (`n_crops = 21`) rather than
`bucket:100-149` (`n_crops = 30`). Both buckets' `exact_accuracy` stay `null`
(cam2 unlabeled) and the 4-dp invalid rates are effectively unchanged, but the
artifact fails independent recomputation — precisely what an auditor or
downstream consumer will attempt.

## 4. Pairwise classification — THREE DEFECTS (one High)

`classify_pair()` is **mutually exclusive and exhaustive**: with GT it returns
exactly one of `BOTH_CORRECT / CURRENT_BETTER / IRANPLATE_BETTER / BOTH_WRONG`;
without GT exactly one of `INCOMPARABLE / CURRENT_ONLY_VALID /
IRANPLATE_ONLY_VALID / NEITHER_VALID`. Independently re-classifying all 71
fully-populated pair records reproduces the stored outcome **71/71**, and
`outcome_counts` equals the recomputed counter exactly (`BOTH_CORRECT 62,
NEITHER_VALID 7, INCOMPARABLE 3, CURRENT_ONLY_VALID 1`).

**No superiority inferred from unmatched detections — CONFIRMED.** The only
directional class present (`CURRENT_ONLY_VALID`, 1 occurrence) is on a *matched*
pair with IoU >= 0.1. Unmatched detections carry `"outcome": "INCOMPARABLE"`,
`iou: 0.0` and a note; no `*_BETTER` / `*_ONLY_VALID` class is ever attached to
them, and unlabeled pairs carry `current_result = iranplate_result = null`.

### DEFECT P-1 (Medium) — `INCOMPARABLE` is overloaded / not purely "unmatched"
Three records are stored as `INCOMPARABLE`, but only **two** are unmatched:

* `cam2@525` — 2 records, genuine unmatched stubs
  (`note: "current detections unmatched by IranPlate-Vision"` /
  `"IranPlate-Vision detections unmatched by current"`), `iou = 0.0`;
* `cam2@555` — a **matched** pair: `iou = 0.642`, both OCR reads valid and
  identical (`"25h28999"`), `gt_status = "UNLABELED"`. It lands in
  `INCOMPARABLE` only because `classify_pair` returns
  `BOTH_CORRECT if gt_available else INCOMPARABLE` when both reads are valid
  without GT.

Report §11 labels all three as "INCOMPARABLE (unmatched detections)", which is
**wrong for 1 of the 3** and understates observed agreement.

### DEFECT P-2 (HIGH) — pairwise outcomes are not exhaustive over the detection set
The pairwise pass only considers frames where **both** detectors produced a box
(`run_phase2b_ab.py`: `if not cur or not ipv: continue`). Consequently
**43 of 185 detections (23 %) never enter the pairwise analysis** and are
recorded nowhere as unmatched:

| camera | detections dropped |
| --- | --- |
| cam1.mp4 | 10 (all IranPlate-Vision only) |
| cam2.mp4 | 33 (30 current-only, 3 IranPlate-Vision-only) |

By detector: 30 `current_detector`, 13 `iranplate_vision`. Concretely, the
current detector finds plates on cam2 frames 220, 250, 265, 285–355, 480–515,
575–595 that IranPlate-Vision misses entirely, and none of these appear in
`phase2b_pairwise_results.json`.

The task requires unmatched detections to be recorded and never used for
superiority. They are indeed never used for superiority — but they are
**silently dropped rather than recorded**, so the pairwise artifact cannot
quantify the 39-vs-12 cam2 detection-count gap that report §8 and §16 rely on.
The two stub records that *are* emitted prove the mechanism exists and was
simply not applied on the `not cur or not ipv` path.

### DEFECT P-3 (Low) — inconsistent schema on stub records
The 2 unmatched stub records omit `gt_status`, `ground_truth`,
`current_ocr_valid`, `iranplate_ocr_valid`, `current_result`,
`iranplate_result` — a different schema from the other 71 records. Any consumer
iterating `pairs` with a uniform schema raises `KeyError`.

## 5. Threshold sweep 0.20/0.30/0.40/0.50/0.60 — CLEAN

`phase2b_bucket_results.json.threshold_sweep` contains exactly the 10 required
cells (5 thresholds x 2 detectors), both detectors present at every threshold.
Every cell has `verified_total = 62` (non-zero), so each yields a real accuracy
figure. Both detectors report `verified_exact = 62/62` at every threshold,
consistent with report §13.

## 6. Crop-expansion experiment — TWO DEFECTS

`crop_expansion` in `phase2b_bucket_results.json` **does** cover the required
`1.00 / 1.05 / 1.10 / 1.15 / 1.20` for **both** detectors (10 cells, identical
factor set, applied through the same `crop_of(frame, box, expand)` to both
detectors' boxes). Report §17's table reproduces those numbers faithfully.

### DEFECT E-1 (Medium) — `phase2b_cam2_expansion.json` uses an off-spec factor grid
The cam2-only artifact uses factors **1.00, 1.10, 1.20, 1.30, 1.40** — 0.05
and 0.15 are **missing**, and 1.30/1.40 are **not in the task spec** — for both
detectors. It is listed as a deliverable in report §19 and cited in report §16
("expansion 1.0->1.4"), so it does not satisfy §19 and cannot be compared
row-for-row with the spec-compliant `crop_expansion` block.

### DEFECT E-2 (Low) — `failed_rate` duplicates `invalid_rate`
In all 10 `crop_expansion` cells `failed_rate == invalid_rate` (e.g.
`current_detector@1.10` -> 0.3762 / 0.3762). Cause: `run_phase2b_ab.py` computes
`"failed_rate": round(sum(1 for r in sub if not r["ocr_valid"]) ...)`, the same
predicate as `invalid`. In `detector_summary` the two rates genuinely differ
(`failed_rate` = empty OCR text: 0.1188 current, 0.0 IPV vs `invalid_rate`
0.3168 / 0.131), so the expansion table's `failed_rate` column must not be read
as an OCR-failure rate.


## 7. Statistical overclaiming — SIX DEFECTS

The report's overall verdict (`MORE_DATA_REQUIRED`, "no measurable difference",
"cam2 unproven") is **appropriately hedged**, and §18/§19 explicitly list the
2-plates / 1-camera / no-repeat limitations. However, several individual
statements present small-sample results as decisive.

### DEFECT S-1 (Medium) — "fully reproduced and explained" / "root cause" (headline, §15)
> "it is a **crop-boundary quantization artifact**, not a detector-quality
> difference … **fully reproduced and explained**"; "**Root cause**, one sample
> at a time"; "**Implication (fact):** … a 24-point swing".

The 24-point swing is `47/62` vs `62/62` on **one plate (plate B, 21 crops)** in
**one deterministic OCR run**. A single-crop flip of a CTC decoder is not a
stable effect size, and the same JSON shows the *current* detector swinging to
`56/62` under `floor` while IranPlate-Vision stays at `62/62`
(`phase2b_crop_sensitivity_results.json.summary`), i.e. the sign of the artifact
is convention-dependent. "Fully explained" / "root cause" overstate what a
6-sample single-run ablation supports; the evidence supports "*a* crop-edge
convention can change accuracy on plate B", not a general 24-point sensitivity.

### DEFECT S-2 (Medium) — "Robust across crop sizes? **Yes (both)**" (§9 / decision matrix)
> "100 % exact in every verified bucket for both".

Only **2 of 5 buckets contain any verified crop** (`100-149`: 21, `ge200`: 41).
The other three (`lt80`, `80-99`, `150-199`) have `n_verified = 0` and
`exact_accuracy = null` for both detectors. "Every verified bucket" is
therefore 2 buckets — and both are the *same two plates* re-cropped. The
decision-matrix verdict "Yes" reads as broad crop-size robustness the data
cannot support: the small-crop regime where cam2 actually fails (§8) has
**zero** verified coverage.

### DEFECT S-3 (Low) — threshold-invariance asserted as a "Fact" (§13)
> "**Fact:** verified accuracy is threshold-insensitive … The Phase 2A cam1
> regression was therefore **not** a threshold effect".

The sweep varies only the detector threshold while holding the crop convention
fixed; §15 shows the same 62 verified samples moving 47/62 ↔ 62/62 under a 1-px
crop change. The sweep is consistent with "not a threshold effect" but cannot
*establish* it: `62/62` at all five thresholds is a saturated metric with no
discriminating power (one flip would have registered). Presenting a ceiling
result as positive evidence of invariance is an overclaim.

### DEFECT S-4 (Medium) — directional cam2 verdicts from n = 12 (§8, §16)
> §16 table: "invalid, round crop 0.821 vs 0.917 -> **current better**";
> "invalid, floor crop 0.846 vs 0.750 -> **IPV better**".

These per-row verdicts are asserted on 12 vs 39 crops with no uncertainty
interval; 1 crop = 8.3 % of the IranPlate-Vision set. The surrounding prose
correctly retracts them ("not evidence of superiority"), yet the table still
prints directional verdicts, and the executive summary coexists with them.
Those rows should read *indeterminate*, not *better/worse*.

### DEFECT S-5 (Medium) — report §12 latency p95 values contradict the JSON
Report §12 states detector p95 **25.8 / 25.4 ms** and OCR p95 **13.2 / 12.6 ms**.
Stored values (`detector_summary[*].overall`) are detector p95
**22.65 / 22.54 ms** and OCR p95 **13.6 / 11.25 ms**. All p50 values in the
report do match. The p95 figures are unreproducible from any stored artifact —
apparently computed with a different percentile convention than the
`ab_helpers.percentile()` used everywhere else. This does not change the
"no latency difference" verdict, but the report publishes numbers the artifacts
do not support.

### DEFECT S-6 (Medium) — "62/62 verified frames exact" reads as recall (§6)
> "both detectors achieved **62/62 verified frames exact**
> (`verified_frame_exact_accuracy = 1.000`)".

`frame_level.verified_frames = 62` counts labeled-range frames **where that
detector produced a box**; zero-box labeled frames are appended with
`n_boxes = 0` and `gt_status = "LABELED"` but only reach `frames_sampled`. So
"62/62" is a per-detected-frame rate, not a recall figure — it excludes the 10
cam1 frames where the current detector found nothing but IranPlate-Vision did,
and the 29 cam2 frames in the opposite situation. Placed next to the accuracy
number it invites a recall reading these data do not support (the real recall
numbers are in the file but unsurfaced: `frames_with_detection` 101 vs 84 of 192
sampled frames).


---

## Summary of concrete defects

| ID | Area | Severity | Defect |
| --- | --- | --- | --- |
| B-1 | buckets | Medium | `current_detector/cam2@585`: published `width=100.0` but `bucket="80-99"`; bucket assignment truncates the *unrounded* width, so the record is not reproducible from its own fields and the crop is counted in the wrong bucket. |
| P-1 | pairwise | Medium | `INCOMPARABLE` mixes 2 genuinely unmatched detections with 1 **matched** (IoU 0.642) agreeing pair (`cam2@555`); report §11 mislabels all 3 as "unmatched detections". |
| P-2 | pairwise | **High** | 43/185 detections (23 %) never enter the pairwise analysis (33 cam2, 10 cam1) and are not recorded as INCOMPARABLE — outcomes are not exhaustive; the 39-vs-12 cam2 detection gap is invisible in the pairwise artifact. |
| P-3 | pairwise | Low | The 2 unmatched stub records use a different schema (no `gt_status` / validity / result fields) → `KeyError` for uniform consumers. |
| E-1 | expansion | Medium | `phase2b_cam2_expansion.json` uses factors 1.00/1.10/1.20/1.30/1.40 instead of the required 1.00/1.05/1.10/1.15/1.20 (0.05 and 0.15 missing; 1.30/1.40 off-spec). |
| E-2 | expansion | Low | `failed_rate` in all 10 `crop_expansion` cells duplicates `invalid_rate` (same predicate `not ocr_valid`). |
| S-1 | report | Medium | "Fully reproduced and explained" / "root cause" / "24-point swing" stated as fact on 6 samples from 1 plate in a single run; the sign of the artifact is convention-dependent. |
| S-2 | report | Medium | Decision-matrix "Robust across crop sizes? Yes" rests on 2 of 5 buckets (the same 2 plates); the small-crop regime has zero verified coverage. |
| S-3 | report | Low | Threshold-invariance claimed as a "Fact" from a saturated 62/62 ceiling metric. |
| S-4 | report | Medium | §16 prints "current better" / "IPV better" verdicts on n=12 vs n=39 with no interval, contradicting the adjacent "unproven" verdict. |
| S-5 | report | Medium | §12 latency p95 values (25.8 / 25.4 / 13.2 / 12.6 ms) contradict stored values (22.65 / 22.54 / 13.6 / 11.25 ms). |
| S-6 | report | Medium | "62/62 verified frames exact" is a per-detected-frame rate that excludes zero-detection frames; it reads as recall but is not. |

## Categories verified CLEAN

1. Full re-computation of every stored aggregate in `detector_summary` and
   `phase2b_bucket_results.json.buckets` (16 scopes, ~570 values, 0 mismatches).
2. The UNLABELED / verified-GT-only rule, including null-not-zero semantics for
   every accuracy field on cam2 and on unverified buckets.
3. Bucket boundary definitions in `ab_helpers.BUCKETS` and boundary-value
   behaviour of `bucket_for` (exactly 80 -> `80-99`, exactly 200 -> `ge200`).
4. Mutual exclusivity / exhaustivity of `classify_pair`, and the rule that no
   superiority is inferred from unmatched (INCOMPARABLE) detections.
5. Threshold-sweep coverage of 0.20 / 0.30 / 0.40 / 0.50 / 0.60 for **both**
   detectors, each with non-zero verified totals.
6. Spec-compliant factor coverage (1.00 / 1.05 / 1.10 / 1.15 / 1.20) of the main
   `crop_expansion` block, applied identically to both detectors.

## Bottom line

The arithmetic in the stored artifacts is sound — every number in the JSON
reproduces exactly from the raw `records`. The defects are (a) one
non-reproducible record/bucket assignment, (b) a pairwise section that silently
drops 23 % of detections and therefore cannot support the detection-count
comparison the report leans on, (c) an off-spec cam2 expansion artifact plus a
duplicated metric column, and (d) several report statements — the p95 numbers,
the "unmatched" label on a matched pair, the crop-size robustness verdict, the
"fully explained" root-cause claim, the directional cam2 verdicts on n=12, and
the frame-level recall framing — that overstate what a 2-plate, 1-camera,
single-run dataset can support. None of these overturns the report's own
`MORE_DATA_REQUIRED` classification; the overclaims should be softened so the
verdict does not rest on them.

## Audit method notes / limitations

* Percentiles were re-implemented independently (nearest-rank on the sorted
  list) rather than imported, so a shared bug in `ab_helpers.percentile` would
  not be masked.
* Latency figures are single-run wall-clock measurements taken on the same
  machine; no repeat/variance study exists, so no latency difference (p50 or
  p95) in this dataset can be called significant. The audit verifies only that
  report numbers match the stored JSON, not that the JSON's timing methodology
  is sound.
* Records with an `error` key (detector exceptions) carry no `ocr_text` and are
  excluded from all recomputation exactly as the runner excludes them; zero such
  records were found in this run.

