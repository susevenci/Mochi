"""应用上下文：持有所有服务实例（构造器注入，不用全局单例）。"""

from __future__ import annotations

from dataclasses import dataclass

from .config.settings import Settings
from .config.user_settings import UserSettings
from .memory.short_term import ShortTermMemory
from .orchestration.orchestrator import Orchestrator
from .providers.factory import ProviderFactory
from .providers.usage import UsageTracker


@dataclass
class AppContext:
    settings: Settings
    user_settings: UserSettings
    started_at: float
    orchestrator: Orchestrator
    provider_factory: ProviderFactory
    usage: UsageTracker
    history: ShortTermMemory
