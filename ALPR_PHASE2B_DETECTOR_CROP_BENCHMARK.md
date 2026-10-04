# ALPR Phase 2B — Detector A/B + Crop Quality Benchmark

**Date:** 2026-09-30 · **Repo:** `D:\alpr` · **Branch:** `main` · **HEAD:** `f9bd7bb` (unchanged)
**Production code changed:** NO · **Production model changed:** NO · **Commit created:** NO

> **Headline:** with the *same* frames, the *same* confidence threshold and the *same* production OCR, **both detectors reach 62/62 verified exact on cam1**. The regression reported in Phase 2A (`IranPlate-Vision + current OCR` = 0.903) is **reproduced in this run with the crop-boundary mechanism identified** — a **crop-boundary quantization artifact (±1 px)** rather than a detector-quality difference. *Scope of that claim: the reproduction rests on 6 samples from **one plate in a single run**, and the direction/sign of the artifact depends on the crop convention chosen, so a single run on one plate cannot exclude other contributors.* The cam2 "improvement" **changes sign** depending on the same crop convention and is therefore **not established**.
>
> **Also:** "62/62 verified frames exact" is a rate **per detected, verified frame** — frames in which a detector returned no box are excluded from the denominator. It is **not** a recall/frame-detection figure.

---

## 1. Executive summary

| Question | Answer (evidence-based) |
| --- | --- |
| Does IranPlate-Vision beat the production detector on verified OCR accuracy? | **No measurable difference**: 62/62 vs 62/62 verified exact at identical conditions. |
| Are its crops bigger? | **Not on cam1** (median 201.8 px vs production 227.4 px). Overall yes (168.0 vs 138.2) only because it returns fewer cam2 crops. |
| Does it clip the frame boundary? | **No** — 0.0 % clipping for both detectors. |
| Does it improve cam2? | **Unproven** — the invalid-rate difference flips sign with crop convention (current 0.821/IPV 0.917 round vs current 0.846/IPV 0.750 floor). |
| Does it regress cam1? | Only under floor-cropping (56/62); **reproduced in this run with the crop-boundary mechanism identified** (6 samples, 1 plate, 1 run). |
| Latency cost? | **None** — detector p50 20.5 ms vs 20.8 ms; end-to-end p50 30.5 ms vs 30.8 ms. |
| Is the result threshold-dependent? | **No** — both detectors are 62/62 at every threshold 0.2–0.6. |

**Classification: `MORE_DATA_REQUIRED`** — not because the detectors differ, but because the verified dataset covers two plates from one camera while the motivating footage (cam2) has **no ground truth**, and the dominant fragility found is a *crop-extraction* issue that neither detector controls.

---

## 2. Dataset

* `benchmarks/dataset/` — 84 crops extracted by the production detector; **62 verified** (cam1: `۲۸ی۶۸۹۲۳`, `۱۲د۶۷۴۱۳`), **22 cam2 UNLABELED** ([ground_truth.jsonl](benchmarks/dataset/ground_truth.jsonl), [gt_labels.json](benchmarks/dataset/gt_labels.json)).
* Phase 2B does not add crops: it re-runs the **source frames** (every 5th) through both detectors, so comparisons are on identical frames (192 sampled: 72 cam1 + 120 cam2).
* No ground truth was invented for cam2 (task rule). cam2 is used for crop quality, detector behaviour, clipping, confidence and validity only.

## 3. Methodology

```text
identical frame
   ├── Detector A: production plate detector ──► crop ─┐
   └── Detector B: IranPlate-Vision best.pt  ──► crop ─┤
                                                       └── SAME OCR (CURRENT_PRODUCTION) ──► GT
```
* **Identical confidence threshold (0.5) for both detectors** — the Phase 2A run had production at 0.5 and IranPlate-Vision at 0.4, which is itself a confound and is corrected here.
* Accuracy uses the existing normalization/metrics ([benchmarks/metrics.py](benchmarks/metrics.py)); verified samples only.
* Runner: [benchmarks/run_phase2b_ab.py](benchmarks/run_phase2b_ab.py) (reuses the existing adapters, dataset and metrics — no parallel framework).
* Warm-up (6 frames) excluded from all latency figures.

## 4. Detector configurations

