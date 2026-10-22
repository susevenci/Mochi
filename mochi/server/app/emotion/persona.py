"""人格调制（计划书 5.2.7）：同一刺激，不同人格不同反应。

调制公式（计划书 5.2.7）：

```
g = persona.reactivity[category]
g *= mood 偏差修正（心情差 → 正性打折、负性放大）
g *= 关系修正（affinity / trust）
g *= magnitude * (0.5 + 0.5 * confidence)
new = soft_step(current, delta * g, lo, hi)
```

本模块是纯函数：只读 persona 与 state，不改任何东西。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.character_card import Persona
from app.emotion.models import PAD, EmotionState, Stimulus
from app.utils.mathx import soft_step

__all__ = [
    "DEFAULT_BASELINE",
    "baseline_mood",
    "effective_tau",
    "initial_pad",
    "is_label_allowed",
    "modulate",
    "reactivity_for",
]

DEFAULT_BASELINE = PAD(0.10, 0.35, 0.55)
DEFAULT_INITIAL = PAD(0.10, 0.35, 0.55)


def baseline_mood(persona: Persona) -> PAD:
    """人格基线心境（mood 的回归中心）。"""
    if not persona.baseline_mood:
        return DEFAULT_BASELINE
    return PAD.from_dict(persona.baseline_mood, DEFAULT_BASELINE).clamped()


def initial_pad(persona: Persona) -> PAD:
    """初始情绪状态。"""
    if not persona.initial_pad:
        return DEFAULT_INITIAL
    return PAD.from_dict(persona.initial_pad, DEFAULT_INITIAL).clamped()


def effective_tau(persona: Persona, base_tau: float) -> float:
    """人格影响衰减速度：``tau = base_tau * decay_multiplier``。"""
    multiplier = max(0.1, float(persona.decay_multiplier))
    return max(1.0, base_tau * multiplier)


def reactivity_for(persona: Persona, category: str) -> float:
    """刺激类别的反应增益（缺省 1.0）。"""
    return float(persona.reactivity.get(category, 1.0))


@dataclass(frozen=True)
class Modulation:
    """调制结果：新的 PAD 与实际增益（调试用）。"""

    pad: PAD
    gain: float


def modulate(
    stimulus: Stimulus, persona: Persona, state: EmotionState, category: str = ""
) -> Modulation:
    """把刺激调制成实际的 PAD 变化（软饱和，不越界）。"""
    gain = reactivity_for(persona, category or "default")

    mood_bias = state.mood.valence
    if stimulus.dval > 0:
        # 心情差 → 好话听不进去
        gain *= 1.0 - 0.35 * max(0.0, -mood_bias)
    else:
        # 心情差 → 更容易被刺痛
        gain *= 1.0 + 0.45 * max(0.0, -mood_bias)

    if stimulus.dval > 0:
        gain *= 0.7 + 0.6 * state.affinity
    else:
        gain *= 1.0 + 0.3 * state.trust

    gain *= max(0.0, stimulus.magnitude) * (0.5 + 0.5 * max(0.0, stimulus.confidence))

    pad = PAD(
        valence=soft_step(state.pad.valence, stimulus.dval * gain, -1.0, 1.0),
        arousal=soft_step(state.pad.arousal, stimulus.darousal * gain, 0.0, 1.0),
        dominance=soft_step(state.pad.dominance, stimulus.ddominance * gain, 0.0, 1.0),
    ).clamped()
    return Modulation(pad=pad, gain=gain)


def is_label_allowed(persona: Persona, label: str, state: EmotionState) -> bool:
    """标签白名单：禁用标签 + 解锁规则。"""
    if label in persona.forbidden_labels:
        for rule in persona.unlock_rules:
            if not isinstance(rule, dict) or str(rule.get("label")) != label:
                continue
            condition = str(rule.get("condition", ""))
            if _eval_unlock(condition, state):
                return True
        return False
    return True


def _eval_unlock(condition: str, state: EmotionState) -> bool:
    """极简解锁条件求值：只支持 ``field op value`` 三段式（不执行任意表达式）。"""
    if not condition:
        return False
    parts = condition.replace(">", " > ").replace("<", " < ").split()
    if len(parts) != 3:
        return False
    field, op, raw = parts
    values = {
        "affinity": state.affinity,
        "trust": state.trust,
        "patience": state.patience,
        "intensity": state.intensity,
    }
    if field not in values:
        return False
    try:
        target = float(raw)
    except ValueError:
        return False
    current = values[field]
    if op == ">":
        return current > target
    if op == "<":
        return current < target
    return False
