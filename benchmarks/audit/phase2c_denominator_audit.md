# Phase 2C — Denominator & Protocol-Parity Audit

Audit target: `benchmarks/run_phase2c_ab.py`, `benchmarks/phase2c_canonical.py`
Data: `benchmarks/results/phase2c_raw_results.json`, `phase2c_summary.json`,
`phase2c_bucket_results.json`, `phase2c_latency.json`, `phase2c_crop_results.json`
Audit script (read-only recompute): `benchmarks/audit/_recompute_check.py`
Canonical convention: **trunc**. Run tags present in raw data: **run0 only**.

| # | Area | Verdict |
|---|------|---------|
| 1 | Protocol parity | **CLEAN** (2B finding D1 eliminated) |
| 2 | Denominator correctness | **CLEAN** |
| 3 | FAILED vs INVALID | **CLEAN** (2B bug not reproduced) |
| 4 | Canonical convention | **CLEAN** |
| 5 | Latency + repeatability | **FAIL** (latency CLEAN; repeatability run missing) |

---

## 1. Protocol parity — CLEAN

`build_detectors(conf, iou, max_det, imgsz)` (run_phase2c_ab.py:100-122):

```python
def call(model, frame):
    res = model.predict(frame, conf=conf, iou=iou, max_det=max_det, imgsz=imgsz,
                        agnostic_nms=PROTOCOL["agnostic_nms"],
                        half=PROTOCOL["half"], verbose=False)[0]
    ...
return {"detector_a_current":     lambda f: call(a_model, f),
        "detector_b_iranplate":   lambda f: call(b_model, f)}
```

* **One shared call site.** Both arms are the *same* `call()` closure; the only
  differing argument is the `model` object. `conf`, `iou`, `max_det`, `imgsz`
  arrive as identical bound arguments from `main()` (line 569:
  `build_detectors(args.conf, args.iou, args.max_det, PROTOCOL["imgsz"])`);
  `agnostic_nms` and `half` are read from the same frozen `PROTOCOL` dict for
  both. Byte-identical inference configuration is structural, not coincidental.
* **B bypasses the adapter's own defaults.** `IranPlateDetectorAdapter.detect()`
  (adapters/registry.py:274-284) is *never called*. It would have used its own
  `conf=0.25` default and passed **no** `iou`, `max_det`, `imgsz`,
  `agnostic_nms`, or `half`. The runner uses the adapter only as a **weights
  loader** (`b.load(); b_model = b.model`, lines 105-107) and then calls
  `b_model.predict(...)` through the shared `call()`. No path in the runner
  references `.detect(`.
* **No private postprocessing.** The shared `call()` performs one identical
  transform on both arms: iterate `res.boxes.data.tolist()`, unpack
  `[x1,y1,x2,y2,conf,cls]`, emit raw dicts. There is no confidence filter, no
  NMS re-run, no box re-ordering, no class filter, no size filter, and no
  per-arm threshold anywhere in the runner. Downstream, `run_pass` applies
  `extract_plate_crop` (identical module; only the `convention` loop variable
  differs) to both arms.
* **Stored protocol** (phase2c_raw_results.json `protocol`):
  `conf=0.5, iou=0.45, max_det=12, imgsz=640, agnostic_nms=false, half=false,
  crop_convention="trunc", clip=true, pad_x=0, pad_y=0, ocr="CURRENT_PRODUCTION"`.

**Phase 2B finding D1 (B running at iou=0.7 / max_det=300) is ELIMINATED.**
---

## 2. Denominator correctness — CLEAN

Recomputed independently from `phase2c_raw_results.json` (`records` filtered to
`convention=="trunc"`, `run=="run0"`) and cross-checked against the stored
`per_run_summary.run0` blocks. **All stored values reproduce exactly.**

Frame census (`frame_rows`, per detector; cam1 72 frames + cam2 120 frames):

| Detector | frames_total | with_detection | without_detection |
|---|---|---|---|
| A detector_a_current | 192 | 101 | 91 |
| B detector_b_iranplate | 192 | 84 | 108 |
| A cam1.mp4 | 72 | 62 | 10 |
| A cam2.mp4 | 120 | 39 | 81 |
| B cam1.mp4 | 72 | 72 | 0 |
| B cam2.mp4 | 120 | 12 | 108 |

