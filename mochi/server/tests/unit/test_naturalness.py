"""S7 自然度：复读检测。"""

from __future__ import annotations

from app.orchestration.naturalness import ensure_variety


def test_unique_reply_unchanged() -> None:
    assert ensure_variety("今天也要加油。", ["昨天好累。"]) == "今天也要加油。"


def test_exact_repeat_gets_variation() -> None:
    result = ensure_variety("嗯。", ["嗯。", "别的"], interjections=("……这次认真说。",))
    assert result != "嗯。"
    assert "嗯。" in result


def test_empty_reply_unchanged() -> None:
    assert ensure_variety("", ["嗯。"]) == ""
