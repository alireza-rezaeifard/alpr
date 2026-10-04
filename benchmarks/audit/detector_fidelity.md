# Phase 2B — Detector Fidelity & Reproducibility Audit

**Role:** detector-fidelity / reproducibility audit (read-only; no production file edited, nothing committed)
**Subject:** `benchmarks/run_phase2b_ab.py`, `benchmarks/adapters/registry.py`, `benchmarks/adapters/base.py`, production path `alpr_engine.py` + `api.py`
**Repo commit:** `f9bd7bb77ff78d55385895293dce349eee9c3d3a` (branch `main`)
**Date:** 2026-10-03

---

## 0. Verdict (TL;DR)

**The A/B is directionally fair but NOT a clean detector-only comparison.** The most important
negative finding is good news: **`make_production_detector()` does NOT bypass production
preprocessing.** Production feeds a *raw BGR frame* straight into `self._plate_model(frame, ...)`
with **no letterbox/resize of its own** — ultralytics does the internal letterbox. The benchmark
therefore reproduces the production inference path correctly on that axis (the hypothesised
CRITICAL confound **does not exist**).

What does break fidelity:

| # | Severity | Finding |
|---|---|---|
| D1 | **MAJOR** | Detector B runs with ultralytics **defaults** (`iou=0.7`, `max_det=300`, `imgsz=640`) while Detector A is pinned to production `iou=0.45`, `max_det=12`. Detection candidates and NMS are not comparable. |
| D2 | **MAJOR** | Detector A default conf is **0.5**, but production `alpr_engine.PLATE_DET_CONF = 0.6`. The module docstring claims production-conf-by-default — that claim is **false**. |
| D3 | **MAJOR** | Threshold-sweep block computes `verified_count` differently for the two arms (crops-that-parsed vs `len(boxes)`), corrupting the A/B `verified_total`. |
| D4 | MINOR | Crop rasterisation differs from production by ≤1 px (`round()` vs `astype(int)` truncation). |
| D5 | MINOR | Sweep and expansion passes have **no warm-up**; their latency medians include cold-start. |
| D6 | MINOR | Benchmark keeps crops whose OCR returns empty text; production drops those results. |
Confidence sweep and crop-expansion sweeps mitigate D2/D1 partially but do not remove them.

---

## 1. Detector identity, exact weights, SHA-256

### Detector A — "current production plate detector"
* Construction: `run_phase2b_ab.py:61` `make_production_detector()` → `api._ensure_models()`
  (`api.py:49`) → `alpr_engine.AlprEngine(MODEL_DIR)`.
* `MODEL_DIR = os.environ.get("MODEL_DIR", "weigths")` (`api.py:39`) — **environment-dependent**.
  If `MODEL_DIR` is set, Detector A silently points elsewhere. Unset at audit time → `D:\alpr\weigths`.
* Weights: `AlprEngine._load_all()` → `_load_yolo("plate_det_model.pt")` (`alpr_engine.py:121`, `144-155`).

| Field | Value |
|---|---|
| Path | `D:\alpr\weigths\plate_det_model.pt` |
| Size | 5,477,267 bytes |
| SHA-256 | `C70A91B5D695C2B8302BBE4F8AB6112DDC7845159F2FCC91CD50072D401ED00C` |
| Matches `weigths/manifest.json` | yes (in-repo, unchanged) |
| Arch | YOLO11n detect, 1 class (`LicensePlate`), params 2,590,035 |

OCR counterpart (identical for both arms): `D:\alpr\weigths\char_model.pt`, 6,218,616 B,
SHA-256 `08CF1BB9898E364513B5F4872A6E12175D9DE6EB0F41A53D8FC3C8AC58D8A709`, 27 classes, `conf=0.3`.

### Detector B — "IranPlate-Vision"
* Construction: `run_phase2b_ab.py:83` → `adapters/registry.py:264` `IranPlateDetectorAdapter.load()`.
* Path literal (registry.py:265):
  `ROOT / "bench" / "IranPlate-Vision-main" / "IranPlate-Vision-main" / "best.pt"`.

| Field | Value |
|---|---|
| Path | `D:\alpr\bench\IranPlate-Vision-main\IranPlate-Vision-main\best.pt` |
| Exists | yes |
| Size | 5,471,706 bytes |
| SHA-256 | `308C24643EAF49FC38930CEBFC46CA7455E7472F1D83FE98A2AE24443043DE40` |
| Cross-check | matches `ALPR_PHASE1_IMPLEMENTATION_REPORT.md` (`308c24643eaf…`) and `benchmarks/model_manifest.json` |
| Manifest metadata | 1 class `plate`, pinned imgsz 640 |

