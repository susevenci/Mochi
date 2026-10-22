"""编排层统一入口（计划书 5.1.3）。

所有用户输入都从这里进入；任何异常都不允许向上冒泡到连接层。
"""

from __future__ import annotations

import logging

from app.emotion.engine import EmotionEngine

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
        emotion: EmotionEngine | None = None,
    ) -> None:
        self._decision = decision
        self._commands = commands
        self._roleplay = roleplay
        self._turns = turns
        self._emotion = emotion

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
            if self._emotion is not None:
                # /role set 后人格立即生效；情绪状态保留（关系连续）
                self._emotion.set_card(self._commands.card)
            await sink.final(
                turn_id,
                FinalPayload(text=result.text if result else "", route="command"),
            )
            return

        if decision.route == Route.TASK:
            # S1：工具层尚未接入；按对话处理并留痕，S6 改为 ack + 后台执行
            log.info("task route not implemented, fall back to chat turn=%s", turn_id)

        snapshot = None
        if self._emotion is not None:
            snapshot = await self._emotion.apply_text(user_text)
            if not self._emotion.last_text_analysis or not self._emotion.last_text_analysis.hit:
                # Level 2 只做一次很短的分类；失败/超时不影响主链路
                snapshot = await self._emotion.apply_text_llm(user_text, self._roleplay.provider)

        turn = self._turns.create(turn_id)
        try:
            await self._roleplay.reply(turn, user_text, sink, emotion_snapshot=snapshot)
        finally:
            self._turns.discard(turn_id)

    def interrupt(self, turn_id: str) -> bool:
        return self._turns.cancel(turn_id)
