# ALPR Phase 2D — Proposed Production Patch (NOT APPLIED)

**Status: `CROP_FIX_CANDIDATE` — candidate only. Integration is NOT
approved and NOT performed. Production source is UNCHANGED.**
**HEAD:** `f9bd7bb` · **Production code changed:** NO

## 1. Exact production file and lines

`alpr_engine.py`, line 363 (inside `AlprEngine.run`, plate-detection
loop):

```python
# BEFORE (current production, frozen Phase 2D baseline)
363:  x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
368:  plate_crop = frame[y1:y2, x1:x2]
```

```python
# AFTER (proposed — NOT applied)
      x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().tolist()
      x1, y1, x2, y2 = (
          math.floor(x1 + 0.5) if x1 >= 0 else math.ceil(x1 - 0.5),
          math.floor(y1 + 0.5) if y1 >= 0 else math.ceil(y1 - 0.5),
          math.floor(x2 + 0.5) if x2 >= 0 else math.ceil(x2 - 0.5),
          math.floor(y2 + 0.5) if y2 >= 0 else math.ceil(y2 - 0.5),
      )
368:  plate_crop = frame[y1:y2, x1:x2]
```

(`import math` already exists in `alpr_engine.py`? — verify at
integration time; add if absent. The helper form used by the benchmark
is `benchmarks/phase2c_canonical.convert_coord`, convention `round`:
half-away-from-zero, deliberately NOT Python's banker's rounding.)

## 2. Before behavior

* Float box → integer pixels by **truncation toward zero**
  (`.astype(int)`), the Phase 2C-frozen convention.
* For a box whose top edge lands fractionally (e.g.
  `y1 = 595.72`), the crop **includes the entire row 595**, of which
  only the bottom 28 % is inside the true box. On the six Phase-2C
  discordant frames that row is **dark background** (mean brightness
  13.5 vs plate interior 126.7), and its inclusion makes the shared
  char detector emit a spurious character: OCR reads `12d674913`
  instead of `12d67413`.
* Measured (cam1 verified, Phase 2D): Detector A **62/62**,
  Detector B **56/62**; 6 discordant pairs, McNemar exact
  **p = 0.03125**.

## 3. After behavior

* Float box → integer pixels by **rounding half-away-from-zero**.
* The same fractional box (`y1 = 595.72`) starts at row **596**:
  the background sliver is dropped; the crop's bottom gains row 646,
  88 % of which is inside the true box (legitimate plate content).
* Measured (cam1 verified, Phase 2D): Detector A **62/62**
  (unchanged), Detector B **62/62** (+6); **0 discordant pairs**,
  McNemar **p = null** (no difference to test).
* Crop-extraction latency: p50 0.0119 ms (round) vs 0.0121 ms
  (trunc) — delta **-0.0002 ms**, i.e. no measurable cost.
* Clipping: 0/62, 0/72, 0/39, 0/12 — identical to baseline.

## 4. Why it is safe

1. **Deterministic** — pure function of the float box; 36
   determinism tests (`tests/test_phase2d_crop.py`) and 25 safety
   tests (`tests/test_phase2d_safety.py`) pin the behavior.
2. **No accuracy regression** — A is 62/62 under trunc, floor,
   round AND ceil; the convention change cannot reduce verified
   exact accuracy on this dataset.
3. **No clipping** — the change is a 1-px band selection at the
   box edges, never an enlargement; expansion is NOT part of this
   patch (expansion was measured and rejected: non-monotonic,
   A collapses to 33/62 at 1.05×).
4. **No contamination** — the only pixel change is dropping an
   out-of-box background row and adding an in-box plate row
   (Step 9 contamination proxy, `phase2d_postfix_matrix.json`).
5. **Negative-coordinate hazard is documented, not introduced** —
   the benchmark helper clips negatives to 0; raw NumPy slicing
   would wrap. Ultralytics clips boxes to the image at inference,
   so negatives do not occur in practice, but the integration
   must keep an explicit `max(0, …)` / `min(W, …)` guard (see
   tests) rather than relying on NumPy slice semantics.

## 5. Why it is NOT applied now

* Production runs **Detector A**, which is already **62/62** under
  the frozen `trunc` convention. There is **no measured failure to
  recover** for the production detector; the 6 recovered reads
  belong to Detector B, which Phase 2C closed as **not superior**
  and which must **not** be integrated.
* The change alters the integer bbox on **62/62** of A's cam1
  crops (every crop with a fractional edge) while changing no
  measured outcome — a material behavior change with zero measured
  benefit for the current detector.
* Its value is **contingent**: it hardens the crop path against the
  1-px quantization failure mode for any *future* detector whose
  boxes sit near integer boundaries. It should therefore ship only
  as part of a detector-integration PR, with the regression tests
  below, and be reviewed against a multi-plate, multi-camera
  verified dataset (which does not yet exist).

## 6. Tests protecting it

* `tests/test_phase2d_crop.py` (36) — determinism, rounding rules,
  expansion identity, clipping, degenerate-box rejection, validation.
* `tests/test_phase2d_safety.py` (25) — the ten production-safety
  edge cases (boundary-touching, tiny, huge, partial, negative,
  beyond-frame, degenerate, overlapping, duplicate, non-plate).
* Phase 2B/2C tooling suites (162) — protocol, denominators,
  canonical-convention equivalence (`trunc == numpy.astype(int)` on
  2000/2000 random floats).
* New integration test required at integration time: a golden test
  asserting `12d67413` on cam1 frames 180/185/210/215/330/335
  under BOTH detectors with the production OCR, guarding the exact
  regression this patch addresses.

## 7. Rollback strategy

* One-line revert: restore
  `x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)`.
* No data, DB, tracker, event, or model migration is involved —
  the change is confined to the crop-integer conversion of the
  plate-detection loop (and, if applied, the identical line in the
  car-detection loop at `alpr_engine.py:323`).
* Canary: deploy behind the existing camera-scoped config; compare
  per-camera OCR exact/invalid rates for 24 h before full rollout.

## 8. Equivalent alternative

`ceil` produces **identical** measured outcomes on this dataset
(A 62/62, B 62/62, 0 discordant). `round` is recommended as the
primary because it is the standard nearest-integer rule and was the
Phase 2B default; `ceil` is a documented, equally-valid substitute.
`floor` is **rejected** (it reproduces the `trunc` failure: B
56/62).