**Reproducibility note:** sizes are near-identical (5,477,267 vs 5,471,706) because both are
YOLO11n-scale single-class plate detectors — a genuine silent-swap risk. Pin by SHA-256, not filename.

### Offline verification (Task 1)
Grep for `http|https|requests|urllib|download|torch.hub|hf_hub` across `run_phase2b_ab.py`,
`adapters/*.py`, `ab_helpers.py`, `metrics.py`, `normalization.py`:

* **1 hit only** — a comment at `registry.py:49`: `# … (offline, no hub download)`.
* **No** `requests`, `urllib`, `torch.hub`, `huggingface_hub`, or any URL literal in either arm.

Both arms load local `.pt` paths only. No new models are fetched. Offline and reproducible.
(Caveat: ultralytics internally may probe for AMP/autoload, but with local paths and CPU torch
no transfer occurs.)
no transfer occurs.)

---

## 2. Production vs benchmark inference parameters

Production call site — `alpr_engine.AlprEngine.run()` step 3+4 (`alpr_engine.py:355-358`):

```python
plate_detections = self._plate_model(
    frame, show=False, conf=PLATE_DET_CONF, iou=NMS_IOU,
    max_det=PLATE_MAX_DET, verbose=False)
```
Crop at `alpr_engine.py:368`: `plate_crop = frame[y1:y2, x1:x2]`, with
`x1,y1,x2,y2 = box.xyxy[0].cpu().numpy().astype(int)`.

| Parameter | Production (`AlprEngine.run`) | Detector A (`make_production_detector`) | Detector B (`IranPlateDetectorAdapter.detect`) | Match? |
|---|---|---|---|---|
| Weights | `weigths/plate_det_model.pt` | same | `bench/.../best.pt` | intended |
| Input tensor | raw BGR frame, unmodified | raw BGR frame, unmodified | raw BGR frame, unmodified | yes |
| External preprocessing | **none** (no letterbox/resize/ROI) | **none** | **none** | yes |
| Ultralytics internal letterbox | default (LetterBox, stride 32, scaleup) | same default | same default | yes |
| `imgsz` | not passed → default **640** | not passed → **640** | not passed → **640** | yes (by convention only — D7) |
| `conf` | `PLATE_DET_CONF = 0.6` | `--conf` default **0.5** | `--conf` default **0.5** | **no — D2** |
| `iou` (NMS) | `NMS_IOU = 0.45` | hard-coded **0.45** | **not passed → 0.7** | **no — D1** |
| `max_det` | `PLATE_MAX_DET = 12` | **12** | **not passed → 300** | **no — D1** |
| `augment` / `agnostic` | defaults | defaults | defaults | yes |
| `half` | n/a (CPU) | n/a | n/a | yes |
| Device | cuda-if-available; `torch 2.12.0+cpu` → **CPU** | same object | same process → **CPU** | yes |
| Postprocessing | iterate `det.boxes`, `int()` cast of xyxy | iterate `out.boxes.data.tolist()`, float xyxy | identical `.data.tolist()` | D4 |
| Post-filter | `continue` if crop empty **or** `plate_text` empty | empty crop only | same | **D6** |
| Ordering | YOLO returns conf-desc | same (no re-sort) | same (no re-sort) | yes |

### Quantification of the D1 asymmetry
* **NMS IoU.** Production deliberately pins `iou=0.45` (comment at `alpr_engine.py:53-55`:
  *"NMS IoU keeps a single tight box per real object"*, added to stop the "256 LicensePlates"
  over-detection). Detector B at `iou=0.7` **retains duplicate/overlapping boxes for the same
  physical plate** that production would suppress. B will therefore emit systematically more
  crops per plate than A → higher `n_crops`, duplicate text, and a mechanically different
  `median_crop_width`. Any "Detector B produces more crops" claim must be re-run at
  `iou=0.45, max_det=12` before it can be attributed to the model rather than the NMS setting.
* **max_det** 12 vs 300: on plate-like clutter this changes the tail entirely; combined with the
  IoU gap the two arms are **not** operating at the same candidate budget.
* Neither arm asserts `imgsz`; both rely on ultralytics defaults matching the manifests'
  `pinned_imgsz: 640`. That holds, but implicitly (D7).

### Answer to the CRITICAL question in Task 2
> does `make_production_detector()` bypass production preprocessing (feeding a raw BGR frame
> when production feeds a letterboxed/enlarged image)?

**No.** Production performs **no** preprocessing of the frame before plate detection; the raw
BGR frame goes straight to the model and ultralytics performs the letterbox internally.
`make_production_detector()` replicates this exactly. The one fidelity break is the *conf* value
(0.5 vs 0.6), not the geometry. The benchmark also calls `engine._plate_model.predict(...)`
instead of `engine._plate_model(...)`; in ultralytics these are the same path (`__call__`
delegates to `predict`), so this is style, not behaviour.

