"""Phase 3.5 — human annotation workflow server.

A vision-capable reviewer runs:

    python benchmarks/phase3_annotate.py [--port 8077]
                                        [--camera cam2]
                                        [--annotator NAME]

and opens http://localhost:8077/ . CLI extras:

    --list-backups            list GT snapshots (§29)
    --restore-backup NAME     atomically restore a snapshot

The queue (`/api/queue`) prioritises frames (§21):
1 unannotated (UNLABELED) · 2 partially annotated
(IN_PROGRESS) · 3 invalid/inconsistent · 4 REJECTED ·
5 VERIFIED; staged Phase 2B cam2 samples first within a
class, then frame id.

UI features:
  * frame display + queue-ordered frame picker (jump)
  * zoom: fit / 100% / 200% / 400% buttons, mouse-wheel
    zoom anchored at the cursor, click outside the box
    toggles fit <-> 400% at the click point. Display-only:
    stored coordinates are never changed by zooming (§14).
  * plate bbox: drag = draw, drag inside = move, drag a
    corner = resize, button/Delete = delete, live
    coordinate readout (§13)
  * neighbouring sampled frames (-10/-5/+10/+20 frame
    strip) for cross-frame evidence — navigating changes
    the target frame explicitly; another frame's box is
    never copied onto the target (§15)
  * text transcription (raw, never altered), plate type,
    region, readability (six classes + definitions §5),
    uncertainty_reason (§17), occluded/truncated +
    occlusion_type (§18), notes, status (§26)
  * vehicle-instance panel: create/select, see frames per
    instance, duplicate-instance warning (§10/§11)
  * save — server-side §19/§20 validation, atomic JSONL
    rewrite, audit trail (created_at/updated_at/revision,
    §27); reopen/edit/resume from gt/plates.jsonl

Coordinate convention (frozen, §7): integer pixels; origin
top-left; x grows right, y grows down; box is
[x1,x2) x [y1,y2) — start-inclusive/end-exclusive, identical
to NumPy slicing and the Phase 2D crop semantics; x1<=x2,
y1<=y2, x1,y1 >= 0, x2 <= image_width, y2 <= image_height;
drag coordinates are rounded half-up to the nearest integer
(Math.round); pixel coordinates are canonical and no
normalized coordinates are stored. The UI never converts
between conventions.

Keyboard shortcuts (ignored while typing in a field):
A previous frame · D next frame · S save · R quick-set
readability GOOD (readable) · U quick-set UNREADABLE ·
N next unannotated · Delete remove the box.

Frames are served from the manifest-driven Phase 3 sampled
frame set (sessions/*.json), so a third camera added through
the dataset manifest is served without code changes (§22).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmarks.phase3_dataset import (  # noqa: E402
    DATASET_DIR, OCCLUSION_TYPES,
    PLATE_TYPES, READABILITY_DEFINITIONS, READABILITY_LEVELS,
    TRANSITIONAL_READABILITY, UNCERTAINTY_REASONS,
    build_annotation_queue,
    plate_annotation, queue_summary,
    validate_annotation_workflow, validate_plate_annotation)
from benchmarks.phase3_normalization import (  # noqa: E402
    canonical_forms, extract_region_code)

GT_PATH = DATASET_DIR / "gt" / "plates.jsonl"
BACKUP_DIR = DATASET_DIR / "backups"

# ------------------------------------------------------- backup (§29)
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def ensure_backup() -> str | None:
    """Content-addressed snapshot of the canonical GT. Idempotent:
    the same GT bytes are never backed up twice, so repeated
    server starts do not clutter the backup directory."""
    if not GT_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    sha = sha256_file(GT_PATH)
    dst = BACKUP_DIR / f"plates.{sha[:12]}.jsonl"
    if not dst.exists():
        tmp = dst.with_suffix(".tmp")
        tmp.write_bytes(GT_PATH.read_bytes())
        tmp.replace(dst)
    return dst.name


def list_backups() -> list[tuple[str, str]]:
    if not BACKUP_DIR.exists():
        return []
    out = []
    for p in sorted(BACKUP_DIR.glob("plates.*.jsonl")):
        out.append((p.name, sha256_file(p)))
    return out


def restore_backup(name: str) -> None:
    """Atomically restore one snapshot over the canonical GT."""
    if Path(name).name != name:
        print(f"invalid backup name: {name!r}")
        raise SystemExit(2)
    src = BACKUP_DIR / name
    if not src.is_file():
        print(f"backup not found: {name}")
        raise SystemExit(2)
    before = sha256_file(GT_PATH) if GT_PATH.exists() else None
    tmp = GT_PATH.with_suffix(".jsonl.restore.tmp")
    tmp.write_bytes(src.read_bytes())
    tmp.replace(GT_PATH)
    after = sha256_file(GT_PATH)
    print(f"restored {name}: {before} -> {after}")


# ------------------------------------------------------------- records
def load_camera_meta() -> dict:
    meta = {}
    for f in sorted((DATASET_DIR / "cameras").glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        meta[rec["camera_id"]] = rec
    return meta


def load_sampled_frames() -> dict:
    """Decode the sampled frames of EVERY session in the manifest
    (manifest-driven: cam1/cam2/cam3+ without code changes)."""
    from benchmarks.phase3_dataset import read_video_frames
    out = {}
    sess_dir = DATASET_DIR / "sessions"
    for sf in sorted(sess_dir.glob("*.json")):
        s = json.loads(sf.read_text(encoding="utf-8"))
        video = ROOT / s["source"]
        if not video.exists():
            print(f"WARNING: source video missing: {video} "
                  f"(session {s['session_id']})", flush=True)
            continue
        frames = read_video_frames(video, s["sampled_frames"])
        for i, fr in frames.items():
            out[(s["camera_id"], i)] = fr
    return out


# ----------------------------------------------------------------- UI
UI_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Phase 3 annotation</title>
<style>body{font-family:sans-serif;max-width:1300px;margin:auto}
canvas{border:1px solid #333;cursor:crosshair;background:#111}
.row{display:flex;gap:16px} .col{flex:1}
label{display:block;margin-top:6px} input,select{width:100%}
#err{color:#b00;white-space:pre-wrap}
#warn{color:#a60;white-space:pre-wrap}
#coord{font-family:monospace;font-size:12px}
#qs,#audit{font-size:12px;color:#333}
#readdefs li{margin-bottom:2px}
#nbr img{border:1px solid #888}
.small{font-size:12px;color:#444}
kbd{background:#eee;border:1px solid #bbb;border-radius:3px;padding:0 4px}
button{margin-top:4px}</style></head><body>
<h1>Phase 3 plate annotation</h1>
<div class="row"><div class="col">
<label>camera <select id="cam"></select></label>
<label>frame (queue order: unannotated &rarr; in-progress &rarr;
invalid &rarr; rejected &rarr; verified) <select id="frm"></select></label>
<div id="qs"></div>
<label>vehicle instance
<input id="veh" list="vehlist" placeholder="cam2_s001_v001"></label>
<datalist id="vehlist"></datalist>
<div id="warn"></div>
<canvas id="cv" width="960" height="520"></canvas>
<div>
<button id="zfit">fit</button>
<button id="z100">100%</button>
<button id="z200">200%</button>
<button id="z400">400%</button>
<button id="delbox">delete box</button>
</div>
<div id="coord">box: none (drag = draw plate box)</div>
<p class="small"><b>Box interaction:</b> drag on empty area =
draw · drag inside box = move · drag a corner = resize ·
click (no drag) = zoom toggle fit &harr; 400% at the point ·
mouse wheel = zoom at cursor. <b>Neighbouring frames</b>
(other evidence only — the annotation always belongs to the
selected target frame):</p>
<div id="nbr"></div>
</div><div class="col">
<label>plate text (raw transcription, never altered)
<input id="txt" dir="rtl" placeholder="۱۲د۶۷۴۱۳"></label>
<label>plate type <select id="typ"></select></label>
<label>region code <input id="reg" placeholder="13"></label>
<label>readability <select id="read"></select></label>
<ul id="readdefs" class="small"></ul>
<label>uncertainty reason (required for POOR / UNREADABLE /
INVALID_SAMPLE) <input id="unc" list="unclist"
placeholder="letter_ambiguous"></label>
<datalist id="unclist"></datalist>
<label><input type="checkbox" id="occ"> occluded</label>
<label><input type="checkbox" id="tru"> truncated</label>
<label>occlusion type <select id="oct"></select></label>
<label>notes <input id="notes"></label>
<label>annotation status
<select id="stat"></select></label>
<div class="small">UNLABELED = frame has no record yet (queue
state, never stored on a record) · IN_PROGRESS = work started
(includes staged pending_human_review /
provisional_programmatic) · VERIFIED = human-verified ·
REJECTED = explicitly rejected.</div>
<button id="save">save annotation</button>
<div id="err"></div>
<div id="audit"></div>
<h3>existing annotations for this frame</h3><ul id="lst"></ul>
<h3>instances of this camera (click = assign)</h3>
<div id="inst" class="small"></div>
</div></div>
<div class="small">
<b>Coordinate convention (frozen):</b> integer pixels; origin
top-left; x grows right, y grows down; box = [x1,x2)&times;[y1,y2)
start-inclusive / end-exclusive (NumPy-slicing semantics,
identical to the Phase 2D crop convention); x1&le;x2, y1&le;y2,
x1,y1&ge;0, x2&le;image_width, y2&le;image_height; drag corners
round half-up (Math.round); pixel coordinates are canonical —
no normalized coordinates stored; zooming never changes stored
coordinates. <b>Shortcuts</b> (ignored while typing):
<kbd>A</kbd> previous frame · <kbd>D</kbd> next frame ·
<kbd>S</kbd> save · <kbd>R</kbd> quick-set GOOD (readable) ·
<kbd>U</kbd> quick-set UNREADABLE · <kbd>N</kbd> next
unannotated · <kbd>Delete</kbd> remove box.
<b>POOR does not mean guess</b> — leave plate text empty and
record an uncertainty reason instead.
</div>
<script>
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
const READDEFS=__READDEFS__;
let img=new Image(),frames=[],queue=[],annots=[],instances=[],
    cam=__DEFAULTCAM__,box=null,curFrame=null,mode='fit',
    view={scale:1,ox:0,oy:0},drag=null;
async function api(p,m,b){const r=await fetch(p,{method:m||'GET',
headers:{'Content-Type':'application/json'},
body:b?JSON.stringify(b):undefined});return r.json();}
function fitScale(){const W=img.naturalWidth||1,
H=img.naturalHeight||1;return Math.min(cv.width/W,cv.height/H);}
function clampView(){const W=img.naturalWidth||1,
H=img.naturalHeight||1,vw=cv.width/view.scale,
vh=cv.height/view.scale;
view.ox=vw>=W?(W-vw)/2:Math.max(0,Math.min(W-vw,view.ox));
view.oy=vh>=H?(H-vh)/2:Math.max(0,Math.min(H-vh,view.oy));}
function applyView(s,ax,ay){ax=(ax==null)?cv.width/2:ax;
ay=(ay==null)?cv.height/2:ay;
const ix=view.ox+ax/view.scale,iy=view.oy+ay/view.scale;
view.scale=Math.max(0.05,Math.min(16,s));
view.ox=ix-ax/view.scale;view.oy=iy-ay/view.scale;
mode=Math.abs(view.scale-fitScale())<1e-6?'fit':'zoom';
clampView();draw();}
function fit(){applyView(fitScale());}
function draw(){const W=img.naturalWidth||1,H=img.naturalHeight||1;
ctx.setTransform(1,0,0,1,0,0);
ctx.clearRect(0,0,cv.width,cv.height);
ctx.fillStyle='#111';ctx.fillRect(0,0,cv.width,cv.height);
ctx.imageSmoothingEnabled=view.scale<4;
ctx.setTransform(view.scale,0,0,view.scale,
                 -view.ox*view.scale,-view.oy*view.scale);
ctx.drawImage(img,0,0,W,H);
ctx.lineWidth=1/view.scale;
for(const a of annots){if(!a.plate_bbox)continue;
ctx.strokeStyle='#0f0';
ctx.strokeRect(a.plate_bbox.x1,a.plate_bbox.y1,
a.plate_bbox.x2-a.plate_bbox.x1,
a.plate_bbox.y2-a.plate_bbox.y1);}
if(box){ctx.strokeStyle='#ff0';
ctx.strokeRect(box[0],box[1],box[2]-box[0],box[3]-box[1]);}
ctx.setTransform(1,0,0,1,0,0);}
function s2i(sx,sy){return [view.ox+sx/view.scale,
view.oy+sy/view.scale];}
function coord(cur){const el=document.getElementById('coord');
let t=box?('box [x1,x2)x[y1,y2) = ['+box[0]+','+box[2]+')x['+
box[1]+','+box[3]+')  w='+(box[2]-box[0])+
' h='+(box[3]-box[1])):'box: none (drag = draw plate box)';
if(cur)t+='   cursor '+cur[0]+','+cur[1];
el.textContent=t;}
async function loadCams(){const d=await api('/api/dataset');
const cs=d.cameras.map(c=>c.camera_id);
document.getElementById('cam').innerHTML=
cs.map(c=>'<option>'+c+'</option>').join('');
if(!cs.includes(cam))cam=cs[0];
document.getElementById('cam').value=cam;loadFrames();}
async function loadFrames(){const d=await api('/api/frames?camera='+
cam);frames=d.frames;loadInstances();loadQueue(false);}
async function loadQueue(keep){const d=await api('/api/queue?camera='+
cam);queue=d.queue||[];
const sel=document.getElementById('frm');
sel.innerHTML=queue.map((e,i)=>'<option value="'+e.frame_id+'">#'+
(i+1)+' f'+String(e.frame_id).padStart(5,'0')+' ['+e.status+
(e.valid?'':' INVALID')+(e.phase2b_sample?' STAGED':'')+
']</option>').join('');
const s=d.summary||{};
document.getElementById('qs').textContent='queue: UNLABELED '+
(s.UNLABELED||0)+' · IN_PROGRESS '+(s.IN_PROGRESS||0)+
' · VERIFIED '+(s.VERIFIED||0)+' · REJECTED '+(s.REJECTED||0)+
' · invalid '+(s.invalid||0);
if(keep&&curFrame!=null&&queue.some(q=>q.frame_id===curFrame)){
sel.value=String(curFrame);}
else if(queue.length)loadFrame(queue[0].frame_id);}
async function loadInstances(){const d=await api('/api/instances?camera='+
cam);instances=d.instances||[];
const el=document.getElementById('inst');
el.innerHTML=instances.map(v=>'<div><a href="#" data-v="'+
v.vehicle_instance_id+'" data-f="'+v.first_frame+'">'+
v.vehicle_instance_id+'</a> — '+v.n_annotations+
' frames: '+v.frames.slice(0,14).join(',')+
(v.frames.length>14?'…':'')+'</div>').join('');
el.querySelectorAll('a').forEach(a=>a.onclick=e=>{e.preventDefault();
document.getElementById('veh').value=a.dataset.v;
if(queue.some(q=>q.frame_id===+a.dataset.f))
loadFrame(+a.dataset.f);warnDup();});}
function warnDup(){const w=document.getElementById('warn');
w.textContent='';const v=document.getElementById('veh').value.trim();
if(!v)return;
if(instances.some(i=>i.vehicle_instance_id===v))return;
const i=frames.indexOf(curFrame);const near=new Set();
for(const off of [-4,-2,-1,1,2,4]){const j=i+off;
if(j>=0&&j<frames.length)near.add(frames[j]);}
for(const inst of instances){
if(inst.frames.some(f=>near.has(f))){
w.textContent='possible duplicate instance: neighbouring '+
'frames belong to '+inst.vehicle_instance_id+
' — confirm this is a different physical vehicle before saving';
return;}}}
async function loadFrame(f){curFrame=f;box=null;
document.getElementById('frm').value=String(f);
img=new Image();img.onload=()=>{fit();};
img.src='/api/frame?camera='+cam+'&frame='+f;
const d=await api('/api/annotations?camera='+cam+'&frame='+f);
annots=d.annotations;
document.getElementById('lst').innerHTML=annots.map(a=>
'<li><a href="#" data-id="'+a.annotation_id+'">'+
a.annotation_id+'</a> '+(a.plate_text_raw||'(no text)')+' '+
a.readability+' '+a.annotation_status+'</li>').join('');
document.querySelectorAll('#lst a').forEach(a=>a.onclick=e=>{
e.preventDefault();fill(a.dataset.id);});
const vs=[...new Set(annots.map(a=>a.vehicle_instance_id))];
document.getElementById('vehlist').innerHTML=vs.map(v=>
'<option value="'+v+'">').join('');
renderNeighbors();warnDup();coord();draw();}
function renderNeighbors(){const i=frames.indexOf(curFrame);
const el=document.getElementById('nbr');let html='';
for(const off of [-4,-2,-1,1,2,4]){const j=i+off;
if(j<0||j>=frames.length)continue;const f=frames[j];
html+='<a href="#" data-f="'+f+'"><img src="/api/frame?camera='+
cam+'&frame='+f+'" width="110" loading="lazy"><br>f'+f+'</a> ';}
el.innerHTML=html;
el.querySelectorAll('a').forEach(a=>a.onclick=e=>{
e.preventDefault();loadFrame(+a.dataset.f);});}
function fill(id){const a=annots.find(x=>x.annotation_id===id);
if(!a)return;
document.getElementById('veh').value=a.vehicle_instance_id;
document.getElementById('txt').value=a.plate_text_raw||'';
document.getElementById('typ').value=a.plate_type||'unknown';
document.getElementById('reg').value=a.region_code||'';
document.getElementById('read').value=a.readability||'';
document.getElementById('occ').checked=!!a.occluded;
document.getElementById('tru').checked=!!a.truncated;
document.getElementById('oct').value=a.occlusion_type||'none';
document.getElementById('unc').value=a.uncertainty_reason||'';
document.getElementById('notes').value=a.notes||'';
document.getElementById('stat').value=a.annotation_status;
document.getElementById('audit').textContent='revision '+
(a.revision||1)+' · created '+
(a.created_at||a.annotated_at||'—')+' · updated '+
(a.updated_at||a.annotated_at||'—');
if(a.plate_bbox)box=[a.plate_bbox.x1,a.plate_bbox.y1,
a.plate_bbox.x2,a.plate_bbox.y2];
warnDup();draw();coord();}
async function save(){const payload={camera_id:cam,
frame_id:parseInt(document.getElementById('frm').value),
vehicle_instance_id:document.getElementById('veh').value,
plate_text_raw:document.getElementById('txt').value,
plate_type:document.getElementById('typ').value,
region_code:document.getElementById('reg').value||null,
readability:document.getElementById('read').value,
occluded:document.getElementById('occ').checked,
truncated:document.getElementById('tru').checked,
occlusion_type:document.getElementById('oct').value,
uncertainty_reason:document.getElementById('unc').value,
notes:document.getElementById('notes').value,
annotation_status:document.getElementById('stat').value,
plate_bbox:box?{x1:box[0],y1:box[1],x2:box[2],
y2:box[3]}:null};
const d=await api('/api/save','POST',payload);
document.getElementById('err').textContent=d.ok?
('saved '+d.annotation_id+' (rev '+(d.revision||1)+')'):
('ERRORS:\\n'+(d.errors||[]).join('\\n'));
await loadQueue(true);await loadInstances();
if(d.ok)loadFrame(curFrame);}
function nav(delta){const i=document.getElementById('frm').selectedIndex;
const j=Math.max(0,Math.min(queue.length-1,i+delta));
if(queue[j])loadFrame(queue[j].frame_id);}
function nextUnannotated(){const e=queue.find(q=>
q.status==='UNLABELED');
if(e)loadFrame(e.frame_id);
else document.getElementById('err').textContent=
'no unannotated frames left in this queue';}
document.addEventListener('keydown',e=>{const t=e.target.tagName;
if(t==='INPUT'||t==='SELECT'||t==='TEXTAREA')return;
const k=e.key.toLowerCase();
if(k==='a')nav(-1);else if(k==='d')nav(1);
else if(k==='s'){e.preventDefault();save();}
else if(k==='r')document.getElementById('read').value='GOOD';
else if(k==='u')document.getElementById('read').value='UNREADABLE';
else if(k==='n')nextUnannotated();
else if(k==='delete'||k==='backspace'){if(box){e.preventDefault();
box=null;draw();coord();}}});
cv.onmousedown=e=>{const r=cv.getBoundingClientRect();
const sx=e.clientX-r.left,sy=e.clientY-r.top;
if(box){const bx=(box[0]-view.ox)*view.scale,
by=(box[1]-view.oy)*view.scale,
bX=(box[2]-view.ox)*view.scale,
bY=(box[3]-view.oy)*view.scale,th=12;
const cs=[[bx,by,'nw'],[bX,by,'ne'],[bx,bY,'sw'],
[bX,bY,'se']];
for(const c of cs){if(Math.hypot(sx-c[0],sy-c[1])<=th){
drag={type:'resize',c:c[2],sx,sy,orig:box.slice()};return;}}
if(sx>=bx&&sx<=bX&&sy>=by&&sy<=bY){
drag={type:'move',sx,sy,orig:box.slice()};return;}}
drag={type:'new',sx,sy,moved:false};};
cv.onmousemove=e=>{const r=cv.getBoundingClientRect();
const sx=e.clientX-r.left,sy=e.clientY-r.top;
const p=s2i(sx,sy);
if(!drag){coord([Math.round(p[0]),Math.round(p[1])]);return;}
if(drag.type==='new'){
drag.moved=drag.moved||Math.hypot(sx-drag.sx,sy-drag.sy)>=5;
const a=s2i(drag.sx,drag.sy);
box=[Math.round(Math.min(a[0],p[0])),
Math.round(Math.min(a[1],p[1])),
Math.round(Math.max(a[0],p[0])),
Math.round(Math.max(a[1],p[1]))];}
else if(drag.type==='move'){
const dx=Math.round((sx-drag.sx)/view.scale),
dy=Math.round((sy-drag.sy)/view.scale),
W=img.naturalWidth,H=img.naturalHeight,
w=drag.orig[2]-drag.orig[0],h=drag.orig[3]-drag.orig[1];
const x1=Math.max(0,Math.min(W-w,drag.orig[0]+dx)),
y1=Math.max(0,Math.min(H-h,drag.orig[1]+dy));
box=[x1,y1,x1+w,y1+h];}
else if(drag.type==='resize'){
const o=drag.orig;
const fixed={'nw':[o[2],o[3]],'ne':[o[0],o[3]],
'sw':[o[2],o[1]],'se':[o[0],o[1]]}[drag.c];
const mx=Math.max(0,Math.min(img.naturalWidth,Math.round(p[0]))),
my=Math.max(0,Math.min(img.naturalHeight,Math.round(p[1])));
box=[Math.min(fixed[0],mx),Math.min(fixed[1],my),
Math.max(fixed[0],mx),Math.max(fixed[1],my)];}
draw();coord([Math.round(p[0]),Math.round(p[1])]);};
cv.onmouseup=e=>{const d=drag;drag=null;if(!d)return;
if(d.type==='new'&&!d.moved){const r=cv.getBoundingClientRect();
const sx=e.clientX-r.left,sy=e.clientY-r.top;
if(mode==='fit')applyView(4,sx,sy);else fit();}
draw();};
cv.addEventListener('wheel',e=>{e.preventDefault();
const r=cv.getBoundingClientRect();
applyView(view.scale*(e.deltaY<0?1.25:0.8),
e.clientX-r.left,e.clientY-r.top);},{passive:false});
document.getElementById('zfit').onclick=fit;
document.getElementById('z100').onclick=()=>applyView(1);
document.getElementById('z200').onclick=()=>applyView(2);
document.getElementById('z400').onclick=()=>applyView(4);
document.getElementById('delbox').onclick=()=>{box=null;
draw();coord();};
document.getElementById('save').onclick=save;
document.getElementById('cam').onchange=e=>{cam=e.target.value;
loadFrames();};
document.getElementById('frm').onchange=e=>loadFrame(
parseInt(e.target.value));
document.getElementById('veh').onchange=warnDup;
document.getElementById('typ').innerHTML='__TYPES__'.split(',')
.map(t=>'<option>'+t+'</option>').join('');
document.getElementById('read').innerHTML='<option value="">'+
'-- select --</option>'+'__READS__'.split(',')
.map(t=>'<option>'+t+'</option>').join('');
document.getElementById('stat').innerHTML='__STATUSES__'
.split(',').map(s=>{const p=s.split('|');
return '<option value="'+p[0]+'">'+p[1]+'</option>';}).join('');
document.getElementById('oct').innerHTML='__OCCTYPES__'.split(',')
.map(t=>'<option>'+t+'</option>').join('');
document.getElementById('unclist').innerHTML='__UNCERTS__'
.split(',').map(t=>'<option value="'+t+'">').join('');
document.getElementById('readdefs').innerHTML=
Object.entries(READDEFS).map(([k,v])=>'<li><b>'+k+
'</b> — '+v+'</li>').join('')+
'<li><b>PENDING_HUMAN_REVIEW</b> — transitional value on '+
'staged records; not one of the six annotation classes</li>';
loadCams();
</script></body></html>"""

