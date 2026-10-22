"""情绪状态机（计划书 5.2.4）：转移是否合法。

三条约束中，本模块负责**第三条（禁止直跳）**与"条件转移的守卫求值"；
不应期与最小强度门槛由引擎在拿到 PAD 之后判定（它们依赖时间与强度）。

守卫是**结构化数据**（``{name, value}``），由本文件注册的函数求值，
不执行任何表达式字符串（安全且可单测）。
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DATA_DIR = Path(__file__).resolve().parent / "data"
TRANSITIONS_FILE = DATA_DIR / "transitions.yaml"

__all__ = [
    "TransitionContext",
    "TransitionDecision",
    "TransitionRule",
    "TransitionTable",
    "load_transitions",
]


@dataclass(frozen=True)
class TransitionContext:
    """判定一次转移所需的全部上下文。"""

    pad_valence: float = 0.0
    pad_arousal: float = 0.0
    pad_dominance: float = 0.0
    intensity: float = 0.0
    idle_seconds: float = 0.0
    affinity: float = 0.0
    trust: float = 0.0
    patience: float = 1.0
    stimulus_tag: str = ""
    magnitude: float = 0.0
    hours: float = 12.0


@dataclass(frozen=True)
class TransitionDecision:
    """裁决结果。``via`` 非空表示需要中转标签。"""

    allowed: bool
    reason: str = ""
    via: str | None = None

    @staticmethod
    def allow(reason: str = "") -> TransitionDecision:
        return TransitionDecision(allowed=True, reason=reason)

    @staticmethod
    def deny(reason: str, via: str | None = None) -> TransitionDecision:
        return TransitionDecision(allowed=False, reason=reason, via=via)


@dataclass(frozen=True)
class TransitionRule:
    """一条条件转移。"""

    sources: frozenset[str]
    target: str
    guards: tuple[dict[str, Any], ...] = ()
    cooldown: float = 0.0


@dataclass(frozen=True)
class TransitionTable:
    """状态机规则表。"""

    rules: tuple[TransitionRule, ...] = ()
    blocked_direct: frozenset[tuple[str, str]] = frozenset()
    allowed_labels: frozenset[str] = frozenset()

    def is_known_label(self, label: str) -> bool:
        return label in self.allowed_labels

    def rules_for(self, source: str, target: str) -> tuple[TransitionRule, ...]:
        return tuple(
            rule
            for rule in self.rules
            if rule.target == target and (source in rule.sources or "*" in rule.sources)
        )


# ── 守卫注册表 ────────────────────────────────────────────────────────────
GuardFn = Callable[[dict[str, Any], TransitionContext], bool]


def _guard_valence_gt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.pad_valence > float(spec.get("value", 0.0))


def _guard_valence_lt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.pad_valence < float(spec.get("value", 0.0))


def _guard_arousal_gt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.pad_arousal > float(spec.get("value", 0.0))


def _guard_arousal_lt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.pad_arousal < float(spec.get("value", 0.0))


def _guard_dominance_gt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.pad_dominance > float(spec.get("value", 0.0))


def _guard_dominance_lt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.pad_dominance < float(spec.get("value", 0.0))


def _guard_intensity_gt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.intensity > float(spec.get("value", 0.0))


def _guard_intensity_lt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.intensity < float(spec.get("value", 0.0))


def _guard_affinity_gt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.affinity > float(spec.get("value", 0.0))


def _guard_trust_gt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.trust > float(spec.get("value", 0.0))


def _guard_patience_lt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.patience < float(spec.get("value", 0.0))


def _guard_idle_gt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.idle_seconds > float(spec.get("value", 0.0))


def _guard_magnitude_gt(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    return ctx.magnitude > float(spec.get("value", 0.0))


def _guard_tag_in(spec: dict[str, Any], ctx: TransitionContext) -> bool:
    allowed = spec.get("value") or []
    return ctx.stimulus_tag in allowed


GUARDS: dict[str, GuardFn] = {
    "valence_gt": _guard_valence_gt,
    "valence_lt": _guard_valence_lt,
    "arousal_gt": _guard_arousal_gt,
    "arousal_lt": _guard_arousal_lt,
    "dominance_gt": _guard_dominance_gt,
    "dominance_lt": _guard_dominance_lt,
    "intensity_gt": _guard_intensity_gt,
    "intensity_lt": _guard_intensity_lt,
    "affinity_gt": _guard_affinity_gt,
    "trust_gt": _guard_trust_gt,
    "patience_lt": _guard_patience_lt,
    "idle_gt": _guard_idle_gt,
    "magnitude_gt": _guard_magnitude_gt,
    "tag_in": _guard_tag_in,
}


@functools.lru_cache(maxsize=1)
def load_transitions() -> TransitionTable:
    """加载转移规则表。"""
    data = yaml.safe_load(TRANSITIONS_FILE.read_text(encoding="utf-8")) or {}
    rules: list[TransitionRule] = []
    for raw in data.get("transitions") or []:
        sources = raw.get("from") or []
        rules.append(
            TransitionRule(
                sources=frozenset(str(s) for s in sources),
                target=str(raw.get("to", "neutral")),
                guards=tuple(dict(g) for g in (raw.get("guards") or [])),
                cooldown=float(raw.get("cooldown", 0.0)),
            )
        )
    blocked = frozenset(
        (str(pair[0]), str(pair[1]))
        for pair in (data.get("blocked_direct") or [])
        if isinstance(pair, (list, tuple)) and len(pair) == 2
    )
    allowed = frozenset(str(x) for x in (data.get("allowed_labels") or []))
    return TransitionTable(rules=tuple(rules), blocked_direct=blocked, allowed_labels=allowed)


def evaluate(
    source: str,
    target: str,
    ctx: TransitionContext,
    table: TransitionTable | None = None,
) -> TransitionDecision:
    """判断 ``source → target`` 是否允许。"""
    tbl = table or load_transitions()
    if not tbl.is_known_label(target):
        return TransitionDecision.deny("unknown_label")
    if (source, target) in tbl.blocked_direct:
        return TransitionDecision.deny("blocked_direct", via="neutral")
    rules = tbl.rules_for(source, target)
    if not rules:
        return TransitionDecision.allow("no_rule")
    for rule in rules:
        if all(_eval_guard(guard, ctx) for guard in rule.guards):
            return TransitionDecision.allow("rule")
    return TransitionDecision.deny("guards_not_met")


def _eval_guard(guard: dict[str, Any], ctx: TransitionContext) -> bool:
    name = str(guard.get("name", ""))
    fn = GUARDS.get(name)
    if fn is None:
        # 未知守卫视为不通过：宁可保守，不要静默放行
        return False
    return fn(guard, ctx)