| | Detector A | Detector B |
| --- | --- | --- |
| Artifact | `weigths/plate_det_model.pt` (production) | `bench/IranPlate-Vision-main/.../best.pt` |
| sha256 | `C70A91B5D695C2B8302BBE4F8AB6112DDC7845159F2FCC91CD50072D401ED00C` | `308C24643EAF49FC38930CEBFC46CA7455E7472F1D83FE98A2AE24443043DE40` |
| Classes | 1 (`plate`) | 1 (`Plates`) |
| Calls | `conf=0.5, iou=0.45, max_det=12` (imgsz = model default) | `conf=0.5` (imgsz = model default, max_det = Ultralytics default) |
| Role | production baseline | candidate under evaluation |

## 5. Ground-truth scope

62 verified crops / 2 unique plates / 1 camera (cam1). **Statistical caution (task §18): percentages are reported with raw counts; the smallest meaningful difference in this dataset is 1 crop = 1.6 %.**

## 6. Overall results (sweep of every 5th frame, conf 0.5, round crop convention)

| Metric | Current Detector | IranPlate-Vision |
| --- | ---: | ---: |
| verified samples | 62 | 62 |
| **exact accuracy** | **1.000 (62/62)** | **1.000 (62/62)** |
| character accuracy | 1.000 | 1.000 |
| edit distance (mean) | 0.000 | 0.000 |
| invalid rate (all crops, incl. UNLABELED cam2) | 0.317 (32/101) | 0.131 (11/84) |
| failed rate (empty OCR) | 0.119 (12/101) | 0.000 (0/84) |
| median crop width | 138.2 px | 168.1 px |
| median crop height | 58.4 px | 53.3 px |
| **clipping rate** | **0.000** | **0.000** |
| detector confidence mean | 0.742 | 0.791 |
| detector latency p50 | 20.83 ms | 20.54 ms |
| OCR latency p50 | 10.59 ms | 9.91 ms |
| total latency p50 | 31.29 ms | 30.59 ms |

Frame level: both detectors achieved **62/62 verified frames exact** (`verified_frame_exact_accuracy = 1.000`).

## 7. cam1 results (the only camera with ground truth)

| Metric | Current Detector | IranPlate-Vision |
| --- | ---: | ---: |
| crops | 62 | 72 (10 extra frames beyond the verified ranges) |
| verified | 62 | 62 |
| exact | **62/62 = 1.000** | **62/62 = 1.000** |
| invalid / failed | 0.000 / 0.000 | 0.000 / 0.000 |
| median crop width | **227.4 px** | 201.8 px |
| clipping | 0.000 | 0.000 |
| detector / OCR / total p50 | 20.6 / 10.1 / 30.8 ms | 20.5 / 9.9 / 30.5 ms |

**cam1 conclusion:** at identical conditions there is **no accuracy difference**; the production detector's crops are ~11 % wider on this camera.

## 8. cam2 diagnostics — `Ground Truth unavailable: accuracy not measurable`

| Metric | Current Detector | IranPlate-Vision |
| --- | ---: | ---: |
| crops detected (120 frames) | 39 | 12 |
| median crop width | 83.0 px | 98.2 px |
| width p10 / p90 | 74.2 / 113.5 px | 75.6 / 119.2 px |
| clipping rate | 0.000 | 0.000 |
| OCR invalid rate (round) | **0.821** | 0.917 |
| OCR invalid rate (floor) | 0.846 | **0.750** |
| failed (empty OCR) | 0.308 | 0.000 |
| detector confidence mean | 0.710 | 0.675 |
| detector / total latency p50 | 21.0 / 33.1 ms | 20.7 / 31.1 ms |

**Facts:** IranPlate-Vision finds **far fewer** cam2 plates (12 vs 39). Its invalid rate is *worse* under the round convention and *better* under floor.
**Observation:** the difference is driven by a handful of samples (1 crop ≈ 8.3 % of that 12-crop set).
**Hypothesis (untested):** box framing on sub-100 px plates is what varies; both detectors under-size the plate relative to its true extent (see §19 expansion results, which are non-monotonic and therefore do not confirm it).

## 9. Crop-size analysis (buckets, both cameras)

Buckets are exactly `benchmarks/ab_helpers.bucket_for()`: `lt80` (0–79), `80-99`, `100-149`, `150-199`, `ge200` (≥ 200). Accuracy is reported only where ground truth exists (`gt_status == LABELED`); every other cell reads *Ground Truth unavailable — accuracy not measurable*. Regenerate with `python benchmarks/audit/build_bucket_tables.py` (source of truth: `benchmarks/results/phase2b_detector_crop_results.json` → `records`, 185 rows).

### 9.1 Per detector × width bucket (all columns required by task §8)

