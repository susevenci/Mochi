"""上下文装配（计划书 5.3.3 的 S1 子集）。

不变量 I2：``layer="roleplay"`` 时**绝不注入任何工具 schema**。
按"完整轮次"截断：绝不出现孤立的 user 或 assistant 消息。
"""

from __future__ import annotations

from collections.abc import Sequence

from app.config.character_card import CharacterCard
from app.memory.tokens import count_tokens, truncate_tokens
from app.providers.base import ChatMessage

# 字符预算（S1 用字符近似 token；S6 换成 tiktoken 精确计数）
PERSONA_CHARS = 900
OUTPUT_FORMAT_CHARS = 450
EMOTION_CHARS = 700
MEMORY_CHARS = 900
DIALOG_CHARS = 2400
PERSONA_TOKENS = 420
EMOTION_TOKENS = 320
MEMORY_TOKENS = 380
OUTPUT_TOKENS = 260
DIALOG_TOKENS = 1200

OUTPUT_FORMAT = """\
【输出格式】
先输出回复正文（不要逐字重复你最近说过的话），然后换行输出 <<<MOOD>>> 再输出一个 JSON：
{"emotion":{"label":"neutral","delta_valence":0.0,"delta_arousal":0.0,"confidence":0.0},
 "action":{"expression":"relaxed","motion":"idle_sway","priority":"normal"}}
label 只能从这个列表选：neutral,happy,excited,amused,affectionate,shy,proud,curious,
sleepy,bored,lonely,sad,worried,angry,hurt,surprised
"""


class ContextBuilder:
    def __init__(self, card: CharacterCard) -> None:
        self._card = card

    @property
    def card(self) -> CharacterCard:
        return self._card

    def set_card(self, card: CharacterCard) -> None:
        self._card = card

    def system_prompt(
        self,
        *,
        emotion_block: str | None = None,
        memory_block: str | None = None,
    ) -> str:
        identity = self._card.identity
        catchphrases = "、".join(identity.catchphrases) or "（无）"
        forbidden = "、".join(identity.forbidden) or "（无）"
        parts = [
            "【人格内核】",
            f"你是{identity.full_name}，{identity.role}。",
            f"性格：{identity.personality.strip()}",
            f"说话风格：{identity.tone}；句子长度：{identity.sentence_length}",
            f"常用口头禅：{catchphrases}",
            f"绝不出现的词句：{forbidden}",
            "",
            "【表达约束】",
            "- 永远以角色身份说话，不自称 AI 或语言模型",
            "- 回复控制在 60 字以内，不要长篇说教",
            "- 不用 emoji，可用少量颜文字",
        ]
        if emotion_block:
            parts += ["", emotion_block]
        if memory_block:
            parts += ["", memory_block]
        parts += ["", OUTPUT_FORMAT]
        return "\n".join(parts)

    def build(
        self,
        recent: Sequence[tuple[str, str]],
        user_input: str,
        *,
        layer: str = "roleplay",
        emotion_block: str | None = None,
        memory_block: str | None = None,
    ) -> list[ChatMessage]:
        """组装 messages。``layer="roleplay"`` 时工具预算恒为 0（I2）。"""
        if layer != "roleplay":
            raise NotImplementedError("S1 只实现 roleplay 层")

        emotion_block = truncate_tokens(emotion_block, EMOTION_TOKENS) if emotion_block else None
        memory_block = truncate_tokens(memory_block, MEMORY_TOKENS) if memory_block else None
        system = truncate_tokens(
            self.system_prompt(emotion_block=emotion_block, memory_block=memory_block),
            1800,
        )
        messages: list[ChatMessage] = [ChatMessage(role="system", content=system)]

        # 从最近往前取整轮，直到 token 预算耗尽（不切断一问一答）
        budget = DIALOG_TOKENS
        selected: list[tuple[str, str]] = []
        for user, assistant in reversed(recent):
            cost = count_tokens(user) + count_tokens(assistant)
            if cost > budget and selected:
                break
            selected.append((user, assistant))
            budget -= cost

        for user, assistant in reversed(selected):
            messages.append(ChatMessage(role="user", content=user))
            messages.append(ChatMessage(role="assistant", content=assistant))

        messages.append(ChatMessage(role="user", content=user_input))
        return messages
