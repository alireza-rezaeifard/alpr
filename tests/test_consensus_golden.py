"""Phase 0: consensus golden cases (design §4.5-§4.8, D.1 row 6).

Covers the audit's worked example plus the required edge cases: partial,
empty, conflicting, low-confidence, identical, different lengths, noisy,
single observation, ties.
"""
from __future__ import annotations

from pipeline import consensus as cs
from pipeline.config import PipelineConfig
from pipeline.types import PlateRead

CFG = PipelineConfig()


def cands(text: str, conf: float, runner_up: dict | None = None) -> list:
    """Per-position ranked candidates for *text* (top-K, §4.1)."""
    out = []
    for i, ch in enumerate(text):
        pair = [(ch, conf)]
        ru = (runner_up or {}).get(i)
        if ru:
            pair.append(ru)                    # (char, conf) rank-1
        out.append(pair)
    return out


def read(text: str, *, det_conf: float, char_conf: float, frame: int = 0,
         usable: bool = True, weight: float | None = None,
         runner_up: dict | None = None, char_count: int | None = None,
         area: int = 4800, aspect: float = 4.6, sharpness: float = 120.0,
         brightness_ok: bool = True) -> PlateRead:
    r = PlateRead(
        frame_idx=frame, ts=f"2026-09-29T00:00:{frame:02d}Z", text=text,
        char_candidates=cands(text, char_conf, runner_up),
        char_count=len(text) if char_count is None else char_count,
        plate_det_conf=det_conf, plate_area_px=area, aspect_ratio=aspect,
        sharpness=sharpness, brightness_ok=brightness_ok, usable=usable,
        bbox=None, vehicle_bbox=None,
    )
    r.weight = (cs.observation_weight(r, CFG, quality=1.0)
                if weight is None else weight)
    return r


# ---------------------------------------------------------------- Case A --
def test_case_a_dissenter_loses_to_majority():
    """Audit example: 0.82 / 0.77(one char differs) / 0.91 → 12ب34567."""
    r1 = read("12ب34567", det_conf=0.82, char_conf=0.82, frame=0)
    r2 = read("12ب34587", det_conf=0.77, char_conf=0.77, frame=1)
    r3 = read("12ب34567", det_conf=0.91, char_conf=0.91, frame=2)
    result, action = cs.update([r1, r2, r3], CFG, plate_valid=True)

    assert result is not None
    assert result.plate == "12ب34567"               # expected winner
    assert 0.80 <= result.confidence <= 0.95        # design: ~0.9
    assert 0.0 < result.agreement_ratio < 1.0       # dissenter counted honestly
    assert result.posterior_min < 1.0               # one position is contested
    assert action == cs.CONFIRM                     # 3 obs, valid, agree ≥ 0.6
    assert result.alternates and result.alternates[0] == "12ب34587"
    assert result.best is not None and result.best.frame_idx == 2   # 0.91 wins


def test_case_a_determinism():
    r1 = read("12ب34567", det_conf=0.82, char_conf=0.82, frame=0)
    r2 = read("12ب34587", det_conf=0.77, char_conf=0.77, frame=1)
    r3 = read("12ب34567", det_conf=0.91, char_conf=0.91, frame=2)
    a = cs.update([r1, r2, r3], CFG, plate_valid=True)
    b = cs.update([r1, r2, r3], CFG, plate_valid=True)
    assert a[0] == b[0] and a[1] == b[1]            # byte-identical result


# ------------------------------------------------------------- edge cases --
def test_empty_ocr_suppressed():
    empty = read("", det_conf=0.9, char_conf=0.9, usable=False, char_count=0)
    result, action = cs.update([empty], CFG, closing=True)
    assert result is None
    assert action == cs.SUPPRESS                    # §4.6: usable_obs == 0


def test_single_observation_holds_then_force_at_close():
    r = read("12b34567", det_conf=0.9, char_conf=0.9)
    result, action = cs.update([r], CFG, plate_valid=True)
    assert action == cs.HOLD                        # confirm_min_obs = 3
    assert result is not None and result.plate == "12b34567"
    _, closing_action = cs.update([r], CFG, closing=True, plate_valid=True)
    assert closing_action == cs.FORCE               # single obs still forces


