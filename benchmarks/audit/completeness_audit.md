# Phase 2B Completeness & Safety Audit

**Auditor:** completeness/safety reviewer · **Date:** 2026-10-03 · **Mode:** read-only on production code
**Subject:** `D:\alpr\ALPR_PHASE2B_DETECTOR_CROP_BENCHMARK.md` (282 lines)
**Scope:** completeness against the 24-section task spec, machine-readable artifact schema, production safety, numeric consistency, fact/claim hygiene, diagnostics hygiene.
**Constraint honoured:** no production file edited; nothing committed; this file is the only artifact created.

---

## 0. Verdict summary

| Dimension | Verdict |
| --- | --- |
| Spec coverage (24 sections) | **14 PRESENT · 9 PARTIAL · 1 MISSING** |
| Numeric accuracy | 22 of 24 spot-checks CONSISTENT; **2 real inconsistencies** (§12 p95 latency) + 1 rounding drift |
| Production safety | **PASS** — zero production files modified; only `.gitignore` (tracked) touched |
| Machine-readable artifacts | 8/8 filenames exist; schemas **undocumented**; 1 field bug (`failed_rate` = `invalid_rate`) |
| Fact/observation/hypothesis separation | **PASS** — no overstatement found |
| Blocking issues | 0 |
| Must-fix-before-signoff | 3; must-fix-before-merge 3 (see §10) |

---

## 1. Section-by-section checklist (all 24 spec sections)

Report section numbering does **not** equal spec numbering (report uses §1–§19 plus 4 unnumbered tail sections; spec §22/§23 are rendered as the unnumbered "Decision matrix" tail). Mapping below is by **spec section number**.

| Spec § | Requirement | Report location | Status | Note |
| --- | --- | --- | --- | --- |
| 1 | Purpose / scope statement | L1–6 headline | PRESENT | States frames, threshold and OCR held constant |
| 2 | Executive summary, evidence-based answers | §1 (L10–22) | PRESENT | 7-question table, each answer evidence-anchored |
| 3 | Dataset description (cameras, sampling, counts) | §2 (L26–30) | PRESENT | 84 crops / 62 verified / 22 unlabeled; 192 frames, every 5th |
| 4 | Methodology, identical conditions, controls | §3 (L32–43) | PRESENT | ASCII diagram; names the Phase 2A threshold confound (0.5 vs 0.4) as corrected |
| 5 | Detector A / B configuration table | §4 (L45–53) | PARTIAL | Artifact, classes, call params, role present. Detector A sha256 given only as "in-repo, unchanged" — **no hash value**, baseline not independently verifiable |
| 6 | Machine-readable per-crop record schema | results JSON + artifacts list | PARTIAL | 31 keys/record present, but **schema never documented** in the report; no schema sidecar file |
| 7 | Overall / combined results table | §6 (L59–77) | PRESENT | 14 metrics incl. char accuracy, edit distance, latency p50 |
| 8 | **Per-bucket metrics: samples, exact acc, char acc, invalid rate, failed rate, median OCR latency, median detector latency, clipping rate** | §9 (L111–121) | **PARTIAL** | Table gives only **3 of 8** required columns (`n / exact / invalid`). Missing: **char accuracy, failed rate, median OCR latency, median detector latency, clipping rate** — all five already exist in `phase2b_bucket_results.json`, so this is a reporting omission, not a data gap |
| 9 | Crop-size / bucket narrative | §9 (L121) | PRESENT | Correctly flags production yields 0 verified 150–199 px crops |
| 10 | Clipping analysis, per-edge counts + rate | §10 (L123–130) | PRESENT | left/right/top/bottom + any, with raw counts `0/101`, `0/84` |
| 11 | **Comparison table, ALL 13 rows, repeated for cam1 / cam2 / each bucket** | §11 (L132–145) | **PARTIAL** | Only **8 rows**, and **not repeated** per bucket — see §2 |
| 12 | Latency table, p50/p95 stage-wise, cold-start excluded | §12 (L147–156) | PARTIAL | p50 column correct; **4 p95 values inconsistent with JSON** — see §4 |
| 13 | Threshold sensitivity sweep | §13 (L158–168) | PRESENT | 0.2–0.6 × 2 detectors; all 10 det/frame values verified |
| 14 | Visual examples / diagnostics pointers | §14 (L170–172) | PRESENT | Case counts (6 / 8 / 17) match `case_index.json` exactly |
| 15 | Failure analysis of the regression | §15 (L174–195) | PRESENT | Strongest section: reproduces 0.903 exactly, names 6 frames, explains via crop quantization |
| 16 | cam2 improvement investigation | §16 (L197–209) | PRESENT | 7-row evidence/verdict table; correctly withdraws the Phase 2A gap |
| 17 | Crop expansion experiment | §17 (L211–221) | PRESENT | 5 levels × 2 detectors; all values verified |
| 18 | **Statistical caution, raw counts alongside percentages** | §5 (L57) + §6/§15/§17 | PRESENT | "smallest meaningful difference = 1 crop = 1.6 %"; `56/62`, `62/62`, `47/62`, `32/101`, `12/101` all carry counts |
| 19 | Limitations | §18 (L223–229) | PRESENT | 5 limitations incl. no repeat/variance study |
| 20 | **Exact deliverable filenames + directory** | L262–273 | PRESENT | All 8 filenames verified on disk — see §3 |
| 21 | Recommendation / next steps | §19 (L231–241) | PRESENT | 4 prioritised steps, explicitly "no production change" |
| 22 | **Production safety statement** | L4 header + §18.3 + L241 | PARTIAL | Header asserts "Production code changed: NO · Commit created: NO". **No enumerated safety section** demonstrating it per protected file, and it does not disclose the `.gitignore` modification |
| 23 | **Decision matrix: 10 named questions, exactly one of 3 verdicts** | L245–260 | PRESENT | **All 10 rows present**; exactly one verdict used: `MORE_DATA_REQUIRED` — see §5 |
| 24 | **Final response format** | — | **MISSING** | Not represented in the report at all. Either chat-reply-only (acceptable) or an appendix is expected — flag for the spec owner |
---

