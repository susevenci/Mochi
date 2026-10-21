"""流式双通道解析（T1-06；对应规划文档 3.5.1）。

LLM 先流式输出正文，再输出 ``<<<MOOD>>>``，最后是一个 JSON 块。
四个必须处理的真实故障：
1. 分隔符被 token 边界拆开（``<<<MO`` + ``OD>>>``）
2. 正文里出现 ``<<<`` 但不是分隔符 → 必须原样回吐，不能吞字
3. JSON 被 max_tokens 截断 → 丢弃该块，正文优先
4. JSON 外面包了 ```json 围栏 → 兼容剥离

四态状态机：TEXT → PENDING → JSON → DONE
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

SEPARATOR = "<<<MOOD>>>"
TRIGGER = "<<<"

STATE_TEXT = "TEXT"
STATE_PENDING = "PENDING"
STATE_JSON = "JSON"
STATE_DONE = "DONE"


def _common_suffix_len(text: str, trigger: str) -> int:
    """text 末尾与 trigger 前缀重合的最长长度（用于决定"先别下发"的尾部）。"""
    for size in range(min(len(text), len(trigger) - 1), 0, -1):
        if trigger.startswith(text[-size:]):
            return size
    return 0


@dataclass(frozen=True)
class MoodResult:
    text: str
    emotion: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    parsed: bool = False
    note: str = ""


class MoodStreamParser:
    def __init__(self, separator: str = SEPARATOR) -> None:
        self._sep = separator
        self._state = STATE_TEXT
        self._pending = ""
        self._json_buf = ""
        self._text_parts: list[str] = []
        self._payload: dict[str, Any] | None = None
        self._note = ""

    @property
    def state(self) -> str:
        return self._state

    def feed(self, chunk: str) -> str:
        """喂入流式片段，返回可立即下发的正文增量（不含情绪 JSON）。"""
        if not chunk or self._state == STATE_DONE:
            return ""
        out = self._feed_json(chunk) if self._state == STATE_JSON else self._feed_text(chunk)
        if out:
            self._text_parts.append(out)
        return out

    def _feed_json(self, chunk: str) -> str:
        self._json_buf += chunk
        self._try_parse_json()
        return ""

    def _feed_text(self, chunk: str) -> str:
        self._pending += chunk
        emitted: list[str] = []
        while True:
            if self._state == STATE_PENDING:
                if self._pending.startswith(self._sep):
                    rest = self._pending[len(self._sep) :]
                    self._pending = ""
                    self._state = STATE_JSON
                    self._json_buf = rest
                    self._try_parse_json()
                    return "".join(emitted)
                if self._sep.startswith(self._pending):
                    return "".join(emitted)  # 仍是分隔符前缀，继续等
                # 失配：整段回吐为正文
                emitted.append(self._pending)
                self._pending = ""
                self._state = STATE_TEXT
                return "".join(emitted)

            index = self._pending.find(TRIGGER)
            if index < 0:
                keep = _common_suffix_len(self._pending, TRIGGER)
                cut = len(self._pending) - keep
                if cut > 0:
                    emitted.append(self._pending[:cut])
                    self._pending = self._pending[cut:]
                return "".join(emitted)

            emitted.append(self._pending[:index])
            self._pending = self._pending[index:]
            self._state = STATE_PENDING

    def _try_parse_json(self) -> None:
        text = self._json_buf.strip()
        if not text:
            return
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.startswith("json"):
                text = text[4:]
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return
        if isinstance(data, dict):
            self._payload = data
            self._state = STATE_DONE
            self._note = ""

    def finish(self) -> MoodResult:
        """结束本轮：把残留缓冲按"正文优先"归还，并给出解析结果。"""
        tail = ""
        if self._state in (STATE_TEXT, STATE_PENDING):
            tail = self._pending
            self._pending = ""
        elif self._state == STATE_JSON:
            self._try_parse_json()
            if self._state == STATE_JSON:
                self._note = "mood_json_unparsed"
                self._state = STATE_DONE

        text = "".join(self._text_parts) + tail
        emotion: dict[str, Any] | None = None
        action: dict[str, Any] | None = None
        if self._payload is not None:
            raw_emotion = self._payload.get("emotion")
            raw_action = self._payload.get("action")
            emotion = raw_emotion if isinstance(raw_emotion, dict) else None
            action = raw_action if isinstance(raw_action, dict) else None
        return MoodResult(
            text=text,
            emotion=emotion,
            action=action,
            parsed=self._payload is not None,
            note=self._note,
        )
