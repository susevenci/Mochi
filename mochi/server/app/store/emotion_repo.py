"""情绪状态持久化（S3 用 JSON 快照，S6 换成 SQLite 实现，接口不变）。

为什么不是 SQLite：S3 是核心阶段，先把"状态可恢复"这件事做对，
不要同时引入异步 DB 与关闭时序的复杂度。``EmotionRepo`` 协议就是为
S6 的替换预留的——S6 只需再写一个实现，引擎一行不用改。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol

from app.emotion.models import EmotionSnapshot, EmotionState

log = logging.getLogger(__name__)

__all__ = ["EmotionRepo", "JsonEmotionRepo"]


class EmotionRepo(Protocol):
    """情绪状态的存取接口（S6 的 SQLite 实现遵循同一协议）。"""

    def load(self) -> EmotionState | None: ...

    def save(self, state: EmotionState) -> None: ...

    def append_snapshot(self, snapshot: EmotionSnapshot) -> None: ...

    def history(self, limit: int = 600) -> list[dict[str, Any]]: ...


class JsonEmotionRepo:
    """JSON 文件实现：原子写（临时文件 + 替换），损坏时回落默认值。"""

    def __init__(self, path: Path, *, history_limit: int = 1200) -> None:
        self._path = path
        self._history_limit = history_limit
        self._history: list[dict[str, Any]] = []
        self._state: EmotionState | None = None

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> EmotionState | None:
        if not self._path.exists():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("情绪状态文件损坏，按空状态启动: %s", exc)
            return None
        if not isinstance(raw, dict):
            return None
        self._history = [item for item in raw.get("history") or [] if isinstance(item, dict)]
        self._state = EmotionState.from_dict(raw.get("state"))
        return self._state

    def save(self, state: EmotionState) -> None:
        self._state = state
        payload = {
            "version": 1,
            "state": state.to_dict(),
            "history": self._history[-self._history_limit :],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def append_snapshot(self, snapshot: EmotionSnapshot) -> None:
        self._history.append(snapshot.to_payload())
        if len(self._history) > self._history_limit:
            self._history = self._history[-self._history_limit :]

    def history(self, limit: int = 600) -> list[dict[str, Any]]:
        return list(self._history[-limit:])
