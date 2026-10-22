"""情感引擎的数据结构（计划书 5.2.3）。

全部使用 **frozen dataclass**：状态一旦产生就不能被原地改写，
变更一律通过 ``dataclasses.replace`` 返回新对象。

这样调试面板拿到的快照不会被 250ms 的 tick 偷偷改掉（不变量 I3）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

__all__ = [
    "EmotionCause",
    "EmotionSnapshot",
    "EmotionState",
    "LLMEmotionHint",
    "PAD",
    "ProactiveIntent",
    "Stimulus",
    "StimulusSource",
    "StyleConstraints",
]


class StimulusSource(StrEnum):
    """刺激来源：10 值封闭枚举（计划书 6.5.5）。

    ``source`` 表示"刺激从哪个通道来"，与开放的 ``tag``（具体是什么刺激）正交。
    """

    USER_TEXT = "user_text"
    USER_VOICE = "user_voice"
    INTERACTION = "interaction"
    TIME_RHYTHM = "time_rhythm"
    RANDOM = "random"
    TASK_RESULT = "task_result"
    SYSTEM = "system"
    LLM_HINT = "llm_hint"
    REUNION = "reunion"
    PROACTIVE = "proactive"


@dataclass(frozen=True)
class PAD:
    """PAD 三维：效价 [-1,1] / 唤醒 [0,1] / 支配 [0,1]（区间不对称！）。"""

    valence: float = 0.05
    arousal: float = 0.30
    dominance: float = 0.55

    def clamped(self) -> PAD:
        from app.utils.mathx import soft_clamp

        return PAD(
            valence=soft_clamp(self.valence, -1.0, 1.0),
            arousal=soft_clamp(self.arousal, 0.0, 1.0),
            dominance=soft_clamp(self.dominance, 0.0, 1.0),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "valence": round(self.valence, 4),
            "arousal": round(self.arousal, 4),
            "dominance": round(self.dominance, 4),
        }

    @classmethod
    def from_dict(cls, raw: Any, default: PAD | None = None) -> PAD:
        base = default or cls()
        if not isinstance(raw, dict):
            return base
        return cls(
            valence=float(raw.get("valence", base.valence)),
            arousal=float(raw.get("arousal", base.arousal)),
            dominance=float(raw.get("dominance", base.dominance)),
        )

    def distance_to(
        self, other: PAD, weights: tuple[float, float, float] = (1.0, 0.85, 0.55)
    ) -> float:
        """加权欧氏距离（支配维度权重最低，它是"辅助区分维度"）。"""
        wv, wa, wd = weights
        dv = self.valence - other.valence
        da = self.arousal - other.arousal
        dd = self.dominance - other.dominance
        return (wv * dv * dv + wa * da * da + wd * dd * dd) ** 0.5


@dataclass(frozen=True)
class Stimulus:
    """一次刺激：引擎的唯一输入。"""

    source: StimulusSource
    tag: str
    magnitude: float = 1.0
    dval: float = 0.0
    darousal: float = 0.0
    ddominance: float = 0.0
    confidence: float = 1.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "tag": self.tag,
            "magnitude": round(self.magnitude, 4),
            "dval": round(self.dval, 4),
            "darousal": round(self.darousal, 4),
            "ddominance": round(self.ddominance, 4),
            "confidence": round(self.confidence, 4),
            "note": self.note,
        }


@dataclass(frozen=True)
class LLMEmotionHint:
    """Roleplay 层回传的 ``<<<MOOD>>>`` 建议（只是建议，引擎有否决权）。"""

    label: str | None = None
    dval: float = 0.0
    darousal: float = 0.0
    ddominance: float = 0.0
    confidence: float = 1.0
    note: str = ""


@dataclass(frozen=True)
class EmotionCause:
    """一次状态变化的溯源记录（调试面板时间轴的悬停内容）。"""

    ts: float
    source: str
    stimulus: str
    delta: PAD
    resulting_label: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": round(self.ts, 3),
            "source": self.source,
            "stimulus": self.stimulus,
            "delta": self.delta.to_dict(),
            "resulting_label": self.resulting_label,
            "note": self.note,
        }


@dataclass(frozen=True)
class StyleConstraints:
    """注入 prompt 的表达约束（引擎给约束，LLM 负责执行）。"""

    max_len: int = 60
    allow_exclamation: bool = False
    allow_ellipsis: bool = True
    allow_hesitation: bool = False
    allow_teasing: bool = False
    forbidden: tuple[str, ...] = ()
    interjections: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_len": self.max_len,
            "allow_exclamation": self.allow_exclamation,
            "allow_ellipsis": self.allow_ellipsis,
            "allow_hesitation": self.allow_hesitation,
            "allow_teasing": self.allow_teasing,
            "forbidden": list(self.forbidden),
            "interjections": list(self.interjections),
            "hints": list(self.hints),
        }


@dataclass(frozen=True)
class ProactiveIntent:
    """主动搭话意图（引擎决定"要不要开口"，文案由角色卡模板给出）。"""

    kind: str
    text: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "emotion_label": self.label}


@dataclass(frozen=True)
class EmotionState:
    """引擎的持久状态（快变量 + 慢变量 + 关系量 + 溯源）。"""

    pad: PAD = field(default_factory=PAD)
    label: str = "neutral"
    secondary_label: str | None = None
    intensity: float = 0.30
    label_confidence: float = 1.0
    mood: PAD = field(default_factory=lambda: PAD(0.10, 0.35, 0.55))
    mood_label: str = "content"
    affinity: float = 0.30
    trust: float = 0.50
    patience: float = 1.00
    updated_at: float = 0.0
    last_stimulus_at: float = 0.0
    last_interaction_at: float = 0.0
    last_label_change_at: float = 0.0
    idle_seconds: float = 0.0
    pending_greeting: str | None = None
    recent_causes: tuple[EmotionCause, ...] = ()
    label_switches: int = 0
    stimuli_seen: int = 0
    last_proactive_at: float = 0.0
    proactive_events: tuple[float, ...] = ()
    last_ambient_at: float = 0.0

    def replace(self, **changes: Any) -> EmotionState:
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pad": self.pad.to_dict(),
            "label": self.label,
            "secondary_label": self.secondary_label,
            "intensity": round(self.intensity, 4),
            "label_confidence": round(self.label_confidence, 4),
            "mood": self.mood.to_dict(),
            "mood_label": self.mood_label,
            "affinity": round(self.affinity, 4),
            "trust": round(self.trust, 4),
            "patience": round(self.patience, 4),
            "updated_at": self.updated_at,
            "last_stimulus_at": self.last_stimulus_at,
            "last_interaction_at": self.last_interaction_at,
            "last_label_change_at": self.last_label_change_at,
            "idle_seconds": round(self.idle_seconds, 3),
            "pending_greeting": self.pending_greeting,
            "recent_causes": [cause.to_dict() for cause in self.recent_causes],
            "label_switches": self.label_switches,
            "stimuli_seen": self.stimuli_seen,
            "last_proactive_at": self.last_proactive_at,
            "proactive_events": list(self.proactive_events),
            "last_ambient_at": self.last_ambient_at,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> EmotionState:
        if not isinstance(raw, dict):
            return cls()
        causes: list[EmotionCause] = []
        for item in raw.get("recent_causes") or []:
            if not isinstance(item, dict):
                continue
            causes.append(
                EmotionCause(
                    ts=float(item.get("ts", 0.0)),
                    source=str(item.get("source", StimulusSource.SYSTEM)),
                    stimulus=str(item.get("stimulus", "")),
                    delta=PAD.from_dict(item.get("delta")),
                    resulting_label=str(item.get("resulting_label", "neutral")),
                    note=str(item.get("note", "")),
                )
            )
        return cls(
            pad=PAD.from_dict(raw.get("pad")),
            label=str(raw.get("label", "neutral")),
            secondary_label=raw.get("secondary_label"),
            intensity=float(raw.get("intensity", 0.3)),
            label_confidence=float(raw.get("label_confidence", 1.0)),
            mood=PAD.from_dict(raw.get("mood")),
            mood_label=str(raw.get("mood_label", "content")),
            affinity=float(raw.get("affinity", 0.3)),
            trust=float(raw.get("trust", 0.5)),
            patience=float(raw.get("patience", 1.0)),
            updated_at=float(raw.get("updated_at", 0.0)),
            last_stimulus_at=float(raw.get("last_stimulus_at", 0.0)),
            last_interaction_at=float(raw.get("last_interaction_at", 0.0)),
            last_label_change_at=float(raw.get("last_label_change_at", 0.0)),
            idle_seconds=float(raw.get("idle_seconds", 0.0)),
            pending_greeting=raw.get("pending_greeting"),
            recent_causes=tuple(causes),
            label_switches=int(raw.get("label_switches", 0)),
            stimuli_seen=int(raw.get("stimuli_seen", 0)),
            last_proactive_at=float(raw.get("last_proactive_at", 0.0)),
            proactive_events=tuple(float(x) for x in (raw.get("proactive_events") or [])),
            last_ambient_at=float(raw.get("last_ambient_at", 0.0)),
        )


@dataclass(frozen=True)
class EmotionSnapshot:
    """引擎对外的只读视图：广播、prompt 注入、表现映射都用它（不变量 I3）。"""

    pad: PAD
    label: str
    secondary_label: str | None
    intensity: float
    label_confidence: float
    mood: PAD
    mood_label: str
    affinity: float
    trust: float
    patience: float
    idle_seconds: float
    causes: tuple[EmotionCause, ...] = ()
    pending_greeting: str | None = None
    label_changed: bool = False
    reason: str = ""
    ts: float = 0.0

    @classmethod
    def from_state(
        cls, state: EmotionState, *, label_changed: bool = False, reason: str = ""
    ) -> EmotionSnapshot:
        return cls(
            pad=state.pad,
            label=state.label,
            secondary_label=state.secondary_label,
            intensity=state.intensity,
            label_confidence=state.label_confidence,
            mood=state.mood,
            mood_label=state.mood_label,
            affinity=state.affinity,
            trust=state.trust,
            patience=state.patience,
            idle_seconds=state.idle_seconds,
            causes=state.recent_causes,
            pending_greeting=state.pending_greeting,
            label_changed=label_changed,
            reason=reason,
            ts=state.updated_at,
        )

    def to_payload(self) -> dict[str, Any]:
        """``emotion.update`` 的载荷（不含表现部分，表现走 ``performance.cue``）。"""
        return {
            "pad": self.pad.to_dict(),
            "label": self.label,
            "secondary_label": self.secondary_label,
            "intensity": round(self.intensity, 4),
            "label_confidence": round(self.label_confidence, 4),
            "mood": self.mood.to_dict(),
            "mood_label": self.mood_label,
            "affinity": round(self.affinity, 4),
            "trust": round(self.trust, 4),
            "patience": round(self.patience, 4),
            "idle_seconds": round(self.idle_seconds, 3),
            "causes": [cause.to_dict() for cause in self.causes[-10:]],
            "pending_greeting": self.pending_greeting,
            "label_changed": self.label_changed,
            "reason": self.reason,
            "ts": round(self.ts, 3),
        }
