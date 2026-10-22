"""工具基类与上下文（T6-09）。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

Risk = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, content: str, **data: Any) -> ToolResult:
        return cls(True, content, data)

    @classmethod
    def failure(cls, content: str) -> ToolResult:
        return cls(False, content)


ConfirmFn = Callable[[str, dict[str, Any]], Awaitable[bool]]


@dataclass
class ToolContext:
    memory: Any
    emotion: Any = None
    skills: Any = None
    confirm: ConfirmFn | None = None
    now: float | None = None


class Tool:
    name: str = ""
    description: str = ""
    layer: Literal["agent", "roleplay", "system"] = "agent"
    risk: Risk = "low"
    args_model: type[BaseModel] = BaseModel

    async def run(self, args: Any, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        parameters = self.args_model.model_json_schema()
        parameters.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }
