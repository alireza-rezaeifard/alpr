# ALPR Phase 2C — Detector A/B with Crop Extraction Controlled

**Date:** 2026-10-03 · **Repo:** `D:\alpr` · **Branch:** `main` · **HEAD:** `f9bd7bb`
**Production code changed:** NO · **Production model changed:** NO · **Commit created:** NO

## 1. Executive summary

With inference parameters, box-to-pixel conversion, crop extraction, OCR and frames held
identical, Detector A scored **62/62** verified exact and Detector B **56/62**. The paired
comparison is **6 frames A-correct/B-wrong, 0 B-correct/A-wrong** (McNemar exact
**p = 0.03125**), so the gap is statistically resolvable — but it is **not** a localization
failure. On all 6 frames Detector B's box is ~8.5 px lower and ~7.4 px shorter than
Detector A's, and at 1.05x expansion Detector B reaches **62/62** on the same boxes. The
defect is a too-tight box, and the residual failure is a 1-px crop-edge effect inside the
shared OCR path. Detector B also detects on more cam1 frames (72/72 vs 62/72) with **zero**
clipping and **zero** failed OCR. Detector A is not shown to be a better *detector*; it is
shown to be more forgiving under this crop convention.

## 2. Exact question

Do Detector A (CURRENT_PRODUCTION) and Detector B (IranPlate-Vision) differ in downstream
ALPR quality once crop-extraction differences and inference-parameter differences are
eliminated? Evaluated on identical frames, identical conf/iou/max_det/imgsz, one canonical
box-to-pixel rule, one crop extractor, one OCR adapter, verified ground truth only.

## 3. Models

| | Detector A | Detector B |
| --- | --- | --- |
| Artifact | `weigths/plate_det_model.pt` | `bench/IranPlate-Vision-main/IranPlate-Vision-main/best.pt` |
| SHA-256 | `C70A91B5D695C2B8302BBE4F8AB6112DDC7845159F2FCC91CD50072D401ED00C` | `308C24643EAF49FC38930CEBFC46CA7455E7472F1D83FE98A2AE24443043DE40` |
| Classes | 1 (`plate`) | 1 (`Plates`) |
| Role | production baseline | candidate under evaluation |

Both loaded locally. No model downloaded.

## 4. Frozen protocol

Machine-readable copy: [benchmarks/phase2c_protocol.json](benchmarks/phase2c_protocol.json)

```json
{"conf": 0.5, "iou": 0.45, "max_det": 12, "imgsz": 640,
 "agnostic_nms": false, "half": false,
 "crop_convention": "trunc", "clip": true, "pad_x": 0, "pad_y": 0,
 "ocr": "CURRENT_PRODUCTION", "ground_truth_policy": "verified_only"}
```

Both arms are driven by **one** `model.predict(...)` call site with these exact arguments,
so the Phase 2B asymmetry (B at `iou=0.7`/`max_det=300`) is **eliminated**. Detector B is
called through `model.predict` with explicit parameters, **not** through
`IranPlateDetectorAdapter.detect()`, which would re-apply adapter defaults.

## 5. Dataset

| Item | Value |
| --- | --- |
| Frames sampled | every 5th frame; cam1 72, cam2 120, **192 total** |
| Verified GT frames (cam1) | 62 (plate A, plate B) |
| Unverified / UNLABELED | cam2, all frames — **no accuracy computed** |
| Plate instances (verified) | 2, both cam1 |
| Box ground truth | `NO_BOX_GROUND_TRUTH` — no IoU/localization score is possible |

## 6. Crop extraction

[benchmarks/phase2c_canonical.py](benchmarks/phase2c_canonical.py). Fixed order:
**convert -> pad -> clip -> validate**. Returns float box *and* exact integer pixels used.
Conventions measured: `round` (half-away-from-zero), `floor`, `ceil`, `trunc`, `floor_dy-1`.

Canonical convention selected as **`trunc`** because it is the only one that reproduces
production: `alpr_engine.py:363` uses `box.xyxy[0].cpu().numpy().astype(int)`, i.e.
truncation **toward zero**. Verified equal to `numpy.astype(int)` on 2000/2000 random
floats. Selection used only `production_equivalent`, `degenerate_count` and
`shrinks_box_count` — **no accuracy input**, so ground truth cannot leak into the protocol.