def test_partial_reads_do_not_flip_majority():
    """7-char partials parked; 8-char mode wins (§4.5 step 1)."""
    reads = [read("12b34567", det_conf=0.8, char_conf=0.8, frame=i)
             for i in range(3)]
    reads += [read("2b34567", det_conf=0.7, char_conf=0.7, frame=3 + i,
                   char_count=7) for i in range(2)]
    result, action = cs.update(reads, CFG, plate_valid=True)
    assert result.length_mode_weight >= 0.6
    assert result.plate == "12b34567"
    assert action == cs.CONFIRM


def test_different_lengths_equal_weight_holds():
    a = read("12b34567", det_conf=0.8, char_conf=0.8, frame=0)
    b = read("12b345678", det_conf=0.8, char_conf=0.8, frame=1, char_count=9)
    result, action = cs.update([a, b], CFG, plate_valid=True)
    assert result.length_mode_weight == 0.5          # tie → below 0.6 threshold
    assert action == cs.HOLD


def test_tie_break_is_deterministic():
    """Two chars with identical vote mass: stable, never random."""
    r1 = read("12b34567", det_conf=0.5, char_conf=0.5, frame=0)
    r2 = read("12b34537", det_conf=0.5, char_conf=0.5, frame=1)  # pos6: '7' vs '3'
    first, _ = cs.update([r1, r2], CFG, plate_valid=True)
    second, _ = cs.update([r1, r2], CFG, plate_valid=True)
    assert first.plate == second.plate
    assert first.posterior_min <= 0.5 + 1e-6        # 50/50 → weak char flagged


def test_identical_candidates_confidence_monotonic():
    reads = []
    values = []
    for i in range(6):
        reads.append(read("12b34567", det_conf=0.9, char_conf=0.9, frame=i))
        result, _ = cs.update(list(reads), CFG, plate_valid=True)
        values.append(result.confidence)
    assert all(values[i] <= values[i + 1] + 1e-9 for i in range(len(values) - 1))
    assert values[-1] > 0.9                          # agreement → 1.0 pushes up


def test_low_weight_reads_do_not_vote():
    """Sub-threshold garbage is stored but never counted (§4.2 min_obs_weight)."""
    good = read("12b34567", det_conf=0.9, char_conf=0.9, frame=0)
    garbage = read("99999", det_conf=0.1, char_conf=0.1, frame=1,
                   usable=False, char_count=5, weight=0.001)
    result, action = cs.update([good, garbage], CFG, plate_valid=True)
    assert result.plate == "12b34567"
    assert result.agreement_ratio == 1.0              # garbage weight ≈ 0
    assert action == cs.HOLD                          # only 1 voting observation


def test_noisy_rank1_candidate_swings_weak_position():
    """A dissenter with a rank-1 vote for the majority char still loses."""
    r1 = read("12b34567", det_conf=0.8, char_conf=0.8, frame=0)
    r2 = read("12b34587", det_conf=0.7, char_conf=0.7, frame=1,
              runner_up={6: ("6", 0.6)})            # rank-1 points at '6'
    r3 = read("12b34567", det_conf=0.9, char_conf=0.9, frame=2)
    result, action = cs.update([r1, r2, r3], CFG, plate_valid=True)
    assert result.plate == "12b34567"
    assert result.posterior_min > 0.75               # rank-1 vote helps '6'
    assert action == cs.CONFIRM


def test_conflicting_candidates_never_confirm_without_agreement():
    """4 vs 4 split: agreement < 0.6 blocks CONFIRM (§4.6)."""
    reads = [read("12b34567", det_conf=0.7, char_conf=0.7, frame=i)
             for i in range(4)]
    reads += [read("12b34597", det_conf=0.7, char_conf=0.7, frame=4 + i)
              for i in range(4)]
    result, action = cs.update(reads, CFG, plate_valid=True)
    assert 0.4 <= result.agreement_ratio <= 0.6
    assert action == cs.HOLD


