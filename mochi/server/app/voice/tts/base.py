"""TTS Provider 抽象：流式产出音频字节。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class TTSProvider(Protocol):
    def synthesize(
        self,
        text: str,
        *,
        rate: float = 1.0,
        pitch: float = 0.0,
        volume: float = 1.0,
    ) -> AsyncIterator[bytes]: ...

    async def aclose(self) -> None: ...