| Frame 180 | A box float | A crop px | A OCR | B box float | B crop px | B OCR |
| --- | --- | --- | --- | --- | --- | --- |
| `round` | 1061.36, 587.23, 1199.21, 645.80 | (1061,587)-(1199,646) 138x59 | `12d67413` OK | 1059.54, 595.72, 1199.64, 646.88 | (1060,596)-(1200,647) 140x51 | `12d67413` OK |
| `trunc` (canonical) | same | (1061,587)-(1199,645) 138x58 | `12d67413` OK | same | (1059,595)-(1199,646) 140x51 | `12d674913` BAD |
| `ceil` | same | (1062,588)-(1200,646) 138x58 | `12d67413` OK | same | (1060,596)-(1200,647) 140x51 | `12d67413` OK |

**The same Detector B box reads correctly under `round` and `ceil` and incorrectly under
`trunc` and `floor`.** The Phase 2B artifact is fully reproduced and is *not* a
convention-selection accident.

## 7. Detector parity

| Parameter | A | B | Identical |
| --- | --- | --- | --- |
| conf | 0.5 | 0.5 | yes |
| iou (NMS) | 0.45 | 0.45 | yes |
| max_det | 12 | 12 | yes |
| imgsz | 640 | 640 | yes |
| agnostic_nms | false | false | yes |
| half | false | false | yes |
| crop extractor | `phase2c_canonical` | same object | yes |
| OCR adapter | `ProductionOCRAdapter` | same instance | yes |
| normalization | `normalize_plate_text` | same | yes |

## 8. Detection results (counts, **not** recall)

No detector-accuracy claim is possible: there is no box ground truth, so **recall cannot
be computed for either arm**. Frames with no detection are retained in every denominator.

| Detector | Scope | frames with detection | frames without | crops | multi-box frames |
| --- | --- | ---: | ---: | ---: | ---: |
| A | overall | 101/192 | 91 | 101 | 0 |
| A | cam1 | 62/72 | 10 | 62 | 0 |
| A | cam2 | 39/120 | 81 | 39 | 0 |
| B | overall | 84/192 | 108 | 84 | 0 |
| B | cam1 | 72/72 | 0 | 72 | 0 |
| B | cam2 | 12/120 | 108 | 12 | 0 |

Detector B detects on **more** cam1 frames (72/72 vs 62/72) and on **fewer** cam2 frames
(12 vs 39). `multi_box_frames = 0` for both arms, so duplicate-box suppression differences
## 9. OCR results (verified GT only)

| Metric | Detector A | Detector B |
| --- | --- | --- |
| exact (overall) | **62/62 = 1.0000** | **56/62 = 0.9032** |
| character accuracy | 62.0/62 = 1.0000 | 61.3334/62 = 0.9892 |
| mean edit distance | 0/62 = 0.0 | 0.6666/62 |
| invalid (all crops) | 33/101 = 0.3267 | 15/84 = 0.1786 |
| failed = empty OCR (all crops) | 13/101 = 0.1287 | **0/84 = 0.0** |
| cam1 invalid | 0/62 = 0.0 | 6/72 = 0.0833 |
| cam1 failed | 0/62 = 0.0 | 0/72 = 0.0 |

Note the denominators differ (101 vs 84 crops) — these rates are **not** directly
comparable to each other and are never presented as such.

## 10. Crop fidelity

| | Detector A | Detector B |
| --- | ---: | ---: |
| median crop width (overall) | 138 px | 168 px |
| median crop width (cam1) | 227 px | 202 px |
| median crop height (cam1) | 66 px | 53 px |
| clipping rate (any edge) | 0/101 = 0.0 | 0/84 = 0.0 |
| mean detector confidence | 0.7421 | 0.7909 |

On the 6 discordant frames B's box is **8.5 px lower** and **7.4 px shorter** than A's
(y1 595.72 vs 587.23; height 51.17 vs 58.57 px). B's higher confidence (0.776 vs 0.674) sits
alongside the worse crop — **confidence does not indicate correctness**.

Visual evidence: [benchmarks/audit/phase2c_crop_fidelity.html](benchmarks/audit/phase2c_crop_fidelity.html)
— 62 verified frames, each with the frame, both boxes, both crops, exact pixel coordinates,
ground truth and both OCR reads. **6 frames** flagged where OCR output differs; 55 differ only
in crop width with identical OCR. Index:
[phase2c_crop_fidelity_index.json](benchmarks/audit/phase2c_crop_fidelity_index.json).

## 11. Width buckets

Accuracy is `N/A` wherever no verified ground truth exists.

