"""LLM 运行时配置（界面可改，即时生效）。

优先级：``settings.json`` 的 ``llm`` 段 > ``.env``（Settings）> 代码默认。
``api_key`` **绝不写日志**，对外只暴露掩码。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.providers.base import LLMError, LLMProvider
from app.providers.openai_compatible import OpenAICompatibleProvider

from .settings import Settings
from .user_settings import UserSettings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    disable_thinking: bool = True
    source: str = "env"  # user | env


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "••••"
    return f"{key[:2]}••••{key[-4:]}"


def parse_models(payload: object) -> list[str]:
    """从 OpenAI 兼容的 /models 响应里提取模型 ID（去重、排序）。"""
    items = payload.get("data") if isinstance(payload, dict) else None
    return sorted(
        {str(item["id"]) for item in items or [] if isinstance(item, dict) and item.get("id")}
    )


class LLMSettingsService:
    """持有当前 LLM 配置与 Provider 实例；配置变更时重建 Provider（热切换）。"""

    def __init__(self, settings: Settings, user_settings: UserSettings) -> None:
        self._settings = settings
        self._user = user_settings
        self._config = self._resolve()
        self._provider: LLMProvider | None = None

    @property
    def config(self) -> LLMConfig:
        return self._config

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = self._build(self._config)
        return self._provider

    def _resolve(self) -> LLMConfig:
        stored = self._user.get("llm")
        llm = stored if isinstance(stored, dict) else {}
        base_url = str(llm.get("base_url") or self._settings.llm_base_url)
        api_key = str(llm.get("api_key") or self._settings.llm_api_key)
        model = str(llm.get("model") or self._settings.llm_model_chat)
        raw_thinking = llm.get("disable_thinking")
        disable_thinking = raw_thinking if isinstance(raw_thinking, bool) else True
        source = "user" if any(llm.get(k) for k in ("base_url", "api_key", "model")) else "env"
        return LLMConfig(
            base_url=base_url,
            api_key=api_key,
            model=model,
            disable_thinking=disable_thinking,
            source=source,
        )

    def _build(self, config: LLMConfig) -> LLMProvider:
        return OpenAICompatibleProvider(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
            timeout=self._settings.llm_timeout_seconds,
        )

    async def update(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        disable_thinking: bool | None = None,
    ) -> LLMConfig:
        patch: dict[str, object] = {}
        if base_url is not None:
            patch["base_url"] = base_url
        if api_key is not None:
            patch["api_key"] = api_key
        if model is not None:
            patch["model"] = model
        if disable_thinking is not None:
            patch["disable_thinking"] = disable_thinking
        if patch:
            self._user.patch({"llm": patch})
        self._config = self._resolve()
        await self._reset_provider()
        log.info(
            "llm 配置已更新 base_url=%s model=%s thinking=%s api_key=%s",
            self._config.base_url,
            self._config.model,
            "off" if self._config.disable_thinking else "on",
            "已设置" if self._config.api_key else "空",
        )
        return self._config

    async def list_models(self) -> list[str]:
        """请求 ``{base_url}/models``，返回模型 ID 列表。"""
        config = self._config
        url = config.base_url.rstrip("/") + "/models"
        headers: dict[str, str] = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(20.0)) as client:
                response = await client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMError("LLM_TIMEOUT", "模型服务无响应") from exc
        except httpx.HTTPError as exc:
            raise LLMError("LLM_NETWORK", str(exc)) from exc

        if response.status_code in (401, 403):
            raise LLMError("LLM_AUTH_FAILED", f"HTTP {response.status_code}")
        if response.status_code >= 400:
            raise LLMError("LLM_BAD_REQUEST", f"HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMError("LLM_BAD_RESPONSE", "返回不是 JSON") from exc

        models = parse_models(payload)
        log.info("llm 模型列表获取成功 count=%d base_url=%s", len(models), config.base_url)
        return models

    async def _reset_provider(self) -> None:
        if self._provider is not None:
            await self._provider.aclose()
            self._provider = None

    async def aclose(self) -> None:
        await self._reset_provider()
