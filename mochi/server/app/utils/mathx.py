"""数学原语：情感引擎唯一允许的数值运算入口（计划书 1.4.3）。

七个原语全部是**纯函数**，不读时钟、不碰状态，因此可以单测到边界：

- ``soft_step``：软饱和（越接近边界增量越小，避免"顶格后无响应"）
- ``soft_clamp``：带平滑膝部的限幅（不硬裁剪）
- ``exp_decay``：指数回归
- ``gaussian_score``：高斯核（标签推导的距离打分）
"""

from __future__ import annotations

import math

__all__ = [
    "clamp01",
    "exp_decay",
    "gaussian_score",
    "lerp",
    "soft_clamp",
    "soft_step",
]

# 让膝部函数在 x=knee 处值与斜率都等于 1 的常数：e^K - 1 = K
_KNEE_K = 1.7632228343518967


def clamp01(value: float) -> float:
    """截到 [0, 1]。"""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def lerp(start: float, end: float, ratio: float) -> float:
    """线性插值。"""
    return start + (end - start) * ratio


def _soft_knee(x: float, knee: float) -> float:
    """膝部压缩：f(0)=0, f(knee)=knee, f'(0)=f'(knee)=1（比 tanh 更"贴"线性）。"""
    if knee <= 0.0:
        return x
    ratio = x / knee
    return knee * (math.exp(_KNEE_K * ratio) - 1.0) / (math.exp(_KNEE_K) - 1.0)


def soft_clamp(value: float, lo: float, hi: float) -> float:
    """软限幅：中间线性，靠近上下界平滑压缩，且**永不越界**。

    与硬 ``clamp`` 的区别：硬裁剪会让曲线出现折角（看起来"卡住"），
    软限幅在边界附近提前减速，曲线是圆润的。
    """
    if hi <= lo:
        return lo
    if value <= lo:
        return lo
    if value >= hi:
        return hi
    knee = 0.15 * (hi - lo)
    if value - lo < knee:
        return lo + _soft_knee(value - lo, knee)
    if hi - value < knee:
        return hi - _soft_knee(hi - value, knee)
    return value


def soft_step(current: float, delta: float, lo: float, hi: float) -> float:
    """软饱和步进：越接近边界，同样大小的刺激造成的实际变化越小。

    关键性质：
    - ``delta=0`` 时恒等返回 ``current``；
    - 顶格时（room<=0）不再越界；
    - 中间区域近似线性（步长 ≈ delta）。
    """
    if delta == 0.0:
        return current
    span = hi - lo
    if span <= 0.0:
        return lo
    room = (hi - current) if delta > 0 else (current - lo)
    if room <= 0.0:
        return current
    return current + delta * min(1.0, room / (0.35 * span))


def exp_decay(current: float, target: float, dt: float, tau: float) -> float:
    """指数回归：``target + (current - target) * exp(-dt/tau)``。

    ``dt=0`` 恒等；``tau<=0`` 视为"立即到位"。
    """
    if dt <= 0.0:
        return current
    if tau <= 0.0:
        return target
    return target + (current - target) * math.exp(-dt / tau)


def gaussian_score(distance: float, radius: float) -> float:
    """高斯核打分：距离越近分值越高（radius 越大越宽容）。"""
    if radius <= 0.0:
        return 0.0
    return math.exp(-(distance**2) / (2.0 * radius**2))
