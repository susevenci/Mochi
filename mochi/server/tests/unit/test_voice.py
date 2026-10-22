"""S4 语音链路：文本切句、ASR 会话、TTS 流、特征与 WS 协议。"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from fastapi.testclient import TestClient

from app.config.character_card import CharacterCard, Identity
from app.config.llm_settings import LLMConfig
from app.config.settings import Settings
from app.emotion.presentation import TtsParams
from app.memory.context_builder import ContextBuilder
from app.memory.short_term import ShortTermMemory
from app.orchestration.events import CuePayload, FinalPayload
from app.orchestration.roleplay import RoleplayService
from app.orchestration.turn_registry import TurnRegistry
from app.voice.asr.base import ASRResult
from app.voice.asr.features import analyze_pcm
from app.voice.asr.session import AsrSession
from app.voice.asr.vad import EnergyVAD
from app.voice.pipeline import TTSStreamer, VoiceService
from app.voice.tts.edge_tts import format_pitch, format_rate, format_volume
from app.voice.tts.text_prep import SentenceSplitter, clean_for_tts, split_sentences


class FakeASR:
    def __init__(self, text: str = "你好呀") -> None:
        self.text = text
        self.calls = 0

    async def transcribe(self, pcm: bytes, sample_rate: int = 16_000) -> ASRResult:
        self.calls += 1
        return ASRResult(
            text=self.text,
            duration_s=len(pcm) / 2 / sample_rate,
            confidence=0.9,
        )

    async def aclose(self) -> None:
        return None


class FakeTTS:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def synthesize(self, text, *, rate=1.0, pitch=0.0, volume=1.0):
        self.texts.append(text)
        yield b"ID3"
        yield b"\x00" * 16

    async def aclose(self) -> None:
        return None


class FakeAudioSink:
    def __init__(self) -> None:
        self.begins: list[tuple[str, str, int]] = []
        self.chunks: list[bytes] = []
        self.ends = 0
        self.stops = 0

    async def audio_begin(self, turn_id: str, *, fmt: str, sample_rate: int) -> None:
        self.begins.append((turn_id, fmt, sample_rate))

    async def audio_chunk(self, turn_id: str, seq: int, chunk: bytes) -> None:
        self.chunks.append(chunk)

    async def audio_end(self, turn_id: str) -> None:
        self.ends += 1

    async def audio_stop(self, turn_id: str) -> None:
        self.stops += 1


def test_text_prep_strips_mood_and_splits() -> None:
    text = "**你好**呀！今天<<<MOOD>>>{\"emotion\":{\"label\":\"happy\"}}"
    assert "MOOD" not in clean_for_tts(text)
    assert clean_for_tts("**你好**呀！") == "你好呀！"
    assert split_sentences("第一句。第二句！") == ["第一句。", "第二句！"]
    long = "这是一句非常长的话，" * 8
    parts = split_sentences(long)
    assert len(parts) > 1
    assert all(len(part) <= 41 for part in parts)


def test_sentence_splitter_handles_chunk_boundary() -> None:
    splitter = SentenceSplitter()
    assert splitter.feed("你好") == []
    assert splitter.feed("呀。今天") == ["你好呀。"]
    assert splitter.flush() == ["今天"]


def test_edge_tts_formatters() -> None:
    assert format_rate(1.08) == "+8%"
    assert format_rate(0.86) == "-14%"
    assert format_pitch(7.0) == "+7Hz"
    assert format_volume(1.1) == "+10%"


def test_audio_features_volume_difference() -> None:
    import numpy as np

    quiet = (np.ones(8000, dtype=np.int16) * 300).tobytes()
    loud = (np.ones(8000, dtype=np.int16) * 6000).tobytes()
    quiet_features = analyze_pcm(quiet)
    loud_features = analyze_pcm(loud)
    assert loud_features.magnitude_scale > quiet_features.magnitude_scale * 1.2


def test_energy_vad_endpoint() -> None:
    import numpy as np

    vad = EnergyVAD()
    speech = (np.ones(4000, dtype=np.int16) * 5000).tobytes()
    silence = (np.zeros(1600, dtype=np.int16)).tobytes()
    vad.process(speech)
    for _ in range(8):
        vad.process(silence)
    assert vad.saw_speech
    assert vad.endpoint


def test_asr_session_partial_and_final() -> None:
    partials: list[str] = []
    finals: list[tuple[str, str, float]] = []
    errors: list[tuple[str, str]] = []

    async def on_partial(text: str) -> None:
        partials.append(text)

    async def on_final(result, mode, features) -> None:
        finals.append((result.text, mode, features.magnitude_scale))

    async def on_error(code: str, detail: str) -> None:
        errors.append((code, detail))

    session = AsrSession(
        provider=FakeASR("你好世界"),
        on_partial=on_partial,
        on_final=on_final,
        on_error=on_error,
        partial_interval=0.0,
    )
    async def scenario() -> None:
        session.begin()
        await session.feed(b"\x00\x10" * 8000)
        await asyncio.sleep(0.02)
        await session.end()

    asyncio.run(scenario())
    assert finals
    assert finals[0][0] == "你好世界"
    assert errors == []


def test_asr_session_empty_audio_is_error() -> None:
    errors: list[tuple[str, str]] = []

    async def on_partial(_text: str) -> None:
        return None

    async def on_final(_result, _mode, _features) -> None:
        return None

    async def on_error(code: str, detail: str) -> None:
        errors.append((code, detail))

    session = AsrSession(
        provider=FakeASR(),
        on_partial=on_partial,
        on_final=on_final,
        on_error=on_error,
    )

    async def scenario() -> None:
        session.begin()
        await session.end()

    asyncio.run(scenario())
    assert errors[0][0] == "ASR_NO_SPEECH"


def test_tts_streamer_sends_audio() -> None:
    sink = FakeAudioSink()
    provider = FakeTTS()
    streamer = TTSStreamer(
        provider=provider,
        sink=sink,
        turn_id="t1",
        params=TtsParams(),
        cancel_check=lambda: False,
    )

    async def scenario() -> None:
        streamer.start()
        streamer.feed("第一句。")
        streamer.feed("第二句。")
        await streamer.finish()

    asyncio.run(scenario())
    assert provider.texts == ["第一句。", "第二句。"]
    assert sink.begins[0][1] == "mp3"
    assert len(sink.chunks) >= 3
    assert sink.ends == 1
    assert streamer.first_audio_ms is not None


def test_tts_streamer_cancel_sends_stop() -> None:
    sink = FakeAudioSink()
    checks = [False, True, True, True, True]

    def cancel() -> bool:
        return checks.pop(0) if checks else True

    streamer = TTSStreamer(
        provider=FakeTTS(),
        sink=sink,
        turn_id="t2",
        params=TtsParams(),
        cancel_check=cancel,
    )

    async def scenario() -> None:
        streamer.start()
        streamer.feed("不会播放。")
        await streamer.finish()

    asyncio.run(scenario())
    assert sink.stops == 1


def test_ws_audio_messages(client: TestClient, monkeypatch) -> None:
    ctx = client.app.state.ctx
    fake_asr = FakeASR("你好呀")
    ctx.voice._asr = fake_asr  # noqa: SLF001 - 测试替换供应商

    async def no_chat(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(ctx.orchestrator, "handle_chat", no_chat)
    pcm = b"\x00\x10" * 1600

    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {
                "v": 1,
                "type": "audio.in_begin",
                "id": "a1",
                "ts": 1.0,
                "payload": {"sample_rate": 16000, "format": "pcm16", "mode": "push_to_talk"},
            }
        )
        ws.send_json(
            {
                "v": 1,
                "type": "audio.in_chunk",
                "id": "a2",
                "ts": 1.0,
                "payload": {"data": base64.b64encode(pcm).decode(), "seq": 0},
            }
        )
        ws.send_json(
            {
                "v": 1,
                "type": "audio.in_end",
                "id": "a3",
                "ts": 1.0,
                "payload": {"reason": "user"},
            }
        )
        types = []
        final_text = None
        for _ in range(8):
            message = ws.receive_json()
            types.append(message["type"])
            if message["type"] == "asr.final":
                final_text = message["payload"]["text"]
                break
        assert "asr.final" in types
        assert final_text == "你好呀"


def test_roleplay_with_voice_streams_audio(tmp_path: Path) -> None:
    class Provider:
        async def stream(self, messages, **_kwargs):
            for chunk in ["你好。", "今天也要加油。", "<<<MOOD>>>", "{}"]:
                yield chunk

        async def aclose(self) -> None:
            return None

    class FakeLLM:
        provider = Provider()
        config = LLMConfig(base_url="http://fake/v1", api_key="k", model="fake")

    class Sink(FakeAudioSink):
        def __init__(self) -> None:
            super().__init__()
            self.deltas: list[str] = []
            self.finals: list[FinalPayload] = []
            self.cues: list[CuePayload] = []

        async def delta(self, turn_id: str, text: str) -> None:
            self.deltas.append(text)

        async def final(self, turn_id: str, payload: FinalPayload) -> None:
            self.finals.append(payload)

        async def error(self, turn_id: str, code: str, detail: str = "") -> None:
            return None

        async def cue(self, turn_id: str, payload: CuePayload) -> None:
            self.cues.append(payload)

    card = CharacterCard(
        id="test",
        name="小测",
        identity=Identity(full_name="小测", role="桌面伙伴", personality="温柔"),
    )
    settings = Settings(data_dir=tmp_path, voice_enabled=True, llm_api_key="")
    voice = VoiceService(settings, tts=FakeTTS(), asr=FakeASR())
    service = RoleplayService(
        llm=FakeLLM(),  # type: ignore[arg-type]
        temperature=0.8,
        builder=ContextBuilder(card),
        history=ShortTermMemory(),
        voice=voice,
    )
    turn = TurnRegistry().create("voice-turn")
    sink = Sink()

    async def scenario() -> None:
        await service.reply(turn, "你好", sink)  # type: ignore[arg-type]
        await voice.aclose()

    asyncio.run(scenario())
    assert sink.finals[0].text == "你好。今天也要加油。"
    assert sink.begins and sink.ends == 1
    assert sink.chunks
