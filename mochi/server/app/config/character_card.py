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


class Presentation(BaseModel):
    """角色卡与表现层的绑定（计划书 5.8.2）：模型名 + 情绪→表情映射。

    模型名对应 ``data/live2d/<模型名>/`` 目录；留空表示"用衣柜里第一个可用模型"，
    交叉校验时只告警不报错（T2-13）。
    """

    live2d_model: str | None = None
    # 情绪标签 → .exp3.json 里的表情名；只有模型声明了 Expressions 才有意义
    emotion_expressions: dict[str, str] = Field(default_factory=dict)


class ProactiveConfig(BaseModel):
    """主动性参数（计划书 5.2.6e）：主动搭话的门槛与打扰预算。"""

    enabled: bool = True
    lonely_threshold_seconds: float = 2400.0
    spontaneous_interval_seconds: float = 900.0
    max_per_hour: int = 3
    min_interval_seconds: float = 600.0
    quiet_hours: tuple[int, int] = (23, 7)


class Persona(BaseModel):
    """人格对情绪反应的调制参数（计划书 5.2.7）。

    全部字段有默认值：旧角色卡不写 persona 也能跑。
    """

    baseline_mood: dict[str, float] = Field(default_factory=dict)
    initial_pad: dict[str, float] = Field(default_factory=dict)
    # 刺激类别 → 反应增益（praise/insult/intimate/care/task_fail/unexpected/tease）
    reactivity: dict[str, float] = Field(default_factory=dict)
    decay_multiplier: float = 1.0
    refractory_seconds: float = 8.0
    dominance_recovery: float = 0.0
    label_bias: dict[str, float] = Field(default_factory=dict)
    # 人格滤镜：同一刺激可被重新解释（如元气把骂人当玩笑）
    stimulus_overrides: dict[str, dict[str, object]] = Field(default_factory=dict)
    forbidden_labels: list[str] = Field(default_factory=list)
    unlock_rules: list[dict[str, object]] = Field(default_factory=list)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    interjections: dict[str, list[str]] = Field(default_factory=dict)
    proactive_lines: dict[str, list[str]] = Field(default_factory=dict)
    greetings: dict[str, str] = Field(default_factory=dict)
    ack_templates: dict[str, str] = Field(default_factory=dict)


class CharacterCard(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    identity: Identity
    presentation: Presentation = Field(default_factory=Presentation)
    persona: Persona = Field(default_factory=Persona)
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
