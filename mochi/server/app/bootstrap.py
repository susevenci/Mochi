"""依赖装配（对应计划书 5.8.5，借鉴 EchoBot runtime/bootstrap.py）。

所有服务在一个函数里显式装配，用构造器注入而非全局单例，便于单测替换 mock。
装配顺序：配置 → 角色卡 → 记忆 → Provider → 编排三件套 → 引擎（S3）。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .config.character_card import CardLoader
from .config.llm_settings import LLMSettingsService
from .config.settings import Settings
from .config.user_settings import UserSettings
from .context import AppContext
from .memory.context_builder import ContextBuilder
from .memory.short_term import ShortTermMemory
from .orchestration.commands import CommandRouter
from .orchestration.decision import DecisionService
from .orchestration.orchestrator import Orchestrator
from .orchestration.roleplay import RoleplayService
from .orchestration.turn_registry import TurnRegistry
from .providers.usage import UsageTracker

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHARACTERS_DIR = PROJECT_ROOT / "characters"


def load_settings() -> Settings:
    return Settings()


def bootstrap(settings: Settings) -> AppContext:
    settings.ensure_dirs()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    user_settings = UserSettings(settings.data_dir / "settings.json")

    cards = CardLoader(CHARACTERS_DIR, settings.character)
    builder = ContextBuilder(cards.current)
    history = ShortTermMemory(max_turns=20)
    llm = LLMSettingsService(settings, user_settings)
    usage = UsageTracker()

    orchestrator = Orchestrator(
        decision=DecisionService(),
        commands=CommandRouter(cards=cards, history=history, builder=builder),
        roleplay=RoleplayService(
            llm=llm,
            temperature=settings.llm_temperature_roleplay,
            builder=builder,
            history=history,
        ),
        turns=TurnRegistry(),
    )

    log.info(
        "bootstrap data_dir=%s character=%s model=%s token=%s",
        settings.data_dir,
        cards.current.id,
        llm.config.model,
        "enabled" if settings.server_token else "disabled",
    )
    return AppContext(
        settings=settings,
        user_settings=user_settings,
        started_at=time.time(),
        orchestrator=orchestrator,
        llm=llm,
        usage=usage,
        history=history,
    )
