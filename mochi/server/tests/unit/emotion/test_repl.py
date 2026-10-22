"""CLI 原型（T3-G）：命令分发与脚本模式。"""

from __future__ import annotations

from app.emotion import repl


def test_repl_commands(engine_factory, inject_stimulus, capsys) -> None:
    engine, _clock, _repo = engine_factory()
    assert repl._run_command(engine, "state")
    assert repl._run_command(engine, "labels")
    assert repl._run_command(engine, "stimuli")
    assert repl._run_command(engine, "inject user_praise 1.2")
    assert repl._run_command(engine, "text 今天辛苦啦")
    assert repl._run_command(engine, "advance 10")
    assert repl._run_command(engine, "tick 1")
    assert repl._run_command(engine, "proactive")
    assert repl._run_command(engine, "unknown")
    assert engine.state.stimuli_seen >= 1
    assert repl._run_command(engine, "quit") is False
    output = capsys.readouterr().out
    assert "[neutral]" in output or "[happy]" in output


def test_repl_main_with_script(engine_factory, monkeypatch, capsys) -> None:
    engine, _clock, _repo = engine_factory()
    monkeypatch.setattr(repl, "_build_engine", lambda _card: engine)
    code = repl.main(["--script", "state\ninject user_praise\nquit"])
    assert code == 0
    assert "Mochi 情感引擎" in capsys.readouterr().out


def test_repl_help_and_bad_inject(engine_factory, capsys) -> None:
    engine, _clock, _repo = engine_factory()
    assert repl._run_command(engine, "")
    assert repl._run_command(engine, "inject")
    assert repl._run_command(engine, "inject no_such_tag")
    output = capsys.readouterr().out
    assert "用法" in output
    assert "未知刺激" in output
