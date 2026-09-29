"""Pure multi-frame consensus engine (design Part 4, §4.8 pseudocode).

No camera, no DB, no threads, no network, no Flutter. Every public function
is deterministic for fixed inputs (no wall-clock, no randomness). torch/cv2
are NOT imported here — quality inputs (sharpness etc.) arrive precomputed
in PlateRead from the collector (Phase 1), exactly as Appendix A mandates.
"""
from __future__ import annotations

import math

from .config import PipelineConfig
from .types import ConsensusCandidate, ConsensusResult, PlateRead

# Rank weights for ranked candidates (§4.5 step 2).
_RANK_WEIGHTS = (1.0, 0.5, 0.25)

# Emit actions (§4.8 decide()).
HOLD = "HOLD"
CONFIRM = "CONFIRM"
EARLY_BEST = "EARLY_BEST"
UPGRADE = "UPGRADE"
FORCE = "FORCE"
SUPPRESS = "SUPPRESS"


def clamp01(value: float) -> float:
    """Clamp to [0, 1]."""
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


def quality_score(lap_var: float, plate_area_px: int, aspect_ratio: float,
                  plate_det_conf: float, mean_char_conf: float,
                  cfg: PipelineConfig) -> float:
    """Composite image quality in [0, 1] (§4.4).

    quality = 0.45·sharpness_norm + 0.25·area_norm
            + 0.10·aspect_pen + 0.20·conf_norm
    """
    sharpness_norm = clamp01(math.log1p(max(lap_var, 0.0))
                             / math.log1p(max(cfg.sharp_ref, 1e-6)))
    area_norm = clamp01(plate_area_px / max(cfg.area_ref, 1))
    aspect_pen = 1.0 - clamp01(abs(aspect_ratio - cfg.expect_aspect)
                               / max(cfg.expect_aspect, 1e-6))
    conf_norm = clamp01((plate_det_conf + mean_char_conf) / 2.0)
    return (0.45 * sharpness_norm + 0.25 * area_norm
            + 0.10 * aspect_pen + 0.20 * conf_norm)


def observation_weight(read: PlateRead, cfg: PipelineConfig,
                       quality: float | None = None) -> float:
    """w_i = plate_det_conf × mean_char_conf × quality (§4.2).

    Quality defaults to quality_score() recomputed from the read fields.
    """
    if quality is None:
        quality = quality_score(read.sharpness, read.plate_area_px,
                                read.aspect_ratio, read.plate_det_conf,
                                read.mean_char_conf(), cfg)
    conf = max(read.plate_det_conf, cfg.min_vote_conf)
    char = max(read.mean_char_conf(), cfg.min_vote_conf)
    return conf * char * max(quality, 0.0)


def is_usable(read: PlateRead, cfg: PipelineConfig,
              usable_so_far: int = 0) -> tuple[bool, str]:
    """Quality gate (§4.3). Returns (usable, rejection_reason)."""
    if read.plate_det_conf < cfg.plate_gate_conf:
        return False, "quality"
    if read.plate_area_px > 0 and read.plate_area_px < cfg.min_plate_width_px ** 2:
        return False, "area"
    if not read.brightness_ok:
        return False, "brightness"
    # Lenient while evidence is scarce: first reads may be soft (§4.3).
    if read.sharpness < cfg.min_sharpness and usable_so_far >= 2:
        return False, "quality"
    return True, ""


def length_consensus(reads: list, cfg: PipelineConfig
                     ) -> tuple[int | None, float, dict]:
    """Group usable reads by char_count; winner L* (§4.5 step 1).

    Returns (L_star, length_mode_weight, {char_count: total_weight}).
    Other lengths are parked — they are partial-plate evidence, not noise.
    """
    weights: dict = {}
    for read in reads:
        if not getattr(read, "usable", False):
            continue
        w = getattr(read, "weight", 0.0)
        if w < cfg.min_obs_weight:
            continue
        weights[read.char_count] = weights.get(read.char_count, 0.0) + w
    total = sum(weights.values())
    if not weights or total <= 0.0:
        return None, 0.0, weights
    best_len = max(weights, key=lambda k: (weights[k], -k))
    return best_len, weights[best_len] / total, weights


