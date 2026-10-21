"""Provider 工厂：多模型分工（计划书 4.3）。

同一套 OpenAI 兼容实现，按用途选择不同模型名：
chat（扮演，质量优先）/ decision（分类，快而稳）/ summary（摘要，便宜）。
"""

from __future__ import annotations

from app.config.settings import Settings

from .base import LLMProvider
from .openai_compatible import OpenAICompatibleProvider


class ProviderFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._provider = OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model_chat,
            timeout=settings.llm_timeout_seconds,
        )
        self._models = {
            "chat": settings.llm_model_chat,
            "decision": settings.llm_model_decision,
            "summary": settings.llm_model_summary,
        }

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    def model_for(self, purpose: str) -> str:
        return self._models.get(purpose, self._settings.llm_model_chat)

    def temperature_for(self, purpose: str) -> float:
        if purpose == "decision":
            return self._settings.llm_temperature_decision
        return self._settings.llm_temperature_roleplay

    async def aclose(self) -> None:
        await self._provider.aclose()