## 2. Spec §11 — comparison table completeness (focus item)

**Required:** a 13-row comparison table, repeated for (a) cam1, (b) cam2 diagnostics, (c) each crop-width bucket.

**Found (§11, L134–145):** a **single** table with **8 rows**, cam1/cam2 as *columns*.

Rows present: `BOTH_CORRECT`, `CURRENT_BETTER`, `IRANPLATE_BETTER`, `BOTH_WRONG`, `CURRENT_ONLY_VALID`, `IRANPLATE_ONLY_VALID`, `NEITHER_VALID`, `INCOMPARABLE`.

**Row-count gap: 8 of 13 — 5 rows missing.** These cannot be reconstructed from `benchmarks/ab_helpers.py::classify_pair` (lines 103–126), which emits exactly the 8 above. The missing 5 are therefore either spec-mandated *derived* comparisons (per-bucket breakdowns, confidence-band comparisons) or an expected superset of the classifier enum. **This is the largest single spec gap.**

The 8 rows that do exist are all consistent with `phase2b_pairwise_results.json` → `outcome_counts`:
`BOTH_CORRECT 62` ✔ · `CURRENT_BETTER 0` ✔ (key absent = zero) · `IRANPLATE_BETTER 0` ✔ · `BOTH_WRONG 0` ✔ · `CURRENT_ONLY_VALID 1` ✔ · `IRANPLATE_ONLY_VALID 0` ✔ · `NEITHER_VALID 7` ✔ · `INCOMPARABLE 3` ✔.

Repetition status:
- **cam1** → covered as a *column* (all 62 BOTH_CORRECT). Functionally adequate.
- **cam2** → covered as a *column*. Adequate.
- **per crop-width bucket** → **NOT DONE.** No bucket-level pairwise comparison exists in the report *or* in any JSON artifact. §9 is per-bucket but carries no pairwise outcome dimension. **MISSING.**

---

## 3. Spec §20 — deliverable filenames & machine-readable schemas (focus item)

All 8 declared paths exist with the exact declared names:

| Declared path | Exists | Size |
| --- | --- | --- |
| `benchmarks/results/phase2b_detector_crop_results.json` | yes | 174,041 B |
| `benchmarks/results/phase2b_pairwise_results.json` | yes | 59,903 B |
| `benchmarks/results/phase2b_bucket_results.json` | yes | 14,235 B |
| `benchmarks/results/phase2b_crop_sensitivity_results.json` | yes | 271,046 B |
| `benchmarks/results/phase2b_cam2_expansion.json` | yes | 989 B |
| `benchmarks/diagnostics/phase2b/ab_diagnostics.html` | yes | 44,870,082 B |
| `benchmarks/diagnostics/phase2b/case_index.json` | yes | 202 B |
| `benchmarks/diagnostics/phase2b/phase2b_crops.jsonl` | yes | 130,863 B (185 lines = 185 records) |