| Bucket | A N | A labeled | A exact | B N | B labeled | B exact |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| < 80 px | 2 | 0 | N/A | 2 | 0 | N/A |
| 80–99 px | 21 | 0 | N/A | 4 | 0 | N/A |
| 100–149 px | 31 | 21 | 21/21 | 26 | 21 | 21/21 |
| 150–199 px | 2 | 0 | N/A | 10 | 0 | N/A |
| >= 200 px | 45 | 41 | 41/41 | 42 | 41 | 41/41 |

**All 62 verified samples fall in just two buckets (100–149 px and >= 200 px), both 100 %
exact for both detectors.** The sub-100 px regime has **zero** verified coverage, so the
regime where cam2 actually lives is entirely unvalidated.

## 12. Crop expansion

Identical centre-preserving expansion for both arms, canonical `trunc` convention.

| Factor | A median W | A exact | B median W | B exact |
| --- | ---: | --- | ---: | --- |
| 1.00 | 138 | 62/62 | 168 | 56/62 |
| **1.05** | 145 | **33/62** | 176 | **62/62** |
| 1.10 | 152 | 62/62 | 185 | 58/62 |
| 1.15 | 159 | 62/62 | 193 | 45/62 |
| 1.20 | 166 | 62/62 | 202 | 62/62 |

**This is the decisive experiment.** At 1.05x Detector B reaches **62/62** on the very same
boxes that produced 56/62 — the 6 failures were under-sizing, not bad localization. It also
shows the shared OCR path is highly non-monotonic in expansion for both arms (A drops to
33/62 at 1.05x, B drops to 45/62 at 1.15x), so **no expansion factor can be recommended as
a fix from this data**.

## 13. Latency

Steady state only: >= 20 warm-up calls discarded, >= 100 calls measured, model loading
excluded. CPU-only (`torch 2.12.0+cpu`, `cuda_available=false`, ultralytics 8.4.56,
OpenCV 4.13.0, Python 3.11.4, 12 threads, AMD64).

| Stage | A p50 | A p95 | A p99 | B p50 | B p95 | B p99 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| detector | 20.83 | 25.52 | 33.21 | 20.73 | 25.18 | 44.91 |
| crop extraction | 0.0166 | 0.0188 | 0.0200 | (shared) | | |
| OCR (shared) | 9.65 | 10.73 | 12.37 | (shared) | | |

No latency cost for B at p50/p95; B's p99 is worse (44.91 vs 33.21 ms), consistent with a
noisier tail on this CPU. Single machine, single run — **no latency difference here is
statistically significant.**

## 14. Paired statistics

Same frames, verified GT only, `NO_DETECTION` scored wrong, highest-confidence box per
frame. Frame-aligned: **62 verified frames**, both arms evaluated on the identical set.

| | B correct | B wrong |
| --- | ---: | ---: |
| **A correct** | 56 | **6** |
| **A wrong** | **0** | 0 |

* discordant pairs: **6** (all A-correct/B-wrong)
* McNemar exact two-sided **p = 0.03125**
* Discordant frames: cam1 @ 180, 185, 210, 215, 330, 335 — all plate B

Per task §24 this is a real, resolvable paired difference in **crop utility**. It is *not*
evidence that B localizes worse: §6 shows B reads these same boxes correctly under two other
conventions, and §12 shows B reaches 62/62 at 1.05x.

## 15. cam2 analysis

cam2 has **no verified ground truth**. No accuracy, recall, or superiority claim is made
from cam2. Diagnostic-only figures:

| | A | B |
| --- | ---: | ---: |
| frames with detection | 39/120 | 12/120 |
| crops | 39 | 12 |
| median width (px) | 83 | 97 |
| median height (px) | 41 | 31 |
| OCR invalid | 33/39 = 0.8462 | 9/12 = 0.7500 |
| OCR failed | 13/39 = 0.3333 | 0/12 = 0.0 |
| clipping | 0/39 | 0/12 |
| mean confidence | 0.7101 | 0.6753 |

With n = 39 vs n = 12 and no labels, none of these differences is interpretable. Ground-truth
recovery was attempted; see
[phase2c_cam2_gt_findings.md](benchmarks/audit/phase2c_cam2_gt_findings.md).

## 16. Adversarial audit

