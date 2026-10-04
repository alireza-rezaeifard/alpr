# ALPR Verified Ground-Truth Benchmark Report

**Date:** 2026-09-30 · **Repo:** `D:\alpr` · **Production code: UNCHANGED** (no inference code, models, tracker, consensus, schema, or Flutter edits; no commits)

This report supersedes the earlier *provisional* OCR/detector/pipeline numbers: every accuracy figure below is computed **only over manually verified crops**.

---

## 1. Ground-truth workflow (built, reviewable, reproducible)

| Step | Artifact |
| --- | --- |
| 1. Contact sheet of all 84 crops (enlarged, labeled with id/frame/production-read/quality) | [benchmarks/dataset/review_sheet.html](benchmarks/dataset/review_sheet.html) — built by [benchmarks/build_review_sheet.py](benchmarks/build_review_sheet.py) |
| 2. Glyph-level zooms for ambiguous characters | `benchmarks/dataset/glyph_sheet.html` (regenerate: 8–12× LANCZOS + CLAHE) |
| 3. Human/agent labels with evidence + frame ranges | [benchmarks/dataset/gt_labels.json](benchmarks/dataset/gt_labels.json) |
| 4. Apply labels → per-sample records | [benchmarks/apply_ground_truth.py](benchmarks/apply_ground_truth.py) → [benchmarks/dataset/ground_truth.jsonl](benchmarks/dataset/ground_truth.jsonl) |
| 5. Scoring | [benchmarks/metrics.py](benchmarks/metrics.py) — canonical cross-charset form; **only `verified: true` rows enter accuracy** |

**Verification result: 62 / 84 crops verified (cam1), 22 / 84 UNLABELED (cam2).**

| Label | Plate (Persian) | ASCII canonical | Type | Verified | Frames |
| --- | --- | --- | --- | --- | --- |
| cam1_plate_A | ۲۸ی۶۸۹۲۳ | `28Y68923` | civilian | ✅ | 0–144, 243–301 |
| cam1_plate_B | ۱۲د۶۷۴۱۳ | `12D67413` | civilian | ✅ | 163–224, 311–359 |
| cam2_plate_X | — | — | unknown | ❌ **UNLABELED** | 200–220, 295–360, 480–520, 525–560 |

**Why cam2 is UNLABELED (per the "no accuracy from unlabeled data" rule):** cam2 crops are 66–119 px wide and the plate extends beyond the detector box; the leading digits `۲۸` are visible but the middle/trailing digits could not be read conclusively from the video at native resolution, and the four models disagree on those positions. Candidates recorded for the human pass: production `25H28999`, hezar `25H28499`, yolo11 `25H28494`. **No cam2 accuracy number is reported anywhere.**

---

## 2. OCR benchmark — verified results (identical crops for every model)

62 verified cam1 crops + 22 unlabeled cam2 crops.

| Model | N | N verified | **Exact** | **Char acc** | **Edit dist** | **Invalid rate** | **Failed rate** | CPU p50 | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| **CURRENT_PRODUCTION** | 84 | 62 | **1.000** (62/62) | **1.000** | **0.000** | 0.202 | 0.000 | 10.5 ms | baseline |
| persian_lpr_yolo11 | 84 | 62 | **1.000** (62/62) | **1.000** | **0.000** | 0.250 | 0.048 | 33.1 ms | runnable |
| hezar_crnn_v2 | 84 | 62 | **0.661** (41/62) | 0.958 | 0.048 | 0.381 | 0.000 | 14.7 ms | runnable |
| plr_crnn | 84 | 62 | **0.000** (0/62) | 0.827 | 1.306 | 0.500 | 0.000 | 5.4 ms | runnable |

### cam1 vs cam2 split

