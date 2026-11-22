"""Download / hash the 9 official IR-LPR Google Drive files.

Research-only helper for the External Dataset Integration phase.
Reads data/manifests/google_drive_manifest.json, downloads each file with
resumable curl (retrying), detects the real file type from magic bytes,
computes SHA256 in a streaming fashion (never loads a file into RAM), and
writes the updated manifest back atomically.

Usage:
    python benchmarks/external_datasets/_download_drive.py --download
    python benchmarks/external_datasets/_download_drive.py --hash
    python benchmarks/external_datasets/_download_drive.py --status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "data" / "manifests" / "google_drive_manifest.json"

CHUNK = 8 * 1024 * 1024

MAGIC_SIGNATURES = (
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07", "rar"),
    (b"\x1f\x8b", "gzip"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"BM", "bmp"),
    (b"GIF8", "gif"),
)


def detect_type(path: Path) -> str | None:
    """Identify the real file type from leading magic bytes (streamed)."""
    try:
        with path.open("rb") as fh:
            head = fh.read(512)
    except OSError:
        return None
    if not head:
        return None
    stripped = head.lstrip()
    if stripped.startswith((b"<!DOCTYPE", b"<html", b"<?xml")):
        return "html"
    for sig, name in MAGIC_SIGNATURES:
        if head.startswith(sig):
            return name
    if head[:6] in (b"ustar\x00", b"ustar "):
        return "tar"
    return "unknown"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def load_manifest() -> dict:
    with MANIFEST_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_manifest(data: dict) -> None:
    """Atomic write so a killed run never corrupts the manifest."""
    fd, tmp = tempfile.mkstemp(dir=str(MANIFEST_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, MANIFEST_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def download_one(entry: dict, attempts: int = 6) -> bool:
    dest = REPO_ROOT / entry["local_path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = (
        "https://drive.usercontent.google.com/download"
        f"?id={entry['file_id']}&export=download&confirm=t"
    )
    for attempt in range(1, attempts + 1):
        if dest.exists() and dest.stat().st_size > 0 and entry["status"] == "downloaded":
            return True
        print(f"[dl] {entry['name']} attempt {attempt}/{attempts}", flush=True)
        cmd = [
            "curl", "-sL", "--fail", "-C", "-",
            "--retry", "5", "--retry-delay", "10",
            "--connect-timeout", "30",
            "-o", str(dest), url,
        ]
        try:
            proc = subprocess.run(cmd, timeout=3 * 3600)
        except subprocess.TimeoutExpired:
            print(f"[dl] {entry['name']} timeout", flush=True)
            time.sleep(20)
            continue
        if proc.returncode != 0:
            print(f"[dl] {entry['name']} curl rc={proc.returncode}", flush=True)
            time.sleep(20)
            continue
        if not dest.exists() or dest.stat().st_size == 0:
            time.sleep(10)
            continue
        dtype = detect_type(dest)
        if dtype == "html":
            # quota / error page masquerading as the payload
            print(f"[dl] {entry['name']} got HTML instead of payload, retrying", flush=True)
            dest.unlink(missing_ok=True)
            time.sleep(60)
            continue
        entry["status"] = "downloaded"
        entry["downloaded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        entry["actual_size_bytes"] = dest.stat().st_size
        entry["detected_type"] = dtype
        print(f"[dl] {entry['name']} OK {entry['actual_size_bytes']:,} bytes ({dtype})", flush=True)
        return True
    entry["status"] = "failed"
    print(f"[dl] {entry['name']} FAILED after {attempts} attempts", flush=True)
    return False


def hash_one(entry: dict) -> bool:
    dest = REPO_ROOT / entry["local_path"]
    if not dest.exists():
        return False
    entry["sha256"] = sha256_file(dest)
    entry["actual_size_bytes"] = dest.stat().st_size
    entry["detected_type"] = detect_type(dest)
    print(f"[hash] {entry['name']} {entry['sha256']} ({entry['actual_size_bytes']:,} bytes)", flush=True)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--download", action="store_true")
    group.add_argument("--hash", action="store_true")
    group.add_argument("--status", action="store_true")
    args = ap.parse_args()

    manifest = load_manifest()
    files = manifest["files"]

    if args.status:
        for e in files:
            p = REPO_ROOT / e["local_path"]
            print(f"{e['index']:>2} {e['name']:<28} {e['status']:<10} "
                  f"exists={p.exists()} size={p.stat().st_size if p.exists() else 0:,} "
                  f"sha256={'yes' if e['sha256'] else 'no'}")
        found = sum(1 for e in files if (REPO_ROOT / e["local_path"]).exists())
        print(f"Files found: {found} / {len(files)}")
        return 0

    if args.download:
        ok = True
        for entry in files:
            p = REPO_ROOT / entry["local_path"]
            if entry["status"] == "downloaded" and p.exists() and p.stat().st_size == entry["actual_size_bytes"]:
                print(f"[dl] {entry['name']} already downloaded", flush=True)
                continue
            if not download_one(entry):
                ok = False
            save_manifest(manifest)
        return 0 if ok else 1

    if args.hash:
        for entry in files:
            if hash_one(entry):
                save_manifest(manifest)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
