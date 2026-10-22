"""静默期噪声（T3-16）：没有刺激时曲线也不该是一条直线。

幅度按 ``sqrt(dt)`` 缩放，保证不同 tick 粒度下的累积方差一致。
噪声只作用在 pad 上，不重置 ``idle_seconds``，因此不会破坏"冷落转 lonely"。
"""

from __future__ import annotations

import random

from app.emotion.models import PAD
from app.utils.mathx import soft_clamp

__all__ = ["noise_step"]

# 每秒标准差（很小，10 分钟累计约 0.02）
NOISE_SIGMA_PER_SQRT_SECOND = 0.0007


def noise_step(pad: PAD, rng: random.Random, dt: float) -> PAD:
    """给 PAD 加一点高斯随机游走（唤醒越高，波动略大）。"""
    if dt <= 0:
        return pad
    scale = NOISE_SIGMA_PER_SQRT_SECOND * (dt**0.5) * (0.7 + 0.6 * pad.arousal)
    return PAD(
        valence=soft_clamp(pad.valence + rng.gauss(0.0, scale), -1.0, 1.0),
        arousal=soft_clamp(pad.arousal + rng.gauss(0.0, scale), 0.0, 1.0),
        dominance=soft_clamp(pad.dominance + rng.gauss(0.0, scale), 0.0, 1.0),
    )