* **NO_DETECTION frames are emitted as rows, not dropped.** `run_pass` lines
  160-173 append a record with `detection_status="NO_DETECTION"` for **every**
  convention, so an empty frame is still counted. Recomputed record counts:
  A overall 192 records = 101 DETECTED + 91 NO_DETECTION; B overall 192 =
  84 + 108; A cam1 72 = 62 + 10. `detected_crops + no_detection_records ==
  frames_total` holds exactly for all six slices.
* **Accuracy denominators are `labeled_crops`; NO_DETECTION is penalized in the
  paired test.** `exact` / `char_accuracy` / `mean_edit_distance` divide by
  `len(labeled)` = verified-GT crops. Crucially, `paired()` (lines 368-370)
  inserts `{"exact": False, ...}` for every NO_DETECTION frame on a verified
  frame, so a miss counts as a **wrong** answer, never as a dropped observation.
  Verified-frame denominator for the paired table is 62 (all cam1; cam2 has 0
  verified frames — `gt_frame_counts` = `{"cam1.mp4": 315}` over the full
  315-frame verified ranges, of which 62 land on the interval=5 sample grid).
* In this dataset `frames_with_detection == labeled_crops` on cam1 (A 62/62;
  B 72 detected → 62 labeled), so the 62-denominator reads the same as
  "verified frames" or "labeled crops"; the NO_DETECTION penalty mechanism is
  what makes that equivalence legitimate rather than accidental.
* **UNLABELED rows never carry scores.** Code path: `score_pair(text, ref) if ref
  else {"exact": None, "char_accuracy": None, "edit_distance": None}`
  (lines 216-218). Data check across all run0/trunc records: count of UNLABELED
  rows with non-null `exact` OR `char_accuracy` OR `edit_distance` = **0**, for
  both detectors and both cameras. cam2 (130 unlabeled crops per detector) is
---

## 3. FAILED vs INVALID — CLEAN (the 2B bug is not present)

Definitions in `run_pass` (lines 210-213):

```python
text  = r["raw_text"] or ""
valid = bool(is_valid_iranian(r["raw_text"], r["confidence"] or 0.9))
rec.update({... "ocr_valid": valid, "failed": not text.strip(), ...})
```

`failed` is computed **only** from blank OCR text. `ocr_valid` comes from the
Iranian-plate validity test. They are independent predicates.

Data proof over run0/trunc (all conventions; the canonical one gives the same
picture with 5x the rows):

| Check | Count |
|---|---|
| `failed == True` AND `ocr_text.strip() == ""` | **13** |
| `failed == True` AND non-blank text | **0** |
| `ocr_valid == False` AND non-blank text | **36** |
| `ocr_valid == True` (non-empty valid plate) | **136** |
| `failed is None` (NO_DETECTION or null-crop, OCR never attempted) | 199 |

`failed` (13) is a **strict subset** of `invalid` (13 + 36 = 49 invalid across
all conventions; 34 invalid on the canonical run for A). Empty text trivially
fails the validity test, so containment is expected; the important point is that
the two counters are **not the same set and not the same number**: 36 rows are
invalid with real non-empty text (wrong/mangled plate readouts) and would be
double-counted if `failed` were defined as `not ocr_valid`. In Phase 2B `failed`
was exactly that alias; here it is not. Headline values are therefore distinct
and internally consistent: A invalid 34/101 vs A failed 13/101; B invalid 15/84
vs B failed 0/84.

Also `failed` is `None` (not `True`) for rows where OCR never ran (NO_DETECTION
rows, and rows whose crop was degenerate). Those are excluded from both rates by
the `with_ocr` filter (`ocr_text is not None`), so the invalid and failed
denominators are 101/84 — crops OCR actually attempted — not 192.

---

## 4. Canonical convention — CLEAN

* **All 5 conventions ran.** Distinct values in `records[*].convention`:
  `['ceil', 'floor', 'floor_dy-1', 'round', 'trunc']` — matching `CONVENTIONS`
  (phase2c_canonical.py:29). Each frame × box is recorded once per convention, so
  the matrix is complete (185 crops per convention).
* **Selection used only non-accuracy inputs.** `convention_scores()`
  (run_phase2c_ab.py:297-322) emits exactly four keys per convention:
  `production_equivalent`, `degenerate_count`, `shrinks_box_count`, `n_crops`.
---

## 5. Latency + repeatability — **FAIL**