| Detector | Camera | Width bucket | n samples | exact accuracy | character accuracy | invalid rate | failed rate | median OCR latency (ms) | median detector latency (ms) | clipping rate |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Current | cam1 | < 80 px | 0 | — | — | n/a | n/a | n/a | n/a | n/a |
| Current | cam1 | 80–99 px | 0 | — | — | n/a | n/a | n/a | n/a | n/a |
| Current | cam1 | 100–149 px | 21 | **1.000 (21/21)** | 1.000 | 0.000 (0/21) | 0.000 (0/21) | 11.3 | 20.5 | 0.000 (0/21) |
| Current | cam1 | 150–199 px | 0 | — | — | n/a | n/a | n/a | n/a | n/a |
| Current | cam1 | ≥ 200 px | 41 | **1.000 (41/41)** | 1.000 | 0.000 (0/41) | 0.000 (0/41) | 9.7 | 20.6 | 0.000 (0/41) |
| Current | cam2 | < 80 px | 7 | *Ground Truth unavailable* | *Ground Truth unavailable* | 0.857 (6/7) | 0.000 (0/7) | 13.3 | 22.6 | 0.000 (0/7) |
| Current | cam2 | 80–99 px | 20 | *Ground Truth unavailable* | *Ground Truth unavailable* | 0.750 (15/20) | 0.200 (4/20) | 12.1 | 21.0 | 0.000 (0/20) |
| Current | cam2 | 100–149 px | 10 | *Ground Truth unavailable* | *Ground Truth unavailable* | 0.900 (9/10) | 0.600 (6/10) | 11.3 | 21.0 | 0.000 (0/10) |
| Current | cam2 | 150–199 px | 2 | *Ground Truth unavailable* | *Ground Truth unavailable* | 1.000 (2/2) | 1.000 (2/2) | 10.7 | 20.3 | 0.000 (0/2) |
| Current | cam2 | ≥ 200 px | 0 | — | — | n/a | n/a | n/a | n/a | n/a |
| IranPlate-Vision | cam1 | < 80 px | 0 | — | — | n/a | n/a | n/a | n/a | n/a |
| IranPlate-Vision | cam1 | 80–99 px | 0 | — | — | n/a | n/a | n/a | n/a | n/a |
| IranPlate-Vision | cam1 | 100–149 px | 21 | **1.000 (21/21)** | 1.000 | 0.000 (0/21) | 0.000 (0/21) | 10.4 | 20.5 | 0.000 (0/21) |
| IranPlate-Vision | cam1 | 150–199 px | 10 | *Ground Truth unavailable* | *Ground Truth unavailable* | 0.000 (0/10) | 0.000 (0/10) | 10.4 | 20.2 | 0.000 (0/10) |
| IranPlate-Vision | cam1 | ≥ 200 px | 41 | **1.000 (41/41)** | 1.000 | 0.000 (0/41) | 0.000 (0/41) | 9.8 | 20.5 | 0.000 (0/41) |
| IranPlate-Vision | cam2 | < 80 px | 3 | *Ground Truth unavailable* | *Ground Truth unavailable* | 1.000 (3/3) | 0.000 (0/3) | 11.3 | 20.5 | 0.000 (0/3) |
| IranPlate-Vision | cam2 | 80–99 px | 4 | *Ground Truth unavailable* | *Ground Truth unavailable* | 1.000 (4/4) | 0.000 (0/4) | 10.3 | 20.8 | 0.000 (0/4) |
| IranPlate-Vision | cam2 | 100–149 px | 5 | *Ground Truth unavailable* | *Ground Truth unavailable* | 0.800 (4/5) | 0.000 (0/5) | 10.1 | 20.9 | 0.000 (0/5) |
| IranPlate-Vision | cam2 | 150–199 px | 0 | — | — | n/a | n/a | n/a | n/a | n/a |
| IranPlate-Vision | cam2 | ≥ 200 px | 0 | — | — | n/a | n/a | n/a | n/a | n/a |

`—` = the bucket contains no crops for that camera; `n/a` = denominator zero. *Ground Truth unavailable* means no label exists (all cam2 rows and all sub-150 px rows), so no accuracy or character accuracy is claimed. Clipping rate is 0.000 in every populated bucket.

### 9.2 Comparison repeated per crop-width bucket (task §11)

Crops of both cameras pooled per bucket; accuracy rows use LABELED crops only, geometry / latency / invalidity rows use all crops in the bucket.

