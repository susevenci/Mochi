"""Prompt 注入：把"此刻的内心状态"翻译成模型能用的自然语言（计划书 5.2.10）。

原则：**只给自然语言，不给 PAD 数值**（数值对模型的语气没有帮助，
反而容易泄漏实现细节）。数值只在调试面板里看。
"""

from __future__ import annotations

from app.config.character_card import CharacterCard
from app.emotion.labels import LabelCatalog, load_catalog
from app.emotion.models import EmotionSnapshot, StyleConstraints

__all__ = ["build_prompt_block", "build_style_constraints", "format_style_constraints"]

_LABEL_TEXT = {
    "neutral": "平静",
    "happy": "开心",
    "excited": "兴奋",
    "amused": "觉得好笑",
    "affectionate": "亲近、黏人",
    "shy": "害羞",
    "proud": "得意",
    "curious": "好奇",
    "sleepy": "犯困",
    "bored": "无聊",
    "lonely": "寂寞",
    "sad": "难过",
    "worried": "担心",
    "angry": "生气",
    "hurt": "委屈",
    "surprised": "惊讶",
}


def _valence_text(value: float) -> str:
    if value > 0.3:
        return "偏正面"
    if value > 0.08:
        return "略微偏正面"
    if value < -0.3:
        return "偏负面"
    if value < -0.08:
        return "略微偏负面"
    return "平"


def _arousal_text(value: float) -> str:
    if value > 0.7:
        return "很激动"
    if value > 0.45:
        return "偏亢奋"
    if value < 0.2:
        return "很平静"
    return "中等"


def _dominance_text(value: float) -> str:
    if value > 0.65:
        return "很有气势"
    if value < 0.35:
        return "气势偏弱"
    return "与平时差不多"


def build_prompt_block(
    snapshot: EmotionSnapshot,
    card: CharacterCard | None = None,
    catalog: LabelCatalog | None = None,
) -> str:
    """生成【你此刻的内心状态】文本块。"""
    cat = catalog or load_catalog()
    primary = _LABEL_TEXT.get(snapshot.label, snapshot.label)
    secondary = _LABEL_TEXT.get(snapshot.secondary_label or "", "")
    header = f"情绪：{primary}"
    if secondary:
        header += f"（主）+ {secondary}（次）"
    lines = [
        "【你此刻的内心状态】",
        f"{header}，强度 {snapshot.intensity:.2f}/1.00",
        f"  · 愉悦度 {_valence_text(snapshot.pad.valence)}"
        f"  · 精神唤醒 {_arousal_text(snapshot.pad.arousal)}"
        f"  · 气势 {_dominance_text(snapshot.pad.dominance)}",
    ]
    if snapshot.causes:
        last = snapshot.causes[-1]
        lines.append(f"起因：{last.stimulus}（{last.source}）")
    lines.append(
        f"今日心境：{_LABEL_TEXT.get(snapshot.mood_label, snapshot.mood_label)}"
        f"（愉悦度 {_valence_text(snapshot.mood.valence)}）"
    )
    lines.append(f"与用户的关系：亲密度 {snapshot.affinity:.2f}，信任 {snapshot.trust:.2f}")
    if card is not None and card.persona.label_bias:
        lines.append("记住你本来就是这个性格，别演过头。")
    label_def = cat.get(snapshot.label)
    if label_def is not None and label_def.style:
        lines.append("表现提示：" + "；".join(label_def.style))
    return "\n".join(lines)


def build_style_constraints(
    snapshot: EmotionSnapshot,
    card: CharacterCard | None = None,
    catalog: LabelCatalog | None = None,
) -> StyleConstraints:
    """把情绪翻译成表达约束（字数、语气词、禁止项）。"""
    cat = catalog or load_catalog()
    arousal = snapshot.pad.arousal
    dominance = snapshot.pad.dominance
    max_len = 60
    allow_exclamation = arousal > 0.7
    allow_ellipsis = arousal < 0.6
    allow_hesitation = dominance < 0.35
    allow_teasing = dominance > 0.65

    hints: list[str] = []
    if arousal > 0.7:
        max_len = 40
        hints.append("可以更激动一点，但别刷屏")
    elif arousal < 0.25:
        max_len = 30
        hints.append("慢一点、少一点")
    if dominance < 0.35:
        hints.append("可以有点犹豫")
    if dominance > 0.65:
        hints.append("可以调侃用户")
    hints.append("不要直白说出自己的情绪")

    interjections: list[str] = []
    if card is not None:
        interjections = list(card.persona.interjections.get(snapshot.label, []))
    if not interjections:
        label_def = cat.get(snapshot.label)
        if label_def is not None:
            interjections = list(label_def.interjections)

    forbidden = ("命令句式", "直白地说出情绪")
    return StyleConstraints(
        max_len=max_len,
        allow_exclamation=allow_exclamation,
        allow_ellipsis=allow_ellipsis,
        allow_hesitation=allow_hesitation,
        allow_teasing=allow_teasing,
        forbidden=forbidden,
        interjections=tuple(interjections),
        hints=tuple(hints),
    )


def format_style_constraints(constraints: StyleConstraints) -> str:
    """把表达约束渲染成 prompt 文本（与情绪块同属"结尾高注意力"区）。"""
    lines = [
        "【此刻的表达约束】",
        f"- 回复不超过 {constraints.max_len} 字",
        "- 允许感叹号" if constraints.allow_exclamation else "- 少用感叹号",
        "- 允许省略号" if constraints.allow_ellipsis else "- 少用省略号",
        "- 可以有点犹豫" if constraints.allow_hesitation else "- 说话干脆一点",
        "- 可以轻轻调侃" if constraints.allow_teasing else "- 不要调侃用户",
    ]
    if constraints.interjections:
        lines.append("- 可以自然使用这些语气词：" + "、".join(constraints.interjections[:4]))
    if constraints.forbidden:
        lines.append("- 不要出现：" + "、".join(constraints.forbidden))
    lines.extend(f"- {hint}" for hint in constraints.hints)
    return "\n".join(lines)