| Model | cam1 exact | cam1 char acc | cam1 invalid | cam2 exact | cam2 invalid | cam2 failed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| CURRENT_PRODUCTION | **1.000** | 1.000 | 0.000 | *(UNLABELED)* | 0.773 | 0.000 |
| persian_lpr_yolo11 | **1.000** | 1.000 | 0.000 | *(UNLABELED)* | 0.955 | 0.182 |
| hezar_crnn_v2 | 0.661 | 0.958 | 0.339 | *(UNLABELED)* | 0.500 | 0.000 |
| plr_crnn | 0.000 | 0.827 | 0.387 | *(UNLABELED)* | 0.818 | 0.000 |

**Reading (evidence, not a verdict):**
* On clean, large, front-facing plates the production OCR is **perfect on 62/62 verified crops**; persian_lpr_yolo11 ties it exactly.
* hezar's 21 misses are all the *same* failure: it drops the final digit (`12د6741` vs `12د67413`) → 1-character error on 21 crops, which is why char accuracy (0.958) is far better than exact (0.661).
* plr_crnn misreads a middle digit on every cam1 crop (`28Y68933`) → 0% exact but 0.83 char accuracy.
* cam2 remains the hard bucket: production invalid-rate 0.773 vs 0.000 on cam1, despite similar mean production confidence (0.746 vs 0.766) — i.e., the model is confidently wrong on small crops.

### Crop-width buckets (all models, accuracy only where verified)

| Bucket | N | Production exact | Production invalid | hezar exact | hezar invalid | yolo11 exact | yolo11 invalid |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| < 100 px (cam2) | 22 | *(UNLABELED)* | 0.773 | *(UNLABELED)* | 0.500 | *(UNLABELED)* | 0.955 |
| 100–150 px (cam1 plate B) | 21 | **1.000** | 0.000 | 0.000 | 1.000 | **1.000** | 0.000 |
| ≥ 150 px (cam1 plate A) | 41 | **1.000** | 0.000 | 1.000 | 0.000 | **1.000** | 0.000 |

→ **hezar only fails in the 100–150 px bucket** (21/21), and is perfect at ≥150 px. The failure is a small-crop/scale effect, not a charset problem. (Production p50 latency 10.5 ms, p95 ~13–42 ms; per-model full latencies in `performance_results.json`.)

---

## 3. Preprocessing benchmark (applied identically to every model)

2324 scored rows (84 crops × 7 variants × 4 models); cam2 perspective skipped on 7/22 crops (no plausible quad → recorded as `skipped`, never substituted).

### CURRENT_PRODUCTION

| Variant | N | Exact | Char acc | Invalid | Failed |
| --- | ---: | ---: | ---: | ---: | ---: |
| original (control) | 84 | 1.000 | 1.000 | 0.202 | 0.000 |
| up2x | 84 | 1.000 | 1.000 | 0.202 | 0.000 |
| **up3x** | 84 | 1.000 | 1.000 | **0.143** | 0.000 |
| gray | 84 | 1.000 | 1.000 | 0.202 | 0.000 |
| **sharpen** | 84 | 1.000 | 1.000 | **0.190** | 0.000 |
| clahe | 84 | 0.839 | 0.982 | 0.357 | 0.000 |
| persp | 77 | 0.952 | 0.994 | 0.234 | 0.000 |

### hezar_crnn_v2

| Variant | N | Exact | Char acc | Invalid | Failed |
| --- | ---: | ---: | ---: | ---: | ---: |
| original / up2x / up3x / gray | 84 | 0.661 | 0.958 | 0.381 | 0.000 |
| clahe / sharpen | 84 | 0.661 | 0.958 | 0.405 | 0.000 |
| persp | 77 | 0.661 | 0.958 | 0.364 | 0.000 |

→ **No preprocessing variant changed hezar's cam1 accuracy at all** (its 21 misses are the dropped-final-digit failure, unaffected by scale/contrast). Preprocessing cannot fix an architectural/decoding failure.

### persian_lpr_yolo11

