"""昼夜节律（T3-16）：时间本身也是刺激源。

原则：
- 深夜只降低唤醒与愉悦度，不产生"事件"；
- 节律是**慢变量**，由 ``update_mood`` 的基线偏移体现，不直接改 pad；
- 具体标签仍由 PAD 推导，不在代码里硬写"凌晨一定 sleepy"。
"""

from __future__ import annotations

from app.emotion.models import PAD

__all__ = ["ambient_tag_for_hour", "circadian_baseline", "circadian_scale"]


def circadian_scale(hour: float) -> tuple[float, float]:
    """返回（唤醒倍率，愉悦偏移）。

    02:00 最低（0.72 / -0.05），14:00 左右最高（1.05 / +0.03）。
    用余弦近似，避免引入时区/日出日落库。
    """
    import math

    # 以 14:00 为峰值、02:00 为谷值
    phase = (hour - 14.0) / 24.0 * 2.0 * math.pi
    wave = math.cos(phase)  # 14:00 -> 1, 02:00 -> -1
    arousal_scale = 0.885 + 0.165 * wave
    valence_offset = 0.03 * wave - 0.01
    return arousal_scale, valence_offset


def circadian_baseline(baseline: PAD, hour: float) -> PAD:
    """把人格基线按时段做小幅偏移（不改变人格本身）。"""
    arousal_scale, valence_offset = circadian_scale(hour)
    return PAD(
        valence=max(-1.0, min(1.0, baseline.valence + valence_offset)),
        arousal=max(0.0, min(1.0, baseline.arousal * arousal_scale)),
        dominance=baseline.dominance,
    )


def ambient_tag_for_hour(hour: float) -> str | None:
    """深夜/午后可能出现的自发刺激标签；其余时段返回 ``None``。"""
    if hour >= 23.0 or hour < 6.0:
        return "sleepy_yawn"
    if 13.0 <= hour < 15.0:
        return "daydream"
    return None
