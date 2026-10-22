"""S6：工具注册表、Agent Core 五护栏、确认、Decision LLM 与提醒调度。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from app.memory.service import MemoryService
from app.orchestration.decision import DecisionService, Route
from app.providers.base import ChatResult, ToolCall
from app.scheduler.reminders import ReminderScheduler
from app.skills.meta_tools import SkillActivateTool, SkillListTool
from app.skills.registry import SkillRegistry
from app.store.db import Database
from app.tools.agent_core import AgentCore
from app.tools.base import ToolContext
from app.tools.builtin import (
    EmptyArgs,
    ForgetArgs,
    GetTimeArgs,
    RecallArgs,
    RememberArgs,
    SetReminderArgs,
    build_default_tools,
)
from app.tools.registry import ToolRegistry


class ScriptedProvider:
    def __init__(self, results: list[ChatResult]) -> None:
        self.results = results
        self.calls = 0

    async def chat_tools(self, messages, **_kwargs):
        self.calls += 1
        if self.results:
            return self.results.pop(0)
        return ChatResult(content="完成。")

    async def chat(self, messages, **_kwargs):
        await asyncio.sleep(0.01)
        return ChatResult(content='{"route":"task","confidence":0.9}')

    async def aclose(self):
        return None


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_default_tools():
        registry.register(tool)
    root = Path(__file__).resolve().parents[3] / "skills"
    skills = SkillRegistry(root)
    registry.register(SkillListTool(skills))
    registry.register(SkillActivateTool(skills))
    return registry


def _memory(tmp_path: Path) -> MemoryService:
    return MemoryService(Database(tmp_path / "agent.db"))


def test_registry_schemas_and_layers() -> None:
    registry = _registry()
    assert len(registry.names("agent")) >= 12
    schemas = registry.schemas("agent")
    assert all(item["type"] == "function" for item in schemas)
    assert all("parameters" in item["function"] for item in schemas)
    assert registry.set_enabled("get_time", False)
    assert "get_time" not in registry.names()
    assert registry.set_enabled("get_time", True)
    assert registry.names("roleplay") == []


def test_builtin_tools_roundtrip(tmp_path: Path) -> None:
    async def scenario() -> None:
        memory = _memory(tmp_path)
        await memory.start()
        ctx = ToolContext(memory=memory)
        tools = {tool.name: tool for tool in build_default_tools()}

        now = await tools["get_time"].run(GetTimeArgs(), ctx)
        assert now.ok and "时间" in now.content

        remembered = await tools["remember"].run(
            RememberArgs(content="用户喜欢黑咖啡", importance=0.8), ctx
        )
        assert remembered.ok
        recalled = await tools["recall"].run(RecallArgs(query="黑咖啡"), ctx)
        assert recalled.ok and "黑咖啡" in recalled.content

        reminder = await tools["set_reminder"].run(SetReminderArgs(text="喝水", in_minutes=1), ctx)
        assert reminder.ok
        listed = await tools["list_reminders"].run(EmptyArgs(), ctx)
        assert "喝水" in listed.content

        forgotten = await tools["forget"].run(ForgetArgs(query="黑咖啡"), ctx)
        assert forgotten.ok
        assert "黑咖啡" not in (await tools["recall"].run(RecallArgs(query="黑咖啡"), ctx)).content
        await memory.stop()

    asyncio.run(scenario())


def test_agent_loop_executes_tool_and_finishes(tmp_path: Path) -> None:
    async def scenario() -> None:
        memory = _memory(tmp_path)
        await memory.start()
        call = ToolCall(id="call_1", name="get_time", arguments={})
        provider = ScriptedProvider(
            [
                ChatResult(content="", tool_calls=(call,)),
                ChatResult(content="现在是下午。"),
            ]
        )
        agent = AgentCore(provider=provider, registry=_registry())
        result = await agent.run("现在几点", ToolContext(memory=memory))
        assert result.text == "现在是下午。"
        assert result.steps == 2
        assert result.tools_used == ["get_time"]
        await memory.stop()

    asyncio.run(scenario())


def test_agent_high_risk_requires_confirmation(tmp_path: Path) -> None:
    async def scenario() -> None:
        memory = _memory(tmp_path)
        await memory.start()
        await memory.store_memory(
            __import__("app.memory.extractor", fromlist=["MemoryCandidate"]).MemoryCandidate(
                type="fact", content="秘密", importance=0.9
            )
        )
        call = ToolCall(id="call_2", name="forget", arguments={"query": "秘密"})
        provider = ScriptedProvider(
            [
                ChatResult(content="", tool_calls=(call,)),
                ChatResult(content="那我先不删了。"),
            ]
        )
        confirmed = []

        async def confirm(tool: str, args: dict) -> bool:
            confirmed.append((tool, args))
            return False

        agent = AgentCore(provider=provider, registry=_registry())
        result = await agent.run(
            "把秘密忘掉",
            ToolContext(memory=memory, confirm=confirm),
        )
        assert confirmed and confirmed[0][0] == "forget"
        assert result.tools_used == []
        assert (await memory.recall("秘密"))[0]["content"] == "秘密"
        await memory.stop()

    asyncio.run(scenario())


def test_agent_unknown_tool_error_is_fed_back(tmp_path: Path) -> None:
    async def scenario() -> None:
        memory = _memory(tmp_path)
        await memory.start()
        call = ToolCall(id="call_3", name="not_a_tool", arguments={})
        provider = ScriptedProvider(
            [
                ChatResult(content="", tool_calls=(call,)),
                ChatResult(content="我换一种方式。"),
            ]
        )
        agent = AgentCore(provider=provider, registry=_registry())
        result = await agent.run("试试", ToolContext(memory=memory))
        assert "换一种方式" in result.text
        await memory.stop()

    asyncio.run(scenario())


def test_agent_max_steps(tmp_path: Path) -> None:
    async def scenario() -> None:
        memory = _memory(tmp_path)
        await memory.start()
        call = ToolCall(id="call_x", name="get_time", arguments={})
        provider = ScriptedProvider([ChatResult(content="", tool_calls=(call,))] * 20)
        agent = AgentCore(provider=provider, registry=_registry(), max_steps=3)
        result = await agent.run("循环", ToolContext(memory=memory))
        assert result.error == "MAX_STEPS"
        assert result.steps == 3
        await memory.stop()

    asyncio.run(scenario())


def test_decision_llm_fallback_and_modes() -> None:
    async def scenario() -> None:
        provider = ScriptedProvider([])
        service = DecisionService()
        result = await service.classify("今天有点复杂", provider=provider)
        assert result.route == Route.TASK
        assert result.matched_rule == "llm_classifier"

        chat_only = await service.classify("帮我写个总结", route_mode="chat_only")
        assert chat_only.route == Route.CHAT
        force = await service.classify("你好", route_mode="force_agent")
        assert force.route == Route.TASK
        command = await service.classify("/help", route_mode="chat_only")
        assert command.route == Route.COMMAND

    asyncio.run(scenario())


def test_decision_timeout_falls_back_to_chat() -> None:
    class Slow:
        async def chat(self, *_args, **_kwargs):
            await asyncio.sleep(2)
            return ChatResult(content='{"route":"task","confidence":0.9}')

    async def scenario() -> None:
        result = await DecisionService().classify("普通聊天", provider=Slow())
        assert result.route == Route.CHAT

    asyncio.run(scenario())


def test_reminder_scheduler_tick(tmp_path: Path) -> None:
    class FakeEmotion:
        def __init__(self) -> None:
            self.stimuli = []

        async def apply_stimulus(self, stimulus):
            self.stimuli.append(stimulus)

    async def scenario() -> None:
        memory = _memory(tmp_path)
        await memory.start()
        await memory.add_reminder("喝水", time.time() - 1)
        emitted: list[tuple[str, str]] = []

        async def emit(text: str, label: str) -> None:
            emitted.append((text, label))

        emotion = FakeEmotion()
        scheduler = ReminderScheduler(memory=memory, emotion=emotion, emit=emit)
        fired = await scheduler.tick()
        assert len(fired) == 1
        assert emitted and "喝水" in emitted[0][0]
        assert emitted[0][1] == "proud"
        assert emotion.stimuli
        assert await scheduler.tick() == []
        await memory.stop()

    asyncio.run(scenario())


def test_skill_meta_tools(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = Path(__file__).resolve().parents[3] / "skills"
        registry = SkillRegistry(root)
        ctx = ToolContext(memory=None)
        listed = await SkillListTool(registry).run(EmptyArgs(), ctx)
        assert "reminder" in listed.content
        activated = await SkillActivateTool(registry).run(
            __import__("app.skills.meta_tools", fromlist=["SkillActivateArgs"]).SkillActivateArgs(
                name="reminder"
            ),
            ctx,
        )
        assert activated.ok and "set_reminder" in activated.content

    asyncio.run(scenario())


def test_orchestrator_task_flow_ack_and_report(tmp_path: Path) -> None:
    from app.config.character_card import CardLoader
    from app.memory.context_builder import ContextBuilder
    from app.memory.short_term import ShortTermMemory
    from app.orchestration.commands import CommandRouter
    from app.orchestration.decision import DecisionService
    from app.orchestration.events import CuePayload, FinalPayload
    from app.orchestration.orchestrator import Orchestrator
    from app.orchestration.turn_registry import TurnRegistry

    class RoleplayStub:
        def __init__(self, provider) -> None:
            self.provider = provider

        async def reply(self, *args, **kwargs) -> None:
            return None

    class Sink:
        def __init__(self) -> None:
            self.finals: list[FinalPayload] = []

        async def delta(self, turn_id: str, text: str) -> None:
            return None

        async def final(self, turn_id: str, payload: FinalPayload) -> None:
            self.finals.append(payload)

        async def error(self, turn_id: str, code: str, detail: str = "") -> None:
            return None

        async def cue(self, turn_id: str, payload: CuePayload) -> None:
            return None

        async def confirm_request(self, *args, **kwargs) -> None:
            return None

    async def scenario() -> None:
        (tmp_path / "test.yaml").write_text(
            """id: test