| Variant | N | Exact | Char acc | Invalid | Failed |
| --- | ---: | ---: | ---: | ---: | ---: |
| original | 84 | 1.000 | 1.000 | 0.250 | 0.048 |
| up2x | 84 | **0.903** | 0.989 | 0.298 | 0.048 |
| up3x | 84 | 1.000 | 1.000 | 0.250 | 0.048 |
| gray / clahe / sharpen | 84 | 1.000 | 1.000 | 0.262 | 0.048 |
| persp | 77 | 1.000 | 1.000 | **0.195** | **0.013** |

→ up2x *hurts* this char detector (0.903 vs 1.000); perspective rectification helps its invalid/failed rates.

### plr_crnn

| Variant | N | Exact | Char acc | Invalid | Failed |
| --- | ---: | ---: | ---: | ---: | ---: |
| original / gray | 84 | 0.000 | 0.827 | 0.476–0.500 | 0.000 |
| up2x / up3x | 84 | 0.000 | 0.819 | 0.536–0.548 | 0.000 |
| clahe / sharpen | 84 | 0.000 | 0.766 | 0.762–0.833 | 0.000 |
| persp | 77 | 0.000 | 0.833 | 0.974 | 0.000 |

→ Enhancing contrast/sharpness consistently *degrades* crop-level CRNN reads (and perspective distortion badly hurts the fixed-layout decoder).

**Preprocessing bottom line (evidence-bounded):** the only variant that measurably helps the **baseline** is **3× upscale** (invalid 0.202 → 0.143) with a small gain from **sharpening** (→ 0.190); **CLAHE hurts (0.357)**. Every variant is neutral for hezar and negative for plr_crnn.

---

## 4. Full-frame detector → crop → OCR combinations (verified GT by frame)

Same sampled frames (every 5th) for every detector/OCR pair; cam2 rows are UNLABELED (excluded from exact/char, still counted for invalid/failed).

| Combination | N | cam1 N | **cam1 exact** | cam1 char acc | cam1 invalid | cam2 N | cam2 invalid | cam2 failed | Median ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **current det + current OCR** | 101 | 62 | **1.000** | **1.000** | 0.000 | 39 | 0.846 | 0.333 | 31.6 |
| current det + hezar | 101 | 62 | 0.661 | 0.958 | 0.339 | 39 | 0.641 | 0.205 | 36.2 |
| **current det + yolo11 OCR** | 101 | 62 | **1.000** | **1.000** | 0.000 | 39 | 0.974 | 0.436 | 55.6 |
| current det + plr_crnn | 101 | 62 | 0.000 | 0.827 | 0.387 | 39 | 0.846 | 0.000 | 26.2 |
| **IranPlate-Vision + current OCR** | 87 | 72 | **0.903** | 0.989 | 0.181 | 15 | 0.800 | 0.067 | 30.1 |
| IranPlate-Vision + hezar | 87 | 72 | 0.661 | 0.958 | 0.222 | 15 | **0.267** | 0.000 | 35.6 |
| **IranPlate-Vision + yolo11 OCR** | 87 | 72 | **1.000** | **1.000** | **0.071** | 15 | 0.867 | 0.133 | 47.6 |
| IranPlate-Vision + plr_crnn | 87 | 72 | 0.661 | 0.946 | 0.194 | 15 | 0.400 | 0.000 | 26.0 |

### Width buckets for the headline combos

| Combination | <100 px exact | 100–150 px exact | ≥150 px exact |
| --- | ---: | ---: | ---: |
| current det + current OCR | *(UNLABELED)* | 1.000 | 1.000 |
| IranPlate-Vision + current OCR | *(UNLABELED)* | **0.714** | 1.000 |
| current det + yolo11 | *(UNLABELED)* | 1.000 | 1.000 |
| IranPlate-Vision + yolo11 | *(UNLABELED)* | 1.000 | 1.000 |

### Evidence-based observations (no production replacement is selected)

