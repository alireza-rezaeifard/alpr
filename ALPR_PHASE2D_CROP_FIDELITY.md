# ALPR Phase 2D — Crop Extraction Fidelity & Coordinate Semantics

**Date:** 2026-10-04 · **Repo:** `D:\alpr` · **Branch:** `main`
**HEAD:** `f9bd7bb77ff78d55385895293dce349eee9c3d3a` (dirty: `.gitignore`,
`conftest.py` modified; benchmark reports/tests untracked — pre-existing, untouched)
**Production code changed:** NO · **Production model changed:** NO

## 1. Purpose

Freeze and document the deterministic crop-extraction semantics that Phase 2C
identified as the root cause of the 6 discordant cam1 frames. This document is
the normative reference for the Phase 2D benchmark; it is written **from
source**, not from assumption.

## 2. Asset identity (Step 1 record)

| Asset | Path | SHA-256 |
| --- | --- | --- |
| Detector A (production) | `weigths/plate_det_model.pt` | `C70A91B5D695C2B8302BBE4F8AB6112DDC7845159F2FCC91CD50072D401ED00C` |
| Detector B (IranPlate-Vision) | `bench/IranPlate-Vision-main/IranPlate-Vision-main/best.pt` | `308C24643EAF49FC38930CEBFC46CA7455E7472F1D83FE98A2AE24443043DE40` |
| Production OCR (char YOLO) | `weigths/char_model.pt` | `08CF1BB9898E364513B5F4872A6E12175D9DE6EB0F41A53D` (6,218,616 B) |
| cam1.mp4 (restored raw) | `cam1.mp4` | `E3FD570F7CD14AE6CB7930C95DA82D3F4A7DB598B2DD6B227A4F31F5C4FEF088` (16,109,000 B) |
| cam2.mp4 (restored raw) | `cam2.mp4` | `237E30A0545D82ACC267CC29985D597C39C29D407D7AD69888BBFB16D77D64F1` (129,390,859 B) |

All hashes match the Phase 2C manifest (`ALPR_PHASE2C_DETECTOR_AB_BENCHMARK.md`
§3, §20). Environment: Python 3.11.4, torch 2.12.0+cpu, ultralytics 8.4.56,
OpenCV 4.13.0, numpy 2.4.6, 12 CPUs, CUDA unavailable.

## 3. Complete crop path (production, verified line-by-line)

```text
frame (BGR uint8 ndarray, H×W×3, from cv2.VideoCapture)
  → alpr_engine.py:355  self._plate_model(frame, show=False, conf=PLATE_DET_CONF=0.6,
                          iou=NMS_IOU=0.45, max_det=PLATE_MAX_DET=12, verbose=False)
  → ultralytics Results; det.boxes is a Boxes object
  → alpr_engine.py:362  for box in det.boxes:
  → bbox representation: box.xyxy[0]  — torch.float32 tensor [x1, y1, x2, y2]
        pixel coordinates, (x1,y1) = top-left, (x2,y2) = bottom-right.
        ultralytics NMS postprocessing clips boxes to the image bounds, so
        0 <= x1 <= x2 <= W and 0 <= y1 <= y2 <= H hold at inference time.
  → coordinate conversion: alpr_engine.py:363
        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
        torch → CPU → numpy float32 → int64
        numpy .astype(int) TRUNCATES TOWARD ZERO (== int(v) for floats;
        verified equal on 2000/2000 random floats in Phase 2C, differs from
        floor() on negatives and from round()/ceil() on fractional parts).
  → integer conversion: trunc-toward-zero, applied independently to all 4 edges.
        No clamping, no padding, no centre-preserving transform.
  → clipping: NONE explicit. alpr_engine.py:368
        plate_crop = frame[y1:y2, x1:x2]
        NumPy basic slicing silently clips indices above the frame bound
        (x2 > W → W) and silently WRAPS negative indices (x1 < 0 → frame
        end). The wrap branch is unreachable in practice because ultralytics
        clips boxes to the image bounds, but it is a latent hazard — see §6.
  → degenerate rejection: alpr_engine.py:369
        if plate_crop.shape[0] == 0 or plate_crop.shape[1] == 0: continue
        (empty crop → dropped; this is the only crop-validity gate)
  → resize/preprocessing: NONE. The raw pixel crop is passed unchanged to
        alpr_engine.py:372 → _assemble_chars() → alpr_engine.py:249
        self._char_model(plate_crop, conf=CHAR_DET_CONF=0.3, iou=0.45, verbose=False)
        The character YOLO performs its own internal letterbox resize to its
        training imgsz (640). No benchmark code resizes the crop either.
  → OCR assembly: alpr_engine.py:263-281 — char boxes sorted by x1
        (x1 also .astype(int)), class index → CHAR_CLASSNAMES, joined
        left-to-right. No confidence threshold on the assembled text.
```