name: 小测
identity:
  full_name: 小测
  role: 桌面伙伴
  personality: 温柔
persona:
  ack_templates:
    task: 好，我记一下。
""",
            encoding="utf-8",
        )
        cards = CardLoader(tmp_path, "test")
        memory = _memory(tmp_path)
        await memory.start()
        call = ToolCall(
            id="reminder_1",
            name="set_reminder",
            arguments={"text": "明天交稿", "in_minutes": 30},
        )
        provider = ScriptedProvider(
            [
                ChatResult(content="", tool_calls=(call,)),
                ChatResult(content="已经记下了。"),
            ]
        )
        agent = AgentCore(provider=provider, registry=_registry())
        orchestrator = Orchestrator(
            decision=DecisionService(),
            commands=CommandRouter(
                cards=cards,
                history=ShortTermMemory(),
                builder=ContextBuilder(cards.current),
                memory=memory,
            ),
            roleplay=RoleplayStub(provider),  # type: ignore[arg-type]
            turns=TurnRegistry(),
            memory=memory,
            agent=agent,
            route_mode="force_agent",
        )
        reports: list[tuple[str, str]] = []

        async def report(text: str, label: str) -> None:
            reports.append((text, label))

        orchestrator.set_report_sink(report)
        sink = Sink()
        await orchestrator.handle_chat("task1", "帮我记一下明天交稿", sink)  # type: ignore[arg-type]
        assert sink.finals[0].route == "task"
        assert "记一下" in sink.finals[0].text
        for _ in range(20):
            if reports:
                break
            await asyncio.sleep(0.05)
        assert reports and "记下" in reports[0][0]
        reminders = await memory.list_reminders()
        assert reminders and reminders[0]["text"] == "明天交稿"
        await memory.stop()

    asyncio.run(scenario())


def test_confirmation_store_resolves() -> None:
    from app.orchestration.confirmation import ConfirmationStore

    class Sink:
        def __init__(self) -> None:
            self.request_id = ""

        async def confirm_request(
            self, turn_id: str, request_id: str, tool: str, args: dict, **kwargs
        ) -> None:
            self.request_id = request_id

    async def scenario() -> None:
        store = ConfirmationStore()
        sink = Sink()

        async def approve_later() -> None:
            for _ in range(20):
                if sink.request_id:
                    break
                await asyncio.sleep(0.01)
            assert store.resolve(sink.request_id, True)

        task = asyncio.create_task(approve_later())
        approved = await store.request(
            sink,  # type: ignore[arg-type]
            "t1",
            "forget",
            {"query": "x"},
            timeout=1.0,
        )
        await task
        assert approved is True
        assert store.pending == 0

    asyncio.run(scenario())
