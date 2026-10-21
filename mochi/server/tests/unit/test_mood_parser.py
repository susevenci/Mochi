"""双通道解析状态机测试（T1-06 验收）：覆盖规划文档 3.5.1 的四类真实故障。"""

from __future__ import annotations

from app.orchestration.mood_parser import MoodStreamParser


def test_single_chunk_with_mood() -> None:
    parser = MoodStreamParser()
    payload = '{"emotion":{"label":"happy"},"action":{"expression":"smile"}}'
    out = parser.feed(f"你好呀<<<MOOD>>>{payload}")
    assert out == "你好呀"
    result = parser.finish()
    assert result.text == "你好呀"
    assert result.parsed is True
    assert result.emotion == {"label": "happy"}
    assert result.action == {"expression": "smile"}


def test_separator_split_across_chunks() -> None:
    parser = MoodStreamParser()
    chunks = ["你好", "<<<MO", "OD>>>", '{"emotion":{"label":"shy"}}']
    outs = [parser.feed(chunk) for chunk in chunks]
    assert "".join(outs) == "你好"
    result = parser.finish()
    assert result.text == "你好"
    assert result.parsed is True
    assert result.emotion == {"label": "shy"}


def test_no_separator_keeps_full_text() -> None:
    parser = MoodStreamParser()
    assert parser.feed("只是普通回复") == "只是普通回复"
    result = parser.finish()
    assert result.text == "只是普通回复"
    assert result.parsed is False


def test_truncated_json_keeps_text() -> None:
    parser = MoodStreamParser()
    parser.feed('好的<<<MOOD>>>{"emotion":{"label":"ha')
    result = parser.finish()
    assert result.text == "好的"
    assert result.parsed is False
    assert result.note == "mood_json_unparsed"


def test_fake_separator_is_returned_not_swallowed() -> None:
    parser = MoodStreamParser()
    out1 = parser.feed("前面<<<abc")
    out2 = parser.feed("后面")
    assert "前面" in out1 + out2
    result = parser.finish()
    assert result.text == "前面<<<abc后面"
    assert result.parsed is False


def test_trailing_bracket_held_then_released() -> None:
    parser = MoodStreamParser()
    out1 = parser.feed("结尾<")
    out2 = parser.feed("不是分隔")
    assert out1 == "结尾"
    assert out1 + out2 == "结尾<不是分隔"
    result = parser.finish()
    assert result.text == "结尾<不是分隔"


def test_code_fence_json() -> None:
    parser = MoodStreamParser()
    parser.feed('嗯<<<MOOD>>>```json\n{"emotion":{"label":"shy"}}\n```')
    result = parser.finish()
    assert result.parsed is True
    assert result.emotion == {"label": "shy"}
    assert result.text == "嗯"
