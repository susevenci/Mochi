"""角色卡加载与校验（计划书 5.8.2 的 S1 子集）。

S3 起扩展 persona / presentation 段；S1 只关心人格内核与降级文案。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Identity(BaseModel):
    full_name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    personality: str = Field(min_length=1)
    tone: str = ""
    sentence_length: str = "偏短，10~35 字"
    catchphrases: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)


class CharacterCard(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    identity: Identity
    greeting: str = ""
    fallback: str = "唔…我这边好像有点状况，等我一下。"


class CardLoader:
    """启动时扫描角色卡目录；切换角色卡只需重新 load（计划书 5.8.4）。"""

    def __init__(self, directory: Path, card_id: str = "tsundere") -> None:
        self._dir = directory
        self._current = self.load(card_id)

    @property
    def current(self) -> CharacterCard:
        return self._current

    def list_ids(self) -> list[str]:
        if not self._dir.exists():
            return []
        return sorted(path.stem for path in self._dir.glob("*.yaml"))

    def load(self, card_id: str) -> CharacterCard:
        path = self._dir / f"{card_id}.yaml"
        if not path.exists():
            available = ", ".join(self.list_ids()) or "（无）"
            raise FileNotFoundError(f"角色卡不存在: {card_id}；可选: {available}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"角色卡格式错误（应为对象）: {path}")
        card = CharacterCard.model_validate(raw)
        self._current = card
        return card