Top-level keys are stable: `generated_at` + detector-scoped blocks; per-detector blocks are `{overall, cam1.mp4, cam2.mp4}` with a fixed ~40-key metric set; `frame_level` is `{current_detector, iranplate_vision}`. Naming conventions are consistent (`detector@convention` for sweeps; `lt80 / 80-99 / 100-149 / 150-199 / ge200` for buckets).

### Spec §6 record schema check
Records in `phase2b_detector_crop_results.json` (185) and `phase2b_crops.jsonl` (185) carry **31 keys**, covering every plausibly-required metric key:
`camera, frame, detector, box_rank, confidence, x1, y1, x2, y2, width, height, area, aspect_ratio, bucket, clipped_left/right/top/bottom/any, ocr_text, ocr_confidence, ocr_valid, ground_truth, gt_status, detector_latency_ms, ocr_latency_ms, total_latency_ms, pred_canonical, ref_canonical, exact, char_accuracy, edit_distance, edit_distance_norm, failed`.

Gaps found:
1. **`ocr_confidence` is `null` on every sampled record** — key present but carries no information.
2. **No `crop_convention` field on the main records.** Round is recorded only in the `methodology` header block and in the separate sensitivity file; a consumer of `records` cannot tell which convention produced a row.
3. **No provenance keys**: no source-video path, frame index/timestamp, camera resolution, detector checkpoint hash, OCR engine id, or `verified` boolean (verifiability only inferable from `gt_status`).
4. **No schema documentation anywhere** — not in the report, no `*_schema.json` sidecar. Only `benchmarks/audit/detector_fidelity.md` and `verify_results.py` describe it, and those are audit scratch files, not deliverables.

### Field bug found
`phase2b_bucket_results.json` → `crop_expansion.*.failed_rate` is **numerically identical to `invalid_rate` in all 10 rows** (e.g. `current_detector@1.00` → both `0.3168`). Elsewhere `failed_rate` is distinct and smaller (overall `0.1188` vs invalid `0.3168`). Copy/paste error in the expansion block of `run_phase2b_ab.py`. The report never surfaces `failed_rate` for expansion, so no *reported* number is wrong — but the JSON is.
| 5 | Detector A / B configuration table | §4 (L45–53) | PARTIAL | Artifact, classes, call params, role present. Detector A sha256 given only as "in-repo, unchanged" — **no hash value**, baseline not independently verifiable |
| 6 | Machine-readable per-crop record schema | results JSON + artifacts list | PARTIAL | 31 keys/record present, but **schema never documented** in the report; no schema sidecar file |
---

## 4. Numeric consistency — 24 spot-checks against the JSON

**CONSISTENT (22):**

