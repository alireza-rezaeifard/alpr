import json
from pathlib import Path
p = Path(r"D:\alpr\benchmarks\dataset\gt_labels.json")
d = json.loads(p.read_text(encoding="utf-8"))
for k, v in d.get("labels", {}).items():
    print(k, json.dumps({kk: vv for kk, vv in v.items() if kk != "applies_to"}, ensure_ascii=True)[:400])
    print("   applies_to:", json.dumps(v.get("applies_to"), ensure_ascii=True)[:300])
print("TOPKEYS", list(d.keys()))
for k in d:
    if k != "labels":
        print(k, json.dumps(d[k], ensure_ascii=False)[:500])