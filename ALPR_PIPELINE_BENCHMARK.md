# ALPR Pipeline Benchmark (Benchmark C — combination matrix)

**Protocol:** 96 sampled frames (cam1+cam2 every 10th frame); every runnable detector fed every runnable OCR on the SAME frames; format-validity judged by the unchanged production validator. **Classification: DETECTOR_PLUS_OCR for all rows** — no runnable external FULL_ALPR pipeline existed (PlateHunter: weights missing; PelakX: weights missing by design). No accuracy claims (UNLABELED).

## Combination matrix

| Combination | Crops | Non-empty | Valid format | Invalid rate | Median ms | Label |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| **current_production det + current_production OCR** | 49 | 44 | 34 | 0.227 | 32.8 | **CURRENT_PRODUCTION baseline** |
| current_production det + hezar | 49 | 45 | 27 | 0.400 | 36.6 | old det + new OCR |
| current_production det + plr_crnn | 49 | 49 | 21 | 0.571 | 27.6 | old det + new OCR |
| current_production det + persian_lpr_yolo11 | 49 | 43 | 31 | 0.279 | 56.6 | old det + new OCR |
| iranplate_vision_yolo + current_production OCR | 43 | 43 | 34 | 0.209 | 46.8 | **new det + old OCR** |
| iranplate_vision_yolo + hezar | 43 | 43 | 31 | 0.279 | 51.8 | new det + new OCR |
| iranplate_vision_yolo + plr_crnn | 43 | 43 | 26 | 0.395 | 42.2 | new det + new OCR |
| iranplate_vision_yolo + persian_lpr_yolo11 | 43 | 43 | 36 | **0.163** | 66.8 | new det + new OCR |
| plr_yolo_plate + current_production OCR | 63 | 63 | 46 | 0.270 | 75.0 | new det + old OCR |
| plr_yolo_plate + hezar | 63 | 63 | 46 | 0.270 | 79.7 | new det + new OCR |
| plr_yolo_plate + plr_crnn | 63 | 63 | 28 | 0.556 | 70.8 | new det + new OCR |
| plr_yolo_plate + persian_lpr_yolo11 | 63 | 62 | 31 | 0.500 | 93.1 | new det + new OCR |

## Evidence-bounded readings (no winners — §20)

* **Baseline holds up.** current det + current OCR is within the top tier of valid-format yield while being the **fastest credible combination** (32.8 ms median crop-pipeline latency).
* **"new detector + old OCR" is the most interesting axis.** IranPlate-Vision's detector + the unchanged production OCR yields the same 34 valid formats from fewer crops (43 vs 49) with a slightly *lower* invalid rate (0.209 vs 0.227) — i.e., its detections may be *cleaner* inputs for the same OCR. This is the first candidate for a controlled detector swap experiment.
* **"old detector + new OCR" did not help.** Both CRNN substitutes degrade format validity on the production detector's crops (0.400 hezar, 0.571 plr_crnn). Note hezar's failures concentrate on cam2-class small crops (see OCR report) — its errors are *different* from production's, which retains value for consensus ensembling even though it is worse standalone.
* **"new detector + new OCR" (IranPlate-Vision + persian_lpr_yolo11) posts the lowest invalid rate (0.163)** but: (a) it is 2× baseline latency, (b) format-validity ≠ correctness on unlabeled data, (c) persian_lpr_yolo11 was the least stable model on cam1-quality crops in the OCR-only run. Treat as a curiosity until ground truth exists.
* plr_crnn is dominated in every combination (invalid rate ≥ 0.395) — consistent with its cam1 instability (4 unique outputs on a 2-plate scene).

## Full-pipeline classification

| Pipeline | Class | Status |
| --- | --- | --- |
| Production engine (det + chars + vehicle + attributes) | FULL_ALPR | runnable (baseline) |
| IranPlate-Vision full app (Flask+RTSP) | FULL_ALPR | partial — detector+hezar OCR path exercised; app stack out of scope |
| PlateHunter | FULL_ALPR | **blocked** — weights missing |
| PelakX | FULL_ALPR | **blocked** — no weights offline |

## Reproduce

```bash
python benchmarks/run_pipeline_bench.py   # writes results/pipeline_results.json
```