| # | Report claim | JSON value | OK |
| --- | --- | --- | --- |
| 1 | §6 exact 62/62 = 1.000 both | `exact_accuracy 1.0, n_exact 62, n_verified 62` | ✔ |
| 2 | §6 char acc 1.000 / edit dist 0.000 | `char_accuracy 1.0, mean_edit_distance 0.0` | ✔ |
| 3 | §6 invalid `0.317 (32/101)` | `0.3168, n_crops 101` | ✔ |
| 4 | §6 failed `0.119 (12/101)` | `0.1188` | ✔ |
| 5 | §6 median width `138.2 / 168.1` | `median_crop_width` | ✔ |
| 6 | §6 median height `58.4 / 53.3` | `median_crop_height` | ✔ |
| 7 | §6 clipping 0.000 both | `clipped_*` all 0, `clipping_rate 0.0` | ✔ |
| 8 | §6 conf mean `0.742 / 0.791` | `0.7418 / 0.7909` | ✔ |
| 9 | §6 latency p50 `20.83/20.54`, `10.59/9.91`, `31.29/30.59` | identical | ✔ exact |
| 10 | §7 cam1 crops `62 / 72` | `n_crops 62 / 72` | ✔ |
| 11 | §7 cam1 median width `227.4 / 201.8` | identical | ✔ |
| 12 | §7 cam1 latency `20.6/10.1/30.8` and `20.5/9.9/30.5` | `20.59/10.05/30.79`, `20.52/9.87/30.50` | ✔ |
| 13 | §8 cam2 crops `39 / 12` | `n_crops 39 / 12` | ✔ |
| 14 | §8 cam2 median width `83.0 / 98.2` | identical | ✔ |
| 15 | §8 cam2 p10/p90 `74.2/113.5`, `75.6/119.2` | identical | ✔ |
| 16 | §8 cam2 invalid round `0.821 / 0.917` | `0.8205 / 0.9167` | ✔ |
| 17 | §8 cam2 invalid floor `0.846 / 0.750` | sensitivity `0.8462 / 0.75` | ✔ |
| 18 | §8 cam2 failed `0.308/0.000`, conf `0.710/0.675`, lat `21.0/33.1`, `20.7/31.1` | `0.3077/0.0`, `0.7096/0.6753`, `21.0/33.08`, `20.7/31.12` | ✔ |
| 19 | §13 all ten `detections_per_frame` (0.792/0.740/0.682/0.526/0.469; 0.536/0.500/0.453/0.438/0.427) | identical | ✔ |
| 20 | §15 grid: current `62/62, 62/62, 47/62, 62/62`; IPV `62/62, 56/62, 62/62, 62/62` | identical, and `56/62 = 0.9032` reproduces Phase 2A 0.903 | ✔ |
| 21 | §17 expansion exact `1.000/0.968/0.952/1.000/0.935`, IPV `1.000`×5; invalid column | `1.0/0.9677/0.9516/1.0/0.9355` | ✔ |
| 22 | §16 expansion `0.917→0.833`, `0.821→0.821` | cam2_expansion `@1.00`/`@1.40` | ✔ |

**INCONSISTENT (2) — both in §12, both p95 columns:**

| Report §12 claim | `phase2b_detector_crop_results.json` | Delta |
| --- | --- | --- |
| detector p95 Current **25.8 ms** | `detector_latency_ms_p95 = 22.65` | **+3.15 ms** |
| detector p95 IranPlate **25.4 ms** | `detector_latency_ms_p95 = 22.54` | **+2.86 ms** |
| OCR p95 Current **13.2 ms** | `ocr_latency_ms_p95 = 13.6` | −0.4 ms |
| OCR p95 IranPlate **12.6 ms** | `ocr_latency_ms_p95 = 11.25` | **+1.35 ms** |

The p50 columns in the *same* table are correct, so the row is internally mixed. Either the p95s come from an undisclosed run, or the nearest-rank helper `ab_helpers.percentile` is applied inconsistently between passes. The report cites no source for the p95 column, so it is currently unverifiable from artifacts — a **defect**, not merely a citation gap.

**MINOR rounding drift (1):** executive summary (L15) says "Overall yes (**168.0** vs 138.2)" while §6 and the JSON say **168.1**. §1's "201.8 px vs 227.4 px" is correct. Use one value in both places.

**Unverifiable narrative claims (2, low severity):** §15's "same 140×51 px" crop and "≥ 120 s finalized" have no JSON backing. Acceptable as once-observed measurements, but should be labelled as such.

---

## 5. Spec §23 — decision matrix completeness (focus item)

The matrix at L247–258 contains **exactly 10 rows**, and all 10 map to the questions named in the brief:

| # | Question | Present | Verdict given |
| --- | --- | --- | --- |
| 1 | Improve verified OCR accuracy? | yes | No measurable improvement |
| 2 | Improve crop size? | yes | Mixed; not on cam1 |
| 3 | Reduce clipping? | yes | Equal |
| 4 | Improve cam2 diagnostics? | yes | Unproven |
| 5 | Regress cam1? | yes | Yes, under one crop convention |
| 6 | Is the regression explained? | yes | Yes — crop quantization + OCR fragility |
| 7 | Latency cost? | yes | None (within noise) |
| 8 | Robust across crop sizes? | yes | Yes (both) |
| 9 | Threshold tuning responsible? | yes | No |
| 10 | Enough evidence for controlled production A/B? | yes | No |

Every row has an **Evidence** column populated with a number. Verdict vocabulary is respected: prose verdicts per row, while the machine token `MORE_DATA_REQUIRED` appears as the classification at L22, L233 and L260 — all consistent. The other two allowed tokens (`READY_FOR_CONTROLLED_A_B`, `NOT_WORTH_INTEGRATING`) appear nowhere in the repo, which is correct.

