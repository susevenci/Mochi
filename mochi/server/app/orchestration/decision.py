"""决策层：规则优先（计划书 5.1.2a）。

S1 只实现规则引擎；规则未命中一律 ``CHAT``。
LLM 兜底分类在 S6 接入，届时本节的三段式结构不变。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


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


LLM_PROMPT = (
    "判断用户这句话该走哪条路：chat=闲聊/情绪表达，task=需要工具完成的任务，"
    'emotional=明显情绪倾诉。只输出 JSON：{"route":"chat|task|emotional","confidence":0.0-1.0}。'
)


class DecisionService:
    def __init__(self, confidence_threshold: float = 0.6) -> None:
        self._threshold = confidence_threshold

    async def classify(
        self,
        text: str,
        *,
        provider: Any = None,
        route_mode: str = "auto",
    ) -> DecisionResult:
        started = time.perf_counter()
        result = classify_rules(text)
        # 显式模式：命令永远优先；其余按用户滑杆强制
        if result is not None and result.route == Route.COMMAND:
            return self._finish(result, started)
        if route_mode == "chat_only":
            return self._finish(DecisionResult(Route.CHAT, "mode_chat_only"), started)
        if route_mode == "force_agent":
            return self._finish(DecisionResult(Route.TASK, "mode_force_agent"), started)
        if result is None and provider is not None:
            result = await self._classify_llm(text, provider, started)
        if result is None:
            result = DecisionResult(Route.CHAT, None, confidence=0.5)
        if result.confidence < self._threshold:
            result = DecisionResult(Route.CHAT, "low_confidence", result.confidence)
        return self._finish(result, started)

    async def _classify_llm(
        self, text: str, provider: Any, started: float
    ) -> DecisionResult | None:
        try:
            from app.providers.base import ChatMessage

            call = provider.chat(
                [
                    ChatMessage(role="system", content=LLM_PROMPT),
                    ChatMessage(role="user", content=text),
                ],
                temperature=0.0,
                max_tokens=64,
            )
            response = await asyncio.wait_for(call, timeout=0.8)
            raw = response.content.strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return None
            payload = json.loads(match.group(0))
            route = str(payload.get("route", "chat"))
            if route not in {item.value for item in Route}:
                return None
            confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.5))))
            return DecisionResult(Route(route), "llm_classifier", confidence)
        except Exception:  # noqa: BLE001 - 决策层不允许抛错
            return None

    def _finish(self, result: DecisionResult, started: float) -> DecisionResult:
        latency = int((time.perf_counter() - started) * 1000)
        return DecisionResult(result.route, result.matched_rule, result.confidence, latency)
