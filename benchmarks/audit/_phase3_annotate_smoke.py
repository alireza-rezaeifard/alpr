"""End-to-end smoke test for the Phase 3
annotation server (benchmarks/phase3_annotate.py).

Starts the server in a subprocess, exercises every
endpoint, verifies save/edit/validation behavior,
then restores gt/plates.jsonl to its pre-test hash.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8077"
GT = "benchmarks/dataset/phase3/gt/plates.jsonl"


def get(path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(
                BASE + path, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post(path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type":
                 "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(
                req, timeout=30) as r:
            return r.status, json.loads(
                r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(
            e.read().decode("utf-8"))


def sha_file(p: str) -> str:
    return hashlib.sha256(
        open(p, "rb").read()).hexdigest()


def main() -> int:
    before = sha_file(GT)
    n_before = len([ln for ln in open(
        GT, encoding="utf-8").read().splitlines()
        if ln.strip()])
    proc = subprocess.Popen(
        [sys.executable, "benchmarks/phase3_annotate.py",
         "--port", "8077"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(120):
            try:
                get("/")
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("FAIL: server never came up")
            return 1
        checks = []

        st, body = get("/")
        html = body.decode("utf-8")
        checks.append(("GET / UI",
                       st == 200
                       and "civilian" in html
                       and "PENDING_HUMAN_REVIEW"
                       in html
                       and "plate_bbox" in html))

        st, body = get("/api/dataset")
        cams = json.loads(body)["cameras"]
        checks.append((
            "GET /api/dataset",
            st == 200
            and {c["camera_id"] for c in cams}
            == {"cam1", "cam2"}))

        st, body = get("/api/frames?camera=cam1")
        fr1 = json.loads(body)["frames"]
        st2, body2 = get("/api/frames?camera=cam2")
        fr2 = json.loads(body2)["frames"]
        checks.append((
            "GET /api/frames",
            st == 200 and len(fr1) == 72
            and len(fr2) == 120))

        st, body = get(
            "/api/annotations?camera=cam1&frame=0")
        anns = json.loads(body)["annotations"]
        checks.append((
            "GET /api/annotations (frame 0 has "
            "plate A)",
            st == 200
            and any(a["plate_text_ascii"] == "28Y68923"
                    for a in anns)))

        st, body = get("/api/frame?camera=cam1&frame=0")
        checks.append((
            "GET /api/frame (JPEG bytes)",
            st == 200 and len(body) > 10000
            and body[:3] == b"\xff\xd8\xff"))

        test_payload = {
            "camera_id": "cam1", "frame_id": 10,
            "vehicle_instance_id":
                "cam1_s001_vSMOKE",
            "plate_text_raw": "۳۷ت۹۲۱۵۸",
            "plate_type": "taxi", "region_code": "73",
            "readability": "EXCELLENT",
            "occluded": False, "truncated": False,
            "notes": "smoke test record",
            "annotation_status": "verified",
            "plate_bbox": {"x1": 100, "y1": 200,
                           "x2": 300, "y2": 260}}
        st, out = post("/api/save", test_payload)
        aid = out.get("annotation_id")
        checks.append(("POST /api/save (valid)",
                       st == 200 and out.get("ok")
                       and aid ==
                       "cam1_s001_vSMOKE_p001_f00010"))

        st, body = get(
            "/api/annotations?camera=cam1&frame=10")
        found = [a for a in
                 json.loads(body)["annotations"]
                 if a["annotation_id"] == aid]
        checks.append((
            "save persisted (resume from disk)",
            st == 200 and len(found) == 1
            and found[0]["plate_text_ascii"]
            == "37T92158"
            and found[0]["plate_bbox"]["x1"] == 100))

        test_payload["notes"] = "smoke test EDITED"
        st, out = post("/api/save", test_payload)
        st, body = get(
            "/api/annotations?camera=cam1&frame=10")
        found = [a for a in
                 json.loads(body)["annotations"]
                 if a["annotation_id"] == aid]
        checks.append((
            "POST /api/save (edit rewrites by id)",
            st == 200 and len(found) == 1
            and found[0]["notes"]
            == "smoke test EDITED"))

        bad = dict(test_payload)
        bad["plate_text_raw"] = ""
        bad["annotation_status"] = "verified"
        st, out = post("/api/save", bad)
        checks.append((
            "POST /api/save rejects invalid "
            "(empty verified text)",
            st == 200 and out.get("ok") is False
            and out.get("errors")))
        bad2 = dict(test_payload)
        bad2["plate_bbox"] = {"x1": 300, "y1": 200,
                              "x2": 100, "y2": 260}
        st, out = post("/api/save", bad2)
        checks.append(("POST /api/save rejects inverted box",
                       st == 200 and out.get("ok") is False
                       and out.get("errors")))

        # ---- Phase 3.5 additions (baseline 10 above) ----
        st, body = get("/api/queue?camera=cam2")
        qd = json.loads(body)
        q = qd.get("queue", [])
        prios = [e["priority"] for e in q]
        checks.append((
            "GET /api/queue (cam2 priority order)",
            st == 200 and len(q) == 120
            and qd.get("summary", {}).get("UNLABELED") == 78
            and prios == sorted(prios)
            and any(e["phase2b_sample"] for e in q)))

        st, body = get("/api/instances?camera=cam2")
        inst = json.loads(body).get("instances", [])
        checks.append(("GET /api/instances (cam2)",
                       st == 200 and len(inst) == 9
                       and all(v["frames"]
                               for v in inst)))

        st, body = get("/")
        html = body.decode("utf-8")
        checks.append((
            "UI: readability classes / shortcuts / "
            "coordinate convention",
            "INVALID_SAMPLE" in html
            and "previous frame" in html
            and "[x1,x2)" in html
            and "PENDING_HUMAN_REVIEW" in html))

        bname = f"plates.{before[:12]}.jsonl"
        bpath = ("benchmarks/dataset/phase3/backups/"
                 + bname)
        checks.append((
            "GT backup snapshot byte-identical (§29)",
            __import__("os").path.isfile(bpath)
            and sha_file(bpath) == before))


        print()
        failed = 0
        for name, ok in checks:
            print(f"  {'PASS' if ok else 'FAIL'}: "
                  f"{name}")
            failed += not ok
        print(f"\n{len(checks) - failed}/{len(checks)}"
              f" smoke checks passed")
        return 1 if failed else 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        # restore original dataset file
        keep = [ln for ln in open(
            GT, encoding="utf-8").read().splitlines()
            if ln.strip()
            and "vSMOKE" not in ln]
        with open(GT, "w", encoding="utf-8") as f:
            f.write("\n".join(keep) + "\n")
        after = sha_file(GT)
        n_after = len(keep)
        print(f"dataset restored: hash match="
              f"{before == after} "
              f"({n_before} -> {n_after} records)")
        if before != after:
            print("FAIL: dataset file not restored!")
            return 1
        # ---- Phase 3.5 §29/§30: backup recovery path ----
        bname = f"plates.{before[:12]}.jsonl"
        bpath = ("benchmarks/dataset/phase3/backups/"
                 + bname)
        backup_ok = (__import__("os").path.isfile(bpath)
                     and sha_file(bpath) == before)
        print(f"backup snapshot byte-identical: "
              f"{backup_ok}")
        restore_ok = False
        if backup_ok:
            # no-op restore: exercises the recovery code path
            # against identical bytes (must not change GT).
            r = subprocess.run(
                [sys.executable,
                 "benchmarks/phase3_annotate.py",
                 "--restore-backup", bname],
                capture_output=True, text=True)
            restore_ok = (r.returncode == 0
                          and sha_file(GT) == before)
            print(f"backup recovery (no-op restore) ok: "
                  f"{restore_ok}")
        if not backup_ok or not restore_ok:
            print("FAIL: backup/recovery check failed!")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
