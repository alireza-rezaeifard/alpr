"""Builds benchmarks/dataset/review_sheet.html — a contact sheet of ALL crops
for manual ground-truth review (task: verified GT workflow).

Each tile shows the crop (4x enlarged, nearest-neighbor to preserve detail),
its id, source video/frame, production OCR string, and an editable GT field.
Review in a browser; the resulting labels go into ground_truth.jsonl via
apply_ground_truth.py or direct editing.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "benchmarks" / "dataset"


def b64(path: Path) -> str:
    data = path.read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode()


def main() -> None:
    meta = [json.loads(l) for l in open(DATASET / "metadata.jsonl",
                                        encoding="utf-8")]
    rows = []
    for m in meta:
        crop = DATASET / m["crop_path"]
        img = b64(crop) if crop.exists() else ""
        q = m["quality"]
        rows.append(f"""
<div class="tile" id="{m['id']}">
  <img src="{img}" class="zoom"><img src="{img}" class="orig">
  <div class="info">
    <b>{m['id']}</b><br>
    {m['source_video']} @ f{m['frame']} ({m['time_s']}s)<br>
    prod OCR: <code>{m['production_ocr_raw']}</code> (conf {m['production_confidence']})<br>
    {q['width']}x{q['height']} blur={q['blur_score']} bright={q['brightness']}
  </div>
</div>""")
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>ALPR GT review — {len(meta)} crops</title>
<style>
body {{ background:#111; color:#ddd; font-family:Consolas,monospace; }}
.tile {{ display:inline-block; margin:8px; padding:8px; background:#1c1c1c;
        border:1px solid #333; vertical-align:top; width:460px; }}
.zoom {{ image-rendering:pixelated; width:440px; }}
.orig {{ width:110px; margin-top:4px; image-rendering:pixelated; }}
code {{ color:#6f6; }}
h1 {{ font-size:16px; }}
</style></head><body>
<h1>ALPR ground-truth review sheet — {len(meta)} crops (read each plate, record text in ground_truth.jsonl)</h1>
{''.join(rows)}
</body></html>"""
    out = DATASET / "review_sheet.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(meta)} tiles)")


if __name__ == "__main__":
    main()