def test_unconfirmed_on_invalid_plate():
    reads = [read("12b34567", det_conf=0.9, char_conf=0.9, frame=i)
             for i in range(3)]
    _, action = cs.update(reads, CFG, plate_valid=False)
    assert action == cs.HOLD                         # CONFIRM requires plate_valid


def test_best_frame_selection():
    reads = [read("12b34567", det_conf=0.6, char_conf=0.6, frame=0),
             read("12b34567", det_conf=0.95, char_conf=0.95, frame=1),
             read("12b34567", det_conf=0.7, char_conf=0.7, frame=2)]
    result, _ = cs.update(reads, CFG, plate_valid=True)
    assert result.best is not None and result.best.frame_idx == 1


def test_decide_rules():
    common = dict(usable_obs=3, length_mode_weight=1.0,
                  agreement_ratio_value=1.0, char_mean=0.99,
                  plate_valid=True, quality=0.7,
                  already_emitted=False, upgrades=0, best_quality=0.7,
                  closing=False, cfg=CFG)
    assert cs.decide(**common) == cs.CONFIRM
    assert cs.decide(**{**common, "plate_valid": False}) == cs.HOLD
    assert cs.decide(**{**common, "agreement_ratio_value": 0.4}) == cs.HOLD
    assert cs.decide(**{**common, "usable_obs": 2}) == cs.HOLD
    assert cs.decide(**{**common, "usable_obs": 1,
                        "char_mean": 0.99, "quality": 0.9}) == cs.HOLD  # disabled
    enabled = PipelineConfig(enable_early_best=True)
    assert cs.decide(**{**common, "cfg": enabled, "usable_obs": 1,
                        "char_mean": 0.99, "quality": 0.9}) == cs.EARLY_BEST
    up = {**common, "already_emitted": True, "quality": 0.9, "best_quality": 0.7}
    assert cs.decide(**up) == cs.UPGRADE            # 0.9 > 0.7 × 1.15
    assert cs.decide(**{**up, "upgrades": 1}) == cs.HOLD
    assert cs.decide(**{**up, "quality": 0.71}) == cs.HOLD       # no 1.15x gain
    assert cs.decide(**{**common, "closing": True}) == cs.FORCE
    assert cs.decide(**{**common, "closing": True,
                        "usable_obs": 0}) == cs.SUPPRESS
    assert cs.decide(**{**common, "closing": True, "agreement_ratio_value": 0.1,
                        "char_mean": 0.1}) == cs.SUPPRESS


def test_quality_score_bounds_and_monotonicity():
    low = cs.quality_score(10, 500, 2.0, 0.5, 0.5, CFG)
    high = cs.quality_score(300, 4800, 4.6, 0.95, 0.95, CFG)
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert high > low
    assert cs.quality_score(10_000, 10**6, 4.6, 2.0, 2.0, CFG) == 1.0  # clamped


def test_quality_gate_rejections():
    bad_conf = read("12b34567", det_conf=0.2, char_conf=0.9)
    assert cs.is_usable(bad_conf, CFG) == (False, "quality")
    dark = read("12b34567", det_conf=0.9, char_conf=0.9, brightness_ok=False)
    assert cs.is_usable(dark, CFG) == (False, "brightness")
    small = read("12b34567", det_conf=0.9, char_conf=0.9, area=100)
    assert cs.is_usable(small, CFG) == (False, "area")
    # Sharpness gate is lenient by default (min_sharpness=0.0); exercise it
    # with an explicitly configured threshold (§4.3 "lenient while scarce").
    strict = PipelineConfig(min_sharpness=50.0)
    soft = read("12b34567", det_conf=0.9, char_conf=0.9, sharpness=0.0)
    assert cs.is_usable(soft, strict, usable_so_far=0)[0] is True   # first reads
    assert cs.is_usable(soft, strict, usable_so_far=2)[0] is False  # then rejected
    assert cs.is_usable(soft, CFG, usable_so_far=5)[0] is True      # default lenient