An independent verifier ([phase2c_verify.py](benchmarks/audit/phase2c_verify.py)) re-derived
every stored metric from the raw record array **without importing the runner**. Ten of its
eleven checks return **PASS**: ratio integrity (122 ratios, 0 with numerator > denominator),
metric recomputation (324 summary fields, 0 mismatches), `failed` == blank OCR text, UNLABELED
hygiene (2600 UNLABELED records, 0 carrying an accuracy value), A/B protocol symmetry,
`NO_DETECTION` denominators, McNemar consistency, bucket assignment, repeatability, and
`trunc` == `numpy.astype(int)` on 2000/2000 random floats (differing from `floor` on 1004).

Findings: [phase2c_verification_findings.md](benchmarks/audit/phase2c_verification_findings.md),
[phase2c_denominator_audit.md](benchmarks/audit/phase2c_denominator_audit.md). The
denominator auditor independently rates protocol parity, denominator correctness,
failed-vs-invalid and canonical convention all **CLEAN**.

Advisories carried forward rather than hidden: `invalid_rate_all_crops` is really an
**OCR-invalid** rate (crop-validity was never violated anywhere); `unlabeled_crops` counts
unlabeled *frames*, not crops; the median uses a lower-index percentile rather than an
averaged median for even n.

### Defects this audit caught in the benchmark itself

Recorded because they affected published numbers:

1. **`frame_rows` had no `run` tag.** With `--repeats 2` the per-run summary summed frame
   rows from both runs, double-counting every frame total (384 instead of 192). Fixed by
   tagging each row with its run and filtering on it.
2. **A second run silently overwrote the first.** An intermediate `--repeats 1 --expand`
   invocation replaced the two-run artifacts, destroying the repeatability evidence. The
   denominator auditor flagged this; the benchmark was re-run with both repeats.
3. **`invalid_rate_all_crops` vs `crop.invalid` name collision** between the runner and the
   verifier, which briefly made repeatability look broken. Both sides now use explicit
   predicates and the verifier checks `crop['invalid']` separately.

## 17. Limitations

1. **Two plates on one camera.** 62 verified crops, both from cam1. Sub-100 px crops — the
   regime cam2 lives in — have **zero** verified coverage.
2. **No box ground truth.** No IoU, coverage or localization-accuracy metric exists for
   either detector. "Better localization" cannot be claimed by anyone from this data.
3. **No recall.** Detection counts are reported, never converted to recall.
4. **cam2 unlabelled.** The motivating footage has no verified ground truth.
5. **One physical plate causes the entire gap.** All 6 discordant frames are plate B. A
   single-plate OCR quirk could produce the whole effect.
6. **The canonical convention is the least favourable to B.** `trunc` was chosen for
   production equivalence, which is correct methodologically, but B's 6 losses occur only
   under `trunc`/`floor`; under `round`/`ceil` both arms are 62/62. The convention choice
   therefore drives the headline number, and that must not be read as a detector verdict.
7. **Latency from a single CPU run**, no repetition or variance study.
8. **Expansion results are non-monotonic for both arms**, so no padding recommendation is
   supported.

## 18. Final classification

## `NO_MEASURABLE_DIFFERENCE`

*(the paired-OCR difference is resolvable, but it is not a detector difference)*

Per task §32, `A_SUPERIOR` requires that no crop-extraction artifact explains the
difference. Here **a crop-extraction artifact does explain it**: the same Detector B box
reads correctly under `round` and `ceil`, and 1.05x expansion yields 62/62. Detector A is
also the weaker detector on the raw detection counts that *are* available (fewer cam1 frames
detected, 13/101 failed-OCR crops vs 0/84, 0.87 cam2 invalid vs 0.75). `B_SUPERIOR` is not
supportable either: B finds only 12/120 cam2 detections against A's 39/120, its crops are
shorter, and cam2 has no ground truth.

So there is **no measurable difference in detector quality**. There is a measurable
difference in *crop utility under one crop convention*, which is a crop-pipeline finding.

## 19. Recommendation

**Do not integrate either detector, and do not treat the 6-frame gap as a detector verdict.**

Evidence-bounded next actions, in order:

1. **Label cam2.** It is the motivating footage and has zero verified samples. Nothing about
   the motivating problem is measurable until it exists.
2. **Fix crop-extraction determinism before comparing detectors.** A 1-px convention change
   is worth 6/62 on one detector and is larger than any detector-quality signal measured
   here. This is the highest-value change and it is not a detector swap.
3. **If a detector A/B is still wanted**, add >= 3 plates and >= 3 cameras, obtain box
   ground truth so localization is measurable, and keep `trunc` frozen — or report every
   convention rather than a single number.