| Bucket | Metric | Current Detector | IranPlate-Vision |
| --- | --- | ---: | ---: |
| < 80 px | verified samples | 0 | 0 |
| | exact accuracy | *Ground Truth unavailable* | *Ground Truth unavailable* |
| | character accuracy | *Ground Truth unavailable* | *Ground Truth unavailable* |
| | edit distance (mean) | *Ground Truth unavailable* | *Ground Truth unavailable* |
| | invalid rate | 0.857 (6/7) | 1.000 (3/3) |
| | failed rate | 0.000 (0/7) | 0.000 (0/3) |
| | median crop width (px) | 69.7 | 75.6 |
| | median crop height (px) | 33.9 | 26.3 |
| | clipping rate | 0.000 (0/7) | 0.000 (0/3) |
| | detector latency p50 (ms) | 22.6 | 20.5 |
| | OCR latency p50 (ms) | 13.3 | 11.3 |
| | total latency p50 (ms) | 35.8 | 31.7 |
| 80–99 px | verified samples | 0 | 0 |
| | exact accuracy | *Ground Truth unavailable* | *Ground Truth unavailable* |
| | character accuracy | *Ground Truth unavailable* | *Ground Truth unavailable* |
| | edit distance (mean) | *Ground Truth unavailable* | *Ground Truth unavailable* |
| | invalid rate | 0.750 (15/20) | 1.000 (4/4) |
| | failed rate | 0.200 (4/20) | 0.000 (0/4) |
| | median crop width (px) | 82.5 | 89.9 |
| | median crop height (px) | 40.5 | 29.1 |
| | clipping rate | 0.000 (0/20) | 0.000 (0/4) |
| | detector latency p50 (ms) | 21.0 | 20.8 |
| | OCR latency p50 (ms) | 12.1 | 10.3 |
| | total latency p50 (ms) | 33.2 | 31.1 |
| 100–149 px | verified samples | 21 | 21 |
| | exact accuracy | **1.000 (21/21)** | **1.000 (21/21)** |
| | character accuracy | 1.000 | 1.000 |
| | edit distance (mean) | 0.000 | 0.000 |
| | invalid rate | 0.290 (9/31) | 0.154 (4/26) |
| | failed rate | 0.194 (6/31) | 0.000 (0/26) |
| | median crop width (px) | 137.9 | 139.9 |
| | median crop height (px) | 58.3 | 51.1 |
| | clipping rate | 0.000 (0/31) | 0.000 (0/26) |
| | detector latency p50 (ms) | 20.8 | 20.6 |
| | OCR latency p50 (ms) | 11.3 | 10.4 |
| | total latency p50 (ms) | 31.5 | 30.8 |
| 150–199 px | verified samples | 0 | 0 |
| | exact accuracy | *Ground Truth unavailable* | *Ground Truth unavailable* |
| | character accuracy | *Ground Truth unavailable* | *Ground Truth unavailable* |
| | edit distance (mean) | *Ground Truth unavailable* | *Ground Truth unavailable* |
| | invalid rate | 1.000 (2/2) | 0.000 (0/10) |
| | failed rate | 1.000 (2/2) | 0.000 (0/10) |
| | median crop width (px) | 186.1 | 162.2 |
| | median crop height (px) | 65.0 | 47.4 |
| | clipping rate | 0.000 (0/2) | 0.000 (0/10) |
| | detector latency p50 (ms) | 20.3 | 20.2 |
| | OCR latency p50 (ms) | 10.7 | 10.4 |
| | total latency p50 (ms) | 30.9 | 30.8 |
| ≥ 200 px | verified samples | 41 | 41 |
| | exact accuracy | **1.000 (41/41)** | **1.000 (41/41)** |
| | character accuracy | 1.000 | 1.000 |
| | edit distance (mean) | 0.000 | 0.000 |
| | invalid rate | 0.000 (0/41) | 0.000 (0/41) |
| | failed rate | 0.000 (0/41) | 0.000 (0/41) |
| | median crop width (px) | 228.4 | 201.8 |
| | median crop height (px) | 66.0 | 53.3 |
| | clipping rate | 0.000 (0/41) | 0.000 (0/41) |
| | detector latency p50 (ms) | 20.6 | 20.5 |
| | OCR latency p50 (ms) | 9.7 | 9.8 |
| | total latency p50 (ms) | 30.3 | 30.4 |

