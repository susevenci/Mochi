"""ContextBuilder 测试（T1-05 验收）：I2 纯净上下文 + 按轮次截断。"""

from __future__ import annotations

from app.config.character_card import CharacterCard, Identity
from app.memory.context_builder import ContextBuilder


def _builder() -> ContextBuilder:
    card = CharacterCard(
        id="test",
        name="小测",
        identity=Identity(full_name="小测", role="桌面伙伴", personality="温柔、话少"),
    )
    return ContextBuilder(card)


def test_roleplay_has_zero_tool_schema() -> None:
    """I2：扮演层 prompt 中不得出现工具相关内容。"""
    messages = _builder().build([], "你好")
    assert messages[0].role == "system"
    joined = "".join(message.content for message in messages).lower()
    assert "tools" not in joined
    assert "工具" not in joined
    assert "function" not in joined


def test_system_prompt_contains_persona_and_format() -> None:
    text = _builder().system_prompt()
    assert "小测" in text
    assert "<<<MOOD>>>" in text
    assert "桌面伙伴" in text


def test_truncation_keeps_whole_turns() -> None:
    recent = [("问" * 500, "答" * 500) for _ in range(10)]
    messages = _builder().build(recent, "现在")
    body = messages[1:-1]
    assert len(body) % 2 == 0  # 绝不切断一问一答
    assert len(body) < 20
    assert messages[-1].content == "现在"
