"""交互刺激（A/B/C 三类，计划书 5.2.6b）。

- **A 类**：前端上报即触发情绪（摸头、戳身体、被戏弄…）
- **B 类**：后端内部推导（抚摸后的余韵、任务结果…）
- **C 类**：只更新状态、不产生 PAD 增量（拖拽开始、双击、窗口恢复）

显式区分 C 类很重要：否则用户拖一下窗口、开个面板，情绪就乱跳。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.emotion.models import Stimulus, StimulusSource
from app.emotion.stimuli.catalog import StimulusCatalog, load_catalog

__all__ = [
    "INTERACTION_CLASS_A",
    "INTERACTION_CLASS_B",
    "INTERACTION_CLASS_C",
    "InteractionOutcome",
    "classify_interaction",
]

# 前端上报且**产生情绪**的交互
INTERACTION_CLASS_A: frozenset[str] = frozenset(
    {
        "pat_head",
        "touch_face",
        "poke_body",
        "dragged",
        "teased",
        "interrupted",
        "window_minimized",
    }
)

# 前端上报但**只记状态**的交互
INTERACTION_CLASS_C: frozenset[str] = frozenset(
    {
        "drag_start",
        "drag_end",
        "double_click",
        "window_restored",
    }
)

# 后端内部推导
INTERACTION_CLASS_B: frozenset[str] = frozenset(
    {
        "content_after_pat",
        "task_success",
        "task_fail",
        "gift",
        "user_returned",
    }
)


@dataclass(frozen=True)
class InteractionOutcome:
    """一次交互事件的处理结果。"""

    stimulus: Stimulus | None = None
    tracked_only: bool = False
    note: str = ""


def classify_interaction(
    event_type: str,
    *,
    count: int = 1,
    area: str = "",
    catalog: StimulusCatalog | None = None,
) -> InteractionOutcome:
    """把前端事件翻译成刺激（可能是 ``None``：C 类只跟踪）。"""
    cat = catalog or load_catalog()
    if event_type in INTERACTION_CLASS_C:
        return InteractionOutcome(tracked_only=True, note="class_c")
    if event_type not in INTERACTION_CLASS_A:
        return InteractionOutcome(tracked_only=True, note="unknown_event")
    definition = cat.get(event_type)
    if definition is None:
        return InteractionOutcome(tracked_only=True, note="no_definition")
    magnitude = 1.0
    if event_type == "teased":
        # 反复戳弄：越多次越生气
        magnitude = min(2.0, 0.8 + 0.1 * max(1, count))
    return InteractionOutcome(
        stimulus=Stimulus(
            source=StimulusSource.INTERACTION,
            tag=event_type,
            magnitude=magnitude,
            dval=definition.dval,
            darousal=definition.darousal,
            ddominance=definition.ddominance,
            confidence=0.95,
            note=area,
        ),
        note="class_a",
    )