**Facts (with raw counts):** in the **only 2 of 5** buckets where ground truth exists (100–149 px: 21/21 each; ≥ 200 px: 41/41 each), **both detectors are 100 % exact, character accuracy 1.000, edit distance 0.000** — no per-bucket accuracy difference. *Caveat: both verified buckets come from the same 2 plates; the < 100 px regime has **zero verified coverage**, so this does not establish robustness across crop sizes.* The production detector produces no verified 150–199 px crops; IranPlate-Vision produces 10 there, all UNLABELED cam2. Sub-150 px buckets have **no ground truth at all** (verified samples = 0 for both detectors), so their accuracy rows are explicitly not measurable; the only measurable sub-150 px signal is validity/failure — Current is better on invalid rate (0.857 vs 1.000 at < 80 px; 0.750 vs 1.000 at 80–99 px; 0.290 vs 0.154 at 100–149 px) but carries a non-zero failed rate (0.194 at 100–149 px) that IranPlate-Vision does not (0.000). Clipping rate is **0.000 in every bucket for both detectors**. Bucket counts below 150 px are tiny (n = 2–20), so per-crop differences there are not statistically meaningful (task §18).

## 10. Clipping analysis

| Detector | clipped_left | right | top | bottom | any (rate) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current | 0 | 0 | 0 | 0 | **0 / 101 (0.000)** |
| IranPlate-Vision | 0 | 0 | 0 | 0 | **0 / 84 (0.000)** |

**Fact:** neither detector places boxes on the frame boundary, so *frame-boundary* clipping is not the cam2 problem. The cam2 failure mode seen in Phase 2A is **box under-sizing** (plate extends past the detected box), which boundary-clipping flags cannot detect — see §16 limitations.

## 11. Pairwise analysis (matched boxes, IoU ≥ 0.1)

| Outcome | cam1 | cam2 | Meaning |
| --- | ---: | ---: | --- |
| BOTH_CORRECT | **62** | 0 | identical correctness — no superiority |
| CURRENT_BETTER | 0 | 0 | — |
| IRANPLATE_BETTER | 0 | 0 | — |
| BOTH_WRONG | 0 | 0 | — |
| CURRENT_ONLY_VALID | 0 | 1 | validity-only signal (no GT) |
| IRANPLATE_ONLY_VALID | 0 | 0 | — |
| NEITHER_VALID | 0 | 7 | both unusable on 7 cam2 pairs |
| INCOMPARABLE (unmatched detections) | 0 | 3 | **not used to infer superiority** |

**Fact:** all 62 GT-comparable cam1 pairs are `BOTH_CORRECT`. No pairwise evidence favours either detector.

**Coverage caveat:** this table covers only frames where **both** detectors produced a box. 43 of the 185 detections (cam1: 10, cam2: 33) sit on frames where the other detector found nothing and are **not** listed here as `INCOMPARABLE`. §11 is therefore valid for matched-box comparisons only and must **not** be used to compare detection counts (see §18 limitation 7).

## 12. Latency (CPU only, GPU = NOT_AVAILABLE, warm-up excluded)

| Stage | Current p50 | Current p95 | IranPlate p50 | IranPlate p95 |
| --- | ---: | ---: | ---: | ---: |
| detector | 20.83 ms | 22.65 ms | 20.54 ms | 22.54 ms |
| crop (in-process slice) | < 0.1 ms | — | < 0.1 ms | — |
| OCR (identical model) | 10.59 ms | 13.60 ms | 9.91 ms | 11.25 ms |
| **total** | **31.29 ms** | **36.24 ms** | **30.59 ms** | **32.47 ms** |

**CORRECTION (2026-10-03).** This table previously printed p95 values of
25.8 / 25.4 / 13.2 / 12.6 ms. Those were wrong. p50 **and** p95 have now been
recomputed directly from the `records` array of
`benchmarks/results/phase2b_detector_crop_results.json` (n = 101 current,
84 IranPlate-Vision; median = `statistics.median`, p95 = nearest-rank
`ceil(0.95·N)` on the sorted list). The JSON's own stored aggregates agree.

| Value | Was (report) | Now (recomputed) |
| --- | ---: | ---: |
| current detector p95 | 25.8 ms | **22.65 ms** |
| IranPlate-Vision detector p95 | 25.4 ms | **22.54 ms** |
| current OCR p95 | 13.2 ms | **13.60 ms** |
| IranPlate-Vision OCR p95 | 12.6 ms | **11.25 ms** |
| current total p95 | — (absent) | **36.24 ms** |
| IranPlate-Vision total p95 | — (absent) | **32.47 ms** |
| all p50 values | correct | unchanged (20.83 / 10.59 / 31.29 and 20.54 / 9.91 / 30.59) |

Cold-start model loading is excluded for this headline pass (warm-up = 6 frames per detector).

## 13. Threshold sensitivity (identical thresholds, both detectors)

