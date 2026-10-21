"""编排层内部的事件出口。

Roleplay 不直接依赖 WebSocket：它只认这个协议，
由 Gateway 提供 WSSink 实现，测试时用记录型假实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class FinalPayload:
    text: str
    route: str
    emotion: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    error: str | None = None
    first_token_ms: int | None = None
    latency_ms: int | None = None
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class CuePayload:
    emotion_label: str
    motion: str
    priority: str = "normal"
    expression: str | None = None


class EventSink(Protocol):
    async def delta(self, turn_id: str, text: str) -> None: ...

    async def final(self, turn_id: str, payload: FinalPayload) -> None: ...

    async def error(self, turn_id: str, code: str, detail: str = "") -> None: ...

    async def cue(self, turn_id: str, payload: CuePayload) -> None: ...
