"""语音服务与 TTS 流式管线（句子级，可与 LLM 流并行）。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.config.settings import Settings
from app.emotion.presentation import TtsParams

from .asr.base import ASRProvider
from .asr.faster_whisper import FasterWhisperASR
from .tts.base import TTSProvider
from .tts.edge_tts import EdgeTTSProvider

log = logging.getLogger(__name__)

__all__ = ["AudioSink", "TTSStreamer", "VoiceService"]


class AudioSink(Protocol):
    async def audio_begin(self, turn_id: str, *, fmt: str, sample_rate: int) -> None: ...

    async def audio_chunk(self, turn_id: str, seq: int, chunk: bytes) -> None: ...

    async def audio_end(self, turn_id: str) -> None: ...

    async def audio_stop(self, turn_id: str) -> None: ...


@dataclass
class TTSStreamer:
    """把句子队列逐句合成并推送；首句与 LLM 流并行。"""

    provider: TTSProvider
    sink: AudioSink
    turn_id: str
    params: TtsParams
    cancel_check: Callable[[], bool]
    _queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    _task: asyncio.Task[None] | None = None
    _started: float = field(default_factory=time.perf_counter)
    first_audio_ms: int | None = None
    sentences: int = 0
    error: str | None = None
    _seq: int = 0
    _stopped: bool = False
    _prefetch_task: asyncio.Task[tuple[str, bytes]] | None = None
    _prefetch_text: str | None = None
    _finished_queue: bool = False

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"tts-{self.turn_id}")

    def feed(self, sentence: str) -> None:
        if sentence.strip() and not self._stopped:
            self._queue.put_nowait(sentence.strip())

    async def finish(self) -> None:
        if self._task is None:
            return
        self._queue.put_nowait(None)
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def cancel(self) -> None:
        self._stopped = True
        self._cancel_prefetch()
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def _cancel_prefetch(self) -> None:
        if self._prefetch_task is not None:
            self._prefetch_task.cancel()
            self._prefetch_task = None
            self._prefetch_text = None

    def _take_prefetch(self) -> None:
        """当前句开始后立刻合成下一句（并发预取，队列最多 1 句）。"""
        if self._prefetch_task is not None or self._finished_queue:
            return
        try:
            item = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        if item is None:
            self._finished_queue = True
            return
        self._prefetch_text = item
        self._prefetch_task = asyncio.create_task(self._collect(item))

    async def _collect(self, sentence: str) -> tuple[str, bytes]:
        data = bytearray()
        async for chunk in self.provider.synthesize(
            sentence,
            rate=self.params.rate,
            pitch=self.params.pitch,
            volume=self.params.volume,
        ):
            data.extend(chunk)
        return sentence, bytes(data)

    async def _send_bytes(self, data: bytes) -> None:
        for start in range(0, len(data), 8192):
            if self._stopped or self.cancel_check():
                return
            if self.first_audio_ms is None:
                self.first_audio_ms = int((time.perf_counter() - self._started) * 1000)
            await self.sink.audio_chunk(self.turn_id, self._seq, data[start : start + 8192])
            self._seq += 1

    async def _run(self) -> None:
        begun = False
        try:
            sentence = await self._queue.get()
            while sentence is not None:
                if self._stopped or self.cancel_check():
                    break
                if not begun:
                    await self.sink.audio_begin(self.turn_id, fmt="mp3", sample_rate=24_000)
                    begun = True
                self.sentences += 1
                self._take_prefetch()
                try:
                    async for chunk in self.provider.synthesize(
                        sentence,
                        rate=self.params.rate,
                        pitch=self.params.pitch,
                        volume=self.params.volume,
                    ):
                        if self._stopped or self.cancel_check():
                            break
                        if self.first_audio_ms is None:
                            self.first_audio_ms = int((time.perf_counter() - self._started) * 1000)
                        await self.sink.audio_chunk(self.turn_id, self._seq, chunk)
                        self._seq += 1
                except Exception as exc:  # noqa: BLE001 - TTS 失败降级为字幕
                    self.error = str(exc)
                    log.warning("TTS failed turn=%s: %s", self.turn_id, exc)
                    break
                if self._stopped or self.cancel_check():
                    break

                if self._prefetch_task is not None:
                    # 预取句已经合成完：直接发送，然后取它后面的一句
                    try:
                        _prefetched_text, data = await self._prefetch_task
                    except Exception as exc:  # noqa: BLE001
                        self.error = str(exc)
                        log.warning("TTS prefetch failed turn=%s: %s", self.turn_id, exc)
                    else:
                        self.sentences += 1
                        await self._send_bytes(data)
                    self._prefetch_task = None
                    self._prefetch_text = None
                    sentence = None if self._finished_queue else await self._queue.get()
                    continue
                sentence = None if self._finished_queue else await self._queue.get()
        finally:
            self._cancel_prefetch()
            if begun:
                if self._stopped or self.cancel_check():
                    await self.sink.audio_stop(self.turn_id)
                else:
                    await self.sink.audio_end(self.turn_id)


class VoiceService:
    """语音装配：TTS 默认 edge-tts，ASR 默认 faster-whisper（惰性加载）。"""

    def __init__(
        self,
        settings: Settings,
        *,
        tts: TTSProvider | None = None,
        asr: ASRProvider | None = None,
    ) -> None:
        self._settings = settings
        self._tts = tts
        self._asr = asr

    @property
    def enabled(self) -> bool:
        return self._settings.voice_enabled

    @property
    def default_params(self) -> TtsParams:
        return TtsParams()

    @property
    def tts(self) -> TTSProvider:
        if self._tts is None:
            self._tts = EdgeTTSProvider(
                voice=self._settings.tts_voice,
                volume=self._settings.tts_volume,
            )
        return self._tts

    @property
    def asr(self) -> ASRProvider | None:
        if not self._settings.asr_enabled:
            return None
        if self._asr is None:
            self._asr = FasterWhisperASR(
                model_size=self._settings.asr_model,
                language=self._settings.asr_language,
                compute_type=self._settings.asr_compute_type,
                initial_prompt=self._settings.asr_initial_prompt,
                download_root=self._settings.data_dir / "models",
            )
        return self._asr

    def open_streamer(
        self,
        turn_id: str,
        sink: AudioSink,
        params: TtsParams,
        cancel_check: Callable[[], bool],
    ) -> TTSStreamer | None:
        if not self.enabled:
            return None
        streamer = TTSStreamer(
            provider=self.tts,
            sink=sink,
            turn_id=turn_id,
            params=params,
            cancel_check=cancel_check,
        )
        streamer.start()
        return streamer

    async def aclose(self) -> None:
        if self._tts is not None:
            await self._tts.aclose()
        if self._asr is not None:
            await self._asr.aclose()
