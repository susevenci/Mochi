"""情感引擎 CLI 原型（T3-01）。

用法：
    python -m app.emotion.repl
    python -m app.emotion.repl --script "state\ninject user_praise\nadvance 60\nstate"

命令：
    state | labels | stimuli
    inject <tag> [magnitude]
    text <一句话>
    advance <秒> | tick <秒>
    proactive
    quit
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.config.character_card import CardLoader
from app.config.settings import Settings
from app.emotion.engine import EmotionEngine
from app.emotion.stimuli.catalog import load_catalog
from app.store.emotion_repo import JsonEmotionRepo

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHARACTERS_DIR = PROJECT_ROOT / "characters"


def _build_engine(card_id: str) -> EmotionEngine:
    settings = Settings()
    settings.ensure_dirs()
    cards = CardLoader(CHARACTERS_DIR, card_id)
    engine = EmotionEngine(
        card=cards.current,
        repo=JsonEmotionRepo(settings.data_dir / "emotion_state.json"),
    )
    engine.load()
    return engine


def _print_state(engine: EmotionEngine) -> None:
    state = engine.state
    print(
        f"[{state.label}] v={state.pad.valence:+.3f} "
        f"a={state.pad.arousal:.3f} d={state.pad.dominance:.3f} "
        f"intensity={state.intensity:.2f} idle={state.idle_seconds:.0f}s "
        f"greeting={state.pending_greeting or '-'}"
    )


def _run_command(engine: EmotionEngine, line: str) -> bool:
    parts = line.strip().split(maxsplit=2)
    if not parts:
        return True
    command = parts[0].lower()
    if command in ("quit", "exit", "q"):
        return False
    if command == "state":
        _print_state(engine)
        return True
    if command == "labels":
        print("、".join(engine._catalog.names))
        return True
    if command == "stimuli":
        print("、".join(load_catalog().tags()))
        return True
    if command == "inject":
        if len(parts) < 2:
            print("用法：inject <tag> [magnitude]")
            return True
        tag = parts[1]
        magnitude = float(parts[2]) if len(parts) > 2 else 1.0
        definition = load_catalog().get(tag)
        if definition is None:
            print(f"未知刺激：{tag}")
            return True
        from app.emotion.models import Stimulus, StimulusSource

        asyncio.run(
            engine.apply_stimulus(
                Stimulus(
                    source=StimulusSource.SYSTEM,
                    tag=tag,
                    magnitude=magnitude,
                    dval=definition.dval,
                    darousal=definition.darousal,
                    ddominance=definition.ddominance,
                    note="repl",
                ),
                preferred_label=definition.label_override,
            )
        )
        _print_state(engine)
        return True
    if command == "text":
        text = line.strip()[len("text") :].strip()
        asyncio.run(engine.apply_text(text))
        _print_state(engine)
        return True
    if command == "advance":
        seconds = float(parts[1]) if len(parts) > 1 else 60.0
        engine.advance(seconds)
        _print_state(engine)
        return True
    if command == "tick":
        seconds = float(parts[1]) if len(parts) > 1 else 1.0
        asyncio.run(engine.tick(seconds))
        _print_state(engine)
        return True
    if command == "proactive":
        intent = engine.poll_proactive()
        print("（不主动）" if intent is None else f"主动：{intent.text}")
        return True
    print(f"未知命令：{command}（state/labels/stimuli/inject/text/advance/tick/proactive/quit）")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mochi 情感引擎 CLI")
    parser.add_argument("--card", default="tsundere")
    parser.add_argument("--script", help="用换行分隔的命令脚本（非交互）")
    args = parser.parse_args(argv)

    engine = _build_engine(args.card)
    print(f"Mochi 情感引擎 · {engine.card.name}（输入 help 查看命令）")
    _print_state(engine)

    if args.script:
        for line in args.script.splitlines():
            if not _run_command(engine, line):
                break
        engine.persist()
        return 0

    for raw in sys.stdin:
        if not _run_command(engine, raw):
            break
    engine.persist()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
