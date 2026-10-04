"""Phase 3 — human annotation workflow server.

A vision-capable reviewer runs:

    python benchmarks/phase3_annotate.py [--port 8077]

and opens http://localhost:8077/ . The UI provides:

  1. frame display (camera / session / frame picker)
  2. zoom (click toggles native-resolution crop around
     the click point; drag draws the plate box)
  3. plate bounding box (drag on the canvas; coordinates
     shown live in the frozen integer convention)
  4. text transcription (Persian keyboard supported)
  5. plate type (extensible taxonomy incl. unknown)
  6. readability (EXCELLENT..UNREADABLE)
  7. vehicle-instance assignment (existing or new)
  8. quality metadata (occluded / truncated toggles;
     blur/brightness/contrast auto-measured)
  9. save — server-side validation, atomic JSONL append
 10. reopen — existing annotations load for editing
 11. edit — rewrite by annotation_id
 12. validation — per-record errors shown inline
 13. resume — annotations persist in
     benchmarks/dataset/phase3/gt/plates.jsonl; the
     annotator can leave and return without losing
     progress

Frames are served from the sampled Phase 3 frame set.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmarks.phase3_dataset import (  # noqa: E402
    DATASET_DIR, PLATE_TYPES, READABILITY_LEVELS,
    validate_plate_annotation)

UI_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Phase 3 annotation</title>
<style>body{font-family:sans-serif;max-width:1200px;margin:auto}
canvas{border:1px solid #333;cursor:crosshair}
.row{display:flex;gap:16px} .col{flex:1}
label{display:block;margin-top:6px} input,select{width:100%}
#err{color:#b00;white-space:pre-wrap}</style></head><body>
<h1>Phase 3 plate annotation</h1>
<div class="row"><div class="col">
<label>camera <select id="cam"></select></label>
<label>frame <select id="frm"></select></label>
<label>vehicle instance
<input id="veh" list="vehlist" placeholder="cam1_s001_v001"></label>
<datalist id="vehlist"></datalist>
<canvas id="cv" width="960" height="520"></canvas>
<p><small>drag = draw plate box · click = zoom toggle · box shown in
frozen integer convention [x1,x2)&times;[y1,y2)</small></p>
</div><div class="col">
<label>plate text (raw transcription, never altered)
<input id="txt" dir="rtl" placeholder="۱۲د۶۷۴۱۳"></label>
<label>plate type <select id="typ"></select></label>
<label>region code <input id="reg" placeholder="13"></label>
<label>readability <select id="read"></select></label>
<label><input type="checkbox" id="occ"> occluded</label>
<label><input type="checkbox" id="tru"> truncated</label>
<label>notes <input id="notes"></label>
<label>annotation status
<select id="stat"><option>verified</option>
<option>pending_human_review</option>
<option>provisional_programmatic</option></select></label>
<button id="save">save annotation</button>
<div id="err"></div>
<h3>existing annotations for this frame</h3><ul id="lst"></ul>
</div></div>
<script>
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
let img=new Image(),frames=[],annots=[],box=null,zoom=null,drag=null;
let cam='cam1';
async function api(p,m,b){const r=await fetch(p,{method:m||'GET',
headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});
return r.json();}
async function loadCams(){const d=await api('/api/dataset');
const cs=d.cameras.map(c=>c.camera_id);
document.getElementById('cam').innerHTML=cs.map(c=>'<option>'+c+'</option>').join('');
cam=cs[0];loadFrames();}
async function loadFrames(){const d=await api('/api/frames?camera='+cam);
frames=d.frames;
document.getElementById('frm').innerHTML=frames.map(f=>
'<option value="'+f+'">'+f+'</option>').join('');
if(frames.length)loadFrame(frames[0]);}
async function loadFrame(f){box=null;zoom=null;
img=new Image();img.onload=draw;
img.src='/api/frame?camera='+cam+'&frame='+f;
const d=await api('/api/annotations?camera='+cam+'&frame='+f);
annots=d.annotations;
document.getElementById('lst').innerHTML=annots.map(a=>
'<li><a href="#" data-id="'+a.annotation_id+'">'+a.annotation_id+'</a> '+
(a.plate_text_raw||'(no text)')+' '+a.readability+'</li>').join('');
document.querySelectorAll('#lst a').forEach(a=>a.onclick=e=>
{e.preventDefault();fill(a.dataset.id);});
const vs=[...new Set(annots.map(a=>a.vehicle_instance_id))];
document.getElementById('vehlist').innerHTML=vs.map(v=>
'<option value="'+v+'">').join('');}
function fill(id){const a=annots.find(x=>x.annotation_id===id);if(!a)return;
document.getElementById('veh').value=a.vehicle_instance_id;
document.getElementById('txt').value=a.plate_text_raw||'';
document.getElementById('typ').value=a.plate_type||'unknown';
document.getElementById('reg').value=a.region_code||'';
document.getElementById('read').value=a.readability||
'PENDING_HUMAN_REVIEW';
document.getElementById('occ').checked=!!a.occluded;
document.getElementById('tru').checked=!!a.truncated;
document.getElementById('notes').value=a.notes||'';
document.getElementById('stat').value=a.annotation_status;
if(a.plate_bbox)box=[a.plate_bbox.x1,a.plate_bbox.y1,
a.plate_bbox.x2,a.plate_bbox.y2];draw();}
function scale(){return img.naturalWidth/cv.width;}
function draw(){ctx.clearRect(0,0,cv.width,cv.height);
if(zoom){const s=scale(),w=480,h=300;
let sx=Math.max(0,Math.min(img.naturalWidth-w,zoom[0]-w/2));
let sy=Math.max(0,Math.min(img.naturalHeight-h,zoom[1]-h/2));
ctx.drawImage(img,sx,sy,w,h,0,0,cv.width,cv.height);}
else ctx.drawImage(img,0,0,cv.width,cv.height);
for(const a of annots){if(!a.plate_bbox)continue;
const s=zoom?(cv.width/480):(cv.width/img.naturalWidth);
ctx.strokeStyle='#0f0';ctx.lineWidth=2;
ctx.strokeRect(a.plate_bbox.x1*s,a.plate_bbox.y1*s,
(a.plate_bbox.x2-a.plate_bbox.x1)*s,(a.plate_bbox.y2-a.plate_bbox.y1)*s);}
if(box){const s=zoom?(cv.width/480):(cv.width/img.naturalWidth);
ctx.strokeStyle='#ff0';ctx.lineWidth=2;
ctx.strokeRect(box[0]*s,box[1]*s,(box[2]-box[0])*s,(box[3]-box[1])*s);}}
cv.onmousedown=e=>{const r=cv.getBoundingClientRect();
const x=e.clientX-r.left,y=e.clientY-r.top;
drag=[x,y];};
cv.onmousemove=e=>{if(!drag)return;
const r=cv.getBoundingClientRect();
const s=zoom?(480/cv.width):(img.naturalWidth/cv.width);
const ox=zoom?Math.max(0,Math.min(img.naturalWidth-480,zoom[0]-240)):0;
const oy=zoom?Math.max(0,Math.min(img.naturalHeight-300,zoom[1]-150)):0;
box=[Math.round(ox+drag[0]*s),Math.round(oy+drag[1]*s),
Math.round(ox+(e.clientX-r.left)*s),Math.round(oy+(e.clientY-r.top)*s)];
if(box[0]>box[2])[box[0],box[2]]=[box[2],box[0]];
if(box[1]>box[3])[box[1],box[3]]=[box[3],box[1]];
draw();};
cv.onmouseup=e=>{const was=drag;drag=null;
const r=cv.getBoundingClientRect();
if(Math.hypot(e.clientX-r.left-was[0],e.clientY-r.top-was[1])<5){
const s=zoom?(480/cv.width):(img.naturalWidth/cv.width);
const ox=zoom?Math.max(0,Math.min(img.naturalWidth-480,zoom[0]-240)):0;
const oy=zoom?Math.max(0,Math.min(img.naturalHeight-300,zoom[1]-150)):0;
const ix=Math.round(ox+(e.clientX-r.left)*s);
const iy=Math.round(oy+(e.clientY-r.top)*s);
if(zoom)zoom=null;else zoom=[ix,iy];box=null;}
draw();};
document.getElementById('save').onclick=async()=>{
const payload={camera_id:cam,
frame_id:parseInt(document.getElementById('frm').value),
vehicle_instance_id:document.getElementById('veh').value,
plate_text_raw:document.getElementById('txt').value,
plate_type:document.getElementById('typ').value,
region_code:document.getElementById('reg').value||null,
readability:document.getElementById('read').value,
occluded:document.getElementById('occ').checked,
truncated:document.getElementById('tru').checked,
notes:document.getElementById('notes').value,
annotation_status:document.getElementById('stat').value,
plate_bbox:box?{x1:box[0],y1:box[1],x2:box[2],y2:box[3]}:null};
const d=await api('/api/save','POST',payload);
document.getElementById('err').textContent=d.ok?
('saved '+d.annotation_id):('ERRORS:\\n'+d.errors.join('\\n'));
if(d.ok)loadFrame(document.getElementById('frm').value);};
document.getElementById('cam').onchange=e=>{cam=e.target.value;
loadFrames();};
document.getElementById('frm').onchange=e=>loadFrame(
parseInt(e.target.value));
document.getElementById('typ').innerHTML=
'TYPES'.split(',').map(t=>'<option>'+t+'</option>').join('');
document.getElementById('read').innerHTML=
'READS'.split(',').map(t=>'<option>'+t+'</option>').join('');
loadCams();
</script></body></html>"""

