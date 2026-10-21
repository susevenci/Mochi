"""决策层：规则优先（计划书 5.1.2a）。

S1 只实现规则引擎；规则未命中一律 ``CHAT``。
LLM 兜底分类在 S6 接入，届时本节的三段式结构不变。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import StrEnum


class Route(StrEnum):
    CHAT = "chat"
    TASK = "task"
    COMMAND = "command"
    EMOTIONAL = "emotional"


@dataclass(frozen=True)
class DecisionResult:
    route: Route
    matched_rule: str | None = None
    confidence: float = 1.0
    latency_ms: int = 0


TASK_PATTERN = re.compile(r"^(帮我|请|给我).*(写|生成|搜索|查|计算|记录|提醒)")
EMOTION_WORDS = ("我好难过", "我生气了", "谢谢你", "你最棒了", "抱抱", "晚安", "滚")


def classify_rules(text: str) -> DecisionResult | None:
    """纯函数、无 IO、< 1ms。返回 None 表示需要 LLM 兜底。"""
    stripped = text.strip()
    if not stripped:
        return DecisionResult(Route.CHAT, "empty_input")
    if stripped.startswith("/"):
        return DecisionResult(Route.COMMAND, "command_prefix")
    if TASK_PATTERN.search(stripped):
        return DecisionResult(Route.TASK, "task_pattern")
    if any(word in stripped for word in EMOTION_WORDS):
        return DecisionResult(Route.EMOTIONAL, "emotion_lexicon")
    return None


class DecisionService:
    def __init__(self, confidence_threshold: float = 0.6) -> None:
        self._threshold = confidence_threshold

    async def classify(self, text: str) -> DecisionResult:
        started = time.perf_counter()
        result = classify_rules(text)
        if result is None:
            result = DecisionResult(Route.CHAT, None, confidence=0.5)
        if result.confidence < self._threshold:
            result = DecisionResult(Route.CHAT, "low_confidence", result.confidence)
        latency = int((time.perf_counter() - started) * 1000)
        return DecisionResult(result.route, result.matched_rule, result.confidence, latency)