| Threshold | Current det/frame | Current verified exact | IPV det/frame | IPV verified exact |
| --- | ---: | ---: | ---: | ---: |
| 0.20 | 0.792 | **62/62** | 0.536 | **62/62** |
| 0.30 | 0.740 | **62/62** | 0.500 | **62/62** |
| 0.40 | 0.682 | **62/62** | 0.453 | **62/62** |
| 0.50 | 0.526 | **62/62** | 0.438 | **62/62** |
| 0.60 | 0.469 | **62/62** | 0.427 | **62/62** |

**Fact:** verified accuracy is threshold-insensitive for both detectors across 0.2–0.6. **The Phase 2A cam1 regression was therefore not a threshold effect either** (both were 62/62 at every threshold) — only crop quantization and crop-convention differ (§15). *Caveat:* this is a saturated 62/62 ceiling metric, so "insensitive" means "no measurable degradation at this ceiling", which is a weaker statement than true threshold-invariance.

**Latency-health caveat for this sweep:** the threshold sweep and the crop-expansion passes (§17) perform **no warm-up** and **re-create the YOLO model for every threshold**, so their `median_detector_latency_ms` values are **cold-start contaminated and must NOT be quoted as steady-state**. Only the headline §12 pass (6 warm-up frames per detector, models reused) is a latency-health number.

## 14. Visual examples

[benchmarks/diagnostics/phase2b/ab_diagnostics.html](benchmarks/diagnostics/phase2b/ab_diagnostics.html) — annotated frames (green = current, blue = IranPlate-Vision), both crops enlarged with each OCR read, the verified GT, and the crop-convention outputs. Contains the 6 small-crop cases, 8 cam2 pairs and **17 crop-boundary sensitivity samples** (the §15 crop-boundary mechanism). Case index: `benchmarks/diagnostics/phase2b/case_index.json`.

## 15. Failure analysis — the cam1 regression, explained

**Measured (identical detector output, only crop edges differ):**

| Configuration | Current detector | IranPlate-Vision |
| --- | ---: | ---: |
| round crop edges | 62/62 | 62/62 |
| **floor crop edges** (Phase 2A combo runner) | 62/62 | **56/62 (= 0.903 — exactly the Phase 2A number)** |
| round −1 px (dx) | **47/62** | 62/62 |
| round +1 px (dx) | 62/62 | 62/62 |

**Reproduction in this run (6 samples, all from **one plate**, cam1 frames 180, 185, 210, 330, 335 and 1 further sample):** the same IranPlate-Vision box reads:

| Crop edges | OCR output |
| --- | --- |
| round / dx ±1 / dy +1 | `12d67413` ✔ correct |
| floor | `12d674913` ✘ (extra digit inserted) |
| dy −1 | `12da67413` ✘ (letter inserted) |

Answers to the §14 checklist: the crop was **not smaller** (same 140×51 px), **not shifted** beyond 1 px, **not clipped** (box interior), the **aspect ratio was unchanged**, **not** a wrong-object box (single detection, correct plate), detector confidence was **0.78 — high despite the bad read** (confidence ≠ correctness). The only difference is **crop-edge quantization**.

**Mechanism identified in this run:** crop-edge quantization is the only difference that varies across these cases. **Scope of this conclusion:** it is reproduced here on **6 samples from 1 plate in a single run**; the **sign** of the artifact is **convention-dependent** (floor vs round), so a single run on one plate **cannot exclude other contributors** to the Phase 2A number. This is an **OCR/crop-extraction robustness issue in the shared downstream path**, and the measured spread (47/62 – 62/62) is larger than any difference measured between the two detectors.

## 16. cam2 improvement investigation

| Evidence | Current | IranPlate-Vision | n | Reading |
| --- | ---: | ---: | ---: | --- |
| invalid, round crop | 0.821 | 0.917 | 39 / 12 | — |
| invalid, floor crop | 0.846 | 0.750 | 39 / 12 | — |
| median crop width | 83.0 px | 98.2 px | 39 / 12 | — |
| clipping | 0 | 0 | 39 / 12 | tie |
| detector threshold | 0.5 | 0.5 | — | controlled |
| detection count | 39 | 12 | — | 12 vs 39, 1 crop ≈ 8.3 % of the IPV set |
| cam2 expansion (supplementary, off-spec factors 1.30/1.40) | 0.821 → 0.821 | 0.917 → 0.833 | 39 / 12 | non-monotonic |

No directional verdict ("current better" / "IPV better") is assigned to any row: n = 12 vs n = 39 on unlabeled data cannot separate a real effect from one or two crops, and the ordering flips with the crop convention. **The cam2 improvement is unproven.**