### 5a. Latency — CLEAN (phase2c_latency.json)

* `warmup_calls = 20` (>= 20 required) — done per detector *before* any timing
  (run_phase2c_ab.py:439-441), plus 20 crop+OCR warm-up iterations
  (lines 451-454) before OCR timing.
* `measured_calls = 100` (>= 100 required). `n = 100` is stored for every sample
  series: both detectors, `crop_extraction`, `ocr`, `total`.
* **Model load is excluded.** `build_detectors()` (which calls
  `api._ensure_models()` and `IranPlateDetectorAdapter.load()`) runs in `main()`
  long before `measure_latency()`; no load occurs inside any timed region.
  Percentiles use nearest-rank `pct()` (lines 224-230).

Stored latency values (ms):

| Series | p50 | p95 | p99 | mean | max | n |
|---|---|---|---|---|---|---|
| detector_a_current | 20.8348 | 25.5195 | 33.2076 | 21.9065 | 93.619 | 100 |
| detector_b_iranplate | 20.7287 | 25.1776 | 44.9055 | 27.298 | 625.5737 | 100 |
| crop_extraction | 0.0166 | 0.0188 | 0.02 | 0.0164 | 0.0207 | 100 |
| ocr | 9.6529 | 10.7331 | 12.3681 | 9.6462 | 12.5906 | 100 |
| total (crop+ocr) | 9.67 | 10.7526 | 12.3879 | 9.6626 | 12.6091 | 100 |

Note for the report writer: `total` is crop-extraction + OCR only
(lines 456-463); detector time is measured in a separate loop. Do not present
`total` as detect+OCR.

### 5b. Repeatability — FAIL

The shipped run contains **only `run0`**. `phase2c_summary.json` has
`repeatability: {"runs": 1}` and `per_run_summary` has exactly one key, `run0`.
The raw file likewise contains only `run0` records, and `frame_rows` carries no
run tag at all. Consequently:

* `repeat["identical"]` was never computed (code only computes it when
  `args.repeats > 1`, lines 585-602).
* **No second run exists, so no claim of identical accuracy / invalid /
  detection signatures can be made or checked.** Task §26 is unmet. This is a
  genuine gap, not a formatting issue.
* The repeatability *code* is correct — it compares
  `{n_boxes, n_detected, n_exact, n_labeled, n_invalid}` per run and sets
  `identical` only when every detector's signature set has cardinality 1 — so a
  re-run with `--repeats 2` produces the required evidence with no code change.
* Secondary consequence: `build_buckets()` defaults to `run_tag="run0"`, fine at
  repeats=1, but per-run frame censuses cannot be separated because `frame_rows`
  has no run tag.

**Verdict: Area 5 is FAIL overall.** Everything else is sound; only the second
repeat run is missing. No headline number in this report depends on run1.

---

## 6. Headline numbers — EXACT stored JSON values

Source: `phase2c_summary.json` → `per_run_summary.run0`, `paired_statistics`;
`phase2c_latency.json` → `latency`. All values below were independently
recomputed from `phase2c_raw_results.json` and match the stored JSON exactly.
Convention = `trunc`, `run0`, interval 5 (192 frames = 72 cam1 + 120 cam2).

### 6a. Detector A (`detector_a_current`)

| Quantity | Overall | cam1.mp4 |
|---|---|---|
| frames_with_detection / frames_total | **101 / 192** | **62 / 72** |
| frames_without_detection | **91** | **10** |
| labeled crops (accuracy denominator) | **62** | **62** |
| unlabeled crops (cam2, UNLABELED) | **130** | 10 |
| exact | **62 / 62 = 1.0** | **62 / 62 = 1.0** |
| char_accuracy | **62.0 / 62 = 1.0** | **62.0 / 62 = 1.0** |
| mean_edit_distance | **0 / 62 = 0.0** | **0 / 62 = 0.0** |
| median_crop_width (px) | **138.0** | **227.0** |
| median_crop_height (px) | **58.0** | **66.0** |
| width percentiles p10/p25/p50/p75/p90 | 82 / 99 / 138 / 227 / 229 | 138 / 138 / 227 / 229 / 229 |
| invalid (`ocr_valid == False`) | **34 / 101 = 0.3366** | **0 / 62 = 0.0** |
| failed (blank OCR text) | **13 / 101 = 0.1287** | **0 / 62 = 0.0** |
| clipping (`clipped_any`) | **0 / 101 = 0.0** | **0 / 62 = 0.0** |
| mean confidence (detected crops) | 0.7421 | 0.7622 |
| multi_box_frames / degenerate crops | 0 / 0 | 0 / 0 |

