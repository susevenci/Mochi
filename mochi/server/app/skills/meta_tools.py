"""Skills 三工具（T6-12）：list / activate / read。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.skills.registry import SkillRegistry
from app.tools.base import Tool, ToolContext, ToolResult


class SkillListTool(Tool):
    name = "skill_list"
    description = "列出当前可用技能（常驻，开销很小）"
    args_model = type("SkillListArgs", (BaseModel,), {})

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        return ToolResult.success(self._registry.list_text())


class SkillActivateArgs(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class SkillActivateTool(Tool):
    name = "skill_activate"
    description = "激活一个技能，把完整说明加入上下文"
    args_model = SkillActivateArgs

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    async def run(self, args: SkillActivateArgs, ctx: ToolContext) -> ToolResult:
        body = self._registry.activate(args.name)
        if body.startswith("技能不存在"):
            return ToolResult.failure(body)
        return ToolResult.success(body)


class SkillReadArgs(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    page: int = Field(default=0, ge=0, le=20)


class SkillReadTool(Tool):
    name = "skill_read"
    description = "读取技能的分页参考资料"
    args_model = SkillReadArgs

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    async def run(self, args: SkillReadArgs, ctx: ToolContext) -> ToolResult:
        text = self._registry.read(args.name, args.page)
        if text.startswith("技能不存在"):
            return ToolResult.failure(text)
        return ToolResult.success(text)
