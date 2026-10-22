"""标签目录与推导（计划书 5.2.2 的"维度 + 离散"混合模型）。

- 16 个标签的 PAD 中心、半径、τ、TTS 参数来自 ``data/labels.yaml``（唯一真相源）。
- ``infer_label`` 用加权高斯距离反推标签；前二名分差 < 0.12 时给出次标签（混合情绪）。
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.emotion.models import PAD
from app.utils.mathx import gaussian_score

DATA_DIR = Path(__file__).resolve().parent / "data"
LABELS_FILE = DATA_DIR / "labels.yaml"

__all__ = [
    "EmotionLabel",
    "LabelCatalog",
    "infer_label",
    "load_catalog",
]


@dataclass(frozen=True)
class EmotionLabel:
    """一个离散情绪标签的完整定义。"""

    name: str
    valence: float
    arousal: float
    dominance: float
    radius: float
    tau: float
    tts: dict[str, float]
    style: tuple[str, ...] = ()
    interjections: tuple[str, ...] = ()

    @property
    def center(self) -> PAD:
        return PAD(self.valence, self.arousal, self.dominance)

    def score(self, pad: PAD) -> float:
        return gaussian_score(pad.distance_to(self.center), self.radius)


@dataclass(frozen=True)
class LabelCatalog:
    """标签目录（一次加载，全进程共享）。"""

    labels: tuple[EmotionLabel, ...]
    high_intensity_labels: frozenset[str]
    threshold: float
    secondary_gap: float

    def get(self, name: str) -> EmotionLabel | None:
        for label in self.labels:
            if label.name == name:
                return label
        return None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(label.name for label in self.labels)

    def by_name(self) -> dict[str, EmotionLabel]:
        return {label.name: label for label in self.labels}


def _parse_label(raw: dict[str, Any]) -> EmotionLabel:
    tts = raw.get("tts") or {}
    return EmotionLabel(
        name=str(raw["name"]),
        valence=float(raw.get("v", 0.0)),
        arousal=float(raw.get("a", 0.0)),
        dominance=float(raw.get("d", 0.5)),
        radius=float(raw.get("radius", 0.22)),
        tau=float(raw.get("tau", 300.0)),
        tts={
            "rate": float(tts.get("rate", 1.0)),
            "pitch": float(tts.get("pitch", 0.0)),
            "volume": float(tts.get("volume", 1.0)),
        },
        style=tuple(str(item) for item in raw.get("style") or ()),
        interjections=tuple(str(item) for item in raw.get("interjections") or ()),
    )


@functools.lru_cache(maxsize=1)
def load_catalog() -> LabelCatalog:
    """加载并缓存标签目录（文件缺失时抛错：没有目录就没有情绪）。"""
    data = yaml.safe_load(LABELS_FILE.read_text(encoding="utf-8")) or {}
    raw_labels = data.get("labels") or []
    infer = data.get("infer") or {}
    labels = tuple(_parse_label(item) for item in raw_labels)
    if not labels:
        raise ValueError(f"标签目录为空: {LABELS_FILE}")
    return LabelCatalog(
        labels=labels,
        high_intensity_labels=frozenset(str(x) for x in data.get("high_intensity_labels") or ()),
        threshold=float(infer.get("threshold", 0.35)),
        secondary_gap=float(infer.get("secondary_gap", 0.12)),
    )


def infer_label(
    pad: PAD,
    catalog: LabelCatalog | None = None,
    bias: dict[str, float] | None = None,
) -> tuple[str, float, str | None]:
    """从 PAD 反推标签。

    返回 ``(label, score, secondary_label)``：
    - 匹配度低于阈值回落 ``neutral``；
    - 前两名分差小于 ``secondary_gap`` 时给出次标签（混合情绪）；
    - ``bias`` 是人格偏置（傲娇更容易 shy/proud），直接加在分值上。
    """
    cat = catalog or load_catalog()
    bias = bias or {}
    scored: list[tuple[float, str]] = []
    for label in cat.labels:
        score = label.score(pad) + float(bias.get(label.name, 0.0))
        scored.append((score, label.name))
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_name = scored[0]
    if best_score < cat.threshold:
        return "neutral", best_score, None
    secondary: str | None = None
    if len(scored) > 1 and (best_score - scored[1][0]) < cat.secondary_gap:
        secondary = scored[1][1]
    return best_name, best_score, secondary
