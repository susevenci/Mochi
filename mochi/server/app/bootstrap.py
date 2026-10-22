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
from .emotion.engine import EmotionEngine
from .memory.context_builder import ContextBuilder
from .memory.service import MemoryService
from .memory.short_term import ShortTermMemory
from .orchestration.commands import CommandRouter
from .orchestration.confirmation import ConfirmationStore
from .orchestration.decision import DecisionService
from .orchestration.orchestrator import Orchestrator
from .orchestration.roleplay import RoleplayService
from .orchestration.turn_registry import TurnRegistry
from .providers.usage import UsageTracker
from .skills.meta_tools import SkillActivateTool, SkillListTool, SkillReadTool
from .skills.registry import SkillRegistry
from .store.db import Database
from .store.emotion_repo import JsonEmotionRepo
from .tools.agent_core import AgentCore
from .tools.builtin import build_default_tools
from .tools.registry import ToolRegistry
from .voice.pipeline import VoiceService

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

    cards = CardLoader(settings.characters_path(), settings.character)
    builder = ContextBuilder(cards.current)
    history = ShortTermMemory(max_turns=20)
    llm = LLMSettingsService(settings, user_settings)
    usage = UsageTracker()
    memory = MemoryService(Database(settings.db_path))
    skills = SkillRegistry(settings.skills_path())
    tools = ToolRegistry()
    for tool in build_default_tools():
        tools.register(tool)
    for tool in (
        SkillListTool(skills),
        SkillActivateTool(skills),
        SkillReadTool(skills),
    ):
        tools.register(tool)
    confirmations = ConfirmationStore()
    agent = AgentCore(provider=llm.provider, registry=tools)
    emotion = EmotionEngine(
        card=cards.current,
        repo=JsonEmotionRepo(settings.data_dir / "emotion_state.json"),
    )
    emotion.load()
    voice = VoiceService(settings)

    stored_agent = user_settings.get("agent")
    route_mode = (
        str(stored_agent.get("route_mode"))
        if isinstance(stored_agent, dict) and stored_agent.get("route_mode")
        else settings.route_mode
    )
    orchestrator = Orchestrator(
        decision=DecisionService(),
        commands=CommandRouter(cards=cards, history=history, builder=builder, memory=memory),
        roleplay=RoleplayService(
            llm=llm,
            temperature=settings.llm_temperature_roleplay,
            builder=builder,
            history=history,
            emotion=emotion,
            voice=voice,
            memory=memory,
        ),
        turns=TurnRegistry(),
        emotion=emotion,
        memory=memory,
        agent=agent,
        skills=skills,
        confirmations=confirmations,
        route_mode=route_mode,
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
        characters=cards,
        started_at=time.time(),
        orchestrator=orchestrator,
        llm=llm,
        usage=usage,
        history=history,
        emotion=emotion,
        voice=voice,
        memory=memory,
        skills=skills,
        tools=tools,
        agent=agent,
        confirmations=confirmations,
    )
