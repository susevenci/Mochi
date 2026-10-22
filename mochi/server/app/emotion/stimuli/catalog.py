"""刺激目录：``data/stimuli.yaml`` 的加载与查询。

所有"这个 tag 对应什么增量"的答案都在这里，代码里不再硬编码数值。
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.emotion.models import StimulusSource

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STIMULI_FILE = DATA_DIR / "stimuli.yaml"

__all__ = ["EmpathyRule", "StimulusDef", "StimulusCatalog", "load_catalog"]


@dataclass(frozen=True)
class StimulusDef:
    """一个刺激标签的定义。"""

    tag: str
    dval: float
    darousal: float
    ddominance: float
    category: str
    habituate: bool
    source: StimulusSource
    label_override: str | None = None


@dataclass(frozen=True)
class EmpathyRule:
    """共情反转规则。"""

    tag: str
    label_override: str | None = None
    valence_scale: float = 1.0


@dataclass(frozen=True)
class StimulusCatalog:
    """刺激目录。"""

    defs: dict[str, StimulusDef]
    empathy: dict[str, EmpathyRule]

    def get(self, tag: str) -> StimulusDef | None:
        return self.defs.get(tag)

    def tags(self) -> tuple[str, ...]:
        return tuple(self.defs.keys())

    def empathy_rule(self, tag: str) -> EmpathyRule | None:
        return self.empathy.get(tag)


@functools.lru_cache(maxsize=1)
def load_catalog() -> StimulusCatalog:
    """加载刺激目录。"""
    data: dict[str, Any] = yaml.safe_load(STIMULI_FILE.read_text(encoding="utf-8")) or {}
    defs: dict[str, StimulusDef] = {}
    for tag, raw in (data.get("stimuli") or {}).items():
        if not isinstance(raw, dict):
            continue
        source_raw = str(raw.get("source", "user_text"))
        try:
            source = StimulusSource(source_raw)
        except ValueError:
            source = StimulusSource.SYSTEM
        defs[str(tag)] = StimulusDef(
            tag=str(tag),
            dval=float(raw.get("dval", 0.0)),
            darousal=float(raw.get("darousal", 0.0)),
            ddominance=float(raw.get("ddominance", 0.0)),
            category=str(raw.get("category", "default")),
            habituate=bool(raw.get("habituate", False)),
            source=source,
            label_override=(str(raw["label_override"]) if raw.get("label_override") else None),
        )
    empathy: dict[str, EmpathyRule] = {}
    for tag, raw in (data.get("empathy") or {}).items():
        if not isinstance(raw, dict):
            continue
        empathy[str(tag)] = EmpathyRule(
            tag=str(tag),
            label_override=(str(raw["label_override"]) if raw.get("label_override") else None),
            valence_scale=float(raw.get("valence_scale", 1.0)),
        )
    return StimulusCatalog(defs=defs, empathy=empathy)