TYPES_JS = ",".join(PLATE_TYPES)
READS_JS = ",".join(READABILITY_LEVELS
                    + (TRANSITIONAL_READABILITY,))
OCCTYPES_JS = ",".join(OCCLUSION_TYPES)
UNCERTS_JS = ",".join(UNCERTAINTY_REASONS)
STATUS_LABELS = (
    ("in_progress", "IN_PROGRESS"),
    ("verified", "VERIFIED"),
    ("rejected", "REJECTED"),
    ("pending_human_review", "PENDING_HUMAN_REVIEW (staged)"),
    ("provisional_programmatic",
     "PROVISIONAL_PROGRAMMATIC (staged)"),
)
STATUS_JS = ",".join(f"{s}|{l}" for s, l in STATUS_LABELS)


class AnnotateHandler(BaseHTTPRequestHandler):
    server_version = "Phase3Annotate/1.1"

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

    def _render_ui(self):
        page = UI_HTML
        page = page.replace("__TYPES__", TYPES_JS)
        page = page.replace("__READS__", READS_JS)
        page = page.replace("__STATUSES__", STATUS_JS)
        page = page.replace("__OCCTYPES__", OCCTYPES_JS)
        page = page.replace("__UNCERTS__", UNCERTS_JS)
        page = page.replace("__READDEFS__", json.dumps(
            READABILITY_DEFINITIONS, ensure_ascii=False))
        page = page.replace("__DEFAULTCAM__", json.dumps(
            getattr(self.server, "default_camera", "") or ""))
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type",
                         "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self._render_ui()
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
            q = self._query()
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
        if url.path == "/api/queue":
            q = self._query()
            cam = q.get("camera", ["cam1"])[0]
            ids = []
            fp = DATASET_DIR / "gt" / "frames.jsonl"
            if fp.exists():
                for line in fp.read_text(
                        encoding="utf-8").splitlines():
                    r = json.loads(line)
                    if r["camera_id"] == cam:
                        ids.append(r["frame_id"])
            anns = self.server.load_annotations()
            entries = build_annotation_queue(anns, ids, cam)
            self._json({"queue": entries,
                        "summary": queue_summary(entries)})
            return
        if url.path == "/api/instances":
            q = self._query()
            cam = q.get("camera", ["cam1"])[0]
            anns = self.server.load_annotations()
            inst = {}
            for a in anns:
                if a["camera_id"] != cam:
                    continue
                vid = a["vehicle_instance_id"]
                d = inst.setdefault(vid, {
                    "vehicle_instance_id": vid,
                    "frames": set(),
                    "plate_instances": set(),
                    "statuses": set(), "n_annotations": 0})
                d["frames"].add(a["frame_id"])
                d["plate_instances"].add(
                    a["plate_instance_id"])
                d["statuses"].add(a["annotation_status"])
                d["n_annotations"] += 1
            out = []
            for vid, d in inst.items():
                frames = sorted(d["frames"])
                out.append({
                    "vehicle_instance_id": vid,
                    "first_frame": frames[0] if frames else None,
                    "frames": frames,
                    "plate_instances":
                        sorted(d["plate_instances"]),
                    "statuses": sorted(d["statuses"]),
                    "n_annotations": d["n_annotations"]})
            out.sort(key=lambda v: (v["first_frame"]
                                    if v["first_frame"] is not None
                                    else 1 << 30))
            self._json({"instances": out})
            return
        if url.path == "/api/annotations":
            q = self._query()
            cam = q.get("camera", ["cam1"])[0]
            frame = int(q.get("frame", ["0"])[0])
            anns = self.server.load_annotations()
            self._json({"annotations": [
                a for a in anns
                if a["camera_id"] == cam
                and a["frame_id"] == frame]})
            return
        if url.path == "/api/frame":
            q = self._query()
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
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(
            self.rfile.read(length).decode("utf-8"))
        rec, errors = self.server.build_record(payload)
        if errors:
            self._json({"ok": False, "errors": errors})
            return
        aid = self.server.persist(rec)
        self._json({"ok": True, "annotation_id": aid,
                    "revision": rec.get("revision", 1)})


