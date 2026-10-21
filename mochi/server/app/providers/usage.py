"""Token 用量统计与成本核算（占位，S6 起接入 SQLite）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .base import Usage

log = logging.getLogger(__name__)


@dataclass
class _Bucket:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, usage: Usage | None) -> None:
        self.calls += 1
        if usage is not None:
            self.prompt_tokens += usage.prompt_tokens
            self.completion_tokens += usage.completion_tokens


class UsageTracker:
    """按用途累加 token；单进程单例（I6）。"""

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}

    def record(self, purpose: str, usage: Usage | None) -> None:
        bucket = self._buckets.setdefault(purpose, _Bucket())
        bucket.add(usage)
        log.info(
            "usage purpose=%s calls=%d prompt=%d completion=%d",
            purpose,
            bucket.calls,
            bucket.prompt_tokens,
            bucket.completion_tokens,
        )

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {
            purpose: {
                "calls": bucket.calls,
                "prompt_tokens": bucket.prompt_tokens,
                "completion_tokens": bucket.completion_tokens,
            }
            for purpose, bucket in self._buckets.items()
        }
