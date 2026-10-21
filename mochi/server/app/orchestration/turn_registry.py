"""Turn 注册表：取消传播与生命周期（规划文档 1.3.5 / 3.5.2）。

用 ``asyncio.Event`` 而非 ``task.cancel()`` 作为主取消信号：
前者在循环里显式检查，清理逻辑不会被跳过；后者可能在任意 await 点抛出。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.utils.ids import ulid


@dataclass
class Turn:
    id: str
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    created_at: float = field(default_factory=time.time)

    def cancel(self) -> None:
        self.cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled.is_set()


class TurnRegistry:
    def __init__(self) -> None:
        self._turns: dict[str, Turn] = {}

    def create(self, turn_id: str | None = None) -> Turn:
        turn = Turn(id=turn_id or ulid())
        self._turns[turn.id] = turn
        return turn

    def get(self, turn_id: str) -> Turn | None:
        return self._turns.get(turn_id)

    def cancel(self, turn_id: str) -> bool:
        turn = self._turns.get(turn_id)
        if turn is None:
            return False
        turn.cancel()
        return True

    def discard(self, turn_id: str) -> None:
        self._turns.pop(turn_id, None)

    @property
    def active(self) -> int:
        return len(self._turns)