class AnnotateServer(HTTPServer):
    """Holds dataset + frame access for the handler."""

    def __init__(self, addr, frames: dict,
                 annotator: str = "human_annotation_tool",
                 default_camera: str | None = None):
        super().__init__(addr, AnnotateHandler)
        self.frames = frames  # (camera, frame) -> ndarray
        self.lock = threading.Lock()
        self.annotator = annotator
        self.default_camera = default_camera
        self.camera_meta = load_camera_meta()

    def load_frame(self, camera: str, frame: int):
        return self.frames.get((camera, frame))

    def load_annotations(self) -> list[dict]:
        if not GT_PATH.exists():
            return []
        return [json.loads(line) for line in
                GT_PATH.read_text(encoding="utf-8")
                .splitlines() if line.strip()]

    def build_record(self, p: dict):
        cam = p.get("camera_id", "cam1")
        fr = int(p.get("frame_id", 0))
        veh = p.get("vehicle_instance_id") or \
            f"{cam}_s001_vNEW"
        pid = f"{veh}_p001"
        aid = f"{pid}_f{fr:05d}"
        box = p.get("plate_bbox")
        status = p.get("annotation_status") or "in_progress"
        # A human save must pick one of the six classes to be
        # verified; non-verified work-in-progress keeps an
        # explicit transitional value (never inferred).
        rb = p.get("readability") or (
            "" if status == "verified"
            else TRANSITIONAL_READABILITY)
        meta = self.camera_meta.get(cam) or {}
        existing = next(
            (a for a in self.load_annotations()
             if a["annotation_id"] == aid), None)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        forms = canonical_forms(p.get("plate_text_raw"))
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
            readability=rb,
            occluded=bool(p.get("occluded")),
            truncated=bool(p.get("truncated")),
            annotation_status=status,
            annotator=p.get("annotator") or self.annotator,
            notes=p.get("notes") or "")
        # optional Phase 3.5 fields (§17/§18) + image bounds
        # for the out-of-frame bbox check (§20) + audit trail
        # (§27: created_at / updated_at / revision; no PII).
        rec["uncertainty_reason"] = str(
            p.get("uncertainty_reason") or "").strip()
        if p.get("occlusion_type"):
            rec["occlusion_type"] = p["occlusion_type"]
        if meta.get("width"):
            rec["image_width"] = int(meta["width"])
        if meta.get("height"):
            rec["image_height"] = int(meta["height"])
        rec["annotated_at"] = now
        rec["created_at"] = (
            (existing.get("created_at")
             or existing.get("annotated_at") or now)
            if existing else now)
        rec["updated_at"] = now
        rec["revision"] = (
            (existing.get("revision") or 0) + 1
            if existing else 1)
        errors = validate_plate_annotation(rec) + \
            validate_annotation_workflow(rec)
        if errors:
            return None, errors
        return rec, []

    def persist(self, rec: dict) -> str:
        with self.lock:
            anns = self.load_annotations()
            # edit = rewrite by annotation_id
            anns = [a for a in anns
                    if a["annotation_id"]
                    != rec["annotation_id"]] + [rec]
            tmp = GT_PATH.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(
                json.dumps(a, ensure_ascii=False)
                for a in anns) + "\n", encoding="utf-8")
            tmp.replace(GT_PATH)
        return rec["annotation_id"]