**Conclusion:** the cam2 difference is **not robust** — it flips sign with the crop convention and rests on 1–2 crops in a 12-crop IPV set. It is **not evidence of superiority**, and the Phase 2A "0.846 vs 0.800" gap is withdrawn as a finding.

**Off-spec note on the expansion row above:** the spec factors are 1.00 / 1.05 / 1.10 / 1.15 / 1.20. `benchmarks/results/phase2b_cam2_expansion.json` also contains **1.30 and 1.40**, which are **off-spec supplementary data** for cam2 only; they are not part of the compliant sweep in §17 and must not be read as spec results.

## 17. Crop expansion experiment (§19)

| Expansion | Current exact / invalid | IranPlate exact / invalid |
| --- | --- | --- |
| 1.00 | 1.000 / 0.317 | 1.000 / 0.131 |
| 1.05 | 0.968 / 0.327 | 1.000 / 0.095 |
| 1.10 | 0.952 / 0.376 | 1.000 / 0.119 |
| 1.15 | 1.000 / 0.307 | 1.000 / 0.083 |
| 1.20 | 0.935 / 0.347 | 1.000 / 0.083 |

Applied identically to both detectors' boxes, no production behaviour touched. **IranPlate-Vision's verified accuracy is stable at 1.000 across all expansions**; the production detector's non-monotonic 1.000 → 0.935 → 1.000 pattern is the same crop-boundary sensitivity as §15. cam2-only expansion (39 vs 12 crops) is non-monotonic for both and does **not** confirm an under-sizing fix. This pass has **no warm-up** (see the §13 latency caveat). *Data correction (2026-10-03):* the `failed_rate` column of the `crop_expansion` block in `phase2b_bucket_results.json` previously duplicated `invalid_rate`; the runner has been fixed (failed = empty OCR output) and the 1.00 rows corrected, while the 1.05–1.20 rows are `null` because they are not derivable from stored artifacts without a re-run.

## 18. Limitations

1. Verified ground truth = **2 plates on 1 camera**; the two cameras give 62 vs 22 crops — small-sample results must be read as raw counts.
2. cam2 (the motivating footage) has **no ground truth**; all cam2 statements are validity/quality diagnostics only.
3. IranPlate-Vision was run with its own Ultralytics defaults for `imgsz`/`max_det` while production uses `max_det=12`; this is a real configuration difference that a production A/B would need to normalize. **Full statement — configuration asymmetry (see [audit](benchmarks/audit/detector_fidelity.md), finding D1/D6):** Detector B runs at Ultralytics defaults **`iou=0.7`, `max_det=300`** while production (Detector A) uses **`iou=0.45`, `max_det=12`**. Consequences: (a) B can emit **duplicate boxes for one physical plate**, which inflates its `n_crops` and `median_crop_width` (84 vs 101 crops overall; cam2 12 vs 39); (b) the **benchmark KEEPS boxes whose OCR output is empty, while production DISCARDS them** (`alpr_engine.py` ~lines 373–374), so `n_crops`, `invalid_rate` and `failed_rate` are not on the same footing as production behaviour. No published number was changed on this basis; it is a comparability limitation, not a correction.
4. **Boundary-clipping flags cannot see box under-sizing** (the plate extending past the box), which is the cam2 failure mode; only 2 of the 22 cam2 crops had a read good enough for a human to verify, so no quantitative under-sizing metric exists yet.
5. Single run per configuration (no repeat/variance study); OCR is deterministic but crop-edge sensitivity means tiny code changes move results.
6. **Latency health:** the threshold sweep (§13) and crop-expansion passes (§17) have **no warm-up** and re-create the YOLO model per threshold/factor, so their `median_detector_latency_ms` is cold-start contaminated and must not be quoted as steady-state. Only §12 (6 warm-up frames per detector) is a latency-health figure.
7. **Pairwise coverage is not exhaustive over the detection set.** The pairwise table in §11 only covers frames where *both* detectors fired. **43 of the 185 detections (cam1: 10, cam2: 33) are excluded** because their frame had no detection from the other detector, and they are **not** reported as `INCOMPARABLE` rows. So §11 supports statements about *matched* boxes only — it **cannot** support the detection-count comparison (39 vs 12 cam2 crops) that §16 discusses. Detection counts must be read from §6/§8, never inferred from §11.

## 18b. Test results

Full suite (`python -m pytest -q`):

```text
11 failed, 486 passed, 116 warnings in 274.42s
```

