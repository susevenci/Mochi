"""扮演层：纯净上下文 + 流式生成 + 双通道解析（计划书 5.1.2b）。

职责边界：
- 不做情绪计算（S3 接入 EmotionEngine 只读状态块）
- 不做工具调用（I2：prompt 中无工具 schema）
- 只负责"把这一轮说好"
"""

from __future__ import annotations

import logging
import time

from app.memory.context_builder import ContextBuilder
from app.memory.short_term import ShortTermMemory
from app.providers.base import LLMError, LLMProvider

from .events import EventSink, FinalPayload
from .mood_parser import MoodStreamParser
from .turn_registry import Turn

log = logging.getLogger(__name__)


class RoleplayService:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        temperature: float,
        builder: ContextBuilder,
        history: ShortTermMemory,
        max_tokens: int = 400,
    ) -> None:
        self._provider = provider
        self._model = model
        self._temperature = temperature
        self._builder = builder
        self._history = history
        self._max_tokens = max_tokens

    async def reply(self, turn: Turn, user_text: str, sink: EventSink) -> None:
        started = time.perf_counter()
        first_token_ms: int | None = None
        parser = MoodStreamParser()
        messages = self._builder.build(self._history.recent(), user_text)
        prompt_chars = sum(len(message.content) for message in messages)
        log.info(
            "roleplay start turn=%s messages=%d prompt_chars=%d",
            turn.id,
            len(messages),
            prompt_chars,
        )

        try:
            async for chunk in self._provider.stream(
                messages,
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            ):
                if turn.is_cancelled:
                    break
                out = parser.feed(chunk)
                if out:
                    if first_token_ms is None:
                        first_token_ms = int((time.perf_counter() - started) * 1000)
                    await sink.delta(turn.id, out)

            result = parser.finish()
            latency_ms = int((time.perf_counter() - started) * 1000)

            if turn.is_cancelled:
                log.info(
                    "roleplay cancelled turn=%s first_token_ms=%s latency_ms=%d",
                    turn.id,
                    first_token_ms,
                    latency_ms,
                )
                await sink.final(
                    turn.id,
                    FinalPayload(
                        text=result.text,
                        route="chat",
                        error="TURN_CANCELLED",
                        first_token_ms=first_token_ms,
                        latency_ms=latency_ms,
                    ),
                )
                return

            if result.text:
                self._history.append(user_text, result.text)
            if not result.parsed:
                log.warning("roleplay mood json missing turn=%s note=%s", turn.id, result.note)

            log.info(
                "roleplay done turn=%s first_token_ms=%s latency_ms=%d chars=%d parsed=%s",
                turn.id,
                first_token_ms,
                latency_ms,
                len(result.text),
                result.parsed,
            )
            await sink.final(
                turn.id,
                FinalPayload(
                    text=result.text,
                    route="chat",
                    emotion=result.emotion,
                    action=result.action,
                    first_token_ms=first_token_ms,
                    latency_ms=latency_ms,
                ),
            )
        except LLMError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            log.warning(
                "roleplay llm error turn=%s code=%s detail=%s",
                turn.id,
                exc.code,
                exc.detail,
            )
            # T1-13：故障不崩窗，用角色卡的人设化降级文案
            await sink.final(
                turn.id,
                FinalPayload(
                    text=self._builder.card.fallback,
                    route="chat",
                    error=exc.code,
                    latency_ms=latency_ms,
                ),
            )