def main():
    ap = argparse.ArgumentParser(
        description="Phase 3 human annotation server")
    ap.add_argument("--port", type=int, default=8077)
    ap.add_argument("--camera", default=None,
                    help="initial camera queue, e.g. cam2 "
                         "(default: first camera in the "
                         "dataset manifest)")
    ap.add_argument("--annotator",
                    default="human_annotation_tool",
                    help="simple annotator identifier stored "
                         "on saved records (no PII)")
    ap.add_argument("--list-backups", action="store_true",
                    help="list GT snapshots and exit")
    ap.add_argument("--restore-backup", metavar="NAME",
                    default=None,
                    help="restore a GT snapshot atomically "
                         "and exit")
    args = ap.parse_args()
    if args.list_backups:
        entries = list_backups()
        if not entries:
            print("no backups found "
                  f"({BACKUP_DIR})")
        for name, sha in entries:
            print(f"{name}  sha256={sha}")
        return
    if args.restore_backup:
        restore_backup(args.restore_backup)
        return
    backup = ensure_backup()
    print(f"GT backup: {backup}", flush=True)
    frames = load_sampled_frames()
    cams = sorted({c for c, _ in frames})
    print(f"serving {len(frames)} sampled frames "
          f"({', '.join(cams)}) on "
          f"http://localhost:{args.port}/", flush=True)
    if args.camera and args.camera not in cams:
        print(f"WARNING: camera {args.camera!r} not in "
              f"dataset manifest; falling back to first "
              f"camera", flush=True)
    srv = AnnotateServer(("127.0.0.1", args.port), frames,
                         annotator=args.annotator,
                         default_camera=args.camera)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
