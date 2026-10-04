# Phase 2C Independent Verification Findings

**Verifier:** `D:\alpr\benchmarks\audit\phase2c_verify.py`
**Full output:** `D:\alpr\benchmarks\audit\phase2c_verify_output.txt`
**Mutation test harness:** `D:\alpr\benchmarks\audit\_mutation_test.py`
**Mutation results:** `D:\alpr\benchmarks\audit\_mutation_results.txt`

**Artifacts verified** (`generated_at = 2026-10-03 14:56:15`, all written 14:56:15):

| File | Size |
|---|---|
| `benchmarks/results/phase2c_raw_results.json` | 2,062,558 B |
| `benchmarks/results/phase2c_summary.json` | 16,719 B |
| `benchmarks/results/phase2c_bucket_results.json` | 6,806 B |
| `benchmarks/results/phase2c_crop_results.json` | 439,392 B |

**Final verdict: PASS (exit code 0).** All ten mandated checks pass, plus the
canonical-convention check. One check (C10, report-vs-JSON) is **SKIPPED**, not
passed, because the report does not exist yet.

---

## 1. Independence of the verifier

`phase2c_verify.py` imports **only** `json`, `math`, `os`, `re`, `sys`, plus
`numpy`, which is imported *lazily inside the C11 convention check only*. It
does **not** import the Phase 2C runner and reuses **none** of its functions, so
a runner bug cannot mask itself. Every statistic (counts, ratios, medians,
means, percentiles, buckets, McNemar table, exact binomial p-value) is
recomputed from the raw records with independently written code.

The verifier honours `P2C_RESULTS_DIR` / `P2C_REPORT_PATH` environment
overrides so mutation testing can run against tampered copies without touching
the real results.

---

## 2. Per-check results