* The **11 failures are PRE-EXISTING and unrelated to Phase 2B**: 6 auth-401 in `test_backend.py`, 3 FFmpeg/OpenH264, 2 other.
* Benchmark/validation tooling files (`tests/test_phase2b_tooling.py`, `tests/test_benchmark_metrics.py`, `tests/test_benchmark_tooling.py`, `tests/test_replay_validation_tooling.py`): **71 passed**.
* `tests/test_phase2b_tooling.py` alone: **41 passed**.
* A pytest **collection crash** was also fixed at root cause: `bench/` holds vendored third-party checkouts, one of which ships `scripts/smoke_test.py`; pytest's default `python_files` patterns match `*_test.py`, and importing that module ran its module-level `sys.exit(1)`, which `SystemExit` (a `BaseException`) escaped as `INTERNALERROR`. Fixed in the **test layer only** (`conftest.py`: `collect_ignore_glob` for `bench/*`, `benchmarks/audit/*`, `.freebuff/*`, plus a `pytest_configure` `testpaths` default of `tests`).
* Full detail: [benchmarks/audit/test_report.md](benchmarks/audit/test_report.md).

## 19. Recommendation

**Classify as `MORE_DATA_REQUIRED`.**

Next steps, in priority order (no production change):
1. **Fix the crop-extraction determinism question first** — quantify `round` vs `floor` vs ±1 px in the production path on a labeled set; a 24-point swing dwarfs the detector question.
2. **Label cam2** (a single human read of the best frame) and re-run this exact benchmark — it makes the whole comparison decidable without any methodology change.
3. If a detector A/B proceeds, normalize configuration (`imgsz`, `max_det`, threshold) and evaluate on ≥ 200 verified crops across ≥ 3 plates/cameras.
4. Only then consider a controlled production A/B behind the existing feature-flag mechanism.

Do **not** integrate, replace or change defaults now.

---

## Decision matrix (task §23)

| Question | Evidence | Verdict |
| --- | --- | --- |
| Does IranPlate improve verified OCR accuracy? | 62/62 vs 62/62 at identical conf; 62/62 pairs BOTH_CORRECT | **No measurable improvement** |
| Does it improve crop size? | cam1 median 201.8 px vs 227.4 px (production wider); overall 168.1 vs 138.2 | **Mixed; not on cam1** |
| Does it reduce clipping? | 0.000 vs 0.000 | **Equal** |
| Does it improve cam2 diagnostics? | invalid flips with crop convention (0.750 ↔ 0.917); 12 vs 39 crops | **Unproven** |
| Does it regress cam1? | only under floor cropping: 56/62 vs 62/62 | **Yes, under one crop convention** |
| Is the regression explained? | 6 samples, 1 plate, 1 run; reproduced by ±1 px crop edges; `12d674913`/`12da67413` | **Mechanism identified in this run (crop-edge quantization); not a general root-cause claim** |
| Latency cost? | 20.54 vs 20.83 ms detector p50; 30.59 vs 31.29 ms total p50 (p95 22.54 vs 22.65 / 32.47 vs 36.24) | **None (within noise)** |
| Robust across crop sizes? | 100 % exact in the **2 of 5** buckets that have verified GT, from the **same 2 plates** | **Yes where verified (2 buckets, same 2 plates); small-crop (< 100 px) regime untested (zero verified coverage)** |
| Threshold tuning responsible? | 62/62 for both at 0.2/0.3/0.4/0.5/0.6 | **No** |
| Enough evidence for a controlled production A/B? | 2 verified plates, 1 camera, cam2 unlabeled | **No** |

**Final classification: `MORE_DATA_REQUIRED`**

## Machine-readable artifacts

```text
benchmarks/results/phase2b_detector_crop_results.json
benchmarks/results/phase2b_pairwise_results.json
benchmarks/results/phase2b_bucket_results.json
benchmarks/results/phase2b_crop_sensitivity_results.json
benchmarks/results/phase2b_cam2_expansion.json
benchmarks/diagnostics/phase2b/ab_diagnostics.html
benchmarks/diagnostics/phase2b/case_index.json
benchmarks/diagnostics/phase2b/phase2b_crops.jsonl
```

## Reproduce

```bash
python benchmarks/run_phase2b_ab.py                 # A/B + buckets + sweep + expansion
python benchmarks/run_phase2b_crop_sensitivity.py   # crop-edge sensitivity
python benchmarks/build_phase2b_diagnostics.py      # visual diagnostics
python -m pytest tests/test_phase2b_tooling.py -q
```
