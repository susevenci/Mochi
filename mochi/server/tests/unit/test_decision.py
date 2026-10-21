"""决策层规则测试（T1-08 验收）。"""

from __future__ import annotations

import asyncio

from app.orchestration.decision import DecisionService, Route, classify_rules


def test_command_prefix() -> None:
    result = classify_rules("/help")
    assert result is not None
    assert result.route == Route.COMMAND
    assert result.matched_rule == "command_prefix"


def test_task_pattern() -> None:
    result = classify_rules("帮我写一个爬虫脚本")
    assert result is not None
    assert result.route == Route.TASK


def test_emotional_lexicon() -> None:
    result = classify_rules("今天真的谢谢你")
    assert result is not None
    assert result.route == Route.EMOTIONAL


def test_plain_chat_returns_none() -> None:
    assert classify_rules("今天天气不错") is None


def test_service_falls_back_to_chat() -> None:
    result = asyncio.run(DecisionService().classify("今天天气不错"))
    assert result.route == Route.CHAT
    assert result.latency_ms >= 0