```
[PASS] C1  ratio integrity: 86 ratio fields, 0 numerator>denominator, 0 value!=num/den
[PASS] C2  metric recomputation: 162 summary fields recomputed from raw records, 0 mismatches
[PASS] C3  failed == blank OCR text: 12 scope checks, 0 mismatches
[PASS] C4  UNLABELED hygiene: 1300 UNLABELED records, 0 carry non-null
            exact/char_accuracy/edit_distance
[PASS] C5  A/B protocol symmetry: one flat param set; identical (camera,frame)
            sets per run run0; identical convention sets; consistent ground
            truth across detectors
[PASS] C6  NO_DETECTION denominator: all without-detection frames are inside
### What each check actually verified

**C1 (86 ratio fields).** Every `{numerator, denominator, value}` triple
anywhere in the summary was walked recursively. No numerator exceeds its
denominator, no zero-denominator ratio carries a non-null value, and every
`value` equals `numerator/denominator` to 1e-3.

**C2 (162 fields).** For every run x detector x camera-scope, the following
were recomputed from raw records and compared: `detected_crops`,
`labeled_crops`, `unlabeled_crops`, `ocr_attempts`, `exact`, `char_accuracy`,
`mean_edit_distance`, `invalid_rate_all_crops`, `failed_rate_all_crops`,
`clipping_rate`, `confidence_mean`, `median_crop_width/height`,
`mean_crop_width/height`, all five `width_percentiles`, and the frame block
(`frames_total`, `frames_with_detection`, `frames_without_detection`,
`n_boxes`, `multi_box_frames`). Additionally `frames_with_detection` was
cross-checked against the number of *distinct* detected `(camera, frame)`
pairs in the records, which catches box-count inflation.

**C3 (12 scope checks).** `failed` was verified twice per scope: the stored
numerator equals the count of blank/whitespace-only `ocr_text`, **and** at the
record level `bool(failed) == (ocr_text is blank)` for every single crop. The
`failed` / `invalid` overlap was measured and is **0 in every scope**, i.e. the
two metrics are genuinely disjoint and `failed` is not a copy of `ocr_valid`.
All 13 of detector A's failures occur on cam2, which is UNLABELED (see §4).

**C4 (1300 UNLABELED records).** No UNLABELED record carries a non-null
`exact`, `char_accuracy`, `edit_distance`, `edit_distance_norm`,
`pred_canonical` or `ref_canonical`. All 305 UNLABELED DETECTED crops have
`(None, None, None)` for exact/char_accuracy/edit_distance.

**C5.** The protocol block is a single flat parameter set (no nested
per-detector sub-objects, no detector-named keys), it is identical between the
raw and summary files, and it declares `crop_convention: trunc` matching the
canonical value. The set of `(camera, frame)` pairs is **identical** for
detector A and detector B (192 frames each), in the records *and* in
`frame_rows`. Convention sets are identical across detectors, and no
`(run, camera, frame, convention)` key has conflicting `ground_truth` /
`gt_status` between detectors.

**C6.** `frames_without_detection` was recomputed from `frame_rows` and matched
for both detectors, per camera and overall (A: 91 of 192; B: 108 of 192). Every
`NO_DETECTION` record maps to a frame counted as without-detection (**0
orphans**), and every without-detection frame has `NO_DETECTION` records
(**0 missing**). `frames_with_detection + frames_without_detection ==
frames_total` holds, so no detector can gain credit by dropping no-detection
frames from the denominator.

**C7.** The 2x2 table was rebuilt from the paired per-frame `exact` flags of
the 62 common LABELED frames: `both_correct=56, a_correct_b_wrong=6,
a_wrong_b_correct=0, both_wrong=0`. `discordant_pairs=6 == 6 + 0` holds.
`mcnemar_exact_p=0.03125` was independently recomputed as the exact two-sided
binomial p `2*(C(6,0)/2^6)=0.03125` and matches exactly; it lies in [0,1] and is
not `None`. The six discordant frame IDs (`cam1.mp4@180, @185, @210, @215,
@330, @335`) were regenerated from the records and match the stored list
exactly. `verified_frames=62` equals the number of paired labeled frames.

**C8.** Every one of the 925 DETECTED crops was re-bucketed from its
`crop_width` using the boundaries <80, 80-99, 100-149, 150-199, >=200 and landed
in the same bucket as stored. Per-bucket `N`, `labeled`, `exact`
numerator/denominator, `char_accuracy`, `invalid`, `failed` and `median_width`
all reproduce, and bucket N sums equal each detector's detected-crop total
(A: 7+20+31+2+41 = 101; B: 2+5+26+10+41 = 84). The external
`phase2c_bucket_results.json` agrees with the summary's `buckets` block and
declares the same canonical convention.

**C9.** The summary declares `repeatability.runs = 1` and the raw records
contain exactly one run (`run0`), with no `identical` claim. There is therefore
no repeatability claim to falsify; the verifier confirms the record count
matches the declared run count rather than assuming a pass. **This check would
fail** if `identical: true` were claimed without runs to back it, or if `runs`
were declared larger than the number of runs actually present.

**C10 - SKIPPED, not passed.** `D:\alpr\ALPR_PHASE2C_DETECTOR_AB_BENCHMARK.md`
does not exist, so the check was skipped exactly as instructed and did **not**
affect the exit code. It must be re-run once the report is written. The logic
is implemented and proven working by mutation testing (see §3).

**C11.** `canonical_convention = "trunc"` is one of the five allowed values
(`round`, `floor`, `ceil`, `trunc`, `floor_dy-1`), and all five are present in
the records. `trunc` was compared against `numpy.astype(int)` on 2000 seeded
pseudo-random floats spanning +/-2000 with a strong fractional part:
**2000/2000 match**, and the same sample differs from `floor` on **1004**
values - so the test genuinely discriminates truncate-toward-zero from floor
rather than passing vacuously. Additionally all 925 DETECTED crops were checked
so that their stored `x1_pixel/y1_pixel/x2_pixel/y2_pixel` equal the value
implied by the record's own `convention` (`round` = floor(x+0.5), `floor`,
`ceil`, `floor_dy-1` = floor with y decremented by 1, `trunc` = int()). Zero
mismatches.
            frames_total/frames_without_detection, 0 orphan NO_DETECTION
            records, 0 missing records
[PASS] C7  McNemar consistency: 2 scope blocks recomputed from paired records;
            table, discordant_pairs, p-value and id lists all consistent
[PASS] C8  bucket assignment: every crop_width maps to its stored bucket;
            per-bucket N/labeled/exact/char_accuracy/invalid/failed/median_width
            reproduce; bucket N sums == detected crops
[PASS] C9  repeatability: summary declares runs=1 and the raw records contain
            1 run(s) -- no repeatability claim is made, so nothing to falsify
[SKIP] C10 report-vs-JSON: ALPR_PHASE2C_DETECTOR_AB_BENCHMARK.md does not exist
            yet - check SKIPPED (explicitly NOT a failure)
[PASS] C11 canonical convention: 'trunc' is one of the 5 allowed; trunc ==
            numpy.astype(int) on 2000/2000 random floats; 925 crop-pixel records
            consistent with their stated convention

RESULT: PASS -- no violation detected by the independent verifier
```
---

## 3. Mutation testing - proof the verifier is not a rubber stamp

A PASS is only meaningful if the verifier can actually fail. Seventeen
deliberate corruptions were injected into throwaway copies of the results
(`_mutation_test.py`), each targeting one specific defect class. Every single
one was caught with a non-zero exit code:

| # | Injected defect | Result |
|---|---|---|
| 1 | `exact` numerator inflated above denominator | CAUGHT (rc=1) |
| 2 | ratio `value` inconsistent with numerator/denominator | CAUGHT (rc=1) |
| 3 | detector B `exact` inflated 56/62 -> 62/62 | CAUGHT (rc=1) |
| 4 | `frames_without_detection` falsified | CAUGHT (rc=1) |
| 5 | `failed` count decoupled from blank OCR text | CAUGHT (rc=1) |
| 6 | fake `exact=True` injected into an UNLABELED record | CAUGHT (rc=1) |
| 7 | detector B evaluated on a shifted frame set | CAUGHT (rc=1) |
| 8 | per-detector params smuggled into the protocol block | CAUGHT (rc=1) |
| 9 | NO_DETECTION frames removed from the denominator | CAUGHT (rc=1) |
| 10 | McNemar `discordant_pairs` zeroed and p set to null | CAUGHT (rc=1) |
| 11 | McNemar table cell swapped | CAUGHT (rc=1) |
| 12 | `mcnemar_exact_p` pushed outside [0,1] | CAUGHT (rc=1) |
| 13 | crops reassigned to the wrong width bucket | CAUGHT (rc=1) |
| 14 | bucket N no longer summing to detected crops | CAUGHT (rc=1) |
| 15 | fake `identical: true` repeatability over divergent runs | CAUGHT (rc=1) |
| 16 | `canonical_convention` set to an unallowed value | CAUGHT (rc=1) |
| 17 | report contradicting the JSON (60/62 instead of 56/62) | CAUGHT (rc=1) |

```
mutation testing: ALL MUTATIONS CAUGHT
```

A control report consistent with the JSON was also planted and correctly did
**not** trigger a failure, confirming C10 discriminates rather than rejecting
every report.

