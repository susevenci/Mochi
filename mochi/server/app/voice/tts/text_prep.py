"""TTS 文本预处理：剥离格式标记、按句切分、软限制长度。"""

from __future__ import annotations

import re

__all__ = ["SentenceSplitter", "clean_for_tts", "split_sentences"]

_SENTENCE_END = re.compile(r"(?<=[。！？!?；;])")
_EMOJI = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f0ff]+",
)
_MARKDOWN = re.compile(r"[*_`#>~]+")
_MOOD_BLOCK = re.compile(r"<<<MOOD>>>.*$", re.DOTALL)
_MAX_SENTENCE_CHARS = 40


def clean_for_tts(text: str) -> str:
    cleaned = _MOOD_BLOCK.sub("", text)
    cleaned = _MARKDOWN.sub("", cleaned)
    cleaned = _EMOJI.sub("", cleaned)
    cleaned = re.sub(r"\[[^\]]{0,20}\]\([^)]*\)", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _split_long(sentence: str, limit: int = _MAX_SENTENCE_CHARS) -> list[str]:
    if len(sentence) <= limit:
        return [sentence]
    pieces: list[str] = []
    remaining = sentence
    while len(remaining) > limit:
        cut = max(
            remaining.rfind("，", 0, limit),
            remaining.rfind(",", 0, limit),
            remaining.rfind(" ", 0, limit),
        )
        if cut < limit // 2:
            cut = limit
        else:
            cut += 1
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return [piece for piece in pieces if piece]


def split_sentences(text: str) -> list[str]:
    cleaned = clean_for_tts(text)
    if not cleaned:
        return []
    sentences: list[str] = []
    for piece in _SENTENCE_END.split(cleaned):
        piece = piece.strip()
        if piece:
            sentences.extend(_split_long(piece))
    return sentences


class SentenceSplitter:
    """流式文本 → 完整句子（标点可能跨 chunk，所以必须缓冲）。"""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> list[str]:
        if not chunk:
            return []
        self._buffer += chunk
        parts = _SENTENCE_END.split(self._buffer)
        if len(parts) <= 1:
            return []
        complete = [part.strip() for part in parts[:-1] if part.strip()]
        self._buffer = parts[-1]
        out: list[str] = []
        for sentence in complete:
            out.extend(split_sentences(sentence))
        return out

    def flush(self) -> list[str]:
        tail = self._buffer
        self._buffer = ""
        return split_sentences(tail)
