"""高风险工具确认（T6-15）：request_id → Future，60s 超时自动拒绝。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.orchestration.events import EventSink
from app.utils.ids import ulid

CONFIRM_TIMEOUT = 60.0


class ConfirmationStore:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def request(
        self,
        sink: EventSink,
        turn_id: str,
        tool: str,
        args: dict[str, Any],
        *,
        timeout: float = CONFIRM_TIMEOUT,
    ) -> bool:
        request_id = ulid()
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await sink.confirm_request(turn_id, request_id, tool, args, timeout_seconds=timeout)
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            return False
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, approved: bool) -> bool:
        future = self._pending.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(bool(approved))
        return True

    @property
    def pending(self) -> int:
        return len(self._pending)
