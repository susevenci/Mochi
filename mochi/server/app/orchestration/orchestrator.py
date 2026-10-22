"""编排层统一入口（计划书 5.1.3）。

所有用户输入都从这里进入；任何异常都不允许向上冒泡到连接层。
S6 起 TASK 路由走 Agent Core：先 ack，后台执行，完成后主动汇报。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.emotion.engine import EmotionEngine

from .commands import CommandRouter
from .confirmation import ConfirmationStore
from .decision import DecisionService, Route
from .events import EventSink, FinalPayload
from .roleplay import RoleplayService
from .turn_registry import TurnRegistry

log = logging.getLogger(__name__)

ReportFn = Callable[[str, str], Awaitable[None]]


class Orchestrator:
    def __init__(
        self,
        *,
        decision: DecisionService,
        commands: CommandRouter,
        roleplay: RoleplayService,
        turns: TurnRegistry,
        emotion: EmotionEngine | None = None,
        memory: Any = None,
        agent: Any = None,
        skills: Any = None,
        confirmations: ConfirmationStore | None = None,
        route_mode: str = "auto",
    ) -> None:
        self._decision = decision
        self._commands = commands
        self._roleplay = roleplay
        self._turns = turns
        self._emotion = emotion
        self._memory = memory
        self._agent = agent
        self._skills = skills
        self._confirmations = confirmations or ConfirmationStore()
        self._route_mode = route_mode
        self._report: ReportFn | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    def set_report_sink(self, report: ReportFn) -> None:
        self._report = report

    def set_route_mode(self, mode: str) -> None:
        self._route_mode = mode

    @property
    def route_mode(self) -> str:
        return self._route_mode

    async def handle_chat(
        self,
        turn_id: str,
        user_text: str,
        sink: EventSink,
        *,
        magnitude_scale: float = 1.0,
    ) -> None:
        decision = await self._decision.classify(
            user_text,
            provider=self._roleplay.provider,
            route_mode=self._route_mode,
        )
        log.info(
            "decision turn=%s route=%s rule=%s latency_ms=%d",
            turn_id,
            decision.route,
            decision.matched_rule,
            decision.latency_ms,
        )

        if decision.route == Route.COMMAND:
            result = await self._commands.handle(user_text)
            if self._emotion is not None:
                # /role set 后人格立即生效；情绪状态保留（关系连续）
                self._emotion.set_card(self._commands.card)
            await sink.final(
                turn_id,
                FinalPayload(text=result.text if result else "", route="command"),
            )
            return

        snapshot = None
        if self._emotion is not None:
            snapshot = await self._emotion.apply_text(
                user_text,
                magnitude_scale=magnitude_scale,
            )
            if not self._emotion.last_text_analysis or not self._emotion.last_text_analysis.hit:
                # Level 2 只做一次很短的分类；失败/超时不影响主链路
                snapshot = await self._emotion.apply_text_llm(
                    user_text,
                    self._roleplay.provider,
                    magnitude_scale=magnitude_scale,
                )

        if decision.route == Route.TASK and self._agent is not None:
            ack = self._commands.card.persona.ack_templates.get("task") or "好，我这就去办。"
            await sink.final(
                turn_id,
                FinalPayload(
                    text=ack,
                    route="task",
                    emotion={"label": snapshot.label} if snapshot else None,
                ),
            )
            task = asyncio.create_task(self._run_task(turn_id, user_text, sink))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return

        turn = self._turns.create(turn_id)
        try:
            await self._roleplay.reply(turn, user_text, sink, emotion_snapshot=snapshot)
        finally:
            self._turns.discard(turn_id)

    async def _run_task(self, turn_id: str, user_text: str, sink: EventSink) -> None:
        from app.tools.agent_core import AgentCore
        from app.tools.base import ToolContext

        assert self._agent is not None
        if isinstance(self._agent, AgentCore):
            self._agent.set_provider(self._roleplay.provider)

        async def confirm(tool: str, args: dict[str, Any]) -> bool:
            return await self._confirmations.request(sink, turn_id, tool, args)

        context = ToolContext(
            memory=self._memory,
            emotion=self._emotion,
            skills=self._skills,
            confirm=confirm,
        )
        try:
            result = await self._agent.run(user_text, context)
        except Exception as exc:  # noqa: BLE001 - 任务失败不拖垮连接
            log.exception("agent task failed: %s", exc)
            result = None
        if result is None:
            text, ok = "这件事我没办成，等我再想想。", False
        else:
            text, ok = result.text or "办好了。", result.error is None
        if self._emotion is not None:
            await self._emotion.apply_task_result(ok, note=user_text[:80])
        if self._memory is not None:
            try:
                await self._memory.append_turn(user_text, text, turn_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("task memory append failed: %s", exc)
        if self._report is not None:
            await self._report(text, "proud" if ok else "worried")

    def interrupt(self, turn_id: str) -> bool:
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        return self._turns.cancel(turn_id)
