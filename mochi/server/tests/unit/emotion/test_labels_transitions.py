"""标签推导与状态机（T3-04 / T3-05）。"""

from __future__ import annotations

import pytest

from app.emotion.labels import infer_label, load_catalog
from app.emotion.models import PAD
from app.emotion.transitions import (
    TransitionContext,
    evaluate,
    load_transitions,
)


def test_catalog_has_sixteen_labels() -> None:
    catalog = load_catalog()
    assert len(catalog.labels) == 16
    assert "neutral" in catalog.names
    assert catalog.threshold == pytest.approx(0.35)
    assert catalog.secondary_gap == pytest.approx(0.12)


@pytest.mark.parametrize("name", ["happy", "sad", "angry", "shy", "lonely", "excited"])
def test_label_centers_map_back_to_themselves(name: str) -> None:
    catalog = load_catalog()
    label = catalog.by_name()[name]
    inferred, score, _ = infer_label(label.center, catalog)
    assert inferred == name
    assert score > 0.9


def test_neutral_fallback_below_threshold() -> None:
    catalog = load_catalog()
    inferred, score, secondary = infer_label(PAD(0.0, 1.0, 0.0), catalog)
    assert inferred == "neutral"
    assert secondary is None
    assert score < catalog.threshold


def test_secondary_label_for_mixed_emotion() -> None:
    catalog = load_catalog()
    happy = catalog.by_name()["happy"].center
    amused = catalog.by_name()["amused"].center
    midpoint = PAD(
        (happy.valence + amused.valence) / 2,
        (happy.arousal + amused.arousal) / 2,
        (happy.dominance + amused.dominance) / 2,
    )
    inferred, _score, secondary = infer_label(midpoint, catalog)
    assert inferred in {"happy", "amused"}
    assert secondary in {"happy", "amused"}
    assert secondary != inferred


def test_label_bias_can_flip_choice() -> None:
    catalog = load_catalog()
    pad = PAD(0.3464, 0.394, 0.418)
    base, _, _ = infer_label(pad, catalog)
    biased, _, _ = infer_label(pad, catalog, {"shy": 0.5})
    assert base == "curious"
    assert biased == "shy"


def test_unknown_label_rejected() -> None:
    decision = evaluate("neutral", "not_a_label", TransitionContext())
    assert not decision.allowed
    assert decision.reason == "unknown_label"


def test_blocked_direct_transition_requires_neutral() -> None:
    decision = evaluate("hurt", "excited", TransitionContext())
    assert not decision.allowed
    assert decision.via == "neutral"


def test_guard_blocks_curious_when_arousal_low() -> None:
    low = evaluate("neutral", "curious", TransitionContext(pad_arousal=0.2))
    high = evaluate("neutral", "curious", TransitionContext(pad_arousal=0.8))
    assert not low.allowed
    assert high.allowed


def test_transition_without_rule_is_allowed() -> None:
    decision = evaluate("happy", "proud", TransitionContext())
    assert decision.allowed
    assert decision.reason == "no_rule"


def test_transition_table_loads_all_labels() -> None:
    table = load_transitions()
    assert len(table.allowed_labels) == 16
    assert ("hurt", "excited") in table.blocked_direct
