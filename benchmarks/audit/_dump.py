import json
d = json.load(open('benchmarks/audit/phase2c_recomputed.json', encoding='utf-8'))
L = []
for k in ("structure", "stored_vs_recomputed_diff", "stored_vs_recomputed_bucket_diff",
          "no_detection", "unlabeled", "labeled", "failed_predicate",
          "failed_dual_predicate", "frame_row_double_count",
          "row_composition_run0_canonical", "gt_structure",
          "repeatability_full", "paired_recomputed", "paired_stored",
          "trunc_vs_numpy_astype_int"):
    L.append("== " + k)
    L.append(json.dumps(d.get(k), indent=1, ensure_ascii=True))
L.append("== recomputed_summary_run0")
L.append(json.dumps(d["recomputed_summary_run0"], indent=1, ensure_ascii=True))
L.append("== recomputed_buckets_run0")
L.append(json.dumps(d["recomputed_buckets_run0"], indent=1, ensure_ascii=True))
L.append("== convention_matrix")
L.append(json.dumps(d["convention_matrix"], indent=1, ensure_ascii=True))
L.append("== convention_scores_stored")
L.append(json.dumps(d["convention_scores_stored"], indent=1, ensure_ascii=True))
L.append("== discordant_detail")
L.append(json.dumps(d["discordant_detail"], indent=1, ensure_ascii=True))
open('benchmarks/audit/_final_dump.txt', 'w', encoding='utf-8').write("\n".join(L))
print("ok")