"""OpenAI 兼容协议实现（DeepSeek / OpenAI / Ollama / LM Studio 共用）。

设计要点（计划书 4.3）：
- 只认 ``base_url + model``，不写 ``if provider == ...``
- 超时/429/5xx 有限重试，401/403 立即失败并映射为 ``LLM_AUTH_FAILED``
- 流式只产出正文增量，``reasoning_content`` 一律丢弃（桌宠不需要思考过程）
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from .base import ChatMessage, ChatResult, LLMError, Usage

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
AUTH_STATUS = {401, 403}


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 60.0,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._model = model
        self._max_retries = max_retries
        self._owns_client = client is None
        # trust_env=False：本地模型与云端点都不走系统代理，避免代理干扰 POST
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers=headers,
            timeout=httpx.Timeout(timeout),
            trust_env=False,
        )

    @property
    def model(self) -> str:
        return self._model

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _body(
        self,
        messages: Sequence[ChatMessage],
        model: str | None,
        temperature: float,
        max_tokens: int,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        return {
            "model": model or self._model,
            "messages": [message.to_wire() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.85,
        max_tokens: int = 512,
    ) -> ChatResult:
        body = self._body(messages, model, temperature, max_tokens, stream=False)
        data = await self._post_with_retry("/chat/completions", body)
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("LLM_EMPTY_RESPONSE", "choices 为空")
        message = choices[0].get("message") or {}
        return ChatResult(
            content=message.get("content") or "",
            model=str(data.get("model") or body["model"]),
            finish_reason=choices[0].get("finish_reason"),
            usage=Usage.from_wire(data.get("usage")),
            reasoning=message.get("reasoning_content") or "",
        )

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.85,
        max_tokens: int = 512,
    ) -> AsyncIterator[str]:
        body = self._body(messages, model, temperature, max_tokens, stream=True)
        try:
            async with self._client.stream("POST", "/chat/completions", json=body) as response:
                if response.status_code in AUTH_STATUS:
                    raise LLMError("LLM_AUTH_FAILED", f"HTTP {response.status_code}")
                if response.status_code >= 400:
                    text = (await response.aread()).decode("utf-8", "ignore")
                    raise LLMError("LLM_BAD_REQUEST", f"HTTP {response.status_code} {text[:200]}")

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        log.debug("跳过无法解析的 SSE 行: %r", raw[:80])
                        continue
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield content
        except httpx.TimeoutException as exc:
            raise LLMError("LLM_TIMEOUT", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise LLMError("LLM_NETWORK", str(exc)) from exc

    async def _post_with_retry(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        last_error: LLMError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(path, json=body)
            except httpx.TimeoutException as exc:
                last_error = LLMError("LLM_TIMEOUT", str(exc))
            except httpx.HTTPError as exc:
                last_error = LLMError("LLM_NETWORK", str(exc))
            else:
                if response.status_code in AUTH_STATUS:
                    raise LLMError("LLM_AUTH_FAILED", f"HTTP {response.status_code}")
                if response.status_code in RETRYABLE_STATUS:
                    last_error = LLMError("LLM_UPSTREAM", f"HTTP {response.status_code}")
                elif response.status_code >= 400:
                    raise LLMError(
                        "LLM_BAD_REQUEST",
                        f"HTTP {response.status_code} {response.text[:200]}",
                    )
                else:
                    return response.json()

            if attempt < self._max_retries:
                delay = 0.5 * (2**attempt)
                log.warning("LLM 第 %d 次重试（%s），%.1fs 后继续", attempt + 1, last_error, delay)
                await asyncio.sleep(delay)

        if last_error is None:  # pragma: no cover - 逻辑上不可达
            raise LLMError("LLM_UNKNOWN", "未获得响应")
        raise last_error
