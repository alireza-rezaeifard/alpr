"""Phase 2B diagnostics — reviewable HTML with the prioritized case list (§13).

Each tile shows: full frame with both detector boxes (green = current
production, blue = IranPlate-Vision), the two crops enlarged, each OCR read,
the verified ground truth, and the crop-boundary sensitivity for that sample.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

import cv2  # noqa: E402

RESULTS = ROOT / "benchmarks" / "results"
DIAG = ROOT / "benchmarks" / "diagnostics" / "phase2b"

PRIORITY = [
    ("current_correct_iranplate_wrong", "Current correct, IranPlate-Vision wrong"),
    ("iranplate_correct_current_wrong", "IranPlate-Vision correct, current wrong"),
    ("both_wrong", "Both wrong"),
    ("clipped", "Clipping cases"),
    ("small_crop", "Small-crop cases (<100 px)"),
    ("cam2", "cam2 samples (UNLABELED)"),
    ("width_delta", "Large crop-width differences"),
]


def b64_img(img) -> str:
    ok, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def crop_from(frame, box):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(round(v)) for v in box[:4]]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    return frame[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else None


def main() -> None:
    DIAG.mkdir(parents=True, exist_ok=True)
    ab = json.loads((RESULTS / "phase2b_detector_crop_results.json").read_text(encoding="utf-8"))
    sens = json.loads((RESULTS / "phase2b_crop_sensitivity_results.json").read_text(encoding="utf-8"))
    pairs = json.loads((RESULTS / "phase2b_pairwise_results.json").read_text(encoding="utf-8"))

    # index A/B records by (camera, frame, detector)
    idx = {}
    for r in ab["records"]:
        if "ocr_text" in r:
            idx.setdefault((r["camera"], r["frame"], r["detector"]), []).append(r)

    # sensitivity: (detector, camera, frame) -> {convention: text}
    sflips = {}
    for f in sens["flips"]:
        sflips[(f["detector"], f["camera"], f["frame"])] = f["outputs"]

    cases = {name: [] for name, _ in PRIORITY}
    for (cam, frame, det), rows in idx.items():
        for det_name, other in (("current_detector", "iranplate_vision"),
                                ("iranplate_vision", "current_detector")):
            pass

    # classify per (camera, frame) using floor convention (the stricter one)
    for pair in pairs["pairs"]:
        if pair["outcome"] == "INCOMPARABLE":
            continue
        cam, frame = pair["camera"], pair["frame"]
        cur = idx.get((cam, frame, "current_detector"), [])
        ipv = idx.get((cam, frame, "iranplate_vision"), [])
        if not cur or not ipv:
            continue
        c, i = cur[0], ipv[0]
        entry = {"camera": cam, "frame": frame, "pair": pair,
                 "current": c, "iranplate": i}
        if pair["gt_status"] == "LABELED":
            if pair["outcome"] == "CURRENT_BETTER":
                cases["current_correct_iranplate_wrong"].append(entry)
            elif pair["outcome"] == "IRANPLATE_BETTER":
                cases["iranplate_correct_current_wrong"].append(entry)
            elif pair["outcome"] == "BOTH_WRONG":
                cases["both_wrong"].append(entry)
        if c.get("clipped_any") or i.get("clipped_any"):
            cases["clipped"].append(entry)
        if c["width"] < 100 or i["width"] < 100:
            cases["small_crop"].append(entry)
        if cam == "cam2.mp4":
            cases["cam2"].append(entry)
        if abs(pair.get("width_delta", 0)) >= 40:
            cases["width_delta"].append(entry)

    # regression cases coming from the crop convention (floor) — the 6 samples
    conv_regressions = []
    for (det, cam, frame), outputs in sflips.items():
        if det != "iranplate_vision":
            continue
        uniq = set(outputs.values())
        if len(uniq) > 1:
            conv_regressions.append({"camera": cam, "frame": frame,
                                     "outputs": outputs})
    cases["convention_sensitivity"] = conv_regressions

    tiles = []
    for name, title in PRIORITY:
        items = cases[name][:6]
        if not items:
            continue
        tiles.append(f"<h2>{title} <span class='n'>({len(cases[name])} samples, showing {len(items)})</span></h2>")
        for it in items:
            cam, frame = it["camera"], it["frame"]
            cap = cv2.VideoCapture(str(ROOT / cam))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
            ok, fr = cap.read()
            cap.release()
            if not ok:
                continue
            c, i = it["current"], it["iranplate"]
            frame_vis = fr.copy()
            cv2.rectangle(frame_vis, (int(c["x1"]), int(c["y1"])),
                          (int(c["x2"]), int(c["y2"])), (0, 200, 0), 3)
            cv2.putText(frame_vis, "current", (int(c["x1"]), int(c["y1"]) - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 0), 2)
            cv2.rectangle(frame_vis, (int(i["x1"]), int(i["y1"])),
                          (int(i["x2"]), int(i["y2"])), (255, 120, 0), 3)
            cv2.putText(frame_vis, "iranplate", (int(i["x1"]), int(i["y2"]) + 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 120, 0), 2)
            cc = crop_from(fr, [c["x1"], c["y1"], c["x2"], c["y2"]])
            ic = crop_from(fr, [i["x1"], i["y1"], i["x2"], i["y2"]])
            conv = sflips.get(("iranplate_vision", cam, frame), {})
            tiles.append(f"""
