"""斜杠命令（S6：会话管理 + 记忆管理）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config.character_card import CardLoader, CharacterCard
from app.memory.context_builder import ContextBuilder
from app.memory.short_term import ShortTermMemory

HELP_TEXT = (
    "可用命令：/help · /role list · /role set <id> · /new · /ls · /switch <id> · "
    "/rename <标题> · /delete <id> · /forget"
)


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
        memory: Any = None,
    ) -> None:
        self._cards = cards
        self._history = history
        self._builder = builder
        self._memory = memory

    @property
    def card(self) -> CharacterCard:
        return self._cards.current

    async def handle(self, text: str) -> CommandResult | None:
        stripped = text.strip()
        if not stripped.startswith("/"):
            return None
        parts = stripped.split(maxsplit=2)
        command = parts[0].lower()
        args = parts[1:]

        if command == "/help":
            return CommandResult(HELP_TEXT)
        if command == "/new":
            self._history.clear()
            if self._memory is not None:
                session_id = await self._memory.create_session()
                return CommandResult(f"新会话已开始（{session_id}）。")
            return CommandResult("好，我们重新开始。")
        if command == "/ls":
            if self._memory is None:
                return CommandResult("会话列表暂不可用。")
            sessions = await self._memory.list_sessions()
            current = self._memory.current_session
            lines = [
                f"{item.id} · {item.title}{'（当前）' if item.id == current else ''} · "
                f"{item.message_count} 条"
                for item in sessions
            ]
            return CommandResult("会话：\n" + "\n".join(lines))
        if command == "/switch":
            if self._memory is None or not args:
                return CommandResult("用法：/switch <会话 id>")
            ok = await self._memory.switch_session(args[0])
            if not ok:
                return CommandResult(f"没有找到会话：{args[0]}")
            self._history.clear()
            return CommandResult(f"已切换到会话 {args[0]}。")
        if command == "/rename":
            title = stripped[len("/rename") :].strip()
            if self._memory is None or not title:
                return CommandResult("用法：/rename <新标题>")
            await self._memory.rename_session(title)
            return CommandResult(f"会话已重命名为「{title}」。")
        if command == "/delete":
            if self._memory is None or not args:
                return CommandResult("用法：/delete <会话 id>")
            await self._memory.delete_session(args[0])
            return CommandResult(f"已删除会话 {args[0]}。")
        if command == "/forget":
            if self._memory is None:
                return CommandResult("记忆服务不可用。")
            await self._memory.forget(all_sessions=True)
            return CommandResult("长期记忆和画像已清空。")
        if command == "/role":
            return self._role(args)
        return CommandResult(f"不认识的命令：{command}，试试 /help")

    def select_card(self, card_id: str) -> CharacterCard:
        card = self._cards.load(card_id)
        self._builder.set_card(card)
        return card

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
