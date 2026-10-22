"""文本情感分析（Level 1 词典 + Level 2 轻量 LLM，计划书 5.2.6a）。

Level 1：词典 + 规则，零成本、<1ms，覆盖高频明确场景；
Level 2：**仅在 Level 1 未命中且文本较长时**调用轻量 LLM（强制 JSON，48 token）。

两条流水线都只产出 ``Stimulus``，不直接改情绪状态（裁决权在引擎）。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.emotion.models import LLMEmotionHint, Stimulus, StimulusSource
from app.emotion.stimuli.catalog import StimulusCatalog, load_catalog
from app.emotion.stimuli.lexicon import NEGATIONS, Lexicon, load_lexicon

log = logging.getLogger(__name__)

__all__ = ["TextAnalysis", "analyze_text", "analyze_with_llm"]

# Level 2 触发阈值：文本太短时词典没命中基本就是寒暄
LEVEL2_MIN_LENGTH = 8
NEGATION_WINDOW = 3


@dataclass(frozen=True)
class TextAnalysis:
    """一次文本分析的结果。"""

    stimuli: tuple[Stimulus, ...] = ()
    hit: bool = False
    confidence: float = 0.0
    level: int = 1
    note: str = ""


def _negated(text: str, index: int) -> bool:
    """情感词前是否紧跟否定词。"""
    prefix = text[max(0, index - NEGATION_WINDOW) : index]
    return any(neg in prefix for neg in NEGATIONS)


def _first_match(text: str, words: tuple[str, ...]) -> tuple[str, int] | None:
    """返回最先出现的词典词及其位置。"""
    best: tuple[str, int] | None = None
    for word in words:
        idx = text.find(word)
        if idx >= 0 and (best is None or idx < best[1]):
            best = (word, idx)
    return best


def analyze_text(
    text: str,
    *,
    lexicon: Lexicon | None = None,
    catalog: StimulusCatalog | None = None,
) -> TextAnalysis:
    """Level 1 分析：词典命中 + 否定反转。"""
    lex = lexicon or load_lexicon()
    cat = catalog or load_catalog()
    if not text.strip():
        return TextAnalysis(note="empty")

    hits: list[tuple[str, str, int, float, bool]] = []  # (tag, word, index, magnitude, negated)
    groups = (
        ("user_praise", lex.praise, 1.0),
        ("user_praise", lex.strong_praise, 1.2),
        ("user_insult", lex.insult, 1.0),
        ("user_insult", lex.strong_insult, 1.2),
        ("user_sad", lex.sad, 1.0),
        ("intimate", lex.intimate, 1.0),
        ("unexpected", lex.surprise, 1.0),
        ("user_care", lex.care, 1.0),
    )
    for tag, words, magnitude in groups:
        found = _first_match(text, words)
        if found is None:
            continue
        word, index = found
        negated = _negated(text, index)
        hits.append((tag, word, index, magnitude, negated))

    if not hits:
        return TextAnalysis(note="no_lexicon_hit")

    # 同一 tag 只保留最强的一次（强夸 + 夸同时命中时不该叠加）
    best: dict[str, tuple[str, str, int, float, bool]] = {}
    for hit in hits:
        current = best.get(hit[0])
        if current is None or hit[3] > current[3]:
            best[hit[0]] = hit
    hits = sorted(best.values(), key=lambda item: item[2])

    # 亲密 + 关心 → 合并成 intimate_care（更接近"被摸头又被关心"）
    tags = {item[0] for item in hits}
    if "intimate" in tags and "user_care" in tags:
        hits = [item for item in hits if item[0] not in ("intimate", "user_care")]
        hits.append(("intimate_care", "亲密+关心", 0, 1.0, False))

    stimuli: list[Stimulus] = []
    for tag, _word, _index, magnitude, negated in hits:
        definition = cat.get(tag)
        if definition is None:
            continue
        dval = definition.dval
        if negated:
            # 极性反转：夸奖被否定 → 轻微负向；辱骂被否定 → 轻微正向
            if tag == "user_praise":
                tag = "user_insult"
                dval = -0.15
            elif tag == "user_insult":
                tag = "user_praise"
                dval = 0.15
            else:
                # 否定掉的自述情绪（我不难过）不算刺激
                continue
            definition = cat.get(tag) or definition
            magnitude = 0.5
        stimuli.append(
            Stimulus(
                source=StimulusSource.USER_TEXT,
                tag=tag,
                magnitude=magnitude,
                dval=dval,
                darousal=definition.darousal * magnitude,
                ddominance=definition.ddominance * magnitude,
                confidence=0.8,
                note="lexicon",
            )
        )

    if not stimuli:
        return TextAnalysis(note="negated_only")
    return TextAnalysis(stimuli=tuple(stimuli), hit=True, confidence=0.8, level=1)


LEVEL2_PROMPT = (
    "你是情绪标注器。只输出一个 JSON，不要解释。"
    '格式：{"polarity": -1|0|1, "intensity": 0.0-1.0, "user_emotion": "sad|angry|happy|neutral",'
    ' "tag": "user_praise|user_insult|user_vent|user_care|intimate|unexpected|neutral",'
    ' "confidence": 0.0-1.0}\n\n用户输入：'
)

_TAG_MAP = {
    "user_praise": "user_praise",
    "user_insult": "user_insult",
    "user_vent": "user_sad",
    "user_care": "user_care",
    "intimate": "intimate",
    "unexpected": "unexpected",
    "neutral": "",
}


async def analyze_with_llm(
    text: str,
    provider: Any,
    *,
    catalog: StimulusCatalog | None = None,
) -> TextAnalysis:
    """Level 2：轻量 LLM 标注（只做分类，不生成回复）。

    坏 JSON / 超时都不影响主流程：返回空分析，由调用方继续用 Level 1 的结果。
    """
    cat = catalog or load_catalog()
    if len(text.strip()) < LEVEL2_MIN_LENGTH:
        return TextAnalysis(note="too_short")
    try:
        from app.providers.base import ChatMessage

        result = await provider.chat(
            [
                ChatMessage(role="system", content=LEVEL2_PROMPT),
                ChatMessage(role="user", content=text),
            ],
            temperature=0.0,
            max_tokens=48,
        )
        payload = _parse_json_object(result.content)
    except Exception as exc:  # noqa: BLE001 - 标注失败不能影响对话
        log.warning("Level2 情绪标注失败: %s", exc)
        return TextAnalysis(note="llm_failed")
    if not payload:
        return TextAnalysis(note="llm_bad_json")

    tag = _TAG_MAP.get(str(payload.get("tag", "")), "")
    if not tag:
        return TextAnalysis(note="llm_neutral")
    definition = cat.get(tag)
    if definition is None:
        return TextAnalysis(note="unknown_tag")
    try:
        intensity = max(0.0, min(1.0, float(payload.get("intensity", 0.5))))
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.5))))
    except (TypeError, ValueError):
        intensity, confidence = 0.5, 0.4
    return TextAnalysis(
        stimuli=(
            Stimulus(
                source=StimulusSource.USER_TEXT,
                tag=tag,
                magnitude=0.5 + 0.5 * intensity,
                dval=definition.dval,
                darousal=definition.darousal,
                ddominance=definition.ddominance,
                confidence=confidence,
                note="llm_level2",
            ),
        ),
        hit=True,
        confidence=confidence,
        level=2,
    )


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """从模型输出里抠出 JSON 对象（容忍 ``` 围栏与前后废话）。"""
    cleaned = re.sub(r"```[a-zA-Z]*", "", text).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def hint_from_payload(payload: dict[str, Any] | None) -> LLMEmotionHint:
    """把 ``<<<MOOD>>>`` 的 JSON 转成 LLM 建议（供引擎裁决）。"""
    if not isinstance(payload, dict):
        return LLMEmotionHint()
    emotion = payload.get("emotion")
    if not isinstance(emotion, dict):
        return LLMEmotionHint()
    try:
        return LLMEmotionHint(
            label=(str(emotion["label"]) if emotion.get("label") else None),
            dval=float(emotion.get("delta_valence", 0.0) or 0.0),
            darousal=float(emotion.get("delta_arousal", 0.0) or 0.0),
            ddominance=float(emotion.get("delta_dominance", 0.0) or 0.0),
            confidence=float(emotion.get("confidence", 0.0) or 0.0),
        )
    except (TypeError, ValueError):
        return LLMEmotionHint()
