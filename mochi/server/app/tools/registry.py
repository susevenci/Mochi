"""工具注册表（T6-09）：按层过滤、热开关、导出 OpenAI schema。"""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolResult

__all__ = ["ToolRegistry"]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._enabled: dict[str, bool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("tool.name 不能为空")
        self._tools[tool.name] = tool
        self._enabled.setdefault(tool.name, True)

    def get(self, name: str) -> Tool | None:
        tool = self._tools.get(name)
        if tool is None or not self._enabled.get(name, True):
            return None
        return tool

    def set_enabled(self, name: str, enabled: bool) -> bool:
        if name not in self._tools:
            return False
        self._enabled[name] = enabled
        return True

    def names(self, layer: str | None = None) -> list[str]:
        return [
            name
            for name, tool in self._tools.items()
            if self._enabled.get(name, True) and (layer is None or tool.layer == layer)
        ]

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "enabled": bool(self._enabled.get(name, True)),
                "layer": tool.layer,
                "risk": tool.risk,
            }
            for name, tool in self._tools.items()
        ]

    def schemas(self, layer: str = "agent") -> list[dict[str, Any]]:
        return [self._tools[name].schema() for name in self.names(layer)]

    async def execute(self, name: str, args: Any, ctx: Any) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult.failure(f"工具未启用或不存在：{name}")
        return await tool.run(args, ctx)
