"""衰减、心境、强度与重复刺激递减（T3-03）。"""

from __future__ import annotations

import math

import pytest

from app.emotion.decay import (
    MOOD_BASELINE_SECONDS,
    apply_habituation,
    compute_intensity,
    decay_toward,
    update_mood,
)
from app.emotion.models import PAD


def test_decay_toward_is_identity_at_dt_zero() -> None:
    pad = PAD(0.8, 0.7, 0.6)
    assert decay_toward(pad, PAD(0.0, 0.2, 0.4), 0.0, 300.0) == pad


def test_decay_toward_half_life_and_converges() -> None:
    tau = 120.0
    result = decay_toward(PAD(1.0, 1.0, 1.0), PAD(0.0, 0.0, 0.0), tau * math.log(2), tau)
    assert result.valence == pytest.approx(0.5, rel=1e-6)
    assert result.arousal == pytest.approx(0.5, rel=1e-6)
    assert result.dominance == pytest.approx(0.5, rel=1e-6)
    near = decay_toward(PAD(1.0, 1.0, 1.0), PAD(0.0, 0.0, 0.0), 20 * tau, tau)
    assert near.valence < 0.001


def test_update_mood_is_slow_relative_to_pad() -> None:
    mood = PAD(0.0, 0.35, 0.55)
    pad = PAD(0.5, 0.35, 0.55)
    updated = update_mood(mood, pad, 60.0, PAD(0.0, 0.35, 0.55))
    # 60 秒内 mood 只吸收约 1.6%；pad 本身则按 tau 衰减
    assert 0.0 < updated.valence - mood.valence < 0.05
    assert update_mood(mood, pad, 0.0, mood) == mood


def test_update_mood_relaxes_to_baseline() -> None:
    baseline = PAD(0.1, 0.3, 0.5)
    mood = PAD(-0.6, 0.8, 0.2)
    one_day = update_mood(mood, baseline, MOOD_BASELINE_SECONDS, baseline)
    ten_days = update_mood(mood, baseline, 10 * MOOD_BASELINE_SECONDS, baseline)
    assert one_day.valence > mood.valence
    assert abs(ten_days.valence - baseline.valence) < 0.05


def test_compute_intensity_range_and_recency() -> None:
    pad = PAD(0.5, 0.6, 0.5)
    mood = PAD(0.1, 0.3, 0.5)
    fresh = compute_intensity(pad, mood, pad.arousal, 1.0)
    stale = compute_intensity(pad, mood, pad.arousal, 0.0)
    assert 0.0 <= stale < fresh <= 1.0


def test_habituation_ratio() -> None:
    delta = PAD(0.2, 0.1, -0.1)
    assert apply_habituation(delta, 0) == delta
    assert apply_habituation(delta, 1).valence == pytest.approx(0.2 * 0.7)
    assert apply_habituation(delta, 2).valence == pytest.approx(0.2 * 0.49)
    assert apply_habituation(delta, 2, factor=0.5).valence == pytest.approx(0.05)
