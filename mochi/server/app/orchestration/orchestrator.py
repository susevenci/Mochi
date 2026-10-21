"""编排层统一入口（计划书 5.1.3）。

所有用户输入都从这里进入；任何异常都不允许向上冒泡到连接层。
"""

from __future__ import annotations

import logging

from .commands import CommandRouter
from .decision import DecisionService, Route
from .events import EventSink, FinalPayload
from .roleplay import RoleplayService
from .turn_registry import TurnRegistry

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        *,
        decision: DecisionService,
        commands: CommandRouter,
        roleplay: RoleplayService,
        turns: TurnRegistry,
    ) -> None:
        self._decision = decision
        self._commands = commands
        self._roleplay = roleplay
        self._turns = turns

    async def handle_chat(self, turn_id: str, user_text: str, sink: EventSink) -> None:
        decision = await self._decision.classify(user_text)
        log.info(
            "decision turn=%s route=%s rule=%s latency_ms=%d",
            turn_id,
            decision.route,
            decision.matched_rule,
            decision.latency_ms,
        )

        if decision.route == Route.COMMAND:
            result = self._commands.handle(user_text)
            await sink.final(
                turn_id,
                FinalPayload(text=result.text if result else "", route="command"),
            )
            return

        if decision.route == Route.TASK:
            # S1：工具层尚未接入；按对话处理并留痕，S6 改为 ack + 后台执行
            log.info("task route not implemented, fall back to chat turn=%s", turn_id)

        turn = self._turns.create(turn_id)
        try:
            await self._roleplay.reply(turn, user_text, sink)
        finally:
            self._turns.discard(turn_id)

    def interrupt(self, turn_id: str) -> bool:
        return self._turns.cancel(turn_id)
