"""S6：SQLite 会话/记忆、摘要、上下文预算与 Skills。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config.character_card import CharacterCard, Identity
from app.memory.context_builder import ContextBuilder
from app.memory.extractor import extract_rules, keywords_for
from app.memory.service import MemoryService
from app.memory.tokens import count_tokens
from app.skills.registry import SkillRegistry
from app.store.db import Database


class FakeLLM:
    def __init__(self, reply: str = "摘要：用户在聊茶和猫。") -> None:
        self.reply = reply
        self.calls = 0

    async def chat(self, messages, **_kwargs):
        self.calls += 1
        from app.providers.base import ChatResult

        return ChatResult(content=self.reply)


def _memory(tmp_path: Path) -> MemoryService:
    return MemoryService(Database(tmp_path / "memory.db"))


def test_database_sessions_and_messages(tmp_path: Path) -> None:
    async def scenario() -> None:
        memory = _memory(tmp_path)
        await memory.start()
        first = memory.current_session
        await memory.append_turn("你好", "你好呀", "t1")
        assert await memory.message_count() == 2
        second = await memory.create_session("第二个")
        assert second != first
        await memory.append_turn("只属于第二个", "嗯", "t2")
        assert await memory.message_count() == 2
        assert await memory.switch_session(first)
        assert (await memory.recent_turns())[0][0] == "你好"
        await memory.rename_session("重命名")
        sessions = await memory.list_sessions()
        assert any(item.title == "重命名" for item in sessions)
        await memory.delete_session(second)
        await memory.stop()

    asyncio.run(scenario())


def test_extractor_and_profile(tmp_path: Path) -> None:
    candidates = extract_rules("我叫阿哲，我喜欢喝乌龙茶，帮我记一下周三交稿")
    contents = " ".join(item.content for item in candidates)
    assert "名字是阿哲" in contents
    assert "喜欢喝乌龙茶" in contents
    assert "周三交稿" in contents
    assert keywords_for("我喜欢乌龙茶")

    async def scenario() -> None:
        memory = _memory(tmp_path)
        await memory.start()
        for item in candidates:
            await memory.store_memory(item)
        profile = await memory.get_profile()
        assert profile["name"] == "阿哲"
        hits = await memory.recall("阿哲")
        assert hits
        assert "阿哲" in hits[0]["content"]
        block = await memory.context_block("我叫什么")
        assert "长期记忆" in block
        assert "阿哲" in block
        await memory.forget(all_sessions=True)
        assert await memory.get_profile() == {}
        await memory.stop()

    asyncio.run(scenario())


def test_summary_keeps_recent_window_and_reduces_context(tmp_path: Path) -> None:
    async def scenario() -> None:
        memory = _memory(tmp_path)
        await memory.start()
        for index in range(40):
            await memory.append_turn(f"用户第{index}句话", f"助手第{index}句回复", f"t{index}")
        provider = FakeLLM()
        summary = await memory.maybe_summarize(provider)
        assert summary
        assert provider.calls >= 1
        recent = await memory.recent_turns()
        assert len(recent) == 20
        full_tokens = sum(
            count_tokens(u) + count_tokens(a) for u, a in (await memory.recent_turns(100))
        )
        assert full_tokens < 5000
        row = await memory._db.fetchone(  # noqa: SLF001 - 验证滚动游标
            "SELECT summarized_upto FROM sessions WHERE id=?", (memory.current_session,)
        )
        assert row and row[0] > 0
        await memory.stop()

    asyncio.run(scenario())


def test_context_builder_memory_budget() -> None:
    card = CharacterCard(
        id="test",
        name="小测",
        identity=Identity(full_name="小测", role="桌面伙伴", personality="温柔"),
    )
    builder = ContextBuilder(card)
    messages = builder.build(
        [("问题" * 200, "回答" * 200) for _ in range(5)],
        "现在",
        memory_block="【长期记忆】\n用户画像：名字=阿哲\n" + "记忆" * 1000,
    )
    system = messages[0].content
    assert "长期记忆" in system
    assert count_tokens(system) <= 1500
    assert messages[-1].content == "现在"


def test_skills_registry_and_path_safety(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3] / "skills"
    registry = SkillRegistry(root)
    names = [item.name for item in registry.list_skills()]
    assert {"reminder", "emotional-support", "morning-greeting"} <= set(names)
    body = registry.activate("reminder")
    assert "set_reminder" in body
    assert "时间解析" in registry.read("reminder", 1)
    assert registry.activate("../etc/passwd").startswith("技能不存在")
    assert registry.is_active("reminder")

    # 30 分钟自动卸载
    registry._active["reminder"] = time.time() - 1801  # noqa: SLF001
    assert "reminder" not in registry.active_names()
    assert not registry.is_active("reminder")


def test_memory_api(client: TestClient) -> None:
    sessions = client.get("/api/v1/memory/sessions")
    assert sessions.status_code == 200
    data = sessions.json()
    assert data["current"]
    created = client.post("/api/v1/memory/sessions", json={"title": "API 会话"})
    assert created.status_code == 200
    session_id = created.json()["id"]
    switched = client.post(f"/api/v1/memory/sessions/{session_id}/switch")
    assert switched.status_code == 200
    memories = client.get("/api/v1/memory/memories")
    assert memories.status_code == 200
    assert "profile" in memories.json()
    tools = client.get("/api/v1/tools").json()["tools"]
    assert len(tools) >= 12
    skills = client.get("/api/v1/skills").json()["skills"]
    assert len(skills) == 3
    route = client.patch("/api/v1/config/agent", json={"route_mode": "chat_only"})
    assert route.status_code == 200
    assert route.json()["route_mode"] == "chat_only"


def test_memory_persists_across_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        first = _memory(tmp_path)
        await first.start()
        await first.after_turn("我叫阿哲，我喜欢黑咖啡", "好的。")
        await first.store_memory(
            __import__("app.memory.extractor", fromlist=["MemoryCandidate"]).MemoryCandidate(
                type="preference", content="用户喜欢黑咖啡", importance=0.9
            )
        )
        await first.stop()

        second = _memory(tmp_path)
        await second.start()
        assert (await second.get_profile())["name"] == "阿哲"
        assert any("黑咖啡" in item["content"] for item in await second.list_memories())
        await second.stop()

    asyncio.run(scenario())
