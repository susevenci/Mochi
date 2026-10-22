"""扮演层：纯净上下文 + 流式生成 + 双通道解析（计划书 5.1.2b）。

职责边界：
- 不做情绪计算（S3 接入 EmotionEngine 只读状态块）
- 不做工具调用（I2：prompt 中无工具 schema）
- 只负责"把这一轮说好"
"""

from __future__ import annotations

import logging
import time

from app.config.llm_settings import LLMSettingsService
from app.emotion.engine import EmotionEngine
from app.emotion.models import EmotionSnapshot
from app.emotion.prompt_block import format_style_constraints
from app.emotion.stimuli.text_analyzer import hint_from_payload
from app.memory.context_builder import ContextBuilder
from app.memory.short_term import ShortTermMemory
from app.providers.base import LLMError, LLMProvider
from app.voice.pipeline import TTSStreamer, VoiceService
from app.voice.tts.text_prep import SentenceSplitter

from .events import CuePayload, EventSink, FinalPayload
from .mood_parser import MoodStreamParser
from .performance import map_emotion
from .turn_registry import Turn

log = logging.getLogger(__name__)


class RoleplayService:
    def __init__(
        self,
        *,
        llm: LLMSettingsService,
        temperature: float,
        builder: ContextBuilder,
        history: ShortTermMemory,
        emotion: EmotionEngine | None = None,
        voice: VoiceService | None = None,
        max_tokens: int = 400,
    ) -> None:
        self._llm = llm
        self._temperature = temperature
        self._builder = builder
        self._history = history
        self._emotion = emotion
        self._voice = voice
        self._max_tokens = max_tokens

    @property
    def provider(self) -> LLMProvider:
        return self._llm.provider

    async def reply(
        self,
        turn: Turn,
        user_text: str,
        sink: EventSink,
        *,
        emotion_snapshot: EmotionSnapshot | None = None,
    ) -> None:
        started = time.perf_counter()
        first_token_ms: int | None = None
        parser = MoodStreamParser()
        frozen = emotion_snapshot
        if frozen is None and self._emotion is not None:
            frozen = self._emotion.snapshot()
        emotion_block = None
        cue = self._emotion.map_to_presentation(frozen) if self._emotion and frozen else None
        if self._emotion is not None and frozen is not None:
            # 一轮内表情/TTS 参数来自同一份不可变快照（不变量 I3）
            emotion_block = (
                self._emotion.prompt_block(frozen)
                + "\n\n"
                + format_style_constraints(self._emotion.style_constraints(frozen))
            )
        splitter = SentenceSplitter()
        tts: TTSStreamer | None = None
        if self._voice is not None:
            tts = self._voice.open_streamer(
                turn.id,
                sink,
                cue.tts if cue is not None else self._voice.default_params,
                lambda: turn.is_cancelled,
            )
        messages = self._builder.build(
            self._history.recent(),
            user_text,
            emotion_block=emotion_block,
        )
        # 每轮取一次配置快照：配置热更新后下一轮立即生效
        provider = self._llm.provider
        model = self._llm.config.model
        disable_thinking = self._llm.config.disable_thinking
        prompt_chars = sum(len(message.content) for message in messages)
        log.info(
            "roleplay start turn=%s messages=%d prompt_chars=%d model=%s thinking=%s",
            turn.id,
            len(messages),
            prompt_chars,
            model,
            "off" if disable_thinking else "on",
        )

        try:
            async for chunk in provider.stream(
                messages,
                model=model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                disable_thinking=disable_thinking,
            ):
                if turn.is_cancelled:
                    break
                out = parser.feed(chunk)
                if out:
                    if first_token_ms is None:
                        first_token_ms = int((time.perf_counter() - started) * 1000)
                    await sink.delta(turn.id, out)
                    if tts is not None:
                        for sentence in splitter.feed(out):
                            tts.feed(sentence)

            result = parser.finish()
            if tts is not None:
                for sentence in splitter.flush():
                    tts.feed(sentence)
            latency_ms = int((time.perf_counter() - started) * 1000)

            if turn.is_cancelled:
                if tts is not None:
                    tts.cancel()
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
            # 表现指令来自 turn 开始时的冻结快照，LLM 建议只影响下一轮
            if cue is not None:
                await sink.cue(
                    turn.id,
                    CuePayload(
                        emotion_label=cue.emotion_label,
                        motion=cue.motion,
                        priority=cue.priority,
                        expression=cue.expression,
                        expression_weight=cue.expression_weight,
                        secondary_expression=cue.secondary_expression,
                        secondary_weight=cue.secondary_weight,
                        auto_release_ms=cue.auto_release_ms,
                        tts=cue.tts.to_dict(),
                        params=cue.params,
                        style_hints=list(cue.style_hints),
                    ),
                )
            else:
                legacy = map_emotion(result.emotion)
                await sink.cue(
                    turn.id,
                    CuePayload(
                        emotion_label=legacy.emotion_label,
                        motion=legacy.motion,
                        priority=legacy.priority,
                        expression=legacy.expression,
                    ),
                )
            final_emotion = result.emotion
            if frozen is not None:
                # 字幕标签也来自引擎快照，避免"画面 shy、标签 angry"（I3）
                final_emotion = {
                    "label": frozen.label,
                    "secondary_label": frozen.secondary_label,
                    "intensity": round(frozen.intensity, 3),
                }
            await sink.final(
                turn.id,
                FinalPayload(
                    text=result.text,
                    route="chat",
                    emotion=final_emotion,
                    action=result.action,
                    first_token_ms=first_token_ms,
                    latency_ms=latency_ms,
                ),
            )
            if self._emotion is not None and result.emotion:
                # 建议在定稿后裁决，只影响下一轮的状态
                await self._emotion.apply_llm_hint(
                    hint_from_payload({"emotion": result.emotion})
                )
            if tts is not None:
                await tts.finish()
                log.info(
                    "tts done turn=%s sentences=%d first_audio_ms=%s error=%s",
                    turn.id,
                    tts.sentences,
                    tts.first_audio_ms,
                    tts.error or "-",
                )
        except LLMError as exc:
            if tts is not None:
                tts.cancel()
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
