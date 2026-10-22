from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _default_data_dir() -> Path:
    # 开发态仓库自带 data/（Live2D 模型、settings.json）；安装态回落到 AppData
    dev_data = PROJECT_ROOT / "data"
    if dev_data.is_dir():
        return dev_data
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / "Mochi"


class Settings(BaseSettings):
    """配置优先级：CLI/.env > 环境变量 > 代码默认（计划书 4.8）。"""

    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── 服务 ──
    server_host: str = "127.0.0.1"
    server_port: int = 8765
    server_token: str = ""
    data_dir: Path = Field(default_factory=_default_data_dir)
    log_level: str = "INFO"

    # ── LLM（S1 起使用）──
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model_chat: str = "deepseek-chat"
    llm_model_decision: str = "deepseek-chat"
    llm_model_summary: str = "deepseek-chat"
    llm_temperature_roleplay: float = 0.85
    llm_temperature_decision: float = 0.0
    llm_timeout_seconds: float = 20.0

    # ── 角色（S1 起使用）──
    character: str = "tsundere"
    characters_dir: Path | None = None

    # ── 语音（S4）──
    voice_enabled: bool = False
    voice_input_mode: str = "push_to_talk"
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_volume: float = 0.9
    asr_enabled: bool = True
    asr_model: str = "tiny"
    asr_language: str = "zh"
    asr_compute_type: str = "int8"
    asr_initial_prompt: str = "以下是桌宠和用户的普通话对话。"
    voice_max_utterance_seconds: float = 30.0

    @field_validator("data_dir", mode="before")
    @classmethod
    def _resolve_blank_data_dir(cls, value: object) -> object:
        """`.env` 里 DATA_DIR= 留空时应使用默认目录，而不是当前工作目录。"""
        if value is None or (isinstance(value, str) and not value.strip()):
            return _default_data_dir()
        return value

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mochi.db"

    def characters_path(self) -> Path:
        """角色卡目录：显式配置 > 仓库自带 > 用户数据目录。"""
        if self.characters_dir is not None:
            return self.characters_dir
        repo_cards = PROJECT_ROOT / "characters"
        if repo_cards.is_dir():
            return repo_cards
        return self.data_dir / "characters"

    def ensure_dirs(self) -> None:
        """运行时数据与代码分离（第 10 章原则 5）。"""
        for name in ("live2d", "voices", "skills", "characters", "logs"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
