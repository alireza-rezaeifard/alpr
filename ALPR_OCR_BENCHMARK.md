# ALPR OCR Benchmark (Benchmark A deep-dive)

> **SUPERSEDED for accuracy figures:** 62/84 crops are now verified (see
> [ALPR_GROUND_TRUTH_BENCHMARK_REPORT.md](ALPR_GROUND_TRUTH_BENCHMARK_REPORT.md)).
> Verified headline: production **1.000 exact / 1.000 char acc / 0.000 invalid on the 62
> verified cam1 crops**; yolo11 1.000; hezar 0.661; plr_crnn 0.000. cam2 remains UNLABELED.

**Protocol:** every model received the identical 84 production-detector crops (62 cam1, 22 cam2), no per-model preprocessing except its own internal resize. Normalization: [benchmarks/normalization.py](benchmarks/normalization.py). Accuracy metrics are computed only over verified ground truth ([benchmarks/dataset/ground_truth.jsonl](benchmarks/dataset/ground_truth.jsonl), task §8/§11).

## Primary metrics (where ground truth exists: NONE yet)

| Model | Exact | Char Acc | Invalid | Failed(empty) | N | N verified | N exact | N incorrect | N invalid | N failed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CURRENT_PRODUCTION | N/V | N/V | N/V | 0 | 84 | 0 | — | — | — | 0 |
| hezar_crnn_v2 | N/V | N/V | N/V | 0 | 84 | 0 | — | — | — | 0 |
| plr_crnn | N/V | N/V | N/V | 0 | 84 | 0 | — | — | — | 0 |
| persian_lpr_yolo11 | N/V | N/V | N/V | 4 | 84 | 0 | — | — | — | 4 |

N/V = not verifiable on unlabeled data. **No accuracy percentage was computed from unlabeled samples.**

## Secondary signals on UNLABELED data (stability & agreement, not accuracy)

| Model | cam1 unique outputs (62 crops, 2 true plates) | cam2 unique outputs (22 crops) | Char-mean style | Notes |
| --- | ---: | ---: | --- | --- |
| CURRENT_PRODUCTION | **2** (`28Y68923` ×41, `12D67413` ×21) | 18 | romanized DTRB | baseline |
| hezar_crnn_v2 | **2** (`28ی68923` ×41, `12د6741` ×21) | 13 | Persian + Persian digits | drops last digit on `12د6741` (7 chars) |
| plr_crnn | 4 (2 plates × variants: `28Y68933`/`28Y6933`, `12H6741`/`12W6741`) | 19 | ASCII abbreviations | least stable |
| persian_lpr_yolo11 | **2** (identical split to production) | 15 (4 empty) | char boxes L→R | char-detector style |

Cross-model disagreement on cam2: **18/22 crops have 4 distinct outputs; 4/22 have 3** — no model pair agrees.

## cam2 suspect strings — same-crop comparison

| frame | production | hezar | plr_crnn | persian_lpr_yolo11 |
| --- | --- | --- | --- | --- |
| 300 | `25H28999` | `25ه2849` | `257899` | `25H28` |
| 305 | `H9H` | `ت8` | `3663` | — |
| 340–355 | `235H284999` | `25/35ه28499` | `35H789` | `325H284` / `25H28` |
| 555 | `25H28999` | `25ه28499` | `25H28397` | `25H28494` |

Observations (evidence, not conclusions):
* hezar and plr_crnn tails (`…2849…`) overlap production's `…284999` on frames 340–355; the leading `2/3` and the letter position vary — consistent with a *low-resolution* crop where different models fail differently.
* persian_lpr_yolo11 outputs are **prefixes** of the same digit sequence (`25H28`, `325H284`) — its char detector finds fewer, larger characters on tiny crops.
* f305 (`H9H`) is unreadable for every model (hezar emits 2 chars, PLR emits noise, yolo11 empty) → crop-level failure.

## Quality grouping (cam2 vs cam1 crops)

| Group | N | Mean W | Mean H | Mean blur (varLap) | Models converging |
| --- | ---: | ---: | ---: | ---: | --- |
| cam1 crops | 62 | 198 px | 63 px | high | all 3 sequence-style models → 2 clusters |
| cam2 crops | 22 | 83 px | 40 px | 9620 | none |

**Working answer (to be confirmed by GT):** cam2 failures are dominated by **crop resolution/quality**, not by a single broken OCR. Candidates differ in *how* they fail, and hezar's decorrelated errors make it the strongest candidate for consensus-style ensembling — pending verified ground truth.

## Confidence calibration

Not computable: hezar/PLR outputs carry no confidence; production reports blended detector+OCR conf; yolo11 char confidences were not propagated (kept for later runs). Recorded as a telemetry TODO.

## Reproduce

```bash
python benchmarks/build_dataset.py
python benchmarks/run_benchmarks.py     # writes results/ocr_results.json
```