<div class="tile">
  <div class="head">{cam} — frame {frame} · gt: <b>{it['pair']['ground_truth'] or 'UNLABELED'}</b> · outcome: <b>{it['pair']['outcome']}</b></div>
  <img class="frame" src="{b64_img(frame_vis)}">
  <div class="row">
    <div><div class="lbl green">current {c['width']:.0f}×{c['height']:.0f} conf={c['confidence']:.2f}</div>
      <img class="crop" src="{b64_img(cc)}">
      <div class="ocr">OCR: <code>{c['ocr_text'] or '(empty)'}</code> {'' if c.get('exact') is None else ('✔' if c['exact'] else '✘')}</div></div>
    <div><div class="lbl blue">iranplate {i['width']:.0f}×{i['height']:.0f} conf={i['confidence']:.2f}</div>
      <img class="crop" src="{b64_img(ic)}">
      <div class="ocr">OCR: <code>{i['ocr_text'] or '(empty)'}</code> {'' if i.get('exact') is None else ('✔' if i['exact'] else '✘')}</div></div>
  </div>
  <div class="conv">iranplate crop-convention outputs: {json.dumps(conv, ensure_ascii=False)}</div>
</div>""")

    # convention sensitivity section (the §14 root cause)
    if conv_regressions:
        tiles.append("<h2>Crop-boundary sensitivity (root cause of the earlier cam1 regression) "
                     f"<span class='n'>({len(conv_regressions)} samples)</span></h2>")
        for cr in conv_regressions[:8]:
            cam, frame = cr["camera"], cr["frame"]
            cap = cv2.VideoCapture(str(ROOT / cam))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
            ok, fr = cap.read()
            cap.release()
            if not ok:
                continue
            i = idx.get((cam, frame, "iranplate_vision"), [None])[0]
            tile_imgs = ""
            for label, (x1, y1, x2, y2) in (("floor", (0, 0, 0, 0)),):
                pass
            # render both conventions' crops explicitly
            from run_phase2b_crop_sensitivity import crop_with
            boxes, _, _ = None, None, None
            # reuse the recorded box
            box = [i["x1"], i["y1"], i["x2"], i["y2"]]
            imgs = ""
            for conv_name in ("round", "floor"):
                cimg = crop_with(fr, box, conv_name)
                if cimg is None:
                    continue
                imgs += (f"<div><div class='lbl blue'>{conv_name} "
                         f"{cimg.shape[1]}×{cimg.shape[0]} → "
                         f"<code>{cr['outputs'].get(conv_name,'?')}</code></div>"
                         f"<img class='crop' src='{b64_img(cimg)}'></div>")
            tiles.append(f"""
<div class="tile"><div class="head">{cam} — frame {frame} — same IranPlate-Vision box, only crop edges differ</div>
<div class="row">{imgs}</div></div>""")

    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Phase 2B detector A/B diagnostics</title>
<style>
body{{background:#0e0e0e;color:#ddd;font-family:Consolas,monospace;margin:8px}}
h1{{font-size:16px}} h2{{font-size:14px;color:#ffd479;margin-top:18px;border-top:1px solid #333;padding-top:8px}}
.n{{color:#888;font-weight:normal}}
.tile{{background:#1b1b1b;border:1px solid #333;margin:10px 0;padding:10px;max-width:1100px}}
.head{{font-size:12px;color:#9fd}}
.frame{{width:100%;max-width:1080px;border:1px solid #444}}
.row{{display:flex;gap:14px;margin-top:8px;flex-wrap:wrap}}
.crop{{width:430px;image-rendering:pixelated;border:1px solid #555;display:block}}
.lbl{{font-size:11px}} .green{{color:#5dd65d}} .blue{{color:#7ab8ff}}
.ocr{{font-size:12px}} code{{color:#6f6}} .conv{{font-size:11px;color:#aaa;margin-top:6px}}
</style></head><body>
<h1>Phase 2B — Detector A/B visual diagnostics ({ab['methodology']['conf']} conf, identical OCR, every 5th frame)</h1>
{''.join(tiles)}
</body></html>"""
    out = DIAG / "ab_diagnostics.html"
    out.write_text(html, encoding="utf-8")

    (DIAG / "case_index.json").write_text(json.dumps(
        {k: len(v) for k, v in cases.items()}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"wrote {out}")
    print("case counts:", {k: len(v) for k, v in cases.items()})


if __name__ == "__main__":
    main()
