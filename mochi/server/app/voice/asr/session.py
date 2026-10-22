"""一次录音会话：缓冲 PCM → 中间字幕 → 最终识别 → 音频特征。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .base import ASRError, ASRProvider, ASRResult
from .features import AudioFeatures, analyze_pcm
from .vad import EnergyVAD

log = logging.getLogger(__name__)

PartialCallback = Callable[[str], Awaitable[None]]
FinalCallback = Callable[[ASRResult, str, AudioFeatures], Awaitable[None]]
ErrorCallback = Callable[[str, str], Awaitable[None]]


@dataclass
class VoiceState:
    """每个 WS 连接一份录音状态（不做全局单例）。"""

    session: AsrSession | None = None


@dataclass
class AsrSession:
    provider: ASRProvider
    on_partial: PartialCallback
    on_final: FinalCallback
    on_error: ErrorCallback
    sample_rate: int = 16_000
    mode: str = "push_to_talk"
    max_seconds: float = 30.0
    partial_interval: float = 1.2
    _pcm: bytearray = field(default_factory=bytearray)
    _vad: EnergyVAD = field(default_factory=EnergyVAD)
    _partial_task: asyncio.Task[None] | None = None
    _ended: bool = False
    _last_partial_at: float = 0.0
    _last_partial_text: str = ""
    _started_at: float = 0.0

    @property
    def pcm(self) -> bytes:
        return bytes(self._pcm)

    @property
    def duration_s(self) -> float:
        return len(self._pcm) / 2 / self.sample_rate

    def begin(self, *, mode: str = "push_to_talk", sample_rate: int = 16_000) -> None:
        self.mode = mode
        self.sample_rate = sample_rate
        self._pcm.clear()
        self._vad.reset()
        self._ended = False
        self._last_partial_at = 0.0
        self._last_partial_text = ""
        self._started_at = time.perf_counter()
        if self._partial_task is not None:
            self._partial_task.cancel()
            self._partial_task = None

    async def feed(self, pcm: bytes) -> None:
        if self._ended or not pcm:
            return
        self._pcm.extend(pcm)
        self._vad.process(pcm, self.sample_rate)
        if self.duration_s >= self.max_seconds:
            await self.end()
            return
        now = time.perf_counter()
        if (
            self._partial_task is None
            and self.duration_s >= 0.8
            and now - self._last_partial_at >= self.partial_interval
        ):
            self._last_partial_at = now
            self._partial_task = asyncio.create_task(self._emit_partial())

    async def _emit_partial(self) -> None:
        snapshot = bytes(self._pcm)
        try:
            result = await self.provider.transcribe(snapshot, self.sample_rate)
        except ASRError as exc:
            log.info("ASR partial failed: %s", exc)
            return
        finally:
            self._partial_task = None
        text = result.text.strip()
        if self._ended or not text or text == self._last_partial_text:
            return
        self._last_partial_text = text
        await self.on_partial(text)

    async def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        if self._partial_task is not None:
            self._partial_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._partial_task
            self._partial_task = None
        if not self._pcm:
            await self.on_error("ASR_NO_SPEECH", "没有收到音频")
            return
        features = analyze_pcm(bytes(self._pcm), self.sample_rate)
        try:
            result = await self.provider.transcribe(bytes(self._pcm), self.sample_rate)
        except ASRError as exc:
            await self.on_error(exc.code, exc.detail)
            return
        except Exception as exc:  # noqa: BLE001 - 识别失败不影响文字通道
            log.exception("ASR final failed")
            await self.on_error("ASR_FAILED", str(exc))
            return
        if not result.ok:
            await self.on_error("ASR_NO_SPEECH", "没有识别到有效语音")
            return
        await self.on_final(result, self.mode, features)

    def cancel(self) -> None:
        self._ended = True
        self._pcm.clear()
        if self._partial_task is not None:
            self._partial_task.cancel()
            self._partial_task = None
