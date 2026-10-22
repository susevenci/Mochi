"""记忆抽取（T6-05）：规则优先，小模型补充。

规则覆盖"值得记"的高频场景：名字、偏好、生日、显式嘱托。
抽取失败绝不阻塞对话；所有条目带 type / importance / keywords。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.providers.base import ChatMessage

__all__ = ["MemoryCandidate", "extract_rules", "extract_with_llm", "keywords_for"]

NAME_PATTERNS = (
    re.compile(r"我(?:叫|名字叫)([\u4e00-\u9fa5A-Za-z0-9_]{1,12})"),
    re.compile(r"叫我([\u4e00-\u9fa5A-Za-z0-9_]{1,12})"),
)
PREFERENCE_PATTERN = re.compile(r"我(?:很)?(喜欢|爱|不喜欢|讨厌)([^，。！？!?\n]{1,20})")
REMEMBER_PATTERN = re.compile(r"(?:记住|记一下|帮我记(?:一下)?)[：:，,]?(.{2,40})")
BIRTHDAY_PATTERN = re.compile(r"我(?:的)?生日(?:是|在)?([0-9]{1,2}月[0-9]{1,2}[日号]?)")


@dataclass(frozen=True)
class MemoryCandidate:
    type: str
    content: str
    importance: float = 0.6
    keywords: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "content": self.content,
            "importance": self.importance,
            "keywords": self.keywords,
        }


def keywords_for(text: str) -> str:
    """中文 bigram + 英文/数字词，供 FTS5 unicode61 使用。"""
    tokens: list[str] = []
    for run in re.findall(r"[\u4e00-\u9fa5]+", text):
        tokens.extend(run[index : index + 2] for index in range(max(0, len(run) - 1)))
        if len(run) == 1:
            tokens.append(run)
    tokens.extend(re.findall(r"[A-Za-z0-9_]{2,}", text))
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return " ".join(ordered[:40])


def extract_rules(text: str) -> list[MemoryCandidate]:
    candidates: list[MemoryCandidate] = []
    seen: set[str] = set()

    def add(kind: str, content: str, importance: float) -> None:
        content = content.strip()
        if not content or content in seen:
            return
        seen.add(content)
        candidates.append(
            MemoryCandidate(
                type=kind,
                content=content,
                importance=importance,
                keywords=keywords_for(content),
            )
        )

    for pattern in NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            add("profile", f"用户的名字是{match.group(1)}", 0.95)
            break
    for match in PREFERENCE_PATTERN.finditer(text):
        add("preference", f"用户{match.group(1)}{match.group(2)}", 0.7)
    for match in BIRTHDAY_PATTERN.finditer(text):
        add("profile", f"用户的生日是{match.group(1)}", 0.9)
    for match in REMEMBER_PATTERN.finditer(text):
        add("fact", match.group(1).strip(), 0.8)
    return candidates


LLM_PROMPT = (
    "从用户的话里抽取值得长期记住的事实。只输出 JSON 数组，每项 "
    '{"type":"profile|preference|fact|event","content":"一句中文","importance":0.0-1.0}。'
    "没有值得记的就输出 []。不要抽取寒暄。用户："
)


async def extract_with_llm(provider: Any, text: str) -> list[MemoryCandidate]:
    if provider is None or len(text.strip()) < 8:
        return []
    try:
        result = await provider.chat(
            [
                ChatMessage(role="system", content=LLM_PROMPT),
                ChatMessage(role="user", content=text),
            ],
            temperature=0.0,
            max_tokens=160,
        )
        raw = result.content.strip()
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        items = json.loads(match.group(0))
    except Exception:  # noqa: BLE001 - 抽取失败不影响对话
        return []
    out: list[MemoryCandidate] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        try:
            importance = max(0.0, min(1.0, float(item.get("importance", 0.5))))
        except (TypeError, ValueError):
            importance = 0.5
        out.append(
            MemoryCandidate(
                type=str(item.get("type") or "fact"),
                content=content,
                importance=importance,
                keywords=keywords_for(content),
            )
        )
    return out
