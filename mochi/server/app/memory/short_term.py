"""短期记忆：会话内的滑动窗口（计划书 5.3.2 的 L1）。

S1 只做内存窗口；S6 换成 SQLite + 摘要压缩，接口保持不变。
"""

from __future__ import annotations


class ShortTermMemory:
    def __init__(self, max_turns: int = 20) -> None:
        if max_turns < 1:
            raise ValueError("max_turns 必须 >= 1")
        self._max_turns = max_turns
        self._turns: list[tuple[str, str]] = []

    @property
    def max_turns(self) -> int:
        return self._max_turns

    def append(self, user: str, assistant: str) -> None:
        self._turns.append((user, assistant))
        if len(self._turns) > self._max_turns:
            self._turns = self._turns[-self._max_turns :]

    def recent(self) -> list[tuple[str, str]]:
        return list(self._turns)

    def clear(self) -> None:
        self._turns.clear()

    def __len__(self) -> int:
        return len(self._turns)
