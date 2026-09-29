"""Dataset manifest loader for the evaluation harness (design Part 6.3).

Phase 0 ships ONLY the loader and the "dataset missing" contract: the
held-out Iranian plate set is not in the repository (it must be collected
and versioned; see design §6.3). The harness must fail loudly and clearly
instead of inventing numbers.
"""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_NAME = "manifest.json"
HELDOUT_DIRS = (
    "eval/iranian_eval_set/heldout",
    "eval/iranian_eval_set/heldout_v1",
)


class DatasetMissing(Exception):
    """Raised when the frozen held-out split is not present on disk."""


def heldout_path() -> str:
    """Return the held-out directory path, or raise DatasetMissing."""
    for rel in HELDOUT_DIRS:
        candidate = os.path.join(ROOT, rel)
        if os.path.isdir(candidate):
            return candidate
    raise DatasetMissing(
        "heldout dataset not found (expected one of: "
        + ", ".join(HELDOUT_DIRS)
        + "). Collect/version it per ALPR_ARCHITECTURE_DESIGN.md §6.3; "
          "no accuracy numbers are produced without it."
    )


def load_manifest(directory: str | None = None) -> dict:
    """Load the split manifest (counts + hashes + licence notes)."""
    directory = directory or heldout_path()
    path = os.path.join(directory, MANIFEST_NAME)
    if not os.path.isfile(path):
        raise DatasetMissing(f"manifest.json missing in {directory}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_visits(directory: str | None = None) -> list:
    """Load ``visits.jsonl`` — one line per vehicle visit (§6.2)."""
    directory = directory or heldout_path()
    path = os.path.join(directory, "visits.jsonl")
    if not os.path.isfile(path):
        raise DatasetMissing(f"visits.jsonl missing in {directory}")
    visits = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                visits.append(json.loads(line))
    return visits


def load_frames_index(directory: str | None = None) -> list:
    """Load ``frames.json`` (COCO-style index) for detection metrics."""
    directory = directory or heldout_path()
    path = os.path.join(directory, "frames.json")
    if not os.path.isfile(path):
        raise DatasetMissing(f"frames.json missing in {directory}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
