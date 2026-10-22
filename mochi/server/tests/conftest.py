from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.providers.base import ChatMessage, ChatResult, Usage


class FakeClock:
    """可推进的假时钟：引擎测试禁止真实等待（计划 T3-06/TX-03）。"""

    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class MockLLMProvider:
    """记录调用并按脚本返回的 Provider 假实现（不触网）。"""

    def __init__(
        self,
        *,
        replies: list[str] | None = None,
        chunks: list[str] | None = None,
        tool_results: list[ChatResult] | None = None,
    ) -> None:
        self.replies = replies or ["好呀。"]
        self.chunks = chunks or ["好", "呀", "。"]
        self.tool_results = tool_results or []
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.85,
        max_tokens: int = 512,
        disable_thinking: bool = False,
    ) -> ChatResult:
        self.calls.append({"kind": "chat", "messages": list(messages), "model": model})
        text = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return ChatResult(content=text, model=model or "mock", usage=Usage(1, 1, 2))

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.85,
        max_tokens: int = 512,
        disable_thinking: bool = False,
    ) -> AsyncIterator[str]:
        self.calls.append({"kind": "stream", "messages": list(messages), "model": model})
        for chunk in self.chunks:
            yield chunk

    async def chat_tools(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[dict[str, Any]] = (),
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> ChatResult:
        self.calls.append({"kind": "chat_tools", "messages": list(messages), "tools": list(tools)})
        if self.tool_results:
            return self.tool_results.pop(0)
        return await self.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """临时数据目录 + 关闭 token，避免污染 %APPDATA% 与依赖本机环境。"""
    return Settings(data_dir=tmp_path, server_token="", llm_api_key="")


@pytest.fixture()
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def mock_provider() -> MockLLMProvider:
    return MockLLMProvider()


@pytest.fixture()
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
