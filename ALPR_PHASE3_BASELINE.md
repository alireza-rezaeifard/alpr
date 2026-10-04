# ALPR Phase 3 — Baseline

**Date:** 2026-10-04 · **Repo:** `D:\alpr` (GitHub: `alireza-rezaeifard/alpr`)
**Branch:** `main` · **HEAD:** `f9bd7bb77ff78d55385895293dce349eee9c3d3a`
**Phase:** evaluation / dataset / ground-truth / benchmark ONLY.

## 1. Git state

* HEAD `f9bd7bb` ("feat(alpr): integrate tracked vehicle events").
* 44 dirty/untracked entries, all **pre-existing** from Phases 0–2D
  (benchmark reports, `benchmarks/`, `tests/test_*_tooling.py`,
  `validation/`, `*.txt` logs). `.gitignore` and `conftest.py` were
  already modified before Phase 3 began.
* **Production diff vs HEAD: EMPTY** for `alpr_engine.py`,
  `video_processor.py`, `api.py`, `db.py`, `camera_manager.py`,
  `plate_validator.py`, `plate_metadata.py`, `verification.py`.
* No commit was created in Phase 3; no production file, weight, API,
  DB schema, or Flutter file was touched.

## 2. Production files and weight hashes (re-verified)

| Artifact | Path | SHA-256 (first 32) | Bytes |
| --- | --- | --- | ---: |
| Detector A (production) | `weigths/plate_det_model.pt` | `C70A91B5D695C2B8302BBE4F8AB6112D` | 5,477,267 |
| Production OCR (char YOLO) | `weigths/char_model.pt` | `08CF1BB9898E364513B5F4872A6E1217` | 6,218,616 |
| Car detector | `weigths/car_det_model.pt` | `0EBBC80D4A7680D14987A577CD21342B` | 5,613,764 |
| Car name ResNet | `weigths/car_name_model.pth` | `674C2DAE68D1E0F37E92D4027AC5669F` | 44,841,766 |
| Color ResNet | `weigths/color_model.pt` | `88E9C6D08F6D8FFC04B097BE2CB3B507` | 44,811,614 |
| Detector B (IranPlate-Vision) | `bench/IranPlate-Vision-main/IranPlate-Vision-main/best.pt` | `308C24643EAF49FC38930CEBFC46CA74` | 5,471,706 |

All match the Phase 2C/2D manifests. **No other plate-detector
weights exist on disk**: `bench/` contains only `IranPlate-Vision-main/`;
the PLR YOLO and persian-lpr-yolov11 adapters reference weights that
are absent, so only **two** detector candidates are runnable.

## 3. Available video and frame assets

| Asset | Frames | Resolution | FPS | SHA-256 (first 32) |
| --- | ---: | --- | ---: | --- |
| `cam1.mp4` (raw, restored) | 360 | 1920×1032 | ~31.0 | `E3FD570F7CD14AE6CB7930C95DA82D3F` |
| `cam2.mp4` (raw, restored) | 599 | 1920×1080 | 25.0 | `237E30A0545D82ACC267CC29985D597C` |

Frame assets: `benchmarks/dataset/` (Phase 2B: 84 crops, metadata,
review sheets), `benchmarks/dataset/2c/cam2/` (Phase 2C review
frames), `benchmarks/audit/cam2_gt/` (Phase 2D: 22 cam2 samples as
native crop + 4× zoom + context PNG + geometry manifest).
`benchmarks/dataset/crops/*.png` (Phase 2B crop PNGs) were NOT
restored after the 2026-10-03 checkpoint incident and remain absent;
every Phase 3 asset is regenerated from the raw videos, so this does
not block Phase 3.

## 4. Current ground-truth assets

* `benchmarks/dataset/gt_labels.json` — **2 verified cam1 plate
  instances** (human/agent visual review in Phase 2B: review sheet +
  glyph zooms):
  * `cam1_plate_A` = `۲۸ی۶۸۹۲۳` (ASCII `28Y68923`), civilian,
    frames [0,144] ∪ [243,301]; letter glyph documented as ambiguous
    ی/ع at this resolution.
  * `cam1_plate_B` = `۱۲د۶۷۴۱۳` (ASCII `12D67413`), civilian,
    frames [163,224] ∪ [311,359].
  * `cam2_plate_X` — `verified: false`, UNLABELED, with unverified
    cross-model candidate hypotheses only.
