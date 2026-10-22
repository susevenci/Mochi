"""自然度后处理（T7-02）：避免逐字复读，保持句式有变化。"""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_SUFFIXES = ("……换个说法。", "嗯，刚刚说过啦。", "——总之就是这样。")


def ensure_variety(
    text: str,
    recent_assistant: Sequence[str],
    *,
    interjections: Sequence[str] = (),
) -> str:
    cleaned = text.strip()
    if not cleaned:
        return text
    if cleaned not in set(recent_assistant):
        return text
    candidates = list(interjections) + list(DEFAULT_SUFFIXES)
    suffix = candidates[0] if candidates else "……"
    return f"{cleaned}{suffix}"
