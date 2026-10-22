"""时钟与本地时间工具。

情感引擎禁止直接调用 ``time.time()``（T3-06 的可测试性要求）：
生产时钟集中在里，测试注入 ``FakeClock`` 即可复现任意时间。
"""

from __future__ import annotations

from datetime import datetime


def system_clock() -> float:
    """返回 Unix 时间戳（秒）。"""
    import time

    return time.time()


def local_hour(timestamp: float) -> float:
    """本地小时（0–24 浮点），用于昼夜节律。"""
    moment = datetime.fromtimestamp(timestamp)
    return moment.hour + moment.minute / 60.0


def in_quiet_hours(hour: float, quiet_hours: tuple[int, int]) -> bool:
    """判断是否处于安静时段；支持跨午夜（如 23–7）。"""
    start, end = quiet_hours
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end