def position_votes(reads: list, length_mode: int, cfg: PipelineConfig
                   ) -> tuple[str, list[float], float, list[ConsensusCandidate]]:
    """Weighted positional voting over L*-length reads (§4.5 step 2-3).

    Returns (consensus_text, char_conf, plate_posterior_min, alternates).
    Ranked candidates vote with rank weights 1.0 / 0.5 / 0.25.
    """
    votes: list[dict] = [{} for _ in range(length_mode)]
    for read in reads:
        if not getattr(read, "usable", False) or read.char_count != length_mode:
            continue
        w = getattr(read, "weight", 0.0)
        if w < cfg.min_obs_weight:
            continue
        candidates = read.char_candidates
        for position in range(length_mode):
            entry = candidates[position] if position < len(candidates) else None
            if entry:
                for rank, (char, _conf) in enumerate(entry[:len(_RANK_WEIGHTS)]):
                    votes[position][char] = (votes[position].get(char, 0.0)
                                             + w * _RANK_WEIGHTS[rank])
            elif read.text and position < len(read.text):
                votes[position][read.text[position]] = (
                    votes[position].get(read.text[position], 0.0) + w)

    consensus_chars: list[str] = []
    char_conf: list[float] = []
    runner_up: list[tuple[str, float]] = []
    for position_votes_for_pos in votes:
        if not position_votes_for_pos:
            consensus_chars.append("?")
            char_conf.append(0.0)
            runner_up.append(("?", 0.0))
            continue
        ordered = sorted(position_votes_for_pos.items(),
                         key=lambda kv: (-kv[1], kv[0]))
        total = sum(ordered[i][1] for i in range(len(ordered)))
        if total <= 0.0:
            consensus_chars.append("?")
            char_conf.append(0.0)
            runner_up.append(("?", 0.0))
            continue
        consensus_chars.append(ordered[0][0])
        char_conf.append(ordered[0][1] / total)
        runner_up.append(ordered[1] if len(ordered) > 1 else ("", 0.0))

    text = "".join(consensus_chars)
    alternates = _alternates(consensus_chars, char_conf, runner_up, cfg)
    posterior_min = min(char_conf) if char_conf else 0.0
    return text, char_conf, posterior_min, alternates


def _alternates(consensus_chars: list, char_conf: list,
                runner_up: list, cfg: PipelineConfig) -> list[str]:
    """Plates from flipping the weakest position to its runner-up (§4.5)."""
    if not char_conf:
        return []
    weakest = min(range(len(char_conf)), key=lambda i: char_conf[i])
    alt_char, alt_weight = runner_up[weakest]
    if not alt_char or alt_char == consensus_chars[weakest] or alt_weight <= 0.0:
        return []
    flipped = list(consensus_chars)
    flipped[weakest] = alt_char
    return ["".join(flipped)]


def agreement_ratio(reads: list, consensus_text: str) -> float:
    """Σ weight of reads equal to consensus / Σ weight over usable (§4.5)."""
    total = 0.0
    agreeing = 0.0
    for read in reads:
        if not getattr(read, "usable", False):
            continue
        w = getattr(read, "weight", 0.0)
        if w <= 0.0:
            continue
        total += w
        if read.text == consensus_text:
            agreeing += w
    return agreeing / total if total > 0.0 else 0.0


def best_frame(reads: list) -> PlateRead | None:
    """Select the highest-quality usable observation (§4.4)."""
    usable = [r for r in reads if getattr(r, "usable", False)]
    if not usable:
        return None
    return max(usable, key=lambda r: (r.weight, r.frame_idx))