Two of my own verifier bugs were found and fixed by this adversarial process:
C7 initially omitted a `r["detector"] != det` guard (letting A and B overwrite
each other's results), and C11 initially assumed `floor_dy-1` shifted x as well
as y. Both were caught by cross-checking recomputed values against the data,
not by trusting the first green run.

## 4. Findings and caveats - the arithmetic is sound, but read it carefully

The numbers reproduce exactly. However, three field **names** in the summary
are misleading, and one materially affects how the headline comparison should
be read. These are reported by the C12 advisory audit.

**(a) `invalid_rate_all_crops` is an OCR-invalid rate, not a crop-validity
rate.** The raw records carry a `crop.invalid` boolean and a
`crop.invalid_reason` string, but `crop.invalid` is `True` for **0 of 925**
detected crops and `invalid_reason` is populated for **0**. The summary's
`invalid` numerator actually counts records with `ocr_valid == False`
(248/925 overall). So "invalid" means "the OCR engine rejected the crop", not
"the crop geometry was invalid". The geometry-validity signal the schema
appears to promise is dead - it is never exercised by this dataset. Any report
describing `invalid` as "invalid crops" would be misleading.

**(b) `unlabeled_crops` counts UNLABELED FRAMES, not crops.** For detector A
overall the stored value is 130, whereas the number of *detected but unlabeled*
crops is 39; 130 is the count of frames whose `gt_status` is not LABELED. The
identity `labeled_crops + unlabeled_crops == frames_total` holds exactly. The
name says "crops" but the quantity is frames, so `130` must not be read as
"130 bad crops".

**(c) Medians use `numpy.percentile(..., method='lower')`.** For even-sized
samples the stored median is `sorted[(n-1)//2]`, not the average of the two
middle values. Example: detector B on cam2 has widths
`[69,76,80,82,83,97,99,102,109,111,120,121]`; the stored `median_crop_width`
is 97.0 (lower method) whereas the conventional median is 98.0. The same
applies to `median_height` (stored 31.0 vs conventional 32.5) and to bucket
`median_width`. The verifier accepts any of the three conventions but flags the
value when it matches none.

**(d) Statistical power is low, and the headline "A beats B" is thin.** The
McNemar test rests on **6 discordant pairs out of 62 verified frames**, all in
one direction (A correct / B wrong), with `p = 0.03125`. That is marginally
significant, rests on a single camera, and would not survive a correction for
the number of scopes examined.

**(e) cam2.mp4 has no verified ground truth at all.** `cam2_status: UNLABELED`,
`verified_plate_instances: 2`, `box_ground_truth: NO_BOX_GROUND_TRUTH`. All 62
accuracy-bearing frames come from cam1 only. Detector A's entire
`frames_without_detection` burden (91 of 192) and all 13 of its OCR failures
are on cam2 - data that contributes **nothing** to the accuracy comparison but
does contribute to the invalid-rate comparison. Consequently detector A's
`invalid_rate_all_crops` of 34/101 (33.7%) versus detector B's 15/84 (17.9%)
is heavily influenced by cam2 crops that have no ground truth. Comparing
invalid rates across detectors while only cam1 contributes to accuracy is an
apples-to-oranges comparison and should be labelled as such.

**(f) Untested code paths.** `multi_box_frames` is 0 everywhere (every frame is
single-box), so the multi-box path is unexercised and `max_det=12` is never
approached. `clipping_rate` is 0/101 and 0/84, so boundary clipping is
unexercised.

**(g) Frame-level verification limitation.** `frame_rows` carries no `run`
column, so frame counts could only be validated against the single pass present
in `frame_rows`. With `runs = 1` this is not a gap today, but a multi-run
summary built from this schema could not have its per-run frame counts verified.

**(h) File-stability caveat observed during verification.** The results files
were rewritten by the background run at **14:56:15**, replacing an earlier
14:37 generation that had 2 runs, 384 frames and 768 `frame_rows`. An
intermediate verification pass executed against a partially-updated pair of
files produced spurious C7/C8 failures that vanished once both files were
consistent. **All results in this document refer to the 14:56:15 generation.**
Anyone re-running the verifier must confirm both files share the same
`generated_at` timestamp, otherwise a mid-write read produces phantom failures.

---

## 5. Statement of which checks passed

Passed: **C1, C2, C3, C4, C5, C6, C7, C8, C9, C11** - plus the C12 advisory
audit, which raised no arithmetic errors but flagged the naming and
interpretation issues in §4.

Skipped (explicitly not a pass): **C10**, because
`D:\alpr\ALPR_PHASE2C_DETECTOR_AB_BENCHMARK.md` does not exist. The check must
be re-run after the report is written; the mutation test confirms the check
does fire on a contradicting report.

No violation of any of the ten rules in task §28 was found in the 14:56:15
artifact set. The verifier exits **0** on this data and exits **non-zero** on
each of 17 distinct injected defects.

## 6. Reproduce

```powershell
cd D:\alpr
python benchmarks\audit\phase2c_verify.py      # exit 0 = pass, 1 = violations
python benchmarks\audit\_mutation_test.py      # proves the checks can fail
```
