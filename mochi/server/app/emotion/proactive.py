"""主动性（T3-17）：决定"要不要开口"，不负责文案生成。

打扰预算（计划书 5.2.6e）：
- 1 小时内最多 ``max_per_hour`` 次；
- 两次间隔至少 ``min_interval_seconds``；
- quiet_hours 内完全不主动；
- 总开关关闭或滑杆为 0 时静默。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.config.character_card import CharacterCard
from app.emotion.models import EmotionState, ProactiveIntent
from app.utils.clock import in_quiet_hours

__all__ = ["ProactiveController", "ProactiveDecision"]

DEFAULT_LINES: dict[str, tuple[str, ...]] = {
    "lonely": ("…你还在吗？", "好安静啊，陪我一会儿嘛。", "喂，别把我忘了…"),
    "bored": ("好无聊…你在忙什么？", "喂，理我一下嘛。"),
    "sad": ("我有点没精神…", "能不能陪我说说话？"),
    "sleepy": ("哈啊…有点困了。",),
}


@dataclass(frozen=True)
class ProactiveDecision:
    intent: ProactiveIntent | None
    reason: str


class ProactiveController:
    """无状态预算计算：时间与计数全部来自 ``EmotionState``。"""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    def evaluate(
        self,
        state: EmotionState,
        card: CharacterCard,
        now: float,
        *,
        local_hour: float,
    ) -> ProactiveDecision:
        cfg = card.persona.proactive
        if not cfg.enabled:
            return ProactiveDecision(None, "disabled")
        if in_quiet_hours(local_hour, cfg.quiet_hours):
            return ProactiveDecision(None, "quiet_hours")
        if state.idle_seconds < cfg.lonely_threshold_seconds:
            return ProactiveDecision(None, "not_idle_enough")
        if state.label not in ("lonely", "bored", "sad", "sleepy"):
            return ProactiveDecision(None, f"label:{state.label}")

        recent = [ts for ts in state.proactive_events if now - ts < 3600.0]
        if len(recent) >= cfg.max_per_hour:
            return ProactiveDecision(None, "budget")
        last = max(recent) if recent else 0.0
        if last and now - last < cfg.min_interval_seconds:
            return ProactiveDecision(None, "min_interval")

        lines = list(
            card.persona.proactive_lines.get(state.label) or DEFAULT_LINES.get(state.label, ())
        )
        if not lines:
            return ProactiveDecision(None, "no_lines")
        text = self._rng.choice(lines)
        return ProactiveDecision(
            ProactiveIntent(kind=state.label, text=text, label=state.label),
            "ok",
        )
