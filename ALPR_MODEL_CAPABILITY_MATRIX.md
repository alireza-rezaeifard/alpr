# ALPR Model Capability Matrix

Roles, plate-type support, IO formats, and licensing for every audited artifact. Type support is marked from **executed behavior or shipped code only** (task §18) — `UNKNOWN` where no evidence exists, `PARTIAL` where partial evidence exists, never inferred from filenames.

## Roles × IO formats

| Model | Roles | Input | Input size | Output | Output charset |
| --- | --- | --- | --- | --- | --- |
| CURRENT_PRODUCTION | PLATE_DETECTOR · CHARACTER_DETECTOR · SEQUENCE_OCR · vehicle/color classifiers | frame / crop | engine-native (5 models) | romanized text + conf | ASCII digits + dtrb letters |
| hezar_crnn_v2 | SEQUENCE_OCR | plate crop | 128×32 gray (config) | Persian text | Persian letters + Persian digits |
| plr_crnn | SEQUENCE_OCR | plate crop | 100×32 RGB | CTC text | ASCII abbreviations (B,D,I,H,E…) + digits |
| persian_lpr_yolo11 | CHARACTER_DETECTOR (+assembly = SEQUENCE_OCR) | plate crop | model imgsz | char boxes → text | ASCII abbreviations (b,d,h,ta,sad…) |
| iranplate_vision_yolo | PLATE_DETECTOR | frame | model imgsz | boxes + conf | — |
| plr_yolo_plate | PLATE_DETECTOR | frame | model imgsz | boxes + conf | — |
| platehunter (blocked) | PLATE_DETECTOR · CHARACTER_DETECTOR · CHARACTER_CLASSIFIER | frame/crop/char | 960 / 608 / config | — | — |
| pelakx (blocked) | FULL_ALPR_PIPELINE | frame | config (640 default) | — | — |

## Plate-type support (§10)

| Model | Civilian | Taxi | Government | Public/Service | Military/Police | Diplomatic | Special | Motorcycle | Free Zone | Temp/Free-zone |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CURRENT_PRODUCTION | YES | PARTIAL | PARTIAL | PARTIAL | PARTIAL | PARTIAL | PARTIAL | UNKNOWN | YES | PARTIAL |
| hezar_crnn_v2 | PARTIAL | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | NO | UNKNOWN | UNKNOWN |
| plr_crnn | PARTIAL | NO | NO | NO | NO | NO | NO (ژ note) | NO | NO | NO |
| persian_lpr_yolo11 | PARTIAL | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | NO | UNKNOWN | UNKNOWN |
| iranplate_vision_yolo | UNKNOWN (detector only — no type head) | — | — | — | — | — | — | — | — | — |
| plr_yolo_plate | UNKNOWN (detector only) | — | — | — | — | — | — | — | — | — |
| PlateHunter | UNKNOWN (blocked) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| PelakX | PARTIAL | PARTIAL | PARTIAL | UNKNOWN | PARTIAL | PARTIAL | PARTIAL | UNKNOWN | PARTIAL | PARTIAL |

Evidence notes:
* CURRENT_PRODUCTION: `plate_validator.py` classifies civilian/taxi/government/diplomatic/police/free-zone categories; free-zone robustness additionally proven by the `best_plate_text` DTRB→YOLO fallback path.
* plr_crnn: `backend.py` hard-decodes layout `NN L DDDDD` and only annotates `ژ` — fixed car-plate layout, no type logic.
* persian_lpr_yolo11: 26 char classes, no layout/type logic.
* hezar: trained on `hezarai/persian-license-plate-v1`; dataset composition (types) undocumented → PARTIAL/UNKNOWN.
* PelakX: ships `configs/countries/ir.yaml` + plate-type reference assets, but no weights → PARTIAL by code, unverified behavior.

## Licenses

| Project | License | Concern |
| --- | --- | --- |
| PersianLicensePlateRecognition | MIT (c) 2025 Sina Eslami | none (attribution) |
| IranPlate-Vision | MIT (c) 2026 | none (attribution) |
| persian-lpr-yolov11 | MIT (badge); dataset Public Domain (Roboflow) | none |
| PelakX | MIT | none |
| hezar library / CRNN V2 model | Apache-2.0 (library) / hub model card | verify model card before redistribution |
| Persian_ALPR_project (PlateHunter) | **NONE FOUND** | **do not reuse code or weights without author permission** |
| production `weigths/` | in-repo provenance (unchanged) | out of scope |

## Blocked-model registry (exact reasons, §1 rule 10)

| Model | Reason | Class |
| --- | --- | --- |
| platehunter_model1 (YOLO26s plate det @960) | missing weight `.pt` (archive has training logs only) | missing weight |
| platehunter_model2 (YOLO26l char det @608) | missing weight `.pt` | missing weight |
| platehunter_model3 (ConvNeXtV2 classifier) | missing checkpoint `.pth` (config + class maps present) | missing weight |
| pelakx pipeline | ships no weights; runtime auto-download from GitHub/HF forbidden (offline mandate) | missing weight + policy |
| persian-lpr fold0–4, 1st-version weights | present and loadable; not run (best-candidate policy) — runnable in a later pass | deferred, not blocked |
