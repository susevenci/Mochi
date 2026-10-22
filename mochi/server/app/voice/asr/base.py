"""ASR Provider 抽象（不变量 I5：业务层不直连 SDK）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ASRError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ASRResult:
    text: str
    language: str = "zh"
    confidence: float = 0.0
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())


class ASRProvider(Protocol):
    async def transcribe(self, pcm: bytes, sample_rate: int = 16_000) -> ASRResult: ...

    async def aclose(self) -> None: ...
