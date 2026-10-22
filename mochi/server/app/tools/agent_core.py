"""Agent Core（T6-10）：工具循环 + 五道护栏。

护栏：最多 8 步 / 单工具 30s / 整体墙钟 120s / 可取消 / 参数校验。
工具错误以 ``ToolResult(ok=False)`` 回灌，让模型自我修正。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import ChatMessage, LLMError
from app.tools.base import ToolContext, ToolResult
from app.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

MAX_STEPS = 8
MAX_WALL_CLOCK = 120.0
TOOL_TIMEOUT = 30.0
LLM_TIMEOUT = 60.0

SYSTEM_PROMPT = """你是 Mochi 的执行层。你可以调用工具完成用户的任务。
- 先用一句话确认任务，再调用工具；不要在工具结果前编造结果。
- 工具失败时根据错误调整参数；最多尝试 8 步。
- 完成后用简洁中文汇报结果，不要输出 JSON 或工具名。
"""


@dataclass
class AgentResult:
    text: str
    steps: int = 0
    tools_used: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class AgentCore:
    def __init__(
        self,
        *,
        provider: Any,
        registry: ToolRegistry,
        max_steps: int = MAX_STEPS,
        max_wall_clock: float = MAX_WALL_CLOCK,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._max_steps = max_steps
        self._max_wall = max_wall_clock

    def set_provider(self, provider: Any) -> None:
        self._provider = provider

    async def run(
        self,
        user_text: str,
        ctx: ToolContext,
        *,
        cancelled: Any = None,
    ) -> AgentResult:
        started = time.monotonic()
        messages = [
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_text),
        ]
        tools = self._registry.schemas("agent")
        used: list[str] = []
        actions: list[dict[str, Any]] = []
        for step in range(1, self._max_steps + 1):
            if cancelled is not None and cancelled():
                return AgentResult("", step, used, actions, "TASK_CANCELLED")
            remaining = self._max_wall - (time.monotonic() - started)
            if remaining <= 0:
                return AgentResult("任务超时了，我先停一下。", step, used, actions, "TASK_TIMEOUT")
            try:
                result = await asyncio.wait_for(
                    self._provider.chat_tools(
                        messages,
                        tools=tools,
                        temperature=0.0,
                        max_tokens=700,
                    ),
                    timeout=min(LLM_TIMEOUT, remaining),
                )
            except (TimeoutError, LLMError) as exc:
                log.warning("agent llm failed step=%s: %s", step, exc)
                return AgentResult(
                    "我这边调用模型失败了，稍后再试。", step, used, actions, "LLM_FAILED"
                )

            if not result.tool_calls:
                return AgentResult(result.content.strip() or "完成了。", step, used, actions)

            calls_wire = []
            for call in result.tool_calls:
                calls_wire.append(
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                )
            messages.append(
                ChatMessage(role="assistant", content=result.content, tool_calls=tuple(calls_wire))
            )

            for call in result.tool_calls:
                tool = self._registry.get(call.name)
                if tool is None:
                    messages.append(
                        ChatMessage(
                            role="tool",
                            content=f"错误：工具 {call.name} 不存在或已关闭",
                            tool_call_id=call.id,
                        )
                    )
                    continue
                try:
                    args = tool.args_model.model_validate(call.arguments)
                except Exception as exc:  # noqa: BLE001 - 参数校验失败回灌
                    messages.append(
                        ChatMessage(
                            role="tool",
                            content=f"参数错误：{exc}",
                            tool_call_id=call.id,
                        )
                    )
                    continue
                if tool.risk == "high":
                    approved = (
                        await ctx.confirm(call.name, args.model_dump())
                        if ctx.confirm is not None
                        else False
                    )
                    if not approved:
                        messages.append(
                            ChatMessage(
                                role="tool",
                                content="用户拒绝了这次操作。",
                                tool_call_id=call.id,
                            )
                        )
                        continue
                try:
                    tool_result = await asyncio.wait_for(tool.run(args, ctx), timeout=TOOL_TIMEOUT)
                except TimeoutError:
                    tool_result = ToolResult.failure("工具执行超时")
                except Exception as exc:  # noqa: BLE001 - 工具异常不终止循环
                    tool_result = ToolResult.failure(str(exc))
                used.append(tool.name)
                if "motion" in tool_result.data:
                    actions.append({"motion": tool_result.data["motion"]})
                messages.append(
                    ChatMessage(
                        role="tool",
                        content=tool_result.content,
                        tool_call_id=call.id,
                    )
                )
        return AgentResult(
            "这个任务我试了几步还没搞定，先停一下。", self._max_steps, used, actions, "MAX_STEPS"
        )
