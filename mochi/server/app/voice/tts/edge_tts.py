"""edge-tts 实现：流式 MP3，支持 rate/pitch/volume。

edge-tts 的 pitch 只接受 ``+NHZ``（不支持百分比），因此情绪标签里的
``pitch=7.0``（百分比语义）在这里换算成 ``+7Hz``；对外接口保持百分比，
保证 cue 的语义不被供应商格式污染。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

log = logging.getLogger(__name__)


def format_rate(rate: float) -> str:
    percent = int(round((max(0.1, rate) - 1.0) * 100))
    return f"{percent:+d}%"


def format_pitch(pitch: float) -> str:
    """百分比语义 → edge-tts 接受的 Hz 偏移。"""
    return f"{int(round(pitch)):+d}Hz"


def format_volume(volume: float) -> str:
    percent = int(round((max(0.0, volume) - 1.0) * 100))
    return f"{percent:+d}%"


class EdgeTTSProvider:
    def __init__(self, *, voice: str = "zh-CN-XiaoxiaoNeural", volume: float = 0.9) -> None:
        self._voice = voice
        self._volume = volume

    async def synthesize(
        self,
        text: str,
        *,
        rate: float = 1.0,
        pitch: float = 0.0,
        volume: float = 1.0,
    ) -> AsyncIterator[bytes]:
        import edge_tts

        communicate = edge_tts.Communicate(
            text,
            self._voice,
            rate=format_rate(rate),
            pitch=format_pitch(pitch),
            volume=format_volume(volume * self._volume),
        )
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                yield bytes(chunk["data"])

    async def aclose(self) -> None:
        return None