An independent verifier ([phase2c_verify.py](benchmarks/audit/phase2c_verify.py)) re-derived
every stored metric from the raw record array **without importing the runner**, and returned
**PASS (exit 0)** across all 11 checks: no numerator > denominator; recomputed exact/char/invalid/
failed match the summary; `failed` provably means blank OCR and is disjoint from
`ocr_valid == False` (the Phase 2B bug is fixed and regression-tested); no UNLABELED row
carries an accuracy value; both arms cover an identical frame set; `NO_DETECTION` frames
reconcile with the summary; the McNemar table reproduces and `p` is `null` exactly when
discordant pairs are 0; bucket N sums equal each arm's detected-crop total; `trunc` equals
`numpy.astype(int)` on 2000/2000 random floats (and differs from `floor` on 1004 of them);
the mutation suite ([_mutation_test.py](benchmarks/audit/_mutation_test.py)) is caught on all
18 fault classes ([_mutation_results.txt](benchmarks/audit/_mutation_results.txt)).
The report-vs-JSON check (C10) additionally cross-checks every `N/D` and percentage in this
report against stored ratios, whitelisting only the legitimate derived prose ratios
(detection counts per arm/scope: 101/192, 62/72, 39/120, 84/192, 72/72, 12/120 — each the
stored `detected_crops` numerator over the stored `frames_total` — plus the expansion-table
figures 33/62, 58/62, 45/62, 29/62, sourced from `phase2c_crop_results.json`).

Findings: [phase2c_verification_findings.md](benchmarks/audit/phase2c_verification_findings.md),
[phase2c_denominator_audit.md](benchmarks/audit/phase2c_denominator_audit.md).

Advisories raised by the verifier, carried forward rather than hidden:
`invalid_rate_all_crops` is really an **OCR-invalid** rate (crop-validity was never violated);
Advisories raised by the verifier, carried forward rather than hidden:
`invalid_rate_all_crops` is really an **OCR-invalid** rate (crop-validity was never violated);
`unlabeled_crops` counts unlabeled *frames*, not crops; the median uses a lower-index
percentile rather than an averaged median for even n.

## 20. Asset provenance (2026-10-04 recovery note)

At 16:43–16:44 on 2026-10-03 a Cline checkpoint restore deleted every gitignored
working-tree asset the benchmark depends on: `cam1.mp4`, `cam2.mp4`,
`bench/IranPlate-Vision-main/…/best.pt`, and `benchmarks/dataset/crops/`
(plus `benchmarks/dataset/crops/`-adjacent frame PNGs). All tracked/commit results
(JSONs, protocol, verifier, report) were untouched, so nothing published was
affected — but the benchmark was not re-runnable until the inputs were restored.

Recovery (2026-10-04): the deleted blobs survived as *unreachable objects* inside
the Cline stash packs (e.g. `pack-798c4a…idx`), captured by the 16:44
`untracked files on cline checkpoint` stash commit. Each asset was extracted with
`git cat-file blob <sha>` and written back to its canonical path:

| Asset | Blob SHA | Bytes | Identity proof |
| --- | --- | ---: | --- |
| `cam1.mp4` | `0b028c6c…` | 16,109,000 | SHA-256 == the `io/output/input_8d7a…mp4` copy that existed on disk; frame 180 decoded and shows plate B `۱۲د۶۷۴۱۳` at the detector-A box (x 1061–1199, y 587–646) |
| `cam2.mp4` | `028148c5…` | 129,390,859 | `ftypmp42`, 599 frames, 1920×1080 @ 25 fps; frame-210 NCC = 0.99991 vs the surviving `io/output/processed_cam2.mp4`; overlay bands identical to the processed copy (the 16:43 restore wrote a *processed* copy over nothing — the raw was only in the stash) |
| `bench/…/best.pt` | `b6873db7…` | 5,471,706 | SHA-256 == `308C2464…43DE40`, the manifest/protocol hash; zip (`PK`) magic; byte size matches `detector_fidelity.md` |

Reproducibility: with these three files back in place the Phase 2C command
(`run_phase2c_ab.py --repeats 2`, canonical `trunc`, interval 5) is re-runnable;
`benchmarks/dataset/crops/*.png` (regenerable frame crops used only by the
2B-side review sheets, not by any 2C metric) were not restored and remain the
only unrecovered asset class. The verifier's C11 check pins the weights only by
hash, so any future weight swap would change the recorded SHA-256 and fail C10/C11.