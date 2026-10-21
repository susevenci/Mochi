"""RoleplayService 测试（T1-06 / T1-13 验收）：流式、取消、故障降级。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from app.config.character_card import CharacterCard, Identity
from app.config.llm_settings import LLMConfig
from app.memory.context_builder import ContextBuilder
from app.memory.short_term import ShortTermMemory
from app.orchestration.events import CuePayload, FinalPayload
from app.orchestration.roleplay import RoleplayService
from app.orchestration.turn_registry import TurnRegistry
from app.providers.base import ChatMessage, ChatResult, LLMError


class FakeProvider:
    def __init__(self, chunks: list[str] | None = None, error: LLMError | None = None) -> None:
        self._chunks = chunks or []
        self._error = error

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.85,
        max_tokens: int = 512,
    ) -> ChatResult:
        raise NotImplementedError

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.85,
        max_tokens: int = 512,
        disable_thinking: bool = False,
    ) -> AsyncIterator[str]:
        if self._error is not None:
            raise self._error
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


class RecordingSink:
    def __init__(self) -> None:
        self.deltas: list[str] = []
        self.finals: list[FinalPayload] = []
        self.cues: list[CuePayload] = []
        self.errors: list[tuple[str, str]] = []

    async def delta(self, turn_id: str, text: str) -> None:
        self.deltas.append(text)

    async def final(self, turn_id: str, payload: FinalPayload) -> None:
        self.finals.append(payload)

    async def error(self, turn_id: str, code: str, detail: str = "") -> None:
        self.errors.append((code, detail))

    async def cue(self, turn_id: str, payload: CuePayload) -> None:
        self.cues.append(payload)


def _card() -> CharacterCard:
    return CharacterCard(
        id="test",
        name="小测",
        identity=Identity(full_name="小测", role="桌面伙伴", personality="温柔"),
        fallback="我出了点小状况。",
    )


class FakeLLM:
    """替身：暴露 provider 与 config，行为与 LLMSettingsService 一致。"""

    def __init__(self, provider: FakeProvider) -> None:
        self.provider = provider
        self.config = LLMConfig(base_url="http://fake/v1", api_key="k", model="fake")


def _service(provider: FakeProvider, history: ShortTermMemory) -> RoleplayService:
    return RoleplayService(
        llm=FakeLLM(provider),  # type: ignore[arg-type]
        temperature=0.8,
        builder=ContextBuilder(_card()),
        history=history,
    )


def test_stream_and_mood() -> None:
    async def scenario() -> tuple[RecordingSink, ShortTermMemory]:
        history = ShortTermMemory()
        provider = FakeProvider(
            [
                "你",
                "好",
                "<<<MOOD>>>",
                '{"emotion":{"label":"happy"},"action":{"expression":"smile"}}',
            ]
        )
        sink = RecordingSink()
        turn = TurnRegistry().create("t1")
        await _service(provider, history).reply(turn, "你好", sink)
        return sink, history

    sink, history = asyncio.run(scenario())
    assert "".join(sink.deltas) == "你好"
    final = sink.finals[0]
    assert final.text == "你好"
    assert final.emotion == {"label": "happy"}
    assert final.action == {"expression": "smile"}
    assert final.error is None
    assert final.first_token_ms is not None
    assert len(history) == 1
    # S2：happy 映射为 touch_head 动作
    assert len(sink.cues) == 1
    assert sink.cues[0].emotion_label == "happy"
    assert sink.cues[0].motion == "touch_head"


def test_cancelled_turn_does_not_write_history() -> None:
    async def scenario() -> tuple[RecordingSink, ShortTermMemory]:
        history = ShortTermMemory()
        provider = FakeProvider(["你好", "呀"])
        sink = RecordingSink()
        turn = TurnRegistry().create("t2")
        turn.cancel()
        await _service(provider, history).reply(turn, "你好", sink)
        return sink, history

    sink, history = asyncio.run(scenario())
    assert sink.finals[0].error == "TURN_CANCELLED"
    assert len(history) == 0


def test_llm_error_uses_persona_fallback() -> None:
    async def scenario() -> RecordingSink:
        provider = FakeProvider(error=LLMError("LLM_TIMEOUT", "timeout"))
        sink = RecordingSink()
        turn = TurnRegistry().create("t3")
        await _service(provider, ShortTermMemory()).reply(turn, "你好", sink)
        return sink

    sink = asyncio.run(scenario())
    final = sink.finals[0]
    assert final.error == "LLM_TIMEOUT"
    assert final.text == "我出了点小状况。"
