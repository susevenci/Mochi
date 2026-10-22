"""应用上下文：持有所有服务实例（构造器注入，不用全局单例）。"""

from __future__ import annotations

from dataclasses import dataclass

from .config.character_card import CardLoader
from .config.llm_settings import LLMSettingsService
from .config.settings import Settings
from .config.user_settings import UserSettings
from .emotion.engine import EmotionEngine
from .memory.service import MemoryService
from .memory.short_term import ShortTermMemory
from .orchestration.confirmation import ConfirmationStore
from .orchestration.orchestrator import Orchestrator
from .providers.usage import UsageTracker
from .skills.registry import SkillRegistry
from .tools.agent_core import AgentCore
from .tools.registry import ToolRegistry
from .voice.pipeline import VoiceService


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
    emotion: EmotionEngine
    voice: VoiceService
    memory: MemoryService
    skills: SkillRegistry
    tools: ToolRegistry
    agent: AgentCore
    confirmations: ConfirmationStore
