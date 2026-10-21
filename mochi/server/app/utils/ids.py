"""ULID：时间有序、可排序的消息 ID（计划书 6.1）。"""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford Base32


def ulid() -> str:
    """返回 26 字符 ULID（48-bit 毫秒时间戳 + 80-bit 随机数）。"""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars: list[str] = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))