Benchmark-only path (`benchmarks/phase2c_canonical.py`, used by Phase 2B/2C/2D):
identical conversion (`convert_box`), but with an **explicit** clip step
(`clip=True`) and optional padding applied **after** conversion in pixel space.
For in-bounds non-negative boxes — the only case observed in Phase 2C
(0/101 and 0/84 crops clipped) — the benchmark path and the production path
produce byte-identical crops. The explicit clip makes the benchmark well-defined
for the synthetic edge cases of Step 11; production relies on NumPy slicing.

## 4. Normative mathematical definition (exactly what production does)

For float box `(x1, y1, x2, y2)` on a frame of height `H`, width `W`:

```text
x1_i = trunc(x1)      # toward zero; == floor() for x1 >= 0
y1_i = trunc(y1)
x2_i = trunc(x2)
y2_i = trunc(y2)

crop = frame[y1_i : y2_i, x1_i : x2_i]     # NumPy basic slicing
```

Properties (all verified from source):

* **Inclusive/exclusive**: `[y1_i, y2_i)` and `[x1_i, x2_i)` — start inclusive,
  end exclusive. A box `x1=100.0, x2=200.0` yields a **100 px** wide crop.
* **Pixel loss**: `effective_width = trunc(x2) − trunc(x1)` can differ from the
  float width `x2 − x1` by up to ±1 px per edge. Example: `x1=100.9, x2=200.1`
  → crop 100..200 = 100 px wide vs float width 99.2 px (a pixel is *gained*);
  `x1=100.1, x2=199.9` → 100..199 = 99 px vs 99.8 (a pixel is *lost*).
  Height behaves identically. This is the 1-px quantization Phase 2C identified.
* **Order of operations**: conversion happens **before** any clipping; there is
  no padding and no centre preservation in production.
* **x/y ordering**: x is column (width axis), y is row (height axis);
  `frame[y, x]`. Boxes are stored `(x1, y1, x2, y2)` top-left/bottom-right.
* **Degenerate boxes**: `x2_i <= x1_i` or `y2_i <= y1_i` produce an empty crop
  which production drops (`shape[0] == 0 or shape[1] == 0`). Production never
  crashes on them; the benchmark helper rejects them as `invalid`.
* **Negative coordinates**: production would wrap (NumPy semantics); the
  benchmark helper clips to 0. Both agree whenever coordinates are ≥ 0, which is
  guaranteed at inference by ultralytics box clipping.

## 5. Why this matters (Phase 2C recap, closed)

Phase 2C is CLOSED with `NO_MEASURABLE_DIFFERENCE`. On the 6 discordant frames
(cam1 @ 180, 185, 210, 215, 330, 335 — all plate `۱۲د۶۷۴۱۳`) Detector B's
box is ~8.5 px lower and ~7.4 px shorter than Detector A's. Under the frozen
`trunc` convention B reads `12d674913` (wrong); under `round`/`ceil` B reads
`12d67413` (correct); at 1.05× expansion B reaches 62/62. The same boxes,
the same OCR — only the integer-coordinate rule changes. **The detector A/B
question is not reopened by Phase 2D.** Phase 2D measures crop-extraction
determinism and its blast radius only.

## 6. Frozen baseline & conventions

* **Frozen production convention (baseline):** `trunc` — the only convention
  that reproduces `alpr_engine.py:363` exactly.
* **Alternative conventions** (benchmarked separately, never silently adopted):
  `floor`, `round` (half-away-from-zero), `ceil`. Each is a deterministic
  pure function of the float box; none is production-equivalent.
* **Expansion** (benchmark-only, centre-preserving, applied in float space
  *before* conversion): 1.00 / 1.01 / 1.02 / 1.03 / 1.05 / 1.07 / 1.10.
  Phase 2C showed expansion is **non-monotonic** for both detectors
  (A drops to 33/62 at 1.05×), so no expansion factor is a candidate fix
  unless the Step 5 sweep contradicts that with a clean margin.

## 7. Reproducibility

* Helper: `benchmarks/phase2d_crop.py` (pure, benchmark-only).
* Runner: `benchmarks/run_phase2d.py` (single detector inference pass per
  frame per detector; all conventions/expansions applied to the cached float
  boxes — detector inference is never re-run per convention).
* Dataset: `benchmarks/results/phase2d_dataset.json` (Step 8, append-only).
* Report: `ALPR_PHASE2D_CROP_FIDELITY_REPORT.md`.
