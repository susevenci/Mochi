"""应用上下文：持有所有服务实例（构造器注入，不用全局单例）。"""

from __future__ import annotations

from dataclasses import dataclass

from .config.character_card import CardLoader
from .config.llm_settings import LLMSettingsService
from .config.settings import Settings
from .config.user_settings import UserSettings
from .memory.short_term import ShortTermMemory
from .orchestration.orchestrator import Orchestrator
from .providers.usage import UsageTracker


@dataclass
class AppContext:
    settings: Settings
    user_settings: UserSettings
    characters: CardLoader
    started_at: float
    orchestrator: Orchestrator
    llm: LLMSettingsService
    usage: UsageTracker
    history: ShortTermMemory