### 6b. Detector B (`detector_b_iranplate`)

| Quantity | Overall | cam1.mp4 |
|---|---|---|
| frames_with_detection / frames_total | **84 / 192** | **72 / 72** |
| frames_without_detection | **108** | **0** |
| labeled crops (accuracy denominator) | **62** | **62** |
| unlabeled crops (cam2, UNLABELED) | **130** | 10 |
| exact | **56 / 62 = 0.9032** | **56 / 62 = 0.9032** |
| char_accuracy | **61.3334 / 62 = 0.9892** | **61.3334 / 62 = 0.9892** |
| mean_edit_distance | **6 / 62 = 0.0968** | **6 / 62 = 0.0968** |
| median_crop_width (px) | **168.0** | **202.0** |
| median_crop_height (px) | **53.0** | **53.0** |
| width percentiles p10/p25/p50/p75/p90 | 109 / 140 / 168 / 202 / 202 | 140 / 140 / 202 / 202 / 202 |
| invalid (`ocr_valid == False`) | **15 / 84 = 0.1786** | **6 / 72 = 0.0833** |
| failed (blank OCR text) | **0 / 84 = 0.0** | **0 / 72 = 0.0** |
| clipping (`clipped_any`) | **0 / 84 = 0.0** | **0 / 72 = 0.0** |
| mean confidence (detected crops) | 0.7909 | 0.8101 |
| multi_box_frames / degenerate crops | 0 / 0 | 0 / 0 |

> **"Overall" accuracy equals cam1 accuracy for both arms by construction** —
> cam2 has zero verified frames (`gt_frame_counts = {"cam1.mp4": 315}`,
> cam2 `verified: false`, `plate_text: null`), so the 62-crop accuracy
> denominator is entirely cam1. Only the invalid / failed / geometry columns
> differ between the "overall" and "cam1" columns, because those denominators
> include cam2 crops.

### 6c. Latency (ms, n = 100 measured, 20 warm-up, model load excluded)

| Series | p50 | p95 | p99 |
|---|---|---|---|
| detector A | **20.8348** | **25.5195** | **33.2076** |
| detector B | **20.7287** | **25.1776** | **44.9055** |
| OCR | **9.6529** | **10.7331** | **12.3681** |
| crop extraction | 0.0166 | 0.0188 | 0.02 |
| total (crop + OCR) | **9.67** | **10.7526** | **12.3879** |

`total` excludes detector inference. Latency is a single shared-frame
measurement on `frames[0]`, and is not arm-specific in any way other than the
detector series.

### 6d. Paired 2×2 (verified frames only, run0, trunc, all cameras = cam1)

|  | **B correct** | **B wrong** | row total |
|---|---|---|---|
| **A correct** | **both_correct = 56** | **a_correct_b_wrong = 6** | 62 |
| **A wrong** | **a_wrong_b_correct = 0** | **both_wrong = 0** | 0 |
| column total | 56 | 6 | **verified_frames = 62** |

* **Discordant pairs (n) = 6** — all in one direction (A right, B wrong).
* **McNemar exact two-sided p = 0.03125** (exact binomial, `mcnemar_exact`,
  lines 345-356; b=6, c=0 → 2·(1/2^6) = 0.03125).
* `paired_statistics.all` and `paired_statistics.cam1` are **identical** in this
  dataset, for the reason noted above (all verified frames are cam1).
* Discordant frame IDs are stored in `paired_statistics.*.discordant_ids`
  (`a_correct_b_wrong`: 6 ids; `a_wrong_b_correct`: `[]`; `both_wrong`: `[]`).

---

## 7. Caveats a report writer must not drop

1. **The repeat run does not exist** (Area 5). Do not state that Phase 2C proved
   run-to-run determinism. Re-run with `--repeats 2` to earn that claim.
2. **All accuracy evidence rests on 62 crops of 2 verified plate instances** from
   a single video (`gt_labels.json`: `cam1_plate_A`, `cam1_plate_B`,
   `verified: true`). n = 62 with 2 distinct physical plates means the effective
   independent sample is far smaller than 62; treat CIs as illustrative.