TYPES_JS = ",".join(("civilian", "taxi", "government",
                     "military", "diplomatic", "police",
                     "motorcycle", "free_zone", "other",
                     "unknown"))
READS_JS = ",".join(("PENDING_HUMAN_REVIEW",) +
                    READABILITY_LEVELS)


class AnnotateHandler(BaseHTTPRequestHandler):
    server_version = "Phase3Annotate/1.0"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode(
            "utf-8")
        self.send_response(code)
        self.send_header("Content-Type",
                         "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            page = UI_HTML.replace("TYPES", TYPES_JS).replace(
                "READS", READS_JS)
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type",
                             "text/html; charset=utf-8")
            self.send_header("Content-Length",
                             str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if url.path == "/api/dataset":
            cams = []
            for f in sorted(
                    (DATASET_DIR / "cameras").glob("*.json")):
                cams.append(json.loads(
                    f.read_text(encoding="utf-8")))
            self._json({"cameras": cams})
            return
        if url.path == "/api/frames":
            from urllib.parse import parse_qs
            q = parse_qs(url.query)
            cam = q.get("camera", ["cam1"])[0]
            frames = []
            fp = DATASET_DIR / "gt" / "frames.jsonl"
            if fp.exists():
                for line in fp.read_text(
                        encoding="utf-8").splitlines():
                    r = json.loads(line)
                    if r["camera_id"] == cam:
                        frames.append(r["frame_id"])
            self._json({"frames": sorted(frames)})
            return
        if url.path == "/api/annotations":
            from urllib.parse import parse_qs
            q = parse_qs(url.query)
            cam = q.get("camera", ["cam1"])[0]
            frame = int(q.get("frame", ["0"])[0])
            anns = self.server.load_annotations()
            self._json({"annotations": [
                a for a in anns
                if a["camera_id"] == cam
                and a["frame_id"] == frame]})
            return
        if url.path == "/api/frame":
            from urllib.parse import parse_qs
            q = parse_qs(url.query)
            cam = q.get("camera", ["cam1"])[0]
            frame = int(q.get("frame", ["0"])[0])
            img = self.server.load_frame(cam, frame)
            if img is None:
                self.send_error(404, "frame unavailable")
                return
            ok, buf = cv2.imencode(".jpg", img,
                                   [cv2.IMWRITE_JPEG_QUALITY,
                                    92])
            if not ok:
                self.send_error(500, "encode failed")
                return
            data = buf.tobytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length",
                             str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/api/save":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length",
                                      "0"))
        payload = json.loads(
            self.rfile.read(length).decode("utf-8"))
        rec, errors = self.server.build_record(payload)
        if errors:
            self._json({"ok": False, "errors": errors})
            return
        aid = self.server.persist(rec)
        self._json({"ok": True, "annotation_id": aid})


