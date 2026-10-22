"""12 个内置工具（T6-11）。外部网络工具失败时返回可读错误，由 Agent Core 回灌。"""

from __future__ import annotations

import time
import webbrowser
from datetime import datetime
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from app.memory.extractor import MemoryCandidate, keywords_for
from app.tools.base import Tool, ToolContext, ToolResult


class EmptyArgs(BaseModel):
    pass


class GetTimeArgs(BaseModel):
    timezone: str = Field(default="local", description="local 或 utc")


class GetTimeTool(Tool):
    name = "get_time"
    description = "获取当前日期和时间"
    args_model = GetTimeArgs

    async def run(self, args: GetTimeArgs, ctx: ToolContext) -> ToolResult:
        moment = datetime.utcnow() if args.timezone == "utc" else datetime.now()
        label = "UTC" if args.timezone == "utc" else "本地"
        return ToolResult.success(f"{label}时间：{moment.strftime('%Y-%m-%d %H:%M:%S')}")


class SetReminderArgs(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    in_minutes: int = Field(default=10, ge=1, le=10080)
    at_iso: str | None = Field(default=None, description="ISO 时间；提供时优先于 in_minutes")


class SetReminderTool(Tool):
    name = "set_reminder"
    description = "创建提醒；到点后桌宠会主动播报"
    args_model = SetReminderArgs

    async def run(self, args: SetReminderArgs, ctx: ToolContext) -> ToolResult:
        now = time.time()
        due_at = now + args.in_minutes * 60
        if args.at_iso:
            try:
                due_at = datetime.fromisoformat(args.at_iso).timestamp()
            except ValueError:
                return ToolResult.failure("时间格式不对，请用 ISO 格式（如 2026-10-22T21:30:00）")
        if due_at <= now:
            return ToolResult.failure("提醒时间已经过去了")
        reminder_id = await ctx.memory.add_reminder(args.text, due_at)
        when = datetime.fromtimestamp(due_at).strftime("%m-%d %H:%M")
        return ToolResult.success(
            f"已记下提醒 #{reminder_id}：{args.text}（{when}）",
            reminder_id=reminder_id,
            due_at=due_at,
        )


class ListRemindersTool(Tool):
    name = "list_reminders"
    description = "列出未到期的提醒"
    args_model = EmptyArgs

    async def run(self, args: EmptyArgs, ctx: ToolContext) -> ToolResult:
        reminders = await ctx.memory.list_reminders()
        if not reminders:
            return ToolResult.success("目前没有待办提醒。")
        lines = [
            f"#{item['id']} {item['text']}（{datetime.fromtimestamp(item['due_at']):%m-%d %H:%M}）"
            for item in reminders
        ]
        return ToolResult.success("待办提醒：\n" + "\n".join(lines))


class RememberArgs(BaseModel):
    content: str = Field(min_length=1, max_length=300)
    importance: float = Field(default=0.7, ge=0.0, le=1.0)


class RememberTool(Tool):
    name = "remember"
    description = "把一条事实写入长期记忆"
    args_model = RememberArgs

    async def run(self, args: RememberArgs, ctx: ToolContext) -> ToolResult:
        candidate = MemoryCandidate(
            type="fact",
            content=args.content,
            importance=args.importance,
            keywords=keywords_for(args.content),
        )
        await ctx.memory.store_memory(candidate)
        return ToolResult.success(f"记住了：{args.content}")


class RecallArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=4, ge=1, le=10)


class RecallTool(Tool):
    name = "recall"
    description = "检索长期记忆"
    args_model = RecallArgs

    async def run(self, args: RecallArgs, ctx: ToolContext) -> ToolResult:
        items = await ctx.memory.recall(args.query, args.limit)
        if not items:
            return ToolResult.success("没有找到相关记忆。")
        return ToolResult.success(
            "相关记忆：\n" + "\n".join(f"- {item['content']}" for item in items),
            memories=items,
        )


class ForgetArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class ForgetTool(Tool):
    name = "forget"
    description = "删除与查询匹配的长期记忆（高风险，需要用户确认）"
    risk = "high"
    args_model = ForgetArgs

    async def run(self, args: ForgetArgs, ctx: ToolContext) -> ToolResult:
        count = await ctx.memory.delete_matching(args.query)
        return ToolResult.success(f"已删除 {count} 条匹配记忆。", deleted=count)


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class WebSearchTool(Tool):
    name = "web_search"
    description = "搜索网页（DuckDuckGo Lite，无需 API Key）"
    args_model = WebSearchArgs

    async def run(self, args: WebSearchArgs, ctx: ToolContext) -> ToolResult:
        url = "https://html.duckduckgo.com/html/?q=" + quote(args.query)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(8.0), trust_env=False, follow_redirects=True
            ) as client:
                response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code >= 400:
                return ToolResult.failure(f"搜索失败：HTTP {response.status_code}")
            import re

            titles = re.findall(
                r'<a[^>]+class="result__a"[^>]*>(.*?)</a>', response.text, re.DOTALL
            )
            cleaned = [re.sub(r"<[^>]+>", "", title).strip() for title in titles[:5]]
            if not cleaned:
                return ToolResult.success("没有找到明显相关的结果。")
            return ToolResult.success("搜索结果：\n" + "\n".join(f"- {item}" for item in cleaned))
        except Exception as exc:  # noqa: BLE001 - 网络失败可回灌
            return ToolResult.failure(f"搜索失败：{exc}")


class WeatherArgs(BaseModel):
    city: str = Field(default="北京", max_length=40)


class WeatherTool(Tool):
    name = "weather"
    description = "查询城市天气（wttr.in）"
    args_model = WeatherArgs

    async def run(self, args: WeatherArgs, ctx: ToolContext) -> ToolResult:
        url = f"https://wttr.in/{quote(args.city)}?format=%l:+%c+%t+%w"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(8.0), trust_env=False) as client:
                response = await client.get(url, headers={"User-Agent": "curl/8"})
            if response.status_code >= 400:
                return ToolResult.failure(f"天气查询失败：HTTP {response.status_code}")
            return ToolResult.success(response.text.strip())
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(f"天气查询失败：{exc}")


class GetEmotionTool(Tool):
    name = "get_emotion"
    description = "读取桌宠当前情绪状态"
    args_model = EmptyArgs

    async def run(self, args: EmptyArgs, ctx: ToolContext) -> ToolResult:
        if ctx.emotion is None:
            return ToolResult.success("情绪引擎未接入。")
        state = ctx.emotion.state
        return ToolResult.success(
            f"当前情绪：{state.label}，强度 {state.intensity:.2f}，亲密度 {state.affinity:.2f}",
            label=state.label,
            pad=state.pad.to_dict(),
        )


class PlayMotionArgs(BaseModel):
    motion: str = Field(default="touch_head", max_length=40)


class PlayMotionTool(Tool):
    name = "play_motion"
    description = "请求前端播放一个 Live2D 动作"
    args_model = PlayMotionArgs

    async def run(self, args: PlayMotionArgs, ctx: ToolContext) -> ToolResult:
        return ToolResult.success(f"动作已排队：{args.motion}", motion=args.motion)


class SaveProfileArgs(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=200)


class SaveProfileTool(Tool):
    name = "save_profile"
    description = "更新用户画像（如名字、称呼、偏好）"
    args_model = SaveProfileArgs

    async def run(self, args: SaveProfileArgs, ctx: ToolContext) -> ToolResult:
        await ctx.memory.set_profile(args.key, args.value)
        return ToolResult.success(f"画像已更新：{args.key}={args.value}")


class SpeakArgs(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class SpeakTool(Tool):
    name = "speak"
    description = "请求用语音播报一段文字（由 TTS 链路执行）"
    args_model = SpeakArgs

    async def run(self, args: SpeakArgs, ctx: ToolContext) -> ToolResult:
        return ToolResult.success(f"将播报：{args.text}", speak=args.text)


class OpenUrlArgs(BaseModel):
    url: str = Field(min_length=8, max_length=500)


class OpenUrlTool(Tool):
    name = "open_url"
    description = "在系统浏览器打开一个 http(s) 链接（高风险）"
    risk = "high"
    args_model = OpenUrlArgs

    async def run(self, args: OpenUrlArgs, ctx: ToolContext) -> ToolResult:
        if not args.url.startswith(("http://", "https://")):
            return ToolResult.failure("只允许 http/https 链接")
        try:
            webbrowser.open(args.url)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(f"打开失败：{exc}")
        return ToolResult.success(f"已在浏览器打开：{args.url}")


def build_default_tools() -> list[Tool]:
    return [
        GetTimeTool(),
        SetReminderTool(),
        ListRemindersTool(),
        RememberTool(),
        RecallTool(),
        ForgetTool(),
        WebSearchTool(),
        WeatherTool(),
        GetEmotionTool(),
        PlayMotionTool(),
        SaveProfileTool(),
        SpeakTool(),
        OpenUrlTool(),
    ]
