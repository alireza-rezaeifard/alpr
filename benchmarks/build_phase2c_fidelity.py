"""Phase 2C — crop visual fidelity HTML (task §12).

For every verified sample: original frame with both detector boxes drawn,
both crops enlarged with their exact pixel coordinates, the ground truth and
both OCR reads. Samples where A and B differ are highlighted.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from phase2c_canonical import extract_plate_crop  # noqa: E402

RESULTS = ROOT / "benchmarks" / "results"
AUDIT = ROOT / "benchmarks" / "audit"
A, B = "detector_a_current", "detector_b_iranplate"


def b64(img) -> str:
    ok, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def frame_at(video, idx):
    cap = cv2.VideoCapture(str(ROOT / video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, fr = cap.read()
    cap.release()
    return fr if ok else None


def main() -> None:
    AUDIT.mkdir(parents=True, exist_ok=True)
    raw = json.loads((RESULTS / "phase2c_raw_results.json").read_text(encoding="utf-8"))
    conv = json.loads((RESULTS / "phase2c_summary.json").read_text(encoding="utf-8"))
    canon = conv["canonical_convention"]

    recs = [r for r in raw["records"] if r["run"] == "run0"
            and r["convention"] == canon and r["gt_status"] == "LABELED"]
    by = {}
    for r in recs:
        by.setdefault((r["camera"], r["frame"], r["detector"]), []).append(r)

    tiles, diff_frames, width_only = [], [], []
    for (cam, frame) in sorted({(c, f) for c, f, _ in by}):
        ra = by.get((cam, frame, A), [])
        rb = by.get((cam, frame, B), [])
        if not ra or not rb:
            continue
        a, b = ra[0], rb[0]
        ocr_differs = a["ocr_text"] != b["ocr_text"]
        outcome_differs = bool(a["exact"]) != bool(b["exact"])
        width_delta = (b["crop"]["crop_width"] - a["crop"]["crop_width"])
        differs = ocr_differs or outcome_differs
        if differs:
            diff_frames.append(f"{cam}@{frame}")
        elif width_delta:
            width_only.append(f"{cam}@{frame} ({width_delta:+d}px)")
        fr = frame_at(cam, frame)
        if fr is None:
            continue

        vis = fr.copy()
        for r, color in ((a, (60, 220, 60)), (b, (70, 140, 255))):
            x1, y1, x2, y2 = r["crop"]["x1_pixel"], r["crop"]["y1_pixel"], \
                             r["crop"]["x2_pixel"], r["crop"]["y2_pixel"]
            cv2.rectangle(vis, (x1, y1), (x2, y2), color, 3)
        vis = cv2.resize(vis, (1080, int(1080 * fr.shape[0] / fr.shape[1])))

        cells = []
        for r, label, cls in ((a, "Detector A (current)", "g"), (b, "Detector B (IranPlate)", "b")):
            crop, _ = extract_plate_crop(fr, r["bbox_float"], convention=canon)
            ok = "✔" if r["exact"] else ("✘" if r["exact"] is False else "N/A")
            c = r["crop"]
            coords = (f"({c['x1_pixel']},{c['y1_pixel']})-({c['x2_pixel']},{c['y2_pixel']}) "
                      f"{c['crop_width']}×{c['crop_height']}")
            img = (b64(cv2.resize(crop, (620, int(620 * crop.shape[0] / crop.shape[1]))))
                   if crop is not None else "(no crop)")
            cells.append(
                f"<div><div class='lbl {cls}'>{label} conf={r['confidence']:.3f}</div>"
                f"<img class='crop' src='{img}'><div class='co'>{coords}</div>"
                f"<div class='ocr'>OCR <code>{r['ocr_text'] or '(empty)'}</code> {ok} "
                f"· invalid={r['ocr_valid']} failed={r['failed']}</div></div>")

        tiles.append(f"""<div class="tile {'diff' if differs else ''}">
<div class="head">{cam} — frame {frame} — GT <code>{a['ground_truth']}</code>
{'— <b class="bad">A/B OCR DIFFERS</b>' if differs else f'— width Δ {width_delta:+d}px (same OCR)'}</div>
<img class="frame" src="{b64(vis)}">
<div class="row">{''.join(cells)}</div></div>""")

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Phase 2C crop fidelity</title><style>
body{{background:#0e0e0e;color:#ddd;font:13px Consolas,monospace;margin:10px}}
h1{{font-size:16px}} .tile{{background:#1b1b1b;border:1px solid #333;margin:10px 0;padding:10px;max-width:1120px}}
.tile.diff{{border-color:#ff6060;box-shadow:0 0 0 1px #ff6060 inset}}
.head{{font-size:12px;color:#9fd;margin-bottom:6px}}
.frame{{width:1080px;border:1px solid #444;display:block}}
.row{{display:flex;gap:16px;margin-top:8px;flex-wrap:wrap}}
.crop{{width:600px;image-rendering:pixelated;border:1px solid #555;display:block}}
.lbl{{font-size:12px}} .g{{color:#5dd65d}} .b{{color:#7ab8ff}} .bad{{color:#ff6060}}
.co{{font-size:11px;color:#aaa}} .ocr{{font-size:12px}} code{{color:#6f6}}
</style></head><body>
<h1>Phase 2C — crop fidelity ({len(tiles)} verified frames, canonical convention
= <b>{canon}</b>, identical inference params, identical OCR)</h1>
<p>green = Detector A, blue = Detector B. <b class="bad">{len(diff_frames)} frames</b>
where A and B produce different OCR output or different correctness;
{len(width_only)} frames differ only in crop width with identical OCR.</p>
{''.join(tiles)}</body></html>"""
    out = AUDIT / "phase2c_crop_fidelity.html"
    out.write_text(html, encoding="utf-8")
    (AUDIT / "phase2c_crop_fidelity_index.json").write_text(json.dumps(
        {"canonical_convention": canon, "frames_rendered": len(tiles),
         "frames_with_a_b_ocr_difference": diff_frames,
         "frames_with_width_difference_only": width_only},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out} ({len(tiles)} tiles, {len(diff_frames)} OCR-differing, "
          f"{len(width_only)} width-only)")


if __name__ == "__main__":
    main()