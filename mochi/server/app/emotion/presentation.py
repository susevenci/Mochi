"""情绪 → 表现的映射（计划书 5.2.9）。

**唯一权威**：动作组映射表在这里（``orchestration/performance.py`` 转发到本模块），
前端只消费 ``performance.cue``，不重复维护"情绪→动作"规则（不变量 I1）。

S2 的事实：本批模型没有可用的 ``.exp3.json`` 表情文件，因此
**action_map 优先 + 参数兜底**，表情通道只在模型真的声明了表情时才用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config.character_card import CharacterCard
from app.emotion.labels import LabelCatalog, load_catalog
from app.emotion.models import EmotionSnapshot

__all__ = [
    "EMOTION_TO_MOTION",
    "HIGH_PRIORITY_LABELS",
    "IDLE_MOTION",
    "PresentationCue",
    "TtsParams",
    "map_emotion",
    "map_snapshot",
]

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

# 瞬时情绪的自动释放时长（前端 2.5s 内释放）
AUTO_RELEASE_MS: dict[str, int] = {"surprised": 2500}

# 参数兜底：模型没有表情文件时，用参数表达情绪（S2 结论）
PARAM_FALLBACK: dict[str, dict[str, float]] = {
    "shy": {"ParamAngleZ": -8.0, "ParamEyeLOpen": 0.85},
    "sad": {"ParamEyeLOpen": 0.75, "ParamAngleZ": 4.0},
    "angry": {"ParamAngleZ": -6.0, "ParamEyeLOpen": 1.0},
    "worried": {"ParamAngleZ": 3.0},
    "surprised": {"ParamEyeLOpen": 1.0},
    "sleepy": {"ParamEyeLOpen": 0.6},
    "proud": {"ParamAngleZ": -3.0},
}


@dataclass(frozen=True)
class TtsParams:
    """TTS 韵律：rate/volume 为倍率，pitch 为**百分比偏移**（+6.0 = +6%）。"""

    rate: float = 1.0
    pitch: float = 0.0
    volume: float = 1.0

    def to_dict(self) -> dict[str, float]:
        return {
            "rate": round(self.rate, 3),
            "pitch": round(self.pitch, 3),
            "volume": round(self.volume, 3),
        }


@dataclass(frozen=True)
class PresentationCue:
    """表现指令（一轮内来自同一份冻结快照，不变量 I3）。"""

    emotion_label: str
    motion: str
    priority: str = "normal"
    expression: str | None = None
    expression_weight: float = 1.0
    secondary_expression: str | None = None
    secondary_weight: float = 0.0
    auto_release_ms: int | None = None
    tts: TtsParams = field(default_factory=TtsParams)
    style_hints: tuple[str, ...] = ()
    params: dict[str, float] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "emotion_label": self.emotion_label,
            "motion": self.motion,
            "priority": self.priority,
            "expression": self.expression,
            "expression_weight": round(self.expression_weight, 3),
            "secondary_expression": self.secondary_expression,
            "secondary_weight": round(self.secondary_weight, 3),
            "auto_release_ms": self.auto_release_ms,
            "tts": self.tts.to_dict(),
            "style_hints": list(self.style_hints),
            "params": dict(self.params),
        }


def _weight_for(intensity: float) -> float:
    """克制原则：表现幅度 = 0.4 + 0.6 * intensity。"""
    return max(0.0, min(1.0, 0.4 + 0.6 * max(0.0, min(1.0, intensity))))


def _secondary_weight_for(intensity: float) -> float:
    """混合情绪的次标签权重：强情绪时次标签退让。"""
    return max(0.0, min(0.4, 0.4 - 0.2 * max(0.0, min(1.0, intensity))))


def map_emotion(emotion: dict[str, object] | None, *, fallback: str = "neutral") -> PresentationCue:
    """兼容 S2 的旧接口：直接把 LLM 给的 label 映射成表现指令。"""
    label = fallback
    if isinstance(emotion, dict):
        raw = emotion.get("label")
        if isinstance(raw, str) and raw:
            label = raw
    motion = EMOTION_TO_MOTION.get(label, IDLE_MOTION)
    priority = "high" if label in HIGH_PRIORITY_LABELS else "normal"
    return PresentationCue(emotion_label=label, motion=motion, priority=priority)


def map_snapshot(
    snapshot: EmotionSnapshot,
    card: CharacterCard | None = None,
    catalog: LabelCatalog | None = None,
) -> PresentationCue:
    """把引擎快照映射成表现指令（表达权重、动作、TTS 韵律、风格提示）。"""
    cat = catalog or load_catalog()
    label = snapshot.label
    motion = EMOTION_TO_MOTION.get(label, IDLE_MOTION)
    priority = "high" if label in HIGH_PRIORITY_LABELS else "normal"
    weight = _weight_for(snapshot.intensity)

    expression: str | None = None
    secondary_expression: str | None = None
    if card is not None:
        expression = card.presentation.emotion_expressions.get(label)
        if snapshot.secondary_label:
            secondary_expression = card.presentation.emotion_expressions.get(
                snapshot.secondary_label
            )

    tts = _merge_tts(snapshot, cat)
    hints: list[str] = []
    primary = cat.get(label)
    if primary is not None:
        hints.extend(primary.style)
    if card is not None:
        hints.extend(card.persona.interjections.get(label, [])[:0])  # 语气词不进 prompt 提示
    return PresentationCue(
        emotion_label=label,
        motion=motion,
        priority=priority,
        expression=expression,
        expression_weight=weight if expression else 0.0,
        secondary_expression=secondary_expression,
        secondary_weight=(
            _secondary_weight_for(snapshot.intensity) if secondary_expression else 0.0
        ),
        auto_release_ms=AUTO_RELEASE_MS.get(label),
        tts=tts,
        style_hints=tuple(hints),
        params=dict(PARAM_FALLBACK.get(label, {})),
    )


def _merge_tts(snapshot: EmotionSnapshot, catalog: LabelCatalog) -> TtsParams:
    """主标签与次标签的 TTS 韵律按权重加权平均。"""
    primary = catalog.get(snapshot.label)
    if primary is None:
        return TtsParams()
    rate, pitch, volume = primary.tts["rate"], primary.tts["pitch"], primary.tts["volume"]
    secondary = catalog.get(snapshot.secondary_label) if snapshot.secondary_label else None
    if secondary is not None:
        w = _secondary_weight_for(snapshot.intensity)
        rate = rate * (1.0 - w) + secondary.tts["rate"] * w
        pitch = pitch * (1.0 - w) + secondary.tts["pitch"] * w
        volume = volume * (1.0 - w) + secondary.tts["volume"] * w
    return TtsParams(rate=rate, pitch=pitch, volume=volume)
