"""斜杠命令（计划书 5.8.4 的 S1 子集）。

命令不走 LLM、不产生情绪刺激（C 类行为）。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.character_card import CardLoader
from app.memory.context_builder import ContextBuilder
from app.memory.short_term import ShortTermMemory

HELP_TEXT = "可用命令：/help · /role list · /role set <id> · /new"


@dataclass(frozen=True)
class CommandResult:
    text: str


class CommandRouter:
    def __init__(
        self,
        *,
        cards: CardLoader,
        history: ShortTermMemory,
        builder: ContextBuilder,
    ) -> None:
        self._cards = cards
        self._history = history
        self._builder = builder

    def handle(self, text: str) -> CommandResult | None:
        stripped = text.strip()
        if not stripped.startswith("/"):
            return None
        parts = stripped.split()
        command = parts[0]
        args = parts[1:]

        if command == "/help":
            return CommandResult(HELP_TEXT)
        if command == "/new":
            self._history.clear()
            return CommandResult("好，我们重新开始。")
        if command == "/role":
            return self._role(args)
        return CommandResult(f"不认识的命令：{command}，试试 /help")

    def _role(self, args: list[str]) -> CommandResult:
        if not args or args[0] == "list":
            ids = self._cards.list_ids()
            current = self._cards.current.id
            listing = "、".join(f"{cid}{'（当前）' if cid == current else ''}" for cid in ids)
            return CommandResult(f"可用角色：{listing}")
        if args[0] == "set" and len(args) >= 2:
            card_id = args[1]
            try:
                card = self._cards.load(card_id)
            except (FileNotFoundError, ValueError) as exc:
                return CommandResult(f"切换失败：{exc}")
            self._builder.set_card(card)
            self._history.clear()
            return CommandResult(f"好，从现在起我是{card.name}。{card.greeting}")
        return CommandResult("用法：/role list 或 /role set <id>")