Nits:
- Row 2's evidence cites "overall 168.1 vs 138.2" — correct here, but conflicts with the executive summary's 168.0 (§4).
- Matrix verdicts are prose, not the enumerated tokens. If the spec requires a token per row this is a format deviation; if tokens are only for the final classification, it is compliant. Make it explicit.

**Status: PRESENT.** No substantive issue.
| 7 | Overall / combined results table | §6 (L59–77) | PRESENT | 14 metrics incl. char accuracy, edit distance, latency p50 |
---

## 6. Production safety (focus item)

`git status --short`:
```
 M .gitignore
?? .freebuff/
?? ALPR_DETECTOR_BENCHMARK.md
?? ALPR_GROUND_TRUTH_BENCHMARK_REPORT.md
?? ALPR_MODEL_BENCHMARK_REPORT.md
?? ALPR_MODEL_CAPABILITY_MATRIX.md
?? ALPR_OCR_BENCHMARK.md
?? ALPR_PHASE1_CAM1_VALIDATION_REPORT.md
?? ALPR_PHASE2B_DETECTOR_CROP_BENCHMARK.md
?? ALPR_PIPELINE_BENCHMARK_REPORT.md
?? benchmarks/
?? tests/test_benchmark_metrics.py
?? tests/test_benchmark_tooling.py
?? tests/test_phase2b_tooling.py
?? tests/test_replay_validation_tooling.py
?? validation/
```
`git diff --stat`: ` .gitignore | 6 ++++++` → **1 file changed, 6 insertions(+), 0 deletions(-)**.

**Verdict: PASS.**

| Protected file | Modified? |
| --- | --- |
| `alpr_engine.py` | NO |
| `video_processor.py` | NO |
| `api.py` | NO |
| `db.py` | NO |
| `camera_manager.py` | NO |
| `docker-compose.yml` | NO |
| `Dockerfile` | NO |
| `flutter_app/**` | NO |

No deletions, no renames, nothing staged, no commits created. `HEAD` remains `f9bd7bb` on `main`.

Two disclosures (neither is a production-code change):
1. **`.gitignore` is a tracked file and it was modified** (added `bench/`, `*.mp4`, `benchmarks/dataset/crops/`). Repo hygiene, not production behaviour, and it errs in the right direction (it *excludes* large artifacts). The report's production-safety header should disclose it for full accuracy.
2. **`.freebuff/` and `validation/` are untracked top-level directories** of unverified provenance. They are not Phase 2B deliverables; `validation/` should be confirmed before the next commit or ignored.

All new work correctly lives under `benchmarks/` plus clearly-named `ALPR_*_BENCHMARK.md` / `ALPR_*_REPORT.md` files at repo root, and tests under `tests/test_*_tooling.py` — consistent with prior benchmark reports.
---

## 7. Fact / observation / hypothesis / recommendation separation

The report holds this line well. **No overstated claim was found.**

- **Measured facts** are labelled "Fact:" (§7, §9, §10, §11, §13, §15 implication) and every checked one is backed by a JSON number (§4).
- **Observations** are labelled "Observation:" (§8 — "driven by a handful of samples (1 crop ≈ 8.3 % of that 12-crop set)").
- **Hypotheses** are explicitly marked "Hypothesis (untested):" (§8, L109) and immediately followed by the evidence that *fails* to confirm it.
- **Recommendations** are quarantined in §19 and the decision matrix, never mixed into result tables.
- **Negative / non-monotonic results are reported, not buried**: §17 shows the *production* detector degrading with expansion (1.000 → 0.935) and labels it the same sensitivity as §15; §16 explicitly **withdraws** the Phase 2A "0.846 vs 0.800" finding.
- **Scope limits stated up front**: cam2's heading reads "Ground Truth unavailable: accuracy not measurable"; §2 states no ground truth was invented.

Two minor overstatement risks:
- §12's p95 values cannot be traced to any artifact (§4) yet read as measured facts with no caveat.
- §15's "±1 px … 47/62 to 62/62 — a 24-point swing" is correct (0.758 → 1.000) and is correctly attributed to the *shared downstream path*, not to either detector. No issue.

---

## 8. Diagnostics hygiene (focus item)

