"""Phase 0: consensus property tests (design §4.8, D.1 row 7, Hypothesis)."""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from pipeline import consensus as cs
from pipeline.config import PipelineConfig
from pipeline.types import PlateRead

CFG = PipelineConfig()


def _read(text: str, conf: float, frame: int, *, char_count: int | None = None,
          usable: bool = True, weight: float = 0.5) -> PlateRead:
    r = PlateRead(
        frame_idx=frame, ts=f"t{frame}", text=text,
        char_candidates=[[(ch, conf)] for ch in text],
        char_count=len(text) if char_count is None else char_count,
        plate_det_conf=conf, plate_area_px=4800, aspect_ratio=4.6,
        sharpness=120.0, brightness_ok=True, usable=usable, weight=weight,
    )
    return r


@settings(max_examples=50, deadline=None)
@given(n_agree=st.integers(min_value=3, max_value=10),
       n_dissent=st.integers(min_value=1, max_value=3),
       seed=st.integers(min_value=0, max_value=10_000))
def test_property_majority_wins_and_agreement_in_unit_interval(n_agree,
                                                               n_dissent, seed):
    """≥3 agreeing reads + N dissenters → consensus is the majority text."""
    truth = "12b34567"
    plate = "12b34597"                       # one char differs at pos 6
    reads = [_read(truth, 0.9, i, weight=0.9) for i in range(n_agree)]
    reads += [_read(plate, 0.7, 100 + i, weight=0.7) for i in range(n_dissent)]
    result, _ = cs.update(reads, CFG, plate_valid=True)
    assert result.plate == truth
    assert 0.0 <= result.agreement_ratio <= 1.0
    assert 0.0 <= result.confidence <= 1.0


@settings(max_examples=40, deadline=None)
@given(extra=st.integers(min_value=1, max_value=15))
def test_property_confidence_never_drops_on_identical_appends(extra):
    """Appending reads identical to the consensus can only raise confidence."""
    reads = [_read("12b34567", 0.85, 0)]
    prev = cs.update(list(reads), CFG, plate_valid=True)[0].confidence
    for i in range(1, extra + 1):
        reads.append(_read("12b34567", 0.85, i))
        conf = cs.update(list(reads), CFG, plate_valid=True)[0].confidence
        assert conf >= prev - 1e-9
        prev = conf


@settings(max_examples=50, deadline=None)
@given(
    noise=st.lists(st.sampled_from(["", "99", "12b3", "12b3456789"]),
                   min_size=0, max_size=6),
    good=st.integers(min_value=0, max_value=4),
)
def test_property_empty_and_partial_never_flip_confirmed_consensus(noise, good):
    """The majority consensus text is immune to empty/partial appends."""
    truth = "12b34567"
    reads = [_read(truth, 0.9, i) for i in range(max(good, 3))]
    baseline = cs.update(list(reads), CFG, plate_valid=True)[0].plate
    for i, text in enumerate(noise):
        # Sub-threshold weight: stored as evidence, excluded from voting
        # (§4.2 min_obs_weight) — so it can never flip the consensus.
        reads.append(_read(text, 0.9, 100 + i, usable=bool(text), weight=0.01))
    after = cs.update(list(reads), CFG, plate_valid=True)[0].plate
    assert baseline == after == truth


@settings(max_examples=50, deadline=None)
@given(shuffle_seed=st.integers(min_value=0, max_value=10_000))
def test_property_deterministic_evidence_order(shuffle_seed):
    """Byte-identical evidence sets → identical results, regardless of order."""
    import random
    base = [_read("12b34567", 0.8, i, weight=0.8) for i in range(4)]
    base += [_read("12b345678", 0.6, 50 + i, weight=0.6) for i in range(2)]
    shuffled = list(base)
    random.Random(shuffle_seed).shuffle(shuffled)
    a = cs.update(list(base), CFG, plate_valid=True)
    b = cs.update(shuffled, CFG, plate_valid=True)
    # Order changes frame-index tie-breaks only; plate + metrics must match.
    assert a[0].plate == b[0].plate
    assert a[1] == b[1]
    assert abs(a[0].confidence - b[0].confidence) < 1e-9
    assert abs(a[0].agreement_ratio - b[0].agreement_ratio) < 1e-9


@settings(max_examples=50, deadline=None)
@given(weights=st.lists(st.floats(min_value=0.0, max_value=1.0,
                                  allow_nan=False, allow_infinity=False),
                        min_size=1, max_size=10))
def test_property_quality_and_confidence_bounded(weights):
    """quality_score stays in [0,1] for any input (clamped design formula)."""
    for i, w in enumerate(weights):
        q = cs.quality_score(w * 1000, int(w * 10000), 1.0 + w * 8, w, w, CFG)
        assert 0.0 <= q <= 1.0