* **No plate bounding-box GT exists anywhere** (Phase 2C recorded
  `NO_BOX_GROUND_TRUTH`). Phase 3 introduces the schema for it but
  cannot fabricate it: box annotation requires visual inspection.
* **cam2 has no verified text GT.** The 22 Phase-2B cam2 samples are
  staged (`benchmarks/audit/cam2_gt/`) but remain
  `PENDING_HUMAN_REVIEW`: this session has no image input, and the
  repo contains no independent (non-OCR) cam2 labels
  (`validation/cam2/*` records are OCR-derived hypotheses, all
  `unconfirmed`/`needs_review`).

## 5. Current benchmark infrastructure (reusable)

* `benchmarks/phase2c_canonical.py` — frozen canonical crop
  extraction (conventions `trunc`/`floor`/`round`/`ceil`,
  centre-preserving `expand_box`, width buckets).
* `benchmarks/phase2d_crop.py` — Phase 2D pure crop helper
  (`extract_crop(frame, bbox, convention, expansion)`), 36
  determinism tests.
* `benchmarks/adapters/registry.py` — `ProductionOCRAdapter`
  (CURRENT_PRODUCTION), `IranPlateDetectorAdapter` (B),
  `HezarCRNNV2Adapter` (hezar 1.0.0 **is installed** → runnable OCR
  candidate), plus adapters whose weights are absent.
* `benchmarks/metrics.py` — `score_pair`, `canonical`,
  `is_valid_iranian`, `aggregate` (exact/char/edit/invalid/failed).
* `benchmarks/normalization.py` — documented normalization R1–R7
  (NFC, zero-width removal, separators, Persian/Arabic digit→ASCII,
  ی/ک variant folding, `FA_TO_ASCII` transliteration, Levenshtein).
* `benchmarks/run_phase2c_ab.py`, `run_phase2d.py` — runners with
  frozen protocol, single-inference-pass design, explicit
  numerator/denominator metrics, McNemar exact test.

## 6. Current test suite

* 627 tests collected (65 files) at HEAD + Phase 2 additions.
* Phase 2D state: 61 new Phase 2D tests pass (36 determinism + 25
  safety); 162 Phase 2A/2B/2C tooling tests pass.
* Full suite: 591 passed / 11 failed — all 11 **pre-existing** and
  unrelated (6 × `test_backend.py::TestCameraEndpoints` HTTP 401;
  2 × `TestSamplingIntervalValidation`; 3 ×
  `test_detection_pipeline_integration.py` incl. the structural
  `KeyError: 'plate_text'` at `routers/detection.py:117`). None
  import any benchmark module.

## 7. Environment

Python 3.11.4 · torch 2.12.0+cpu (CUDA unavailable) · ultralytics
8.4.56 · OpenCV 4.13.0 · numpy 2.4.6 · hezar 1.0.0 · psutil 7.2.2 ·
scipy 1.15.3 (sklearn absent) · Windows 10 (10.0.26200) AMD64,
12 CPUs. Single machine; steady-state latency only.

## 8. Known limitations carried into Phase 3

1. **Two cameras only.** `cam1.mp4`, `cam2.mp4`. No third real
   camera source exists; camera diversity must NOT be fabricated.
   Cross-camera conclusions are impossible.
2. **Two verified plate instances** (both cam1). The ≥10-instances-
   per-camera target is unreachable from available footage.
3. **No box GT** → detector precision/recall/F1/IoU are **not
   measurable** in Phase 3; only detection counts (diagnostic) and
   OCR-on-crop metrics are measurable. Localization infrastructure is
   delivered and unit-proven, awaiting human box annotation.
4. **cam2 text GT unavailable in-session** (no image input).
5. **One physical plate causes the entire Phase 2C/2D gap**
   (cam1 plate B); single-plate OCR quirks cannot be excluded.
6. Sub-100 px crops (cam2's regime) have zero verified coverage.

## 9. Phase 3 scope statement

Phase 3 builds the **neutral evaluation infrastructure** (schema,
validation, normalization, matching, metrics, splits, runner,
diagnostics, annotation workflow, tests) and populates it with
**everything that is honestly verifiable today**: cam1's 2 verified
text instances (62 interval-5 frames) plus cam2's staged-but-unverified
samples. It deliberately does **not** optimize for any prior result
and reports `NOT_AVAILABLE` where evidence does not exist.
