"""情感引擎测试夹具：假时钟 + 真角色卡 + 临时 Repo。"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path

import pytest

from app.config.character_card import CardLoader
from app.emotion.engine import EmotionEngine
from app.emotion.models import Stimulus, StimulusSource
from app.emotion.stimuli.catalog import load_catalog
from app.store.emotion_repo import JsonEmotionRepo

PROJECT_ROOT = Path(__file__).resolve().parents[4]
CHARACTERS_DIR = PROJECT_ROOT / "characters"


class FakeClock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


def make_engine(
    tmp_path: Path,
    card_id: str = "tsundere",
    *,
    clock: FakeClock | None = None,
    hour: float = 14.0,
    seed: int = 7,
    repo_name: str | None = None,
) -> tuple[EmotionEngine, FakeClock, JsonEmotionRepo]:
    cards = CardLoader(CHARACTERS_DIR, card_id)
    fake_clock = clock or FakeClock()
    repo = JsonEmotionRepo(tmp_path / (repo_name or f"emotion-{card_id}-{id(fake_clock)}.json"))
    engine = EmotionEngine(
        card=cards.current,
        repo=repo,
        clock=fake_clock,
        rng=random.Random(seed),
        hour_provider=lambda _: hour,
    )
    return engine, fake_clock, repo


def inject(
    engine: EmotionEngine,
    tag: str,
    *,
    magnitude: float = 1.0,
    preferred_label: str | None = None,
):
    definition = load_catalog().get(tag)
    assert definition is not None, tag
    stimulus = Stimulus(
        source=StimulusSource.USER_TEXT,
        tag=tag,
        magnitude=magnitude,
        dval=definition.dval,
        darousal=definition.darousal,
        ddominance=definition.ddominance,
        confidence=1.0,
    )
    return asyncio.run(
        engine.apply_stimulus(
            stimulus,
            preferred_label=preferred_label or definition.label_override,
        )
    )


@pytest.fixture()
def engine_bundle(tmp_path: Path):
    return make_engine(tmp_path)


@pytest.fixture()
def engine_factory(tmp_path: Path):
    def _make(card_id: str = "tsundere", **kwargs):
        return make_engine(tmp_path, card_id, **kwargs)

    return _make


@pytest.fixture()
def inject_stimulus():
    return inject
