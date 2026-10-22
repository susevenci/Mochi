"""衰减与强度模型（计划书 5.2.5）：两个时间尺度的数值部分。

- 快变量 ``pad``：秒级，指数回归到 ``mood``
- 慢变量 ``mood``：小时～天级，吸收 pad 并向人格基线回归

全部是纯函数：不读时钟、不改状态，测试可以直接给 dt。
"""

from __future__ import annotations

import math

from app.emotion.models import PAD
from app.utils.mathx import clamp01, exp_decay

__all__ = [
    "MOOD_ABSORB_SECONDS",
    "MOOD_BASELINE_SECONDS",
    "apply_habituation",
    "compute_intensity",
    "decay_toward",
    "update_mood",
]

# mood 吸收 pad 的时间常数（1 小时）
MOOD_ABSORB_SECONDS = 3600.0
# mood 向人格基线回归的时间常数（1 天）
MOOD_BASELINE_SECONDS = 86400.0

# 强度公式权重（计划书 5.2.5c）
W_DEVIATION = 0.45
W_AROUSAL = 0.35
W_RECENCY = 0.20


def decay_toward(pad: PAD, mood: PAD, dt: float, tau: float) -> PAD:
    """``pad`` 指数回归到 ``mood``。

    注意 valence 的区间是 [-1,1]，arousal/dominance 是 [0,1]，各自限幅。
    """
    if dt <= 0.0:
        return pad
    return PAD(
        valence=exp_decay(pad.valence, mood.valence, dt, tau),
        arousal=exp_decay(pad.arousal, mood.arousal, dt, tau),
        dominance=exp_decay(pad.dominance, mood.dominance, dt, tau),
    ).clamped()


def update_mood(mood: PAD, pad: PAD, dt: float, baseline: PAD) -> PAD:
    """mood 慢更新：吸收 pad（1h 尺度），同时向人格基线回归（1d 尺度）。"""
    if dt <= 0.0:
        return mood
    absorb = 1.0 - math.exp(-dt / MOOD_ABSORB_SECONDS)
    relax = 1.0 - math.exp(-dt / MOOD_BASELINE_SECONDS)

    # 先吸收 pad，再向基线回归（顺序执行，避免两项叠加造成过冲）
    def step(current: float, pad_value: float, base_value: float) -> float:
        absorbed = current + (pad_value - current) * absorb
        return absorbed + (base_value - absorbed) * relax

    return PAD(
        valence=step(mood.valence, pad.valence, baseline.valence),
        arousal=step(mood.arousal, pad.arousal, baseline.arousal),
        dominance=step(mood.dominance, pad.dominance, baseline.dominance),
    ).clamped()


def compute_intensity(pad: PAD, mood: PAD, arousal: float, recency: float) -> float:
    """情绪强度 [0,1]：偏离心境的程度 + 唤醒度 + 最近被刺激的新鲜度。"""
    deviation = max(
        abs(pad.valence - mood.valence),
        abs(pad.arousal - mood.arousal),
        abs(pad.dominance - mood.dominance),
    )
    return clamp01(W_DEVIATION * deviation + W_AROUSAL * arousal + W_RECENCY * recency)


def apply_habituation(delta: PAD, recent_count: int, factor: float = 0.7) -> PAD:
    """重复刺激递减：同 tag 在窗口内第 n 次触发，幅度按 ``factor**n`` 递减。"""
    if recent_count <= 0:
        return delta
    scale = factor**recent_count
    return PAD(
        valence=delta.valence * scale,
        arousal=delta.arousal * scale,
        dominance=delta.dominance * scale,
    )
