"""提醒调度（T6-14）：到点主动播报 + proud 情绪，重启后仍有效。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.emotion.models import Stimulus, StimulusSource
from app.emotion.stimuli.catalog import load_catalog

log = logging.getLogger(__name__)

EmitFn = Callable[[str, str], Awaitable[None]]


class ReminderScheduler:
    def __init__(
        self,
        *,
        memory: Any,
        emotion: Any,
        emit: EmitFn,
        interval: float = 10.0,
    ) -> None:
        self._memory = memory
        self._emotion = emotion
        self._emit = emit
        self._interval = interval
        self._task: asyncio.Task[None] | None = None
        self._scheduler: Any = None

    async def start(self) -> None:
        if self._task is not None:
            return
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
            scheduler.add_job(self.tick, "interval", seconds=self._interval, id="reminders")
            scheduler.start()
            self._scheduler = scheduler
            log.info("reminder scheduler started (APScheduler)")
        except Exception as exc:  # noqa: BLE001 - 没装 APScheduler 时回落 asyncio loop
            log.info("APScheduler unavailable, use asyncio loop: %s", exc)
            self._task = asyncio.create_task(self._loop(), name="reminders")

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001
                log.warning("reminder tick failed: %s", exc)

    async def tick(self) -> list[dict[str, Any]]:
        due = await self._memory.due_reminders()
        fired: list[dict[str, Any]] = []
        for item in due:
            await self._memory.mark_reminder_fired(item["id"])
            try:
                await self._emotion.apply_stimulus(
                    self._stimulus(item["text"]),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("reminder emotion failed: %s", exc)
            text = f"喂，提醒你：{item['text']}"
            await self._emit(text, "proud")
            fired.append(item)
        return fired

    def _stimulus(self, text: str) -> Stimulus:
        definition = load_catalog().get("reminder_due")
        if definition is None:
            return Stimulus(source=StimulusSource.PROACTIVE, tag="reminder_due", dval=0.1)
        return Stimulus(
            source=StimulusSource.PROACTIVE,
            tag="reminder_due",
            magnitude=1.0,
            dval=definition.dval,
            darousal=definition.darousal,
            ddominance=definition.ddominance,
            confidence=1.0,
            note=text[:80],
        )

    async def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
