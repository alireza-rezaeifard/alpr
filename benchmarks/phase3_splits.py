"""Phase 3 — dataset splits at the vehicle-instance level.

Splits are ALWAYS made at the physical vehicle-instance
level (never the frame level) so that no physical plate
appears in two splits (task §26/§27).

With the current verified dataset (2 instances, 1 camera)
a 60/20/20 split is not statistically meaningful, so the
documented policy is:

  * if n_instances >= 5  → deterministic 60/20/20 split
                           by stable hash of the instance ID
  * otherwise            → ALL instances in the single
                           evaluation (test) split;
                           train/validation exist but are
                           empty, with the rationale
                           recorded. No statistical
                           significance is manufactured.

The module also performs the leakage checks the test
suite enforces: no instance in two splits, no frame
observed under two vehicle instances.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MIN_INSTANCES_FOR_SPLIT = 5


def _stable_hash(value: str) -> int:
    return int(hashlib.sha256(
        value.encode("utf-8")).hexdigest()[:8], 16)


def build_splits(vehicle_instances: list[dict],
                 ratios: tuple[float, float, float]
                 = (0.6, 0.2, 0.2)) -> dict:
    """Assign every vehicle instance to exactly one split.

    Returns {"train": [...], "validation": [...],
             "test": [...], "strategy": str,
             "rationale": str}.
    """
    ids = [v["vehicle_instance_id"] for v in vehicle_instances]
    if len(ids) >= MIN_INSTANCES_FOR_SPLIT:
        # Deterministic instance-level 60/20/20 split.
        order = sorted(ids, key=lambda i: _stable_hash(i))
        n = len(order)
        n_train = round(n * ratios[0])
        n_val = round(n * ratios[1])
        splits = {
            "train": order[:n_train],
            "validation": order[n_train:n_train + n_val],
            "test": order[n_train + n_val:],
        }
        strategy = "instance_level_60_20_20"
        rationale = (
            f"{n} vehicle instances: deterministic "
            "instance-level split by stable SHA-256 hash of "
            "the instance ID; no frame-level assignment, so "
            "no physical plate appears in two splits.")
    else:
        splits = {"train": [], "validation": [],
                  "test": list(ids)}
        strategy = "single_evaluation_set"
        rationale = (
            f"only {len(ids)} verified vehicle instance(s) "
            "exist (need >= 5 for a statistically meaningful "
            "instance-level split); ALL verified instances are "
            "kept in the single evaluation (test) split and "
            "train/validation are left empty. No statistical "
            "significance is manufactured.")
    return {"splits": splits, "strategy": strategy,
            "rationale": rationale}


def check_leakage(annotations: list[dict],
                  splits: dict) -> dict:
    """Verify no instance appears in two splits and no
    frame is assigned to two vehicle instances.

    Returns {"leakage_free": bool, "violations": [...]}.
    """
    violations = []

    # 1. instance -> exactly one split
    instance_split = {}
    for split_name, ids in splits.items():
        for vid in ids:
            if vid in instance_split:
                violations.append(
                    f"vehicle instance {vid} in both "
                    f"{instance_split[vid]} and {split_name}")
            instance_split[vid] = split_name

    # 2. every annotated instance must have a split
    annotated = {a["vehicle_instance_id"]
                 for a in annotations}
    for vid in annotated:
        if vid not in instance_split:
            violations.append(
                f"vehicle instance {vid} has annotations but "
                "no split assignment")

    # 3. no (frame, camera) under two vehicle instances
    frame_owner = {}
    for a in annotations:
        key = (a["camera_id"], a["frame_id"])
        owner = a["vehicle_instance_id"]
        if key in frame_owner and frame_owner[key] != owner:
            violations.append(
                f"frame {key} assigned to both "
                f"{frame_owner[key]} and {owner}")
        frame_owner[key] = owner

    return {"leakage_free": not violations,
            "violations": violations}


def write_splits(splits: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for name in ("train", "validation", "test"):
        payload = {
            "split": name,
            "vehicle_instance_ids":
                splits["splits"][name],
            "strategy": splits["strategy"],
            "rationale": splits["rationale"],
        }
        (out_dir / f"{name}.json").write_text(
            json.dumps(payload, indent=1), encoding="utf-8")
        written[name] = len(splits["splits"][name])
    return written
