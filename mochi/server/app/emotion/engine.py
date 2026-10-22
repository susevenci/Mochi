"""情感引擎外壳（计划书 5.2.13）：薄壳 + 纯函数。

职责边界（引擎只做这些）：
1. 接收刺激 → 调纯函数（调制 / 衰减 / 标签推导 / 状态机）
2. 维护一份**不可变**状态（``EmotionState``，frozen）
3. 按节流广播快照、按节流落盘
4. 提供 ``advance(seconds)`` 时间旅行（验收"离线 8 小时"用）

**不负责**：说什么（Roleplay）、怎么表演（表现层）、存什么（Repo）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import random
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from app.config.character_card import CharacterCard
from app.emotion.decay import apply_habituation, compute_intensity, decay_toward, update_mood
from app.emotion.labels import LabelCatalog, infer_label, load_catalog
from app.emotion.models import (
    PAD,
    EmotionCause,
    EmotionSnapshot,
    EmotionState,
    LLMEmotionHint,
    ProactiveIntent,
    Stimulus,
    StimulusSource,
)
from app.emotion.persona import (
    baseline_mood,
    effective_tau,
    initial_pad,
    is_label_allowed,
    modulate,
)
from app.emotion.presentation import PresentationCue, map_snapshot
from app.emotion.proactive import ProactiveController
from app.emotion.prompt_block import build_prompt_block, build_style_constraints
from app.emotion.stimuli.catalog import load_catalog as load_stimulus_catalog
from app.emotion.stimuli.chronobiology import ambient_tag_for_hour, circadian_baseline
from app.emotion.stimuli.interaction import classify_interaction
from app.emotion.stimuli.noise import noise_step
from app.emotion.stimuli.text_analyzer import TextAnalysis, analyze_text, analyze_with_llm
from app.emotion.transitions import (
    TransitionContext,
    TransitionTable,
    evaluate,
    load_transitions,
)
from app.store.emotion_repo import EmotionRepo
from app.utils.clock import local_hour, system_clock

log = logging.getLogger(__name__)

__all__ = [
    "EmotionEngine",
    "HABITUATION_FACTOR",
    "HABITUATION_WINDOW",
    "TICK_INTERVAL",
]

# 引擎 tick 间隔（秒）：250ms
TICK_INTERVAL = 0.25

# 重复刺激递减的统计窗口（秒）与递减系数
HABITUATION_WINDOW = 60.0
HABITUATION_FACTOR = 0.7

# 广播/落盘节流
BROADCAST_MIN_INTERVAL = 0.5
BROADCAST_DELTA = 0.03
PERSIST_INTERVAL = 5.0

# 强情绪标签的强度门槛
HIGH_INTENSITY_GATE = 0.25

# 离线/重逢判定
REUNION_SECONDS = 6 * 3600
VERY_LONG_ABSENCE_SECONDS = 24 * 3600
OFFLINE_DECAY_SECONDS = 300

# 自发刺激的节流（秒）
AMBIENT_INTERVAL = 900.0

SnapshotListener = Callable[[EmotionSnapshot], Awaitable[None]]


class EmotionEngine:
    """情绪状态的唯一权威（不变量 I1）。"""

    def __init__(
        self,
        *,
        card: CharacterCard,
        repo: EmotionRepo,
        clock: Callable[[], float] | None = None,
        rng: random.Random | None = None,
        catalog: LabelCatalog | None = None,
        transitions: TransitionTable | None = None,
        hour_provider: Callable[[float], float] | None = None,
    ) -> None:
        self._card = card
        self._repo = repo
        self._clock: Callable[[], float] = clock or system_clock
        self._hour = hour_provider or local_hour
        self._rng = rng or random.Random()
        self._catalog = catalog or load_catalog()
        self._transitions = transitions or load_transitions()
        self._proactive = ProactiveController(self._rng)
        self._listeners: list[SnapshotListener] = []
        self._recent_tags: list[tuple[float, str]] = []
        self._last_tick = self._clock()
        self._last_broadcast_at = 0.0
        self._last_broadcast_pad: PAD | None = None
        self._last_persist_at = 0.0
        self._last_text_polarity = 0.0
        self.last_text_analysis: TextAnalysis | None = None
        self._error_count = 0
        self._frozen = False
        self._task: asyncio.Task[None] | None = None
        self._state = self._initial_state()

    # ── 基础访问 ──────────────────────────────────────────────────────────
    @property
    def state(self) -> EmotionState:
        return self._state

    @property
    def card(self) -> CharacterCard:
        return self._card

    @property
    def frozen(self) -> bool:
        """连续异常后引擎会冻结（表情不再变，但对话不中断）。"""
        return self._frozen

    def _initial_state(self) -> EmotionState:
        now = self._clock()
        persona = self._card.persona
        return EmotionState(
            pad=initial_pad(persona),
            label="neutral",
            secondary_label=None,
            intensity=0.30,
            label_confidence=1.0,
            mood=self._effective_baseline(now),
            mood_label="content",
            affinity=0.30,
            trust=0.50,
            patience=1.00,
            updated_at=now,
            last_stimulus_at=now,
            last_interaction_at=now,
            last_label_change_at=0.0,
            idle_seconds=0.0,
            last_ambient_at=now,
        )

    def snapshot(self) -> EmotionSnapshot:
        return EmotionSnapshot.from_state(self._state)

    def subscribe(self, listener: SnapshotListener) -> Callable[[], None]:
        """订阅状态变化；返回取消订阅函数。"""
        self._listeners.append(listener)

        def _unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _unsubscribe

    def set_card(self, card: CharacterCard) -> None:
        """切换角色卡：人格立刻生效，情绪状态保留（关系是连续的）。"""
        self._card = card
        self._state = replace(
            self._state,
            mood=self._effective_baseline(self._clock()),
        )

    # ── 生命周期 ─────────────────────────────────────────────────────────
    async def start(self) -> None:
        """启动 tick 循环（由 FastAPI lifespan 调用）。"""
        if self._task is not None:
            return
        self._last_tick = self._clock()
        self._task = asyncio.create_task(self._run(), name="emotion-tick")

    async def stop(self) -> None:
        """停止 tick 并落盘。"""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        self.persist()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(TICK_INTERVAL)
            now = self._clock()
            dt = max(0.0, now - self._last_tick)
            self._last_tick = now
            try:
                await self.tick(dt)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 引擎异常不能拖垮进程
                log.exception("情感引擎 tick 异常: %s", exc)
                self._handle_error()

    def _handle_error(self) -> None:
        self._error_count += 1
        if self._error_count >= 5:
            # 连续异常 → 冻结为 neutral（3.6 降级：表情不再变，但对话正常）
            self._frozen = True
            self._state = replace(self._state, label="neutral", secondary_label=None)
            log.error("情感引擎连续异常，已冻结为 neutral")

    # ── 状态恢复 ─────────────────────────────────────────────────────────
    def load(self) -> EmotionState:
        """从 Repo 恢复状态并应用离线衰减。"""
        state = self._repo.load()
        now = self._clock()
        if state is None:
            self._last_tick = now
            return self._state
        if state.updated_at <= 0:
            state = replace(state, updated_at=now, last_interaction_at=now)
        self._state = state
        self._apply_offline_decay(now)
        self._last_tick = now
        return self._state

    def _apply_offline_decay(self, now: float) -> None:
        """离线期间情绪不应冻结，也不应清零：回归心境 + 重逢情绪。"""
        gap = now - self._state.updated_at
        if gap <= 0:
            return
        if gap < OFFLINE_DECAY_SECONDS:
            # 不到 5 分钟：视为一直在一起，正常衰减
            self._state = replace(
                self._state,
                pad=decay_toward(self._state.pad, self._state.mood, gap, self._tau()),
                idle_seconds=self._state.idle_seconds + gap,
                updated_at=now,
            )
            self._recompute_label(now)
            return

        self._state = replace(
            self._state,
            pad=self._state.mood,
            intensity=0.20,
            idle_seconds=self._state.idle_seconds + gap,
            updated_at=now,
        )
        self._recompute_label(now)
        if gap > VERY_LONG_ABSENCE_SECONDS:
            self._apply_reunion("very_long_absence", now)
        elif gap > REUNION_SECONDS:
            self._apply_reunion("long_absence", now)

    def _apply_reunion(self, kind: str, now: float) -> None:
        """应用重逢刺激，并标记待播放的开场白。"""
        if kind == "very_long_absence":
            tag = "very_long_absence"
        elif self._state.affinity > 0.5:
            tag = "reunion"
        else:
            tag = "user_returned"
        definition = load_stimulus_catalog().get(tag)
        if definition is None:
            return
        stimulus = Stimulus(
            source=StimulusSource.REUNION,
            tag=tag,
            magnitude=1.0,
            dval=definition.dval,
            darousal=definition.darousal,
            ddominance=definition.ddominance,
            confidence=1.0,
            note=kind,
        )
        self._apply_stimulus_internal(
            stimulus,
            category=definition.category,
            now=now,
            reset_idle=True,
            touch_stimulus=True,
        )
        self._state = replace(self._state, pending_greeting=kind, updated_at=now)

    # ── 刺激入口 ─────────────────────────────────────────────────────────
    async def apply_stimulus(
        self,
        stimulus: Stimulus,
        *,
        preferred_label: str | None = None,
    ) -> EmotionSnapshot:
        """施加一次刺激（引擎唯一的状态写入口）。"""
        if self._frozen:
            return self.snapshot()
        try:
            definition = load_stimulus_catalog().get(stimulus.tag)
            category = definition.category if definition else "default"
            self._apply_stimulus_internal(
                stimulus,
                category=category,
                now=self._clock(),
                preferred_label=preferred_label,
            )
            self._error_count = 0
        except Exception as exc:  # noqa: BLE001 - 情绪异常不能中断对话
            log.exception("应用刺激失败: %s", exc)
            self._handle_error()
        await self._maybe_broadcast(force=True)
        self.persist()
        return self.snapshot()

    def _apply_stimulus_internal(
        self,
        stimulus: Stimulus,
        *,
        category: str,
        now: float,
        preferred_label: str | None = None,
        reset_idle: bool = True,
        touch_stimulus: bool = True,
    ) -> None:
        state = self._state
        old_pad = state.pad
        stimulus_catalog = load_stimulus_catalog()
        definition = stimulus_catalog.get(stimulus.tag)
        effective = stimulus
        preferred = preferred_label

        # ⓪ 人格滤镜：同一刺激可被重新解释（数据驱动，见角色卡 persona）
        override = self._card.persona.stimulus_overrides.get(stimulus.tag)
        if override:
            mapped_tag = str(override.get("tag", stimulus.tag))
            stimulus = replace(
                stimulus,
                tag=mapped_tag,
                dval=_as_float(override.get("dval"), stimulus.dval),
                darousal=_as_float(override.get("darousal"), stimulus.darousal),
                ddominance=_as_float(override.get("ddominance"), stimulus.ddominance),
                note=stimulus.note or "persona_override",
            )
            effective = stimulus
            category = str(override.get("category", category))
            definition = stimulus_catalog.get(mapped_tag)
            label_override = override.get("label_override")
            if isinstance(label_override, str):
                preferred = preferred or label_override

        # ① 重复刺激递减（同 tag 窗口内 1 : 0.7 : 0.49）
        if definition is not None and definition.habituate:
            count = self._recent_count(stimulus.tag, now)
            if count:
                scaled = apply_habituation(
                    PAD(effective.dval, effective.darousal, effective.ddominance),
                    count,
                    HABITUATION_FACTOR,
                )
                effective = replace(
                    effective,
                    dval=scaled.valence,
                    darousal=scaled.arousal,
                    ddominance=scaled.dominance,
                )

        # ② 共情反转：用户负面情绪时桌宠不该跟着一起难过
        if definition is not None:
            rule = stimulus_catalog.empathy_rule(stimulus.tag)
            if rule is not None:
                effective = replace(effective, dval=effective.dval * rule.valence_scale)
                preferred = preferred or rule.label_override
            preferred = preferred or definition.label_override

        # ③ 人格调制 + 软饱和
        modulation = modulate(effective, self._card.persona, state, category)
        new_pad = modulation.pad

        # ④ 关系量与耐心
        affinity = state.affinity
        trust = state.trust
        patience = state.patience
        if effective.dval > 0 and category in ("intimate", "praise", "care"):
            affinity = min(1.0, affinity + 0.008)
        if stimulus.tag == "teased":
            patience = max(0.0, patience - 0.15)
        if stimulus.tag == "interrupted":
            patience = max(0.0, patience - 0.05)
        if stimulus.tag == "user_insult":
            trust = max(0.0, trust - 0.02)
            patience = max(0.0, patience - 0.02)

        intensity = compute_intensity(new_pad, state.mood, new_pad.arousal, 1.0)
        self._state = replace(
            state,
            pad=new_pad,
            intensity=intensity,
            affinity=affinity,
            trust=trust,
            patience=patience,
            last_stimulus_at=now if touch_stimulus else state.last_stimulus_at,
            last_interaction_at=now if reset_idle else state.last_interaction_at,
            idle_seconds=0.0 if reset_idle else state.idle_seconds,
            updated_at=now,
            stimuli_seen=state.stimuli_seen + 1,
        )
        if definition is not None:
            self._recent_tags.append((now, stimulus.tag))
            self._prune_recent_tags(now)
        self._recompute_label(
            now,
            stimulus_tag=stimulus.tag,
            magnitude=stimulus.magnitude,
            preferred_label=preferred,
        )
        self._record_cause(old_pad, self._state.pad, stimulus, now)
        if stimulus.source == StimulusSource.USER_TEXT:
            self._last_text_polarity = effective.dval

    def _recent_count(self, tag: str, now: float) -> int:
        self._prune_recent_tags(now)
        return sum(1 for _, item in self._recent_tags if item == tag)

    def _prune_recent_tags(self, now: float) -> None:
        cutoff = now - HABITUATION_WINDOW
        self._recent_tags = [item for item in self._recent_tags if item[0] >= cutoff]

    def _record_cause(self, old_pad: PAD, new_pad: PAD, stimulus: Stimulus, now: float) -> None:
        cause = EmotionCause(
            ts=now,
            source=str(stimulus.source),
            stimulus=stimulus.tag,
            delta=PAD(
                new_pad.valence - old_pad.valence,
                new_pad.arousal - old_pad.arousal,
                new_pad.dominance - old_pad.dominance,
            ),
            resulting_label=self._state.label,
            note=stimulus.note,
        )
        causes = tuple(list(self._state.recent_causes)[-11:] + [cause])
        self._state = replace(self._state, recent_causes=causes)

    # ── 标签推导与状态机 ─────────────────────────────────────────────────
    def _idle_preferred_label(self, state: EmotionState) -> str | None:
        """长时间无互动时的标签倾向（让"冷落"能被感知，而不是永远 neutral）。"""
        if state.idle_seconds >= 7200 and state.affinity > 0.5:
            return "sad"
        if state.idle_seconds >= 3600:
            return "lonely"
        if state.idle_seconds >= 1800:
            return "bored"
        return None

    def _recompute_label(
        self,
        now: float,
        *,
        stimulus_tag: str = "",
        magnitude: float = 0.0,
        preferred_label: str | None = None,
    ) -> bool:
        """重新推导标签；返回是否发生了标签切换。"""
        state = self._state
        persona = self._card.persona
        inferred, score, secondary = infer_label(
            state.pad,
            self._catalog,
            persona.label_bias,
        )
        if not is_label_allowed(persona, inferred, state):
            inferred, secondary = "neutral", None

        candidate = preferred_label or (
            self._idle_preferred_label(state) if not stimulus_tag else None
        )
        if candidate and candidate not in self._catalog.names:
            candidate = None
        if candidate and not is_label_allowed(persona, candidate, state):
            candidate = None
        if candidate:
            inferred, score, secondary = candidate, 1.0, None

        if inferred == state.label:
            self._state = replace(
                state,
                label_confidence=max(score, state.label_confidence),
                secondary_label=secondary,
            )
            return False

        # 不应期：只累积 PAD，不改标签
        if now - state.last_label_change_at < persona.refractory_seconds:
            return False

        # 最小强度门槛：强情绪需要足够强度
        if (
            inferred in self._catalog.high_intensity_labels
            and state.intensity < HIGH_INTENSITY_GATE
        ):
            inferred, secondary = "neutral", None
            score = max(score, 0.5)

        # 状态机
        decision = evaluate(
            state.label,
            inferred,
            TransitionContext(
                pad_valence=state.pad.valence,
                pad_arousal=state.pad.arousal,
                pad_dominance=state.pad.dominance,
                intensity=state.intensity,
                idle_seconds=state.idle_seconds,
                affinity=state.affinity,
                trust=state.trust,
                patience=state.patience,
                stimulus_tag=stimulus_tag,
                magnitude=magnitude,
            ),
            self._transitions,
        )
        if not decision.allowed:
            if decision.via == "neutral" and state.label != "neutral":
                # 禁止直跳：先回落到 neutral（视觉上"平复了一下"）
                inferred, secondary = "neutral", None
            else:
                return False

        self._state = replace(
            self._state,
            label=inferred,
            secondary_label=secondary if inferred != "neutral" else None,
            label_confidence=score,
            last_label_change_at=now,
            label_switches=state.label_switches + 1,
        )
        return True

    # ── tick / 时间旅行 ──────────────────────────────────────────────────
    async def tick(self, dt: float) -> EmotionSnapshot:
        """一次 tick：衰减 → 心境更新 → 闲置累计 → 标签重推 → 节流广播/落盘。"""
        if self._frozen or dt <= 0:
            return self.snapshot()
        try:
            self._advance_once(dt, now=self._clock())
            await self._maybe_broadcast()
            self._maybe_persist(self._clock())
            self._error_count = 0
        except Exception as exc:  # noqa: BLE001
            log.exception("情感引擎 tick 计算失败: %s", exc)
            self._handle_error()
        return self.snapshot()

    def _advance_once(self, dt: float, *, now: float | None = None) -> None:
        state = self._state
        persona = self._card.persona
        moment = state.updated_at + dt if now is None else now
        baseline = self._effective_baseline(moment)

        pad = decay_toward(state.pad, state.mood, dt, self._tau())
        mood = update_mood(state.mood, pad, dt, baseline)
        pad = noise_step(pad, self._rng, dt)

        dominance = pad.dominance
        recovery = persona.dominance_recovery
        if recovery > 0:
            dominance += (baseline.dominance - dominance) * min(1.0, recovery * dt)
            pad = PAD(pad.valence, pad.arousal, max(0.0, min(1.0, dominance)))

        recency = _recency(max(0.0, moment - state.last_stimulus_at))
        intensity = compute_intensity(pad, mood, pad.arousal, recency)
        patience = min(1.0, state.patience + dt / 3600.0)
        idle_seconds = state.idle_seconds + dt
        self._state = replace(
            state,
            pad=pad,
            mood=mood,
            intensity=intensity,
            patience=patience,
            idle_seconds=idle_seconds,
            updated_at=moment,
        )
        self._recompute_label(moment)
        self._maybe_ambient(moment)

    def advance(self, seconds: float, *, step: float = 1.0) -> EmotionSnapshot:
        """时间旅行：不 sleep，直接推进 N 秒（验收"离线 8 小时"用）。"""
        if seconds <= 0:
            return self.snapshot()
        remaining = float(seconds)
        while remaining > 0:
            dt = min(step, remaining)
            remaining -= dt
            self._advance_once(dt)
        virtual_now = self._state.updated_at
        if seconds > VERY_LONG_ABSENCE_SECONDS:
            self._apply_reunion("very_long_absence", virtual_now)
        elif seconds > REUNION_SECONDS:
            self._apply_reunion("long_absence", virtual_now)
        real_now = self._clock()
        self._rebase_times(real_now - self._state.updated_at)
        self._last_tick = real_now
        return self.snapshot()

    def _rebase_times(self, offset: float) -> None:
        """时间旅行结束后把内部时间戳拉回真实时钟，避免不应期被"未来"卡死。"""
        if offset == 0:
            return
        state = self._state

        def shift(value: float) -> float:
            return value + offset if value > 0 else value

        causes = tuple(replace(cause, ts=shift(cause.ts)) for cause in state.recent_causes)
        self._state = replace(
            state,
            updated_at=state.updated_at + offset,
            last_stimulus_at=shift(state.last_stimulus_at),
            last_interaction_at=shift(state.last_interaction_at),
            last_label_change_at=shift(state.last_label_change_at),
            last_ambient_at=shift(state.last_ambient_at),
            last_proactive_at=shift(state.last_proactive_at),
            proactive_events=tuple(shift(ts) for ts in state.proactive_events),
            recent_causes=causes,
        )

    def _effective_baseline(self, now: float) -> PAD:
        return circadian_baseline(baseline_mood(self._card.persona), self._hour(now))

    def _maybe_ambient(self, now: float) -> None:
        """每 15 分钟检查一次自发刺激（深夜/午后）。"""
        if now - self._state.last_ambient_at < AMBIENT_INTERVAL:
            return
        tag = ambient_tag_for_hour(self._hour(now))
        self._state = replace(self._state, last_ambient_at=now)
        if tag is None:
            return
        definition = load_stimulus_catalog().get(tag)
        if definition is None:
            return
        stimulus = Stimulus(
            source=definition.source,
            tag=tag,
            magnitude=0.5,
            dval=definition.dval,
            darousal=definition.darousal,
            ddominance=definition.ddominance,
            confidence=0.6,
            note="ambient",
        )
        old_pad = self._state.pad
        modulation = modulate(stimulus, self._card.persona, self._state, definition.category)
        recency = _recency(max(0.0, now - self._state.last_stimulus_at))
        self._state = replace(
            self._state,
            pad=modulation.pad,
            intensity=compute_intensity(
                modulation.pad, self._state.mood, modulation.pad.arousal, recency
            ),
            updated_at=now,
        )
        self._recompute_label(now, preferred_label=definition.label_override)
        self._record_cause(old_pad, self._state.pad, stimulus, now)

    def _tau(self) -> float:
        label = self._catalog.get(self._state.label)
        base = label.tau if label else 300.0
        return effective_tau(self._card.persona, base)

    # ── 广播与落盘 ───────────────────────────────────────────────────────
    async def _maybe_broadcast(self, *, force: bool = False) -> None:
        if not self._listeners:
            return
        now = self._clock()
        if force or self._last_broadcast_pad is None:
            changed = True
        else:
            delta = max(
                abs(self._state.pad.valence - self._last_broadcast_pad.valence),
                abs(self._state.pad.arousal - self._last_broadcast_pad.arousal),
                abs(self._state.pad.dominance - self._last_broadcast_pad.dominance),
            )
            changed = (
                delta > BROADCAST_DELTA and now - self._last_broadcast_at >= BROADCAST_MIN_INTERVAL
            )
        if not changed:
            return
        self._last_broadcast_at = now
        self._last_broadcast_pad = self._state.pad
        snapshot = self.snapshot()
        for listener in list(self._listeners):
            try:
                await listener(snapshot)
            except Exception as exc:  # noqa: BLE001 - 单个订阅者失败不影响别人
                log.warning("情绪快照广播失败: %s", exc)

    def _maybe_persist(self, now: float) -> None:
        if now - self._last_persist_at >= PERSIST_INTERVAL:
            self.persist()

    def persist(self) -> None:
        """把当前状态落盘（节流由调用方负责）。"""
        try:
            self._repo.save(self._state)
            self._repo.append_snapshot(self.snapshot())
            self._last_persist_at = self._clock()
        except Exception as exc:  # noqa: BLE001 - 落盘失败不影响运行
            log.warning("情绪状态落盘失败: %s", exc)

    # ── 业务入口 ─────────────────────────────────────────────────────────
    async def apply_text(
        self,
        text: str,
        *,
        magnitude_scale: float = 1.0,
    ) -> EmotionSnapshot:
        """用户文本 → 刺激（Level 1）；``magnitude_scale`` 由语音特征给出。"""
        analysis = analyze_text(text)
        self.last_text_analysis = analysis
        if not analysis.hit:
            return self.snapshot()
        self._last_text_polarity = sum(item.dval for item in analysis.stimuli)
        for stimulus in analysis.stimuli:
            await self.apply_stimulus(
                replace(stimulus, magnitude=stimulus.magnitude * max(0.1, magnitude_scale))
            )
        return self.snapshot()

    async def apply_text_llm(
        self,
        text: str,
        provider: Any,
        *,
        timeout: float = 2.0,
        magnitude_scale: float = 1.0,
    ) -> EmotionSnapshot:
        """Level 2：词典未命中且文本较长时，用轻量 LLM 补标注。"""
        if provider is None or self.last_text_analysis is None:
            return self.snapshot()
        if self.last_text_analysis.hit:
            return self.snapshot()
        try:
            analysis = await asyncio.wait_for(
                analyze_with_llm(text, provider),
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - 标注失败不影响对话
            log.info("Level2 情绪标注跳过: %s", exc)
            return self.snapshot()
        self.last_text_analysis = analysis
        if not analysis.hit:
            return self.snapshot()
        self._last_text_polarity = sum(item.dval for item in analysis.stimuli)
        for stimulus in analysis.stimuli:
            await self.apply_stimulus(
                replace(stimulus, magnitude=stimulus.magnitude * max(0.1, magnitude_scale))
            )
        return self.snapshot()

    async def apply_interaction(
        self,
        event_type: str,
        *,
        count: int = 1,
        area: str = "",
    ) -> EmotionSnapshot:
        """前端交互事件 → 刺激（A 类）或仅跟踪（C 类）。"""
        outcome = classify_interaction(event_type, count=count, area=area)
        if outcome.stimulus is None:
            now = self._clock()
            self._state = replace(self._state, last_interaction_at=now, updated_at=now)
            return self.snapshot()
        return await self.apply_stimulus(outcome.stimulus)

    async def apply_task_result(self, ok: bool, note: str = "") -> EmotionSnapshot:
        """任务结果 → 刺激（S6 的 Agent Core 用）。"""
        tag = "task_success" if ok else "task_fail"
        definition = load_stimulus_catalog().get(tag)
        if definition is None:
            return self.snapshot()
        stimulus = Stimulus(
            source=StimulusSource.TASK_RESULT,
            tag=tag,
            magnitude=1.0,
            dval=definition.dval,
            darousal=definition.darousal,
            ddominance=definition.ddominance,
            confidence=1.0,
            note=note,
        )
        return await self.apply_stimulus(stimulus)

    def _hint_label_allowed(self, label: str, now: float) -> bool:
        persona = self._card.persona
        if not is_label_allowed(persona, label, self._state):
            return False
        if now - self._state.last_label_change_at < persona.refractory_seconds:
            return False
        decision = evaluate(
            self._state.label,
            label,
            TransitionContext(
                pad_valence=self._state.pad.valence,
                pad_arousal=self._state.pad.arousal,
                pad_dominance=self._state.pad.dominance,
                intensity=self._state.intensity,
                idle_seconds=self._state.idle_seconds,
                affinity=self._state.affinity,
                trust=self._state.trust,
                patience=self._state.patience,
            ),
            self._transitions,
        )
        return decision.allowed

    async def apply_llm_hint(self, hint: LLMEmotionHint) -> EmotionSnapshot:
        """裁决 LLM 的情绪建议（7 条规则，引擎有否决权）。"""
        if self._frozen:
            return self.snapshot()
        now = self._clock()
        label = hint.label
        if label is not None and label not in self._catalog.names:
            log.info("忽略非法情绪标签建议: %s", label)
            label = None

        dval = max(-0.5, min(0.5, hint.dval))
        darousal = max(-0.5, min(0.5, hint.darousal))
        ddominance = max(-0.5, min(0.5, hint.ddominance))

        if (
            label is not None
            and label in self._catalog.high_intensity_labels
            and self._state.intensity < HIGH_INTENSITY_GATE
        ):
            log.info("强度不足，忽略强情绪标签建议: %s", label)
            label = None
        if label is not None and not self._hint_label_allowed(label, now):
            log.info("状态机/人格/不应期拒绝标签建议，仅保留 PAD 增量: %s", label)
            label = None

        confidence = max(0.0, min(1.0, hint.confidence))
        weight = 1.0 if confidence >= 0.4 else 0.5

        # 与词典分析矛盾：引擎 0.6、LLM 0.4，避免"嘴上说开心、文本在骂人"
        if (
            self._last_text_polarity
            and dval
            and dval * self._last_text_polarity < 0
            and abs(dval) > 0.25
        ):
            dval *= 0.4
            darousal *= 0.4
            ddominance *= 0.4
            log.info("LLM 情绪建议与文本矛盾，按 0.4 权重融合")

        if dval == 0.0 and darousal == 0.0 and ddominance == 0.0:
            if label is not None and label != self._state.label:
                self._state = replace(
                    self._state,
                    label=label,
                    secondary_label=None,
                    label_confidence=confidence,
                    last_label_change_at=now,
                    label_switches=self._state.label_switches + 1,
                    updated_at=now,
                )
                await self._maybe_broadcast(force=True)
                self.persist()
            return self.snapshot()

        stimulus = Stimulus(
            source=StimulusSource.LLM_HINT,
            tag=f"llm:{label or 'delta'}",
            magnitude=weight,
            dval=dval,
            darousal=darousal,
            ddominance=ddominance,
            confidence=confidence,
            note=hint.note,
        )
        definition = load_stimulus_catalog().get(stimulus.tag)
        category = definition.category if definition else "default"
        try:
            self._apply_stimulus_internal(
                stimulus,
                category=category,
                now=now,
                preferred_label=label,
                reset_idle=False,
                touch_stimulus=False,
            )
            self._error_count = 0
        except Exception as exc:  # noqa: BLE001
            log.exception("应用 LLM 情绪建议失败: %s", exc)
            self._handle_error()
        await self._maybe_broadcast(force=True)
        self.persist()
        return self.snapshot()

    def consume_greeting(self) -> str | None:
        """取走待播放的开场白（前端展示后调用，避免每次 hello 重播）。"""
        greeting = self._state.pending_greeting
        if greeting is not None:
            self._state = replace(self._state, pending_greeting=None)
        return greeting

    # ── 主动性 ───────────────────────────────────────────────────────────
    def poll_proactive(self, now: float | None = None) -> ProactiveIntent | None:
        """检查是否该主动搭话；不会修改 PAD，只记录预算。"""
        moment = self._clock() if now is None else now
        decision = self._proactive.evaluate(
            self._state,
            self._card,
            moment,
            local_hour=self._hour(moment),
        )
        if decision.intent is None:
            return None
        recent = tuple(ts for ts in self._state.proactive_events if moment - ts < 3600.0)
        self._state = replace(
            self._state,
            last_proactive_at=moment,
            proactive_events=recent + (moment,),
            updated_at=moment,
        )
        return decision.intent

    # ── 视图 ─────────────────────────────────────────────────────────────
    def prompt_block(self, snapshot: EmotionSnapshot | None = None) -> str:
        """注入 Roleplay 的【内心状态】文本块。"""
        return build_prompt_block(snapshot or self.snapshot(), self._card, self._catalog)

    def style_constraints(self, snapshot: EmotionSnapshot | None = None) -> Any:
        """注入 Roleplay 的表达约束。"""
        return build_style_constraints(snapshot or self.snapshot(), self._card, self._catalog)

    def map_to_presentation(self, snapshot: EmotionSnapshot | None = None) -> PresentationCue:
        """把快照映射成表现指令（动作/表情/TTS 韵律）。"""
        return map_snapshot(snapshot or self.snapshot(), self._card, self._catalog)

    def history(self, limit: int = 600) -> list[dict[str, Any]]:
        return self._repo.history(limit)


def _recency(seconds_since_stimulus: float) -> float:
    """最近被刺激的新鲜度：60 秒内指数衰减。"""
    if seconds_since_stimulus <= 0:
        return 1.0
    return math.exp(-seconds_since_stimulus / 60.0)


def _as_float(value: object, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default