def decide(*, usable_obs: int, length_mode_weight: float,
           agreement_ratio_value: float, char_mean: float,
           plate_valid: bool, quality: float,
           already_emitted: bool, upgrades: int, best_quality: float,
           closing: bool, cfg: PipelineConfig) -> str:
    """Stopping rules in §4.6 order: first match wins.

    Returns CONFIRM | EARLY_BEST | UPGRADE | FORCE | SUPPRESS | HOLD.
    """
    if closing:
        if usable_obs == 0:
            return SUPPRESS
        if max(char_mean, agreement_ratio_value) >= cfg.force_emit_posterior:
            return FORCE
        return SUPPRESS

    if already_emitted:
        if (upgrades < cfg.max_upgrades and quality > best_quality * cfg.upgrade_quality_gain):
            return UPGRADE
        return HOLD

    if (usable_obs >= cfg.confirm_min_obs
            and length_mode_weight >= cfg.confirm_min_length_weight
            and agreement_ratio_value >= cfg.confirm_min_agreement
            and plate_valid):
        return CONFIRM

    # EARLY_BEST: single perfect read; disabled by default (§4.6: enable
    # only after the Part 6 eval harness proves it).
    if (cfg.enable_early_best and usable_obs == 1 and plate_valid
            and char_mean >= 0.95 and quality >= 0.85):
        return EARLY_BEST

    if (length_mode_weight > 0.0 and length_mode_weight < cfg.confirm_min_length_weight
            and usable_obs >= cfg.confirm_min_obs
            and char_mean >= cfg.force_emit_posterior):
        # Divergent lengths with a confident winner: review-worthy but not
        # confirmed (§4.7 length split / §2.6 pathology). Held for close.
        return HOLD

    return HOLD


def update(reads: list, cfg: PipelineConfig, *, closing: bool = False,
           already_emitted: bool = False, upgrades: int = 0,
           plate_valid: bool = False
           ) -> tuple[ConsensusResult | None, str]:
    """Pure §4.8 pipeline: append→length mode→votes→agreement→decide.

    *reads* are the track's PlateReads (already quality-gated and weighted
    by the caller, which owns state). Deterministic for fixed inputs.
    """
    usable = [r for r in reads if getattr(r, "usable", False)
              and getattr(r, "weight", 0.0) >= cfg.min_obs_weight]
    if not reads:
        return None, SUPPRESS if closing else HOLD

    length_mode, mode_weight, _ = length_consensus(usable, cfg)
    if length_mode is None:
        # No voting evidence: decide against emission.
        action = decide(usable_obs=0, length_mode_weight=0.0,
                        agreement_ratio_value=0.0, char_mean=0.0,
                        plate_valid=False, quality=0.0,
                        already_emitted=already_emitted, upgrades=upgrades,
                        best_quality=0.0, closing=closing, cfg=cfg)
        return None, action

    text, char_conf, posterior_min, alternates = position_votes(
        usable, length_mode, cfg)
    agreement = agreement_ratio(usable, text)
    char_mean = (sum(char_conf) / len(char_conf)) if char_conf else 0.0
    confidence = 0.5 * char_mean + 0.5 * agreement
    best = best_frame(usable)
    best_quality = best.weight if best else 0.0

    result = ConsensusResult(
        track_key="",
        plate=text,
        char_conf=tuple(char_conf),
        agreement_ratio=agreement,
        confidence=confidence,
        posterior_min=posterior_min,
        length_mode_weight=mode_weight,
        best=best,
        alternates=tuple(alternates),
    )
    action = decide(usable_obs=len(usable), length_mode_weight=mode_weight,
                    agreement_ratio_value=agreement, char_mean=char_mean,
                    plate_valid=plate_valid, quality=best_quality,
                    already_emitted=already_emitted, upgrades=upgrades,
                    best_quality=best_quality, closing=closing, cfg=cfg)
    return result, action

    return True, ""
