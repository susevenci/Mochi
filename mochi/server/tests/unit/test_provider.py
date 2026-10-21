"""Provider 请求体测试：关闭思考时注入 chat_template_kwargs。"""

from __future__ import annotations

from app.providers.base import ChatMessage
from app.providers.openai_compatible import OpenAICompatibleProvider


def _provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(base_url="http://127.0.0.1:1/v1", model="m")


def test_body_injects_disable_thinking() -> None:
    body = _provider()._body(  # noqa: SLF001 - 白盒校验请求体
        [ChatMessage(role="user", content="hi")],
        None,
        0.8,
        100,
        stream=True,
        disable_thinking=True,
    )
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["stream"] is True


def test_body_keeps_thinking_when_disabled_flag_off() -> None:
    body = _provider()._body(  # noqa: SLF001
        [ChatMessage(role="user", content="hi")],
        None,
        0.8,
        100,
        stream=False,
    )
    assert "chat_template_kwargs" not in body


def test_gpt_oss_gets_reasoning_effort() -> None:
    """gpt-oss / o-series 用 reasoning_effort 控制思考强度。"""
    provider = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:1/v1", model="openai/gpt-oss-20b"
    )
    body = provider._body(  # noqa: SLF001
        [ChatMessage(role="user", content="hi")],
        None,
        0.8,
        100,
        stream=True,
        disable_thinking=True,
    )
    assert body["reasoning_effort"] == "low"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
