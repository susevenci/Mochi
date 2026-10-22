"""引擎行为：刺激、人格差异、共情、时间旅行、主动性与广播（T3-06/07/10~17）。"""

from __future__ import annotations

import asyncio
import math

import pytest

from app.emotion.models import PAD, LLMEmotionHint, Stimulus, StimulusSource
from app.emotion.stimuli.chronobiology import ambient_tag_for_hour, circadian_baseline
from app.emotion.stimuli.text_analyzer import analyze_text


def test_praise_increases_and_habituates(engine_factory, inject_stimulus) -> None:
    engine, _clock, _repo = engine_factory()
    deltas = []
    previous = engine.state.pad.valence
    for _ in range(3):
        snapshot = inject_stimulus(engine, "user_praise")
        deltas.append(snapshot.pad.valence - previous)
        previous = snapshot.pad.valence
    assert all(delta > 0 for delta in deltas)
    assert deltas[1] < deltas[0]
    assert deltas[2] < deltas[1]
    assert snapshot.label == "happy"


def test_same_insult_different_persona(engine_factory, inject_stimulus) -> None:
    tsundere, _c1, _r1 = engine_factory("tsundere", repo_name="tsundere.json")
    genki, _c2, _r2 = engine_factory("genki", repo_name="genki.json")
    harsh = inject_stimulus(tsundere, "user_insult")
    playful = inject_stimulus(genki, "user_insult")
    assert harsh.label == "hurt"
    assert playful.label == "amused"
    assert harsh.pad.valence < playful.pad.valence


def test_empathy_inversion_uses_worried(engine_factory) -> None:
    engine, _clock, _repo = engine_factory()
    snapshot = asyncio.run(engine.apply_text("我好累，今天真的撑不住了"))
    assert engine.last_text_analysis is not None
    assert engine.last_text_analysis.hit
    assert snapshot.label == "worried"


def test_refractory_keeps_label_but_accumulates_pad(engine_factory, inject_stimulus) -> None:
    engine, clock, _repo = engine_factory()
    clock.advance(100)
    # 先进入 shy
    first = inject_stimulus(engine, "intimate_care")
    assert first.label == "shy"
    clock.advance(1)
    before = engine.state.pad.valence
    second = inject_stimulus(engine, "user_insult")
    assert second.label == "shy"  # 8s 不应期内不改标签
    assert engine.state.pad.valence < before


def test_blocked_direct_transition_goes_through_neutral(engine_factory) -> None:
    engine, clock, _repo = engine_factory()
    clock.advance(100)
    engine._state = engine.state.replace(
        label="hurt",
        intensity=0.9,
        last_label_change_at=0.0,
    )
    changed = engine._recompute_label(clock(), preferred_label="excited")
    assert changed
    assert engine.state.label == "neutral"


def test_time_travel_to_lonely_and_reunion(engine_factory) -> None:
    lonely_engine, _c1, _r1 = engine_factory(repo_name="lonely.json", hour=14.0)
    snapshot = lonely_engine.advance(3650)
    assert snapshot.label == "lonely"
    assert snapshot.idle_seconds >= 3600

    reunion_engine, _c2, _r2 = engine_factory(repo_name="reunion.json", hour=14.0)
    reunion_engine._state = reunion_engine.state.replace(affinity=0.7)
    snapshot = reunion_engine.advance(8 * 3600)
    assert snapshot.pending_greeting == "long_absence"
    assert snapshot.pad.valence > 0
    assert snapshot.label in {"happy", "affectionate", "amused", "excited"}


def test_offline_decay_and_restore(engine_factory) -> None:
    engine, clock, repo = engine_factory(repo_name="restore.json")
    engine._state = engine.state.replace(affinity=0.7)
    engine.persist()
    clock.advance(8 * 3600)

    restored = type(engine)(
        card=engine.card,
        repo=repo,
        clock=clock,
        rng=engine._rng,
        hour_provider=lambda _: 14.0,
    )
    state = restored.load()
    assert state.pending_greeting == "long_absence"
    assert state.pad.valence > 0


def test_llm_hint_invalid_label_ignored(engine_factory) -> None:
    engine, _clock, _repo = engine_factory()
    before = engine.state.pad.valence
    snapshot = asyncio.run(engine.apply_llm_hint(LLMEmotionHint(label="not_a_label", dval=0.2)))
    assert snapshot.label == "neutral"
    assert snapshot.pad.valence > before


def test_llm_hint_delta_clamped(engine_factory) -> None:
    engine, _clock, _repo = engine_factory()
    before = engine.state.pad.valence
    snapshot = asyncio.run(engine.apply_llm_hint(LLMEmotionHint(dval=5.0, confidence=1.0)))
    assert snapshot.pad.valence - before <= 0.51


def test_llm_hint_label_only(engine_factory) -> None:
    engine, clock, _repo = engine_factory()
    clock.advance(100)
    # neutral→happy 有 valence 守卫；proud 没有额外守卫，适合验证 label-only 路径
    snapshot = asyncio.run(engine.apply_llm_hint(LLMEmotionHint(label="proud", confidence=0.9)))
    assert snapshot.label == "proud"