- `ab_diagnostics.html` (44,870,082 B ≈ 42.8 MiB) **is** under `benchmarks/diagnostics/phase2b/` as required. ✔
- It is **untracked** (`?? benchmarks/`) but **NOT ignored**. `.gitignore` currently covers only `bench/`, `*.mp4`, `benchmarks/dataset/crops/` plus pre-existing entries. `benchmarks/diagnostics/` and `benchmarks/results/` are not excluded — a `git add benchmarks/` today **would commit the 42.8 MiB HTML** (the ~519 KB of result JSON and 131 KB of crops JSONL are acceptable; the HTML is not).

**Answer: yes, a `.gitignore` change is needed.** Proposed lines — **NOT APPLIED**, per instructions; the repo owner should decide:

```gitignore
# Generated Phase 2B diagnostics (very large, e.g. ab_diagnostics.html ~43 MB)
benchmarks/diagnostics/
# keep the lightweight case index under version control instead
!benchmarks/diagnostics/phase2b/case_index.json
```

Optional companion if the HTML is ever wanted in-repo (prefer a release artifact instead):
```gitignore
benchmarks/diagnostics/**/*.html
```
---

## 9. Missing / partial items — consolidated

**MISSING**
1. **Spec §24 — final response format.** No representation in the report.
2. **Spec §11 — 5 of 13 comparison rows** absent (only the 8 `classify_pair` outcome classes exist in the code).
3. **Spec §11 — comparison table not repeated per crop-width bucket.** No bucket-level pairwise data exists in any JSON.

**PARTIAL**
4. **Spec §8 — bucket table carries 3 of 8 required metrics**; data for all 8 is already in `phase2b_bucket_results.json`.
5. **Spec §5 — Detector A sha256 not stated** ("in-repo, unchanged"), so the baseline is not independently verifiable.
6. **Spec §6 — record schema undocumented**; `ocr_confidence` null throughout; no `crop_convention` on main records; no provenance keys.
7. **Spec §12 — 4 p95 latency values inconsistent** with the JSON.
8. **Spec §22 — production safety asserted in the header but not enumerated**; `.gitignore` change not disclosed.
9. **`crop_expansion[*].failed_rate` duplicates `invalid_rate`** in `phase2b_bucket_results.json` (data bug; no reported number affected).

**MINOR**
10. Executive summary median width 168.0 vs 168.1 elsewhere.
11. §15's `140×51 px` and `≥ 120 s` claims have no artifact backing.

---

## 10. Prioritised remediation

**P0 — must fix before sign-off**
1. Expand **§11** to the full 13 rows and add a **per-bucket pairwise breakdown**. Requires regenerating data in `run_phase2b_ab.py`; not derivable from existing artifacts. *(benchmark author)*
2. **Source or correct the §12 p95 values** — cite the run/artifact, or replace with JSON values (`22.65 / 22.54` detector, `13.6 / 11.25` OCR). *(benchmark author)*
3. **Complete the §9 bucket table** with the 5 missing columns — pure transcription from `phase2b_bucket_results.json`, no re-run needed. *(benchmark author)*

**P1 — fix before merge**
4. Fix `failed_rate` in the `crop_expansion` block of `run_phase2b_ab.py` (currently mirrors `invalid_rate`) and regenerate `phase2b_bucket_results.json`. *(benchmark author)*
5. **Add the `.gitignore` lines** from §8 so the 42.8 MiB HTML cannot be committed. **Not applied by this audit.** *(repo owner)*
6. Replace "168.0" with "168.1" in the executive summary. *(benchmark author)*

**P2 — quality**
7. Add a `schema` block or `phase2b_record_schema.json` sidecar documenting the 31 record keys; document that `ocr_confidence` is always `null` and why. *(benchmark author)*
8. State Detector A's checkpoint sha256 explicitly. *(benchmark author)*
9. Add an enumerated §22 production-safety subsection listing the protected files with per-file "unmodified" status, and disclose the `.gitignore` change. *(benchmark author)*
10. Confirm provenance of the untracked `validation/` and `.freebuff/` directories before the next commit. *(repo owner)*
11. Clarify with the spec owner whether spec §24 (final response format) belongs in the report file or only in the chat reply. *(spec owner)*

---

## 11. Verification commands used

```powershell
git status --short
git --no-pager diff --stat
Get-Content .gitignore
python -m pytest tests/test_phase2b_tooling.py -q          # 27 passed
python -c "import json; ..."                                # schema/numeric extraction from all 5 result JSONs
```
All JSON parsing was read-only with `encoding='utf-8'`; no artifact was rewritten.

**No file was committed. No production code was modified. The only file written by this audit is `benchmarks/audit/completeness_audit.md`.**
