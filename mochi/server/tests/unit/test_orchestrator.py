"""编排入口测试（T1-08 / T1-09 验收）：命令路由与对话委派。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.config.character_card import CardLoader
from app.memory.context_builder import ContextBuilder
from app.memory.short_term import ShortTermMemory
from app.orchestration.commands import CommandRouter
from app.orchestration.decision import DecisionService
from app.orchestration.events import FinalPayload
from app.orchestration.orchestrator import Orchestrator
from app.orchestration.turn_registry import TurnRegistry

CARD_YAML = """\
id: test
name: 小测
identity:
  full_name: 小测
  role: 桌面伙伴
  personality: 温柔
"""


class StubRoleplay:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def reply(self, turn: object, user_text: str, sink: object) -> None:
        self.calls.append(user_text)
        await sink.final(turn.id, FinalPayload(text="嗯。", route="chat"))  # type: ignore[attr-defined]


class Sink:
    def __init__(self) -> None:
        self.finals: list[FinalPayload] = []

    async def delta(self, turn_id: str, text: str) -> None:
        return None

    async def final(self, turn_id: str, payload: FinalPayload) -> None:
        self.finals.append(payload)

    async def error(self, turn_id: str, code: str, detail: str = "") -> None:
        return None


def _orchestrator(tmp_path: Path, roleplay: StubRoleplay) -> Orchestrator:
    (tmp_path / "test.yaml").write_text(CARD_YAML, encoding="utf-8")
    cards = CardLoader(tmp_path, "test")
    history = ShortTermMemory()
    builder = ContextBuilder(cards.current)
    return Orchestrator(
        decision=DecisionService(),
        commands=CommandRouter(cards=cards, history=history, builder=builder),
        roleplay=roleplay,  # type: ignore[arg-type]
        turns=TurnRegistry(),
    )


def test_command_route_does_not_touch_roleplay(tmp_path: Path) -> None:
    roleplay = StubRoleplay()
    orchestrator = _orchestrator(tmp_path, roleplay)
    sink = Sink()
    asyncio.run(orchestrator.handle_chat("t1", "/help", sink))
    assert sink.finals[0].route == "command"
    assert "/help" in sink.finals[0].text
    assert roleplay.calls == []


def test_chat_route_delegates_to_roleplay(tmp_path: Path) -> None:
    roleplay = StubRoleplay()
    orchestrator = _orchestrator(tmp_path, roleplay)
    sink = Sink()
    asyncio.run(orchestrator.handle_chat("t2", "今天天气不错", sink))
    assert roleplay.calls == ["今天天气不错"]
    assert sink.finals[0].route == "chat"


def test_interrupt_unknown_turn_returns_false(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, StubRoleplay())
    assert orchestrator.interrupt("missing") is False
