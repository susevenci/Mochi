"""Token 计数（T6-03）：优先 tiktoken，缺失时按字符近似。"""

from __future__ import annotations

import functools
from typing import Any


@functools.lru_cache(maxsize=1)
def _encoding() -> Any:
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - 离线/未安装时近似
        return None


def count_tokens(text: str) -> int:
    encoding = _encoding()
    if encoding is not None:
        try:
            return len(encoding.encode(text))
        except Exception:  # noqa: BLE001
            pass
    # 中文约 1 token/1.6 字，英文约 1 token/4 字符；折中取 2.5 字符/token
    return max(1, int(len(text) / 2.5))


def truncate_tokens(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    encoding = _encoding()
    if encoding is not None:
        try:
            tokens = encoding.encode(text)
            if len(tokens) <= limit:
                return text
            return encoding.decode(tokens[:limit])
        except Exception:  # noqa: BLE001
            pass
    return text[: int(limit * 2.5)]
