"""刺激源：词典、Level 2、交互、噪声（T3-08/09/10/16）。"""

from __future__ import annotations

import asyncio
import random

import pytest

from app.emotion.models import PAD, StimulusSource
from app.emotion.stimuli.chronobiology import circadian_baseline, circadian_scale
from app.emotion.stimuli.interaction import classify_interaction
from app.emotion.stimuli.noise import noise_step
from app.emotion.stimuli.text_analyzer import (
    analyze_text,
    analyze_with_llm,
    hint_from_payload,
)
from app.providers.base import ChatResult


def test_lexicon_praise_and_insult() -> None:
    praise = analyze_text("你真聪明，谢谢")
    insult = analyze_text("你真笨")
    assert praise.hit
    assert praise.stimuli[0].tag == "user_praise"
    assert insult.hit
    assert insult.stimuli[0].tag == "user_insult"


def test_lexicon_negation_flips_polarity() -> None:
    analysis = analyze_text("你一点也不笨")
    assert analysis.hit
    stimulus = analysis.stimuli[0]
    assert stimulus.tag == "user_praise"
    assert stimulus.dval > 0
    assert stimulus.magnitude == 0.5


def test_intimate_and_care_merge() -> None:
    analysis = analyze_text("摸摸头，早点睡，别太累")
    tags = {item.tag for item in analysis.stimuli}
    assert "intimate_care" in tags


def test_empty_and_unknown_text() -> None:
    assert not analyze_text("").hit
    assert not analyze_text("嗯嗯好的").hit


class FakeProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def chat(self, messages, **_kwargs) -> ChatResult:
        self.calls += 1
        return ChatResult(content=self.content)


def test_level2_only_for_long_text() -> None:
    provider = FakeProvider("{}")
    analysis = asyncio.run(analyze_with_llm("嗯嗯", provider))
    assert not analysis.hit
    assert analysis.note == "too_short"
    assert provider.calls == 0


def test_level2_parses_json() -> None:
    provider = FakeProvider(
        '```json\n{"tag": "user_vent", "intensity": 0.8, "confidence": 0.7}\n```'
    )
    analysis = asyncio.run(analyze_with_llm("今天心里说不上来的闷得慌", provider))
    assert analysis.hit
    assert analysis.level == 2
    assert analysis.stimuli[0].tag == "user_sad"
    assert analysis.stimuli[0].confidence == pytest.approx(0.7)


def test_level2_bad_json_is_safe() -> None:
    analysis = asyncio.run(analyze_with_llm("今天心里说不上来的闷得慌", FakeProvider("not json")))
    assert not analysis.hit
    assert analysis.note == "llm_bad_json"


def test_interaction_classification() -> None:
    pat = classify_interaction("pat_head", count=1)
    tracked = classify_interaction("drag_start")
    unknown = classify_interaction("something")
    assert pat.stimulus is not None
    assert pat.stimulus.source == StimulusSource.INTERACTION
    assert tracked.tracked_only
    assert unknown.tracked_only


def test_teased_magnitude_grows_with_count() -> None:
    one = classify_interaction("teased", count=1).stimulus
    five = classify_interaction("teased", count=5).stimulus
    assert one is not None and five is not None
    assert five.magnitude > one.magnitude
    assert five.magnitude <= 2.0


def test_noise_is_small_and_deterministic() -> None:
    pad = PAD(0.1, 0.35, 0.55)
    a = noise_step(pad, random.Random(1), 1.0)
    b = noise_step(pad, random.Random(1), 1.0)
    assert a == b
    assert abs(a.valence - pad.valence) < 0.01
    assert noise_step(pad, random.Random(1), 0.0) == pad


def test_circadian_scale_shape() -> None:
    night_arousal, night_offset = circadian_scale(2.0)
    day_arousal, day_offset = circadian_scale(14.0)
    assert night_arousal < day_arousal
    assert night_offset < day_offset
    assert circadian_baseline(PAD(0.1, 0.35, 0.55), 2.0).arousal < 0.35


def test_hint_from_payload() -> None:
    hint = hint_from_payload(
        {
            "emotion": {
                "label": "shy",
                "delta_valence": 0.3,
                "delta_arousal": 0.2,
                "confidence": 0.8,
            }
        }
    )
    assert hint.label == "shy"
    assert hint.dval == pytest.approx(0.3)
    assert hint.confidence == pytest.approx(0.8)
    assert hint_from_payload(None).label is None