### Task 3 — Detector B preprocessing
Detector B also receives the **raw, unmodified BGR frame** (`registry.py:277`:
`self.model.predict(frame_bgr, verbose=False, conf=conf)`) — the same letterbox path production
Had production letterboxed externally, this would be a second critical confound — it does not.

---

## 3. Crop extraction parity (Task 4)

**Single shared function — no confound.** `crop_of()` is defined once at
`run_phase2b_ab.py:97-108` and is the *only* crop routine used by:
* primary A/B pass — line 167 (`crop_of(frame, box)`), inside the loop over **both** `det_name`
  values (line 159);
* threshold sweep — line 340 (both arms);
* crop-expansion sweep — line 424 (both arms, `expand=factor`).

Semantics: centre-preserving box scaling by `expand`, then `max(0, round(x1))`,
`min(w, round(x2))`, `None` on degenerate box. Default `expand=1.0` in the primary pass
⇒ identical no-padding crop for both arms.

Residual differences vs production (MINOR):
* Production uses `numpy.astype(int)` = **truncation toward zero**; `crop_of` uses `round()`
  (banker's rounding). Max 1 px per edge; for a typical 92×38 crop ≈ 1.1 % width and ≈ 2.6 %
  height of the OCR input.
* Production crops are **not** clamped to the frame (`alpr_engine.py:368`) whereas `crop_of`
  clamps — this makes `clipping_rate` a benchmark-only metric and guarantees `crop_of` never raises.
* Production additionally **discards** boxes whose OCR text is empty (`alpr_engine.py:373-374`);
  the benchmark keeps them (**D6**), inflating `n_crops` / `invalid_rate` for whichever arm
  emits noisier boxes — most likely Detector B, since it runs at `iou=0.7`.

**Neither difference is fatal, but D6 biases `n_crops` and `invalid_rate` against whichever
detector produces more duplicate boxes.**

---

## 4. OCR parity (Task 5)

* One adapter object created at `run_phase2b_ab.py:140`: `ocr = ProductionOCRAdapter()`,
  warmed via `ocr.is_available()`.
* That **same instance** is used in the primary pass (line 171), the threshold sweep
  (lines 346, 379) and the expansion sweep (line 424+). Never re-instantiated per arm.
* Its `_load()` (`registry.py:30-41`) calls `api._ensure_models()`, a **process-wide singleton**
  (`api.py:30`, `49-52`), so Detector A's `make_production_detector()` obtains the *identical*
  engine object the OCR adapter holds — same `_char_model`, `CHAR_DET_CONF=0.3`, `NMS_IOU=0.45`.
* Crop → `_to_bgr()` is a pass-through for ndarrays (`base.py:136-138`), so both arms hand the
  OCR byte-identical arrays. Text normalisation via `normalization.normalize_plate_text` is uniform.

**OCR is not a variable. Confirmed.**

---

## 5. Warm-up (Task 6)

* Warm-up **exists** for the primary pass: `run_phase2b_ab.py:149-153` runs `--warmup`
  (default **6**) real frames through *both* detectors *and* the OCR adapter before the measured
  loop. This satisfies spec §17 for the headline numbers (`detector_latency_ms_p50/p95`,
  `ocr_latency_ms_*`, `total_latency_ms_p50`) and warms **both** arms with the **same** 6 frames.
* **Gap (D5, MINOR):** the threshold-sweep pass (lines 322-393) and the expansion pass
  (lines 415-436) run **after** the measured loop with **no warm-up of their own**, and the sweep
  re-creates adapters (`make_ipv_detector(conf)` at line 327 and again at 365 — one `YOLO(path)`
  load per threshold). Any cold-start sample in
  `sweep_summary[*].median_detector_latency_ms` therefore reflects load + first-inference cost,
  not steady-state latency. Magnitude on this host: a YOLO11n CPU forward is ~25 ms steady-state
  (Phase 0 baseline p50 23.97 ms), while the first inference after `YOLO(path)` is typically
  150-600 ms — a single cold sample can dominate a p50 on a short sweep. **Do not quote sweep
  latencies as steady-state.**
* Also, warm-up OCR input is a synthetic `frame[:64,:64]` slice, not a real plate crop — it
exercise the code path but not the true input shape distribution (D10).

---

## 6. Environment (Task 7)

| Item | Value |
|---|---|
| Python | 3.11.4 (MSC v.1934, 64-bit AMD64) |
| torch | 2.12.0**+cpu** |
| CUDA available | **False** |
| Inference device (both arms) | **CPU** |
| OpenCV | 4.13.0 |
| ultralytics | 8.4.56 |
| CPU | AMD Ryzen 5 7600X — 6 cores / 12 threads |
| RAM | 31.1 GiB (33,436,602,368 B) |
| OS | Windows |

**Both arms run in the same process, on the same CPU runtime, with the same ultralytics version
and the same `YOLO` class. No runtime asymmetry.** (Latency figures are CPU-bound and not
representative of any GPU deployment — consistent with `ALPR_ARCHITECTURE_DESIGN.md`, which
already records `torch.cuda.is_available() == False`.)

---

## 7. Discrepancy register (ranked)

### CRITICAL
* **None.** Both arms receive identical frames, identical crop extraction, identical OCR, and
  both use the same internal ultralytics letterbox. The suspected production-preprocessing
  bypass does not exist.

### MAJOR
1. **D1 — NMS / candidate-budget asymmetry.** A: `iou=0.45, max_det=12` (production).
   B: ultralytics defaults `iou=0.7, max_det=300`. Duplicate boxes for one physical plate
   survive NMS on the B side. Directly inflates B's `n_crops`, `median_crop_width`,
   `clipping_rate`, `invalid_rate`, `detections_per_frame` and latency.
   *Fix:* pass `iou=0.45, max_det=12, imgsz=640` in `IranPlateDetectorAdapter.detect`, then re-run.
   (Production files are out of scope for this audit; the fix belongs in `benchmarks/adapters/registry.py`.)
2. **D2 — Detector A conf != production conf.** Default `--conf 0.5` vs
   `alpr_engine.PLATE_DET_CONF = 0.6`. The file docstring (lines 3-4) asserts production conf
   "by default, overridable" — **factually wrong**; `PLATE_DET_CONF` is never imported. Applying
   0.5 to both arms keeps the A/B internally symmetric, but the "current production" arm is then
   not the production operating point, so "B beats production" claims are overstated.
   *Fix:* default `--conf` to `alpr_engine.PLATE_DET_CONF`, or run and report both 0.6 and 0.5.
3. **D3 — sweep `verified_count` computed differently per arm.** The primary sweep block
   increments `n_verified` **per surviving crop** (line 350); the second-arm re-run block sets
   `"verified_count": sum(1 for _ in boxes) if ref else 0` (line 390) — **per box, before the
   `crop is None` filter**. `sweep_summary[*]["verified_total"]` therefore sums two different
   denominators, so `verified_exact / verified_total` in
   `phase2b_bucket_results.json → threshold_sweep` is **not comparable across arms**.
   This is a correctness bug in a reported metric, independent of D1.

### MINOR
4. **D4 — crop rounding:** `round()` (bench) vs `astype(int)` truncation (production); ≤1 px/edge.
5. **D5 — no warm-up** on the sweep/expansion passes; their latency medians are cold-start contaminated.
6. **D6 — empty-text crops retained** in the benchmark but dropped in production; biases
   `n_crops`/`invalid_rate` toward the noisiest detector.
7. **D7 — `imgsz` implicit** for both arms (relying on the 640 default rather than asserting it).
8. **D8 — `MODEL_DIR` env override** silently redirects Detector A's weights (`api.py:39`);
   the benchmark never asserts it is unset.
9. **D9 — near-identical weight file sizes** (5,477,267 vs 5,471,706 B) for the two arms;
   pin by SHA-256, not by name.
10. **D10 — warm-up OCR input** is a synthetic 64x64 slice rather than a real plate crop.

---

## 8. What is verified sound

* Detector B loads a real, present, local `best.pt` under `bench/`, offline, SHA-256 recorded.
* Both arms share one frame list (`collect_frames`, `--interval 5`) — same pixels, same order.
* Crop extraction is one shared function, used identically in every arm and every sweep.
* One shared OCR adapter instance, backed by the same singleton engine object.
* Both arms: same process, same CPU runtime, same torch / ultralytics / OpenCV versions.
* Warm-up present for the headline pass, applied symmetrically to both arms.
* Accuracy restricted to `verified` GT only; cam2 correctly reported as diagnostics only.

## 9. Recommended gate before publishing the A/B

1. Pin `iou=0.45, max_det=12, imgsz=640` on Detector B (D1) and re-run.
2. Set the default conf to `alpr_engine.PLATE_DET_CONF` or report both 0.6 and 0.5 (D2).
3. Fix the sweep `verified_count` symmetry (D3).
4. Assert both weights SHA-256 and `MODEL_DIR` unset at start-up (D8, D9).
5. Re-label every published A/B number as produced **after** fixes 1-3; current results should be
   treated as *exploratory*.

*End of audit. No production file was modified; nothing was committed.*
  exercises the code path but not the true input shape distribution (D10).
uses. Preprocessing is symmetric; only post-letterbox inference parameters differ.
Had production letterboxed externally, this would be a second critical confound — it does not.