def test_proactive_budget_and_quiet_hours(engine_factory) -> None:
    engine, clock, _repo = engine_factory(hour=14.0)
    engine._state = engine.state.replace(idle_seconds=4000, label="lonely")
    first = engine.poll_proactive()
    assert first is not None
    assert engine.poll_proactive() is None  # min interval
    clock.advance(601)
    engine._state = engine.state.replace(idle_seconds=4600)
    assert engine.poll_proactive() is not None

    quiet, _qc, _qr = engine_factory(hour=2.0, repo_name="quiet.json")
    quiet._state = quiet.state.replace(idle_seconds=4000, label="lonely")
    assert quiet.poll_proactive() is None


def test_chronobiology_lowers_night_arousal(engine_factory) -> None:
    night, _c1, _r1 = engine_factory(hour=2.0, repo_name="night.json")
    day, _c2, _r2 = engine_factory(hour=14.0, repo_name="day.json")
    night_snapshot = night.advance(600)
    day_snapshot = day.advance(600)
    assert night_snapshot.pad.arousal < day_snapshot.pad.arousal
    assert circadian_baseline(PAD(0.1, 0.35, 0.55), 2.0).arousal < 0.35
    assert ambient_tag_for_hour(2.0) == "sleepy_yawn"
    assert ambient_tag_for_hour(14.0) == "daydream"
    assert ambient_tag_for_hour(10.0) is None


def test_ambient_stimulus_is_recorded(engine_factory) -> None:
    engine, _clock, _repo = engine_factory(hour=2.0)
    snapshot = engine.advance(1000)
    tags = [cause.stimulus for cause in snapshot.causes]
    assert "sleepy_yawn" in tags


def test_broadcast_listener_and_consume_greeting(engine_factory, inject_stimulus) -> None:
    engine, _clock, _repo = engine_factory()
    received = []

    async def listener(snapshot) -> None:
        received.append(snapshot)

    engine.subscribe(listener)
    asyncio.run(
        engine.apply_stimulus(
            Stimulus(
                source=StimulusSource.USER_TEXT,
                tag="user_praise",
                dval=0.2,
            )
        )
    )
    assert received

    engine._state = engine.state.replace(pending_greeting="long_absence")
    assert engine.consume_greeting() == "long_absence"
    assert engine.consume_greeting() is None


def test_tick_advances_idle(engine_factory) -> None:
    engine, _clock, _repo = engine_factory()
    before = engine.state.idle_seconds
    snapshot = asyncio.run(engine.tick(1.0))
    assert snapshot.idle_seconds >= before + 0.9


def test_style_and_prompt(engine_factory, inject_stimulus) -> None:
    engine, _clock, _repo = engine_factory()
    inject_stimulus(engine, "intimate_care")
    block = engine.prompt_block()
    constraints = engine.style_constraints()
    assert "内心状态" in block
    assert "害羞" in block
    assert constraints.max_len <= 60
    assert "不要直白说出自己的情绪" in constraints.hints


def test_presentation_weight_and_tts(engine_factory, inject_stimulus) -> None:
    engine, _clock, _repo = engine_factory()
    inject_stimulus(engine, "intimate_care")
    cue = engine.map_to_presentation()
    assert cue.emotion_label == "shy"
    assert 5.0 <= cue.tts.pitch <= 7.0  # 主标签 shy 与次标签按强度混合
    expected = 0.4 + 0.6 * engine.state.intensity
    assert cue.expression_weight == pytest.approx(0.0)  # 该卡没有表情映射
    assert 0.4 <= expected <= 1.0


def test_history_written(engine_factory, inject_stimulus) -> None:
    engine, _clock, _repo = engine_factory()
    inject_stimulus(engine, "user_praise")
    engine.persist()
    history = engine.history(10)
    assert history
    assert history[-1]["label"] in {"neutral", "happy"}


def test_text_analysis_negative_polarity(engine_factory) -> None:
    engine, _clock, _repo = engine_factory()
    asyncio.run(engine.apply_text("你真笨"))
    assert engine._last_text_polarity < 0
    assert analyze_text("你真笨").hit


def test_level2_annotation_with_fake_provider(engine_factory) -> None:
    class Provider:
        async def chat(self, messages, **_kwargs):
            from app.providers.base import ChatResult

            return ChatResult(
                content='{"polarity": -1, "intensity": 0.8, "user_emotion": "sad",'
                ' "tag": "user_vent", "confidence": 0.8}'
            )

    engine, _clock, _repo = engine_factory()
    asyncio.run(engine.apply_text("今天心里说不上来的闷得慌"))
    assert engine.last_text_analysis is not None
    assert not engine.last_text_analysis.hit
    snapshot = asyncio.run(engine.apply_text_llm("今天心里说不上来的闷得慌", Provider()))
    assert snapshot.label == "worried"


def test_mathx_decay_reaches_mood() -> None:
    from app.emotion.decay import decay_toward

    end = decay_toward(PAD(0.8, 0.8, 0.8), PAD(0.1, 0.3, 0.5), 1e9, 300)
    assert math.isclose(end.valence, 0.1, abs_tol=1e-6)
