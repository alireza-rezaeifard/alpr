# ALPR Detector Benchmark (Benchmark B deep-dive)

**Protocol:** identical sampled frames (96 total: every 10th frame of cam1+cam2), conf threshold 0.4 for external detectors / production default for the baseline.

**Ground truth: NO_GROUND_TRUTH.** No annotated plate boxes exist for cam1/cam2, therefore **recall / precision / IoU-vs-truth / FP counts were NOT computed** (task §5 forbids inventing them). Everything below is relative/qualitative.

## Results

| Detector | GT | Frames w/ detection | Mean boxes/frame | Mean best-IoU vs production det | CPU p50 ms | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| CURRENT_PRODUCTION plate detector | NO_GROUND_TRUTH | 43/96 | 0.45 | — (reference) | measured in-engine | runnable |
| iranplate_vision_yolo (YOLO, 1 cls) | NO_GROUND_TRUTH | 50/96 | 0.52 | 0.52 | 37.0 | runnable |
| plr_yolo_plate (YOLO, 1 cls) | NO_GROUND_TRUTH | 75/96 | 0.89 | 0.40 | 67.0 | runnable |

## Reading the numbers correctly

* `plr_yolo_plate` fires on 75/96 frames — likely higher sensitivity / lower threshold behavior, **not** proof of better recall; 63 crops passed downstream OCR vs 43–49 for others.
* `iranplate_vision_yolo` has the highest agreement with production (0.52 best-IoU mean) while finding detections on 7 more frames — it is the most plausible *swap-in* detector candidate.
* The production detector is the most conservative (43/96) — consistent with its higher operating threshold inside the engine.

## What would unlock real metrics

Annotate ≥100 frames (bounding boxes) across cam1/cam2, store as `benchmarks/dataset/detector_gt.jsonl`, extend `run_detector_bench.py` — the IoU machinery already exists in that script.

Blocked repositories relevant here: PlateHunter's YOLO26s plate detector (960 px) had the strongest paper claims but **no weights shipped** — excluded per §1 rule 10 rather than skipped silently.
