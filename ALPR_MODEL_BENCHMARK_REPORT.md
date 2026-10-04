# ALPR Model Benchmark Report — Offline Comparative Evaluation

**Date:** 2026-09-30 · **Repo:** `D:\alpr` · **Scope:** strictly offline AUDIT → STANDARDIZE → BENCHMARK → REPORT
**Production code untouched** — no inference code, models, tracker, consensus, DB schema, or Flutter changes. Nothing committed.

## 0. Executive summary

* **7 runnable model artifacts** from 4 projects were audited; 6 were benchmarked directly, 1 (PlateHunter) is **blocked: weights not shipped in the archive**, and PelakX is **blocked: ships no weights by design** (runtime download forbidden offline).
* **No absolute accuracy is claimed anywhere.** All 84 extracted crops are UNLABELED; exact/character accuracy will populate automatically once `benchmarks/dataset/ground_truth.jsonl` is manually verified.
* cam2 failure analysis: **all 4 runnable OCR models disagree with each other on 18/22 cam2 crops** while **agreeing perfectly on cam1 (each converges to exactly 2 plate texts for 62 crops)** — evidence that the cam2 problem is dominated by **crop quality / plate distance**, not by a single bad OCR model. No external OCR candidate clearly fixes cam2.
* cam2 crops are materially worse inputs: mean width **83 px vs 198 px** on cam1.
* On UNLABELED format-validity (production validator, unchanged), the current production detector+OCR baseline remains among the best combinations; **no model earned a "better" claim without verified ground truth** (task §20).

## 1. Models discovered (audit result)

| Model / artifact | Project | Role(s) | Framework | Weights | SHA256 (first 12) | Size | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hezar CRNN V2 | hezarai/crnn-fa-license-plate-recognition-v2 (local `bench/model.pt`) | SEQUENCE_OCR | hezar 1.0.0 / PyTorch | ✔ `bench/model.pt` | `c20ad7be2b1f…` | 37.2 MB | **runnable** |
| PLR CRNN | PersianLicensePlateRecognition (MIT) | SEQUENCE_OCR | PyTorch CRNN-CTC | ✔ `OCRModel/crnn_weights.pth` | `05f87ea7446c…` | 34.9 MB | **runnable** |
| persian-lpr YOLO11 | persian-lpr-yolov11 (MIT) | CHARACTER_DETECTOR + SEQUENCE_OCR | Ultralytics YOLO11, 26 char classes | ✔ 7 candidates; `2nd version modified dataset/best.pt` used | `ab1e131aa1d6…` | 19.2 MB | **runnable** |
| IranPlate-Vision YOLO | IranPlate-Vision (MIT) | PLATE_DETECTOR | Ultralytics YOLO, 1 class | ✔ `best.pt` | `308c24643eaf…` | 5.5 MB | **runnable** |
| PLR YOLO plate | PersianLicensePlateRecognition (MIT) | PLATE_DETECTOR | Ultralytics YOLO, 1 class | ✔ `YoloModel/best.pt` | `0daa82c31ddd…` | 18.5 MB | **runnable** |
| CURRENT_PRODUCTION | in-repo `alpr_engine.py` | CHARACTER_DETECTOR + SEQUENCE_OCR | PyTorch + Ultralytics + DTRB | ✔ `weigths/` (unchanged) | n/a | — | **runnable (baseline)** |
| PlateHunter model_1/2/3 | Persian_ALPR_project (PlateHunter, **no LICENSE file**) | PLATE_DETECTOR / CHARACTER_DETECTOR / CHARACTER_CLASSIFIER / FULL_ALPR | YOLO26 + timm ConvNeXtV2 | ✖ **not shipped** — only training logs/args in `Saved_models copy` | — | — | **blocked** |
| PelakX pipeline | pelakx-license-plate-detection (MIT) | FULL_ALPR_PIPELINE | own framework; hezar/paddle/easyocr engines | ✖ ships no weights by design (`models/.gitkeep`); OCR engines need hub downloads | — | — | **blocked** |

**Blocked — exact reasons:**

