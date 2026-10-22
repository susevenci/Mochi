"""情感轨迹分析（T3-20 / SP4 五项指标）。

用法：
    python scripts/analyze_trajectory.py --simulate 200 --seed 42
    python scripts/analyze_trajectory.py --file docs/evidence/emotion-trace.json

输出为 JSON，便于写进阶段证据与调参记录。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.config.character_card import CardLoader  # noqa: E402
from app.emotion.engine import EmotionEngine  # noqa: E402
from app.emotion.models import Stimulus, StimulusSource  # noqa: E402
from app.emotion.stimuli.catalog import load_catalog  # noqa: E402
from app.store.emotion_repo import JsonEmotionRepo  # noqa: E402

CHARACTERS_DIR = ROOT / "characters"
SIMULATION_TAGS = (
    "user_praise",
    "user_insult",
    "user_care",
    "intimate",
    "user_sad",
    "unexpected",
    "tease",
    "task_success",
    "task_fail",
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def simulate(count: int, seed: int, card_id: str) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    clock = _Clock()
    cards = CardLoader(CHARACTERS_DIR, card_id)
    with tempfile.TemporaryDirectory() as tmp:
        engine = EmotionEngine(
            card=cards.current,
            repo=JsonEmotionRepo(Path(tmp) / "trace.json"),
            clock=clock,
            rng=random.Random(seed),
            hour_provider=lambda _: 14.0,
        )
        catalog = load_catalog()
        engine.persist()
        produced = 0
        turn = 0
        while produced < count:
            # 一段"对话"：先静置，再连续 2–4 条消息（真实输入是成簇的）
            turn += 1
            # 每 8 轮出现一次 10–15 分钟空窗
            interval = (
                rng.uniform(600.0, 900.0)
                if turn % 8 == 0
                else rng.uniform(90.0, 180.0)
            )
            clock.advance(interval)
            engine.advance(interval)
            engine.persist()
            burst_tag = rng.choice(SIMULATION_TAGS)
            burst = min(count - produced, rng.choice((2, 3, 3, 4)))
            for index in range(burst):
                gap = rng.uniform(2.0, 8.0)
                clock.advance(gap)
                engine.advance(gap)
                tag = burst_tag if index and rng.random() < 0.55 else rng.choice(SIMULATION_TAGS)
                definition = catalog.get(tag)
                assert definition is not None
                asyncio.run(
                    engine.apply_stimulus(
                        Stimulus(
                            source=StimulusSource.USER_TEXT,
                            tag=tag,
                            magnitude=rng.uniform(1.0, 1.8),
                            dval=definition.dval,
                            darousal=definition.darousal,
                            ddominance=definition.ddominance,
                            confidence=0.9,
                            note="simulation",
                        ),
                        preferred_label=definition.label_override,
                    )
                )
                produced += 1
        return engine.history(10000)


def load_trace(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    history = raw.get("history") if isinstance(raw, dict) else None
    return [item for item in history or [] if isinstance(item, dict)]


def analyze(history: list[dict[str, Any]]) -> dict[str, Any]:
    raw_points = [item for item in history if isinstance(item.get("pad"), dict)]
    if len(raw_points) < 2:
        return {"error": "not enough points", "points": len(raw_points)}

    # 同一时刻可能写入多条（advance 落盘 + 刺激落盘），按 ts 去重保留最后一条
    by_ts: dict[float, dict[str, Any]] = {}
    for item in raw_points:
        by_ts[round(float(item.get("ts", 0.0)), 3)] = item
    points = [by_ts[key] for key in sorted(by_ts)]
    duration_hours = max(
        1e-9,
        (float(points[-1].get("ts", 0.0)) - float(points[0].get("ts", 0.0))) / 3600.0,
    )

    switches: list[float] = []
    dwell: dict[str, list[float]] = defaultdict(list)
    slopes: list[float] = []
    previous = points[0]
    for current in points[1:]:
        ts0 = float(previous.get("ts", 0.0))
        ts1 = float(current.get("ts", 0.0))
        dt = max(1e-6, ts1 - ts0)
        pad0 = previous.get("pad") or {}
        pad1 = current.get("pad") or {}
        delta = max(
            abs(float(pad1.get("valence", 0.0)) - float(pad0.get("valence", 0.0))),
            abs(float(pad1.get("arousal", 0.0)) - float(pad0.get("arousal", 0.0))),
            abs(float(pad1.get("dominance", 0.0)) - float(pad0.get("dominance", 0.0))),
        )
        slopes.append(delta / dt)
        label0 = str(previous.get("label", "neutral"))
        label1 = str(current.get("label", "neutral"))
        if label0 != label1:
            switches.append(ts1)
            dwell[label0].append(ts1 - ts0)
        previous = current

    # 重复刺激的实际增幅比（从 causes 的去重时间线里取连续同 tag）
    causes: dict[tuple[float, str], dict[str, Any]] = {}
    for point in points:
        for cause in point.get("causes") or []:
            if not isinstance(cause, dict):
                continue
            key = (round(float(cause.get("ts", 0.0)), 3), str(cause.get("stimulus", "")))
            causes[key] = cause
    ordered = sorted(causes.values(), key=lambda item: float(item.get("ts", 0.0)))
    ratios: list[float] = []
    for first, second in zip(ordered, ordered[1:], strict=False):
        if first.get("stimulus") != second.get("stimulus"):
            continue
        delta0 = (first.get("delta") or {}).get("valence", 0.0)
        delta1 = (second.get("delta") or {}).get("valence", 0.0)
        if abs(float(delta0)) > 1e-6 and abs(float(delta1)) > 1e-6:
            ratios.append(float(delta1) / float(delta0))

    silent_changes: list[float] = []
    for previous, current in zip(points, points[1:], strict=False):
        ts0 = float(previous.get("ts", 0.0))
        ts1 = float(current.get("ts", 0.0))
        if ts1 - ts0 < 600.0:
            continue
        pad0 = previous.get("pad") or {}
        pad1 = current.get("pad") or {}
        silent_changes.append(
            abs(float(pad1.get("valence", 0.0)) - float(pad0.get("valence", 0.0)))
            + abs(float(pad1.get("arousal", 0.0)) - float(pad0.get("arousal", 0.0)))
        )

    switch_rate = len(switches) / duration_hours
    max_slope = max(slopes) if slopes else 0.0
    dwell_all = [value for values in dwell.values() for value in values]
    return {
        "points": len(points),
        "duration_hours": round(duration_hours, 3),
        "label_switches": len(switches),
        "switch_rate_per_hour": round(switch_rate, 2),
        "switch_rate_healthy": 4.0 <= switch_rate <= 12.0,
        "mean_dwell_seconds": round(statistics.mean(dwell_all), 1) if dwell_all else 0.0,
        "max_slope_per_second": round(max_slope, 3),
        "max_slope_healthy": max_slope < 0.3,
        "repeat_ratio_median": round(statistics.median(ratios), 3) if ratios else None,
        "repeat_ratio_samples": len(ratios),
        "silent_activity_mean": round(statistics.mean(silent_changes), 4)
        if silent_changes
        else 0.0,
        "silent_activity_healthy": bool(silent_changes)
        and statistics.mean(silent_changes) > 0.01,
        "labels_seen": sorted({str(item.get("label")) for item in points}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Mochi 情感轨迹分析")
    parser.add_argument("--file", type=Path, help="导出的 emotion trace JSON")
    parser.add_argument("--simulate", type=int, default=0, help="模拟刺激次数")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--card", default="tsundere")
    args = parser.parse_args()

    if args.file:
        history = load_trace(args.file)
    elif args.simulate:
        history = simulate(args.simulate, args.seed, args.card)
    else:
        parser.error("需要 --file 或 --simulate")
        return 2
    print(json.dumps(analyze(history), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
