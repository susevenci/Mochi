"""情绪标签 → Live2D 表现指令映射（计划书 5.2.9 的 S2 子集）。

S2 的输入来自 Roleplay 层 LLM 的 ``emotion`` 建议；S3 接入 EmotionEngine 后，
输入换成引擎裁决后的快照，本模块接口不变。

注意：``qiye_10`` 没有 ``.exp3.json`` 表情文件（碧蓝航线模型普遍如此），
因此表现完全由 motion 承担。换模型时只需改这张表。
"""

from __future__ import annotations

from dataclasses import dataclass

IDLE_MOTION = "idle"

# 标签 → 动作组名（组名来自 qiye_10.model3.json 的 Motions 键）
EMOTION_TO_MOTION: dict[str, str] = {
    "neutral": "idle",
    "happy": "touch_head",
    "excited": "touch_special",
    "amused": "touch_head",
    "affectionate": "touch_idle5",
    "shy": "touch_idle3",
    "proud": "touch_special",
    "curious": "touch_idle1",
    "sleepy": "idle10",
    "bored": "idle1",
    "lonely": "idle3",
    "sad": "idle4",
    "worried": "idle5",
    "angry": "touch_drag2",
    "hurt": "idle6",
    "surprised": "touch_special",
}

# 强情绪用 high 优先级（可以打断当前动作），日常用 normal
HIGH_PRIORITY_LABELS = {"excited", "surprised", "angry"}


@dataclass(frozen=True)
class PerformanceCue:
    emotion_label: str
    motion: str
    priority: str = "normal"
    expression: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "emotion_label": self.emotion_label,
            "motion": self.motion,
            "expression": self.expression,
            "priority": self.priority,
        }


def map_emotion(emotion: dict[str, object] | None, *, fallback: str = "neutral") -> PerformanceCue:
    """把 LLM/引擎给出的 emotion 建议映射为可执行的表现指令。"""
    label = fallback
    if isinstance(emotion, dict):
        raw = emotion.get("label")
        if isinstance(raw, str) and raw:
            label = raw
    motion = EMOTION_TO_MOTION.get(label, IDLE_MOTION)
    priority = "high" if label in HIGH_PRIORITY_LABELS else "normal"
    return PerformanceCue(emotion_label=label, motion=motion, priority=priority)
