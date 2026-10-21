"""LLM Provider 抽象（计划书 4.3 / 5.1）。

不变量 I5：业务层（orchestration / emotion / memory）禁止直连 LLM SDK，
一律经此接口；换供应商只改 base_url + model。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str  # system | user | assistant | tool
    content: str
    tool_call_id: str | None = None

    def to_wire(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        return data


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_wire(cls, raw: dict[str, Any] | None) -> Usage | None:
        if not raw:
            return None
        return cls(
            prompt_tokens=int(raw.get("prompt_tokens") or 0),
            completion_tokens=int(raw.get("completion_tokens") or 0),
            total_tokens=int(raw.get("total_tokens") or 0),
        )


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str = ""
    finish_reason: str | None = None
    usage: Usage | None = None
    reasoning: str = ""


class LLMError(Exception):
    """LLM 调用失败的统一异常，``code`` 供前端错误码与降级文案使用。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class LLMProvider(Protocol):
    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.85,
        max_tokens: int = 512,
        disable_thinking: bool = False,
    ) -> ChatResult: ...

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.85,
        max_tokens: int = 512,
        disable_thinking: bool = False,
    ) -> AsyncIterator[str]:
        """逐段产出正文增量（``reasoning_content`` 一律丢弃）。"""
        ...

    async def aclose(self) -> None: ...
