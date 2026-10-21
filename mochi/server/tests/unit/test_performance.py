"""情绪 → 表现映射测试（S2 验收）。"""

from __future__ import annotations

from app.orchestration.performance import map_emotion


def test_known_label_maps_to_motion() -> None:
    cue = map_emotion({"label": "happy"})
    assert cue.emotion_label == "happy"
    assert cue.motion == "touch_head"
    assert cue.priority == "normal"
    assert cue.expression is None  # qiye_10 无 exp3


def test_high_priority_labels() -> None:
    assert map_emotion({"label": "angry"}).priority == "high"
    assert map_emotion({"label": "surprised"}).priority == "high"


def test_unknown_label_falls_back_to_idle() -> None:
    cue = map_emotion({"label": "not_a_label"})
    assert cue.motion == "idle"


def test_none_emotion_defaults_to_neutral() -> None:
    cue = map_emotion(None)
    assert cue.emotion_label == "neutral"
    assert cue.motion == "idle"
