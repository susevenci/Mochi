"""摘要压缩与滚动合并（T6-04）。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.providers.base import ChatMessage

log = logging.getLogger(__name__)

SUMMARY_PROMPT = """你是对话摘要器。把旧摘要和新增对话合并成一段不超过 220 字的中文摘要。
保留：用户事实/偏好、承诺、未完成的事、关系与情绪线索。不要编造，不要评价。
只输出摘要正文。"""


async def summarize(
    provider: Any,
    previous: str,
    transcript: str,
    *,
    max_chars: int = 600,
    timeout: float = 8.0,
) -> str:
    if not transcript.strip():
        return previous.strip()
    content = f"旧摘要：{previous or '（无）'}\n\n新增对话：\n{transcript}"
    try:
        result = await asyncio.wait_for(
            provider.chat(
                [
                    ChatMessage(role="system", content=SUMMARY_PROMPT),
                    ChatMessage(role="user", content=content),
                ],
                temperature=0.2,
                max_tokens=320,
            ),
            timeout=timeout,
        )
        summary = result.content.strip()
        if summary:
            return summary[:max_chars]
    except Exception as exc:  # noqa: BLE001 - 摘要失败用截断兜底
        log.warning("summary failed, fallback to truncate: %s", exc)
    merged = (previous + "\n" + transcript).strip()
    return merged[-max_chars:]