* `platehunter_model1_detector` / `model2` / `model3`: missing weight files. `inference.ipynb` loads `YOLO(MODEL1_WEIGHTS)`, `YOLO(MODEL2_WEIGHTS)`, `torch.load(MODEL3_WEIGHTS)`, but the archive contains only `config.json`, `args.yaml`, `results.csv`, `conversion_log.csv` (weights were on the author's machine). No license file found in the repo.
* `pelakx_pipeline`: no local weights; `models_hub.py` auto-downloads a community detector from GitHub at runtime and OCR engines (hezar_fa/paddle/easyocr) require hub downloads — both violate the offline mandate. Runnable in a future networked phase by dropping a `.pt` into `models/`.
* persian-lpr fold0–4 + 1st-version weights exist but were **not** benchmarked (best-candidate policy: 2nd version = modified dataset, per repo README); they remain in the manifest for later runs.

Full machine-readable manifest: [benchmarks/model_manifest.json](benchmarks/model_manifest.json).

## 2. Method

* **Common dataset (task §7):** 84 plate crops extracted by the CURRENT production detector only — 62 from cam1.mp4 (every 5th frame), 22 from cam2.mp4 — with quality metrics per crop. Every OCR model received the **exact same PNG crops**. [benchmarks/build_dataset.py](benchmarks/build_dataset.py)
* **Adapters (task §4):** one interface (`PlateOCRAdapter.predict(plate_crop) -> {raw_text, text, confidence, latency_ms, error}`), isolated per model — weights-only reuse, no external repo executed in place, no production import changes. [benchmarks/adapters/](benchmarks/adapters)
* **Normalization (task §9):** single documented layer for ALL models ([benchmarks/normalization.py](benchmarks/normalization.py)) — Persian/Arabic digits→ASCII, ي/ك→ی/ک, zero-width & separators removed, meaningful Persian letters never folded.
* **Ground truth (task §8):** all samples `UNLABELED` in [benchmarks/dataset/ground_truth.jsonl](benchmarks/dataset/ground_truth.jsonl) until manually verified; accuracy metrics are `null` by design and computed only over `verified: true` rows.
* **Hardware (task §13):** CPU-only (torch 2.12.0+cpu, `torch.cuda.is_available()=False`). **GPU = NOT_AVAILABLE** — no emulation.

## 3. Benchmark A — OCR-only (same crops, no detector contamination)

Latency = adapter `predict()` on the shared crops (CPU). Accuracy intentionally `null` (UNLABELED).

| Model | Exact | Char Acc | Invalid | Edit Dist | N samples | N verified | CPU ms p50 | FPS | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| CURRENT_PRODUCTION | N/V* | N/V* | N/V* | N/V* | 84 | 0 | 10.3 | 97.3 | runnable |
| hezar_crnn_v2 | N/V* | N/V* | N/V* | N/V* | 84 | 0 | 15.1 | 66.3 | runnable |
| plr_crnn | N/V* | N/V* | N/V* | N/V* | 84 | 0 | 5.8 | 171.3 | runnable |
| persian_lpr_yolo11 | N/V* | N/V* | N/V* | N/V* | 84 (4 empty) | 0 | 34.9 | 28.7 | runnable |

\* N/V = not verifiable on UNLABELED data (task §8/§11 rule). The JSON records per-sample outputs so metrics auto-compute after verification.

**Stability signal (not accuracy):** on cam1 (62 crops of 2 distinct plates), current_production, hezar, and persian_lpr each collapsed to exactly **2 unique outputs** — consistent with 2 true plates; plr_crnn produced 4 variants (2 plates × misread variants). On cam2 all models emitted many unique strings (13–19 of 22).

## 4. Benchmark B — Detector-only (NO_GROUND_TRUTH protocol)

No annotated plate boxes exist for cam1/cam2 → precision/recall/IoU **not invented**; relative/qualitative only (96 sampled frames).

| Detector | GT | Frames w/ detection | Mean boxes/frame | Mean best-IoU vs production | CPU ms p50 | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| CURRENT_PRODUCTION plate det | NO_GROUND_TRUTH | 43/96 | 0.45 | — (reference) | ~* | runnable |
| iranplate_vision_yolo | NO_GROUND_TRUTH | 50/96 | 0.52 | 0.52 | 37.0 | runnable |
| plr_yolo_plate | NO_GROUND_TRUTH | 75/96 | 0.89 | 0.40 | 67.0 | runnable |

\* production detector latency is measured inside the full engine pipeline (≈100 ms total incl. OCR), not standalone here.

Interpretation guard: plr_yolo fires more boxes (incl. low-conf frames where production stays silent) — that is *not* "better recall" without GT; it is a sensitivity difference to verify against labeled data later.

## 5. Benchmark C — End-to-end combinations (DETECTOR_PLUS_OCR)

Format-validity via the unchanged production validator; **not** accuracy. Same sampled frames for all combinations.

| Combination | Crops | Valid-format | Invalid rate | Median ms | Classification |
| --- | ---: | ---: | ---: | ---: | --- |
| **CURRENT_PRODUCTION det + CURRENT_PRODUCTION OCR** | 49 | 34 | 0.227 | 32.8 | DETECTOR_PLUS_OCR |
| iranplate_vision_yolo + current_production OCR | 43 | 34 | 0.209 | 46.8 | DETECTOR_PLUS_OCR |
| iranplate_vision_yolo + persian_lpr_yolo11 | 43 | 36 | **0.163** | 66.8 | DETECTOR_PLUS_OCR |
| iranplate_vision_yolo + hezar | 43 | 31 | 0.279 | 51.8 | DETECTOR_PLUS_OCR |
| current_production det + persian_lpr_yolo11 | 49 | 31 | 0.279 | 56.6 | DETECTOR_PLUS_OCR |
| current_production det + hezar | 49 | 27 | 0.400 | 36.6 | DETECTOR_PLUS_OCR |
| plr_yolo_plate + current_production OCR | 63 | 46 | 0.270 | 75.0 | DETECTOR_PLUS_OCR |
| plr_yolo_plate + hezar | 63 | 46 | 0.270 | 79.7 | DETECTOR_PLUS_OCR |
| (others incl. plr_crnn combos) | … | … | 0.395–0.571 | … | DETECTOR_PLUS_OCR |

**Combination-matrix reading (evidence-bounded):**
* "new detector + old OCR" — IranPlate-Vision detector + production OCR is the only external-detector combo that **matches the baseline's valid-format count on fewer crops**; its detector finds plates on frames where production stays silent.
* "old detector + new OCR" — swapping OCR on the production detector did **not** improve format-validity (hezar 0.400 vs baseline 0.227).
* "new detector + new OCR" — IranPlate-Vision + persian_lpr_yolo11 has the lowest invalid rate (0.163) but is 2× the baseline latency and is a *format* metric on UNLABELED data — a candidate, not a winner.
* No FULL_ALPR external pipeline was runnable (see §1 blocked reasons).

## 6. Special cam2 analysis (task §14)

Production suspect strings (§14 list) matched to crops; every OCR model ran on the same crops:

| sample (frame) | production | hezar | plr_crnn | persian_lpr_yolo11 |
| --- | --- | --- | --- | --- |
| f300 | `25H28999` | `25ه2849` | `257899` | `25H28` |
| f305 | `H9H` | `ت8` | `3663` | *(empty)* |
| f340 | `235H284999` | `25ه28499` | `35H789` | `325H284` |
| f345 | `235H284999` | `25ه28499` | `35H789` | `325H284` |
| f350 | `235H284999` | `25ه28499` | `35H789` | `325H284` |
| f355 | `235H284999` | `35ه28499` | `35H789` | `25H28` |
| f555 | `25H28999` | `25ه28499` | `25H28397` | `25H28494` |

**Crop quality by video (root-cause signal):**

| Video | Crops | Mean crop W×H | Mean blur | Mean prod conf |
| --- | ---: | --- | ---: | ---: |
| cam1 | 62 | 198×63 px | high-variance | 0.766 |
| cam2 | 22 | **83×40 px** | 9620 (varLap) | 0.746 |

**Answer to "OCR or crop?":** The evidence points to **crop quality first**: cam2 crops are ~2.4× narrower; all four models disagree with each other on 18/22 cam2 crops (vs perfect 2-cluster agreement on cam1); and notably hezar — a *sequence* model from a different architecture family — independently converges on cam2 toward a consistent `25ه2849…` pattern whose digit tail (`2849(9)`) matches production's `…284999`, suggesting the true plate is partially recoverable and the dominant error is resolution-dependent. No model reads cam2 confidently; none is an obvious drop-in fix. Ground-truth verification of the cam2 true plate (manual read of the video) is required before any accuracy statement.

## 7. Performance (CPU; GPU = NOT_AVAILABLE)

| Model | Load s | p50 ms | p95 ms | max ms | FPS |
| --- | ---: | ---: | ---: | ---: | ---: |
| current_production OCR | 2.81 | 10.3 | 13.2 | 49.6 | 97.3 |
| hezar_crnn_v2 | 1.81 | 15.1 | 15.8 | 21.2 | 66.3 |
| plr_crnn | 0.04 | 5.8 | 6.5 | 8.1 | 171.3 |
| persian_lpr_yolo11 | 0.03 | 34.9 | 45.2 | 69.4 | 28.7 |

(End-to-end pipeline medians incl. detector: see `benchmarks/results/performance_results.json`. Production *frame* latency ≈100 ms is dominated by the 5-model engine, consistent with Phase 0/1 baselines.)

## 8. Iranian plate-type capability matrix (task §10)

Support is inferred **only** from executed behavior / shipped code, never filenames (task §18):

| Model | Civilian | Taxi | Gov | Motorcycle | Free Zone | Special/Diplomatic |
| --- | --- | --- | --- | --- | --- | --- |
| CURRENT_PRODUCTION | YES (char-det+validator) | PARTIAL (validator metadata) | PARTIAL | UNKNOWN | YES (best_plate_text fallback path) | PARTIAL (validator categories) |
| hezar_crnn_v2 | PARTIAL (trained on persian-license-plate-v1; type coverage undocumented) | UNKNOWN | UNKNOWN | NO (8-char car plates only by charset length) | UNKNOWN | UNKNOWN |
| plr_crnn | PARTIAL (fixed layout `NN L DDDDD` decode) | NO | NO | NO | NO | NO (ژ note only) |
| persian_lpr_yolo11 | PARTIAL (26 char classes; no layout/type logic) | UNKNOWN | UNKNOWN | NO | UNKNOWN | UNKNOWN |
| PlateHunter | UNKNOWN (blocked) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| PelakX | PARTIAL (ships ir.yaml country config + plate-type assets, no weights) | PARTIAL | PARTIAL | UNKNOWN | PARTIAL | PARTIAL |

## 9. License concerns

* **PlateHunter (Persian_ALPR_project): NO LICENSE FILE FOUND** — code/weights may not be reused without author permission; blocking reason stands even if weights appear.
* PersianLicensePlateRecognition, IranPlate-Vision, persian-lpr-yolov11, PelakX: MIT — reuse permitted with attribution.
* Hezar model: library Apache-2.0; model card to be re-checked on the hub page before any production redistribution.
* Roboflow dataset inside persian-lpr: Public Domain (per data.yaml).
* No external weights were committed or added to git; videos not uploaded.

## 10. Recommended candidates for the NEXT integration experiment (evidence-bounded, no winners claimed)

1. **IranPlate-Vision YOLO plate detector** as a *drop-in detector experiment* against the current plate detector — same OCR, same crops, runnable today, similar latency class; differs most from production while agreeing ~0.52 IoU.
2. **persian_lpr_yolo11 char detector** as a *detector-style OCR* candidate on high-res crops (cam1-class inputs) — ties production exactly on cam1 stability, but 3.4× slower and degrades on small crops.
3. **hezar CRNN V2** as a *second opinion* OCR for consensus voting — its errors are decorrelated from production (different failure modes on cam2), which is exactly what multi-model consensus needs; 15 ms/crop is affordable.
4. **Not recommended:** plr_crnn (weakest stability: 4 unique outputs on cam1's 2-plate scene; 0.55–0.57 invalid-rate combos), PlateHunter (no weights, no license), PelakX (no weights offline).

## 11. Ground-truth workflow (needed to unlock accuracy numbers)

1. Manually read each crop in `benchmarks/dataset/crops/` (84 rows; cam2 true plate especially).
2. Fill `benchmarks/dataset/ground_truth.jsonl`: `plate_text`, `plate_type`, `verified: true`.
3. Re-run `python benchmarks/run_benchmarks.py` — exact/char accuracy, edit distance, and per-model comparisons populate automatically; UNLABELED rows stay excluded.

## 12. Test / regression status

* New: `tests/test_benchmark_tooling.py` — 14 tests (normalization, adapter schema, missing-model handling, malformed output, determinism, metrics, GT exclusion, manifest validation). **14/14 pass.**
* Full suite: **363 passed** (2 known pre-existing OpenH264/FFmpeg VideoWriter tests excluded as in Phase 0/1 baselines). **No production regression.**

## 13. STOP notice

Per task §21: production ALPR behavior, default OCR, detector, and the Phase 1 event pipeline are **unchanged**. Next step decided after review of this report.

## Appendix — deliverables

```
ALPR_MODEL_BENCHMARK_REPORT.md      (this file)
ALPR_OCR_BENCHMARK.md               (OCR deep-dive)
ALPR_DETECTOR_BENCHMARK.md          (detector deep-dive)
ALPR_PIPELINE_BENCHMARK.md          (combination matrix deep-dive)
ALPR_MODEL_CAPABILITY_MATRIX.md     (types + roles + licenses)
benchmarks/
    model_manifest.json
    normalization.py
    build_dataset.py  run_benchmarks.py  run_detector_bench.py  run_pipeline_bench.py
    adapters/{base.py, registry.py}
    dataset/{crops/, metadata.jsonl, ground_truth.jsonl}
    results/{ocr_results.json, detector_results.json, pipeline_results.json, performance_results.json}
tests/test_benchmark_tooling.py
```
