"""人格调制（T3-12）。"""

from __future__ import annotations

from pathlib import Path

from app.config.character_card import CardLoader, Persona
from app.emotion.models import PAD, EmotionState, Stimulus, StimulusSource
from app.emotion.persona import (
    baseline_mood,
    effective_tau,
    is_label_allowed,
    modulate,
    reactivity_for,
)

CHARACTERS_DIR = Path(__file__).resolve().parents[4] / "characters"


def _state(**changes) -> EmotionState:
    base = EmotionState(
        pad=PAD(0.1, 0.35, 0.55),
        mood=PAD(0.1, 0.35, 0.55),
        affinity=0.3,
        trust=0.5,
    )
    return base.replace(**changes)


def _stimulus(dval: float) -> Stimulus:
    return Stimulus(
        source=StimulusSource.USER_TEXT,
        tag="user_praise",
        dval=dval,
        darousal=0.1,
        ddominance=0.0,
    )


def test_reactivity_lookup() -> None:
    persona = CardLoader(CHARACTERS_DIR, "tsundere").current.persona
    assert reactivity_for(persona, "insult") == 1.25
    assert reactivity_for(persona, "unknown") == 1.0


def test_negative_mood_discounts_praise_and_amplifies_insult() -> None:
    persona = CardLoader(CHARACTERS_DIR, "tsundere").current.persona
    happy = _state(mood=PAD(0.4, 0.4, 0.55))
    sad = _state(mood=PAD(-0.4, 0.4, 0.55))
    praise_happy = modulate(_stimulus(0.2), persona, happy, "praise")
    praise_sad = modulate(_stimulus(0.2), persona, sad, "praise")
    insult_happy = modulate(_stimulus(-0.2), persona, happy, "insult")
    insult_sad = modulate(_stimulus(-0.2), persona, sad, "insult")
    assert praise_sad.gain < praise_happy.gain
    assert insult_sad.gain > insult_happy.gain


def test_affinity_boosts_positive_stimulus() -> None:
    persona = CardLoader(CHARACTERS_DIR, "tsundere").current.persona
    low = modulate(_stimulus(0.2), persona, _state(affinity=0.0), "praise")
    high = modulate(_stimulus(0.2), persona, _state(affinity=1.0), "praise")
    assert high.gain > low.gain


def test_soft_saturation_near_boundary() -> None:
    persona = CardLoader(CHARACTERS_DIR, "tsundere").current.persona
    state = _state(pad=PAD(0.98, 0.5, 0.5))
    result = modulate(_stimulus(0.4), persona, state, "praise")
    assert result.pad.valence <= 1.0
    assert result.pad.valence > state.pad.valence


def test_forbidden_label_and_unlock_rule() -> None:
    persona = Persona(
        forbidden_labels=["affectionate"],
        unlock_rules=[{"label": "affectionate", "condition": "affinity > 0.5"}],
    )
    low = _state(affinity=0.2)
    high = _state(affinity=0.8)
    assert not is_label_allowed(persona, "affectionate", low)
    assert is_label_allowed(persona, "affectionate", high)
    assert is_label_allowed(persona, "happy", low)


def test_baseline_and_tau() -> None:
    persona = CardLoader(CHARACTERS_DIR, "genki").current.persona
    assert baseline_mood(persona).valence > 0
    assert effective_tau(persona, 300.0) > 300.0  # 元气卡情绪停留更久
    assert effective_tau(Persona(decay_multiplier=2.0), 300.0) == 600.0
