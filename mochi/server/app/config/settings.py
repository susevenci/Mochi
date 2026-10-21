from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
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

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mochi.db"

    def ensure_dirs(self) -> None:
        """运行时数据与代码分离（第 10 章原则 5）。"""
        for name in ("live2d", "voices", "skills", "characters", "logs"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