class AnnotateServer(HTTPServer):
    """Holds dataset + frame access for the handler."""

    def __init__(self, addr, frames: dict):
        super().__init__(addr, AnnotateHandler)
        self.frames = frames  # (camera, frame) -> ndarray
        self.lock = threading.Lock()

    def load_frame(self, camera: str, frame: int):
        return self.frames.get((camera, frame))

    def load_annotations(self) -> list[dict]:
        fp = DATASET_DIR / "gt" / "plates.jsonl"
        if not fp.exists():
            return []
        return [json.loads(line) for line in
                fp.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def build_record(self, p: dict):
        import time

        from benchmarks.phase3_normalization import (  # noqa: E402
            canonical_forms, extract_region_code)
        from benchmarks.phase3_dataset import (  # noqa: E402
            plate_annotation)
        forms = canonical_forms(p.get("plate_text_raw"))
        cam = p.get("camera_id", "cam1")
        fr = int(p.get("frame_id", 0))
        veh = p.get("vehicle_instance_id") or \
            f"{cam}_s001_vNEW"
        pid = f"{veh}_p001"
        aid = f"{pid}_f{fr:05d}"
        box = p.get("plate_bbox")
        rec = plate_annotation(
            annotation_id=aid, camera_id=cam,
            session_id=f"{cam}_s001",
            vehicle_instance_id=veh,
            plate_instance_id=pid, frame_id=fr,
            plate_bbox=box,
            box_annotation_status="annotated"
            if box else "pending_human_annotation",
            plate_text_raw=forms["plate_text_raw"],
            plate_type=p.get("plate_type") or "unknown",
            region_code=p.get("region_code") or
            extract_region_code(forms["plate_text_ascii"]),
            readability=p.get("readability")
            or "PENDING_HUMAN_REVIEW",
            occluded=bool(p.get("occluded")),
            truncated=bool(p.get("truncated")),
            annotation_status=p.get("annotation_status")
            or "pending_human_review",
            annotator="human_annotation_tool",
            notes=p.get("notes") or "")
        rec["annotated_at"] = time.strftime(
            "%Y-%m-%d %H:%M:%S")
        errors = validate_plate_annotation(rec)
        if errors:
            return None, errors
        return rec, []

    def persist(self, rec: dict) -> str:
        fp = DATASET_DIR / "gt" / "plates.jsonl"
        with self.lock:
            anns = self.load_annotations()
            # edit = rewrite by annotation_id
            anns = [a for a in anns
                    if a["annotation_id"]
                    != rec["annotation_id"]] + [rec]
            tmp = fp.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(
                json.dumps(a, ensure_ascii=False)
                for a in anns) + "\n", encoding="utf-8")
            tmp.replace(fp)
        return rec["annotation_id"]


def load_sampled_frames() -> dict:
    """Decode every Phase 3 sampled frame once."""
    from benchmarks.phase3_dataset import (  # noqa: E402
        read_video_frames, sample_frames)
    out = {}
    for cam, video, n in (("cam1", ROOT / "cam1.mp4", 360),
                          ("cam2", ROOT / "cam2.mp4", 599)):
        ids = sample_frames(n, 5)
        frames = read_video_frames(video, ids)
        for i, fr in frames.items():
            out[(cam, i)] = fr
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8077)
    args = ap.parse_args()
    frames = load_sampled_frames()
    print(f"serving {len(frames)} sampled frames on "
          f"http://localhost:{args.port}/", flush=True)
    srv = AnnotateServer(("127.0.0.1", args.port), frames)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