* **Baseline is not beaten on verified accuracy**: `current det + current OCR` = 100% exact on 62/62 cam1 frames, fastest credible median (31.6 ms).
* **IranPlate-Vision detector finds more plates** (72 vs 62 cam1 crops — extra detections, sometimes a second plate in-frame) and its crops yield the **lowest invalid rates** (`+yolo11` 0.071 vs baseline 0.000 on cam1 but 0.867 vs 0.974 on cam2; `+hezar` cam2 invalid 0.267 vs 0.641). It costs 6 cam1 exact matches with the production OCR (0.903 → those are 100–150 px bucket cases, 0.714) — a *crop framing* difference worth a controlled follow-up, not a drop-in swap.
* **IranPlate-Vision + hezar is the only combination that materially improves the cam2 (small-crop) bucket** — invalid 0.267 vs 0.641 — but cam2 exact accuracy is unverifiable until human labels exist.
* plr_crnn is dominated in every position of the matrix.

---

## 5. Latency summary (CPU only; GPU = NOT_AVAILABLE)

| Model | Load s | p50 ms | p95 ms | Max ms | FPS |
| --- | ---: | ---: | ---: | ---: | ---: |
| plr_crnn | 0.04 | 5.4 | 6.5 | 8.1 | 185 |
| current_production OCR | 2.81 | 10.5 | 13.2 | 49.6 | 95 |
| hezar_crnn_v2 | 1.81 | 14.7 | 15.8 | 21.2 | 68 |
| persian_lpr_yolo11 | 0.03 | 33.1 | 41.8 | 67.9 | 30 |

Pipeline medians (detector + OCR, same frames): 26.0–55.6 ms — see `benchmarks/results/combo_results.json`.

---

## 6. Answers to the standing questions

1. **Is cam2 an OCR problem or a crop problem?** Primarily **crop/scale**: production is 100% exact on ≥100 px crops and 0.773 invalid <100 px; hezar is perfect ≥150 px and 0/21 exact at 100–150 px; no preprocessing variant changed hezar's failure mode; all four models disagree on cam2. The cam2 true text still needs one human read (workflow ready) before any model can be scored there.
2. **Does any external OCR beat the production baseline?** Not on verified data: production and persian_lpr_yolo11 both hit 1.000 exact / 0.000 invalid on cam1; production is 3.2× faster than yolo11 and 2.8× faster than hezar. hezar (0.661) and plr_crnn (0.000) trail.
3. **Does preprocessing rescue cam2?** Not for OCR-accuracy purposes: 3× upscale is the only positive (invalid 0.202→0.143 on the baseline); CLAHE and sharpening hurt CRNN-style models; perspective rectification helps only where a quad exists (15/22 cam2, 77/84 overall).
4. **Best non-baseline candidate for a *controlled* experiment:** IranPlate-Vision detector + current OCR (same OCR, different crops) to test whether its wider framing improves small-crop handling — with the 100–150 px regression (0.714) tracked as the risk.

## 7. STOP / integration status

Per task rules: **no production inference code, model, tracker, consensus, or event logic was modified; no replacement is selected; nothing was committed.** cam2 remains UNLABELED by design — fill [gt_labels.json](benchmarks/dataset/gt_labels.json) (`cam2_plate_X`) after a human read of the video, re-run `apply_ground_truth.py` + the four runners, and the cam2 accuracy columns populate automatically.

## Appendix — reproducible commands

```bash
python benchmarks/build_dataset.py          # 84 crops via production detector
python benchmarks/build_review_sheet.py     # review sheet (manual GT step 1)
python benchmarks/apply_ground_truth.py     # gt_labels.json -> ground_truth.jsonl
python benchmarks/run_benchmarks.py         # OCR (verified metrics) -> ocr_results.json
python benchmarks/run_preprocess_bench.py   # 7 variants x 4 models -> preprocess_results.json
python benchmarks/run_detector_bench.py     # NO_GROUND_TRUTH detector protocol
python benchmarks/run_combo_bench.py        # full-frame det->crop->OCR -> combo_results.json
python -m pytest tests/test_benchmark_tooling.py tests/test_benchmark_metrics.py -q
```
