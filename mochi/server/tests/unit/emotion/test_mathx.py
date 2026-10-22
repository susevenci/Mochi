"""七个计算原语的数值性质（T3-03）。"""

from __future__ import annotations

import math

import pytest

from app.utils.mathx import clamp01, exp_decay, gaussian_score, soft_clamp, soft_step


def test_soft_step_middle_is_linear_and_zero_is_identity() -> None:
    assert soft_step(0.0, 0.0, -1.0, 1.0) == 0.0
    assert soft_step(0.0, 0.1, -1.0, 1.0) == pytest.approx(0.1)
    assert soft_step(0.0, -0.1, -1.0, 1.0) == pytest.approx(-0.1)


def test_soft_step_never_crosses_boundary() -> None:
    assert soft_step(1.0, 0.5, -1.0, 1.0) == 1.0
    assert soft_step(-1.0, -0.5, -1.0, 1.0) == -1.0
    # 靠近边界时实际步长被压缩
    assert soft_step(0.9, 0.2, -1.0, 1.0) < 1.0


def test_soft_clamp_never_exceeds_and_keeps_middle() -> None:
    assert soft_clamp(2.0, -1.0, 1.0) == 1.0
    assert soft_clamp(-2.0, -1.0, 1.0) == -1.0
    assert soft_clamp(0.4, -1.0, 1.0) == 0.4
    assert soft_clamp(0.0, 1.0, 1.0) == 1.0


def test_exp_decay_half_life() -> None:
    tau = 300.0
    half = tau * math.log(2.0)
    assert exp_decay(1.0, 0.0, 0.0, tau) == 1.0
    assert exp_decay(1.0, 0.0, half, tau) == pytest.approx(0.5, rel=1e-6)
    assert exp_decay(1.0, 0.0, 10 * tau, tau) < 0.001
    assert exp_decay(1.0, 0.0, 1.0, 0.0) == 0.0


def test_gaussian_score_monotonic() -> None:
    assert gaussian_score(0.0, 0.2) == 1.0
    assert gaussian_score(0.1, 0.2) > gaussian_score(0.3, 0.2)
    assert gaussian_score(0.1, 0.0) == 0.0


def test_clamp01() -> None:
    assert clamp01(-0.2) == 0.0
    assert clamp01(0.3) == 0.3
    assert clamp01(1.4) == 1.0
