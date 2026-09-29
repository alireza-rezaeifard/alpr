# Model Registry (Phase 0)

Machine-readable source of truth: [`manifest.json`](manifest.json).
This file is documentation for humans; the JSON is what tooling reads.

**Nothing was retrained, replaced, quantized, or re-exported in Phase 0.**
The registry exists so that any future change is visible and reviewable.

## Rule (design Part 6.5)

> No model file changes without a `manifest.json` update + a re-recorded
> baseline under `eval/baselines/` + the advisory latency check in CI.

This single rule prevents the silent class-map drift the audit found
(`char_model.pt` exposes class names `'1'…'27'` while `alpr_engine.py`
maps class *indices* through its own `CHAR_CLASSNAMES` list).

## Inventory (verified on disk, hashes in `manifest.json`)

| File | Architecture | Classes | Size | Used by |
|---|---|---|---|---|
| `plate_det_model.pt` | YOLO11n (2,590,035 params) | 1 (`LicensePlate`) | 5.2 MB | `AlprEngine._plate_model` |
| `car_det_model.pt` | YOLO11n (2,624,080 params) | 80 COCO → 4 used (2,3,5,7) | 5.4 MB | `AlprEngine._car_model` |
| `char_model.pt` | YOLO detector (3,016,113 params) | 27 (names are indices) | 5.9 MB | `AlprEngine._char_model` |
| `car_name_model.pth` | ResNet18 fp32 `state_dict` (11,199,983 params) | 27 makes | 42.8 MB | `AlprEngine._car_name_model` |
| `color_model.pt` | ResNet18 fp32 `state_dict` (11,182,668 params) | 12 colours | 42.7 MB | `AlprEngine._color_model` |

Support data: `Plates/city_plateinfo.txt` (city lookup CSV).

## Known, documented risks (not fixed in Phase 0)

1. **`char_model.pt` class semantics** — see rule above; Phase 1 item P1-7.
2. **No accuracy baseline exists** — only latency is measured in Phase 0
   (`eval/bench_latency.py`). Accuracy needs the `heldout` dataset described
   in design §6.3; `eval/run_eval.py` currently reports "dataset missing"
   instead of inventing numbers.
3. **Two ResNet18s dominate CPU** (~45 % of per-frame cost per the audit);
   Phase 2 moves them to event-level computation (design §5.5).

## Empty placeholders

`weigths/dtrb-recoginzer/` and `weigths/yolov8-detector/` contain only
`.gitkeep` files and are referenced exclusively by the legacy `main.py` /
`ui.py` paths, which are not part of the live pipeline.