3. **One GT glyph was resolved using production's charset.**
   `cam1_plate_A.evidence` states the letter glyph is "ambiguous between ی/ع at
   this resolution — recorded with the production DTRB charset letter (y)".
   Since Detector A *is* the production model on production OCR, this label
   choice cannot disadvantage A; it mildly favours it. Quote it when comparing
   A = 62/62 against B = 56/62.
4. **`total` latency is crop+OCR only**, not end-to-end detect→OCR.
5. Detector B's p99 (44.9055) and max (625.5737) show a large tail that the
   p50 hides (20.7287 vs A's 20.8348). A single frame and n=100; do not
   generalise detector speed parity from the p50.

---

## 8. Reproduction

`python benchmarks\audit\_recompute_check.py` recomputes every figure in §2, §3,
§4, §5b and §6 directly from `phase2c_raw_results.json` +
`phase2c_summary.json` and prints the stored counterparts for diffing.
`python benchmarks\audit\_gt_probe.py` dumps the ground-truth provenance used in
§7. Both are read-only and create no files outside `benchmarks\audit\`.
* `repeat["identical"]` was never computed (code only computes it when
  `args.repeats > 1`, lines 585-602).
* **No second run exists, so no claim of identical accuracy / invalid /
  detection signatures can be made or checked.** Task §26 is unmet. This is a
  genuine gap, not a formatting issue.
* The repeatability *code* is correct — it compares
  `{n_boxes, n_detected, n_exact, n_labeled, n_invalid}` per run and sets
  `identical` only when every detector's signature set has cardinality 1 — so a
  re-run with `--repeats 2` produces the required evidence with no code change.
* Secondary consequence: `build_buckets()` defaults to `run_tag="run0"`, fine at
  repeats=1, but per-run frame censuses cannot be separated because `frame_rows`
  has no run tag.

**Verdict: Area 5 is FAIL overall.** Everything else is sound; only the second
repeat run is missing. No headline number in this report depends on run1.
  No accuracy, `exact`, `char_accuracy`, or edit distance is computed or
  referenced. `select_canonical()` (phase2c_canonical.py:171-197) reads only
  `production_equivalent` first, falling back to `(degenerate_count,
  shrinks_box_count)`. Ground truth cannot leak into protocol selection.
* **Stored non-accuracy scores** (phase2c_summary.json
  `convention_scores_non_accuracy`):

  | convention | production_equivalent | degenerate_count | shrinks_box_count | n_crops |
  |---|---|---|---|---|
  | round | false | 0 | 226 | 185 |
  | floor | false | 0 | 740 | 185 |
  | ceil | false | 0 | 0 | 185 |
  | **trunc** | **true** | 0 | 740 | 185 |
  | floor_dy-1 | false | 0 | 1110 | 185 |

* **Chosen: `trunc`**, reason string stored verbatim:
  `"production-equivalent: trunc matches alpr_engine.astype(int)"`. It wins on the
  `production_equivalent` flag alone (first branch), so the accuracy matrix never
  entered the decision.
* **`trunc` == `numpy.astype(int)`.** `convert_coord(..., "trunc")` returns
  `int(v)` (toward zero). Randomised equivalence check over 20,000 uniform floats
  in [-1000, 1000] (seed 7), `int(v) == np.float64(v).astype(int)`:
  **0 mismatches**. This is the documented production semantic (alpr_engine
  `box.xyxy[0].cpu().numpy().astype(int)`), and it differs from `floor` for
  negative coordinates — hence the module keeps both.
* Degenerate handling is symmetric: `extract_plate_crop` returns
  `(None, CropResult(invalid=True))` for zero/negative size; the run records those
  as `failed=True, ocr_valid=None`. Observed count in this run: **0** (`crop_none`
  = 0 for both detectors).
  excluded from every accuracy denominator and appears only as
  `gt_status="UNLABELED"` with `exact=char_accuracy=edit_distance=None`.
* `ratio()` (line 233) always emits `{numerator, denominator, value}`; no metric
  in the file can hide its base.
Both arms are driven at `iou=0.45`, `max_det=12`, byte-identical, through one
call site. Any remaining A/B difference can no longer be attributed to the NMS
or candidate-budget asymmetry. Contrast with `run_phase2b_ab.py`, which called
`det.detect(frame, conf=...)` per-arm